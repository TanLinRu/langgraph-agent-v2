"""Orchestrator —— 顶层编排器。

模块职责
--------
组合 :class:`Planner`、:class:`Dispatcher` (Local / ACP)、
:smod:`orchestrator.summarizer`,把"计划→派发→综合"三阶段串成一个
``async def run()`` 协程。

为什么不把整个 run() 写在一个文件里:
    * Planner / Dispatcher / Summarizer 各自有独立的领域逻辑
    * 拆开后每个文件 < 200 行,易于单测
    * 新增"远程 dispatcher" / "新 prompt 模板" 只需改对应模块

事件协议
--------
``run()`` 的产出严格遵循 :mod:`src.agent.events` 中定义的事件 schema,
与前端 ``messageManager`` 一一对应,见 ``docs/diff.md`` 第 9.1 节。
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent

from src.agent import models as _models
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.orchestrator._events import (
    make_done,
    make_message,
    make_metrics,
    make_task_update,
)
from src.agent.orchestrator.dispatcher import make_dispatcher
from src.agent.orchestrator.planner import Planner
from src.agent.orchestrator.summarizer import stream as summarize_stream
from src.agent.tools import TOOLS

logger = logging.getLogger(__name__)

# 单轮直接回复前缀 —— LLM 经常在 plan 文本里写 ``- direct: Reply to user: ...``,
# 这种时候直接显示后半段,避免 "Reply to user:" 这种指令残留
_DIRECT_PREFIXES = ("Reply to user: ", "Reply: ", "Answer: ")


class Orchestrator:
    """多 agent 编排器。

    在 ``__init__`` 时一次性构建所有 sub-agent (langgraph 图 / ACP 映射),
    ``run()`` 每次只走"plan → dispatch → (summarize)" 三阶段流水线。

    属性
    ----
    config: ``AgentConfig`` 实例
    model:  supervisor 用的 LLM (用于 plan + summary)
    sub_agents: ``{agent_id: compiled_graph}``  本地 langgraph sub-agent
    acp_agents: ``{agent_id: cli_id}``  ACP 模式 sub-agent
    planner: :class:`Planner` 实例,plan 阶段复用
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        # supervisor 用的 LLM,plan/summary 都用它
        self.model = _models.resolve_model(config)
        # sub-agent 注册表
        self.sub_agents: dict[str, Any] = {}
        self.acp_agents: dict[str, str] = {}
        # plan 阶段对象,内部持有 model
        self.planner = Planner(config)
        # 一次性把 config 转成 sub-agent
        self._build_sub_agents()

    # ── Sub-agent 构建 ──────────────────────────────────────────

    def _build_sub_agents(self) -> None:
        """遍历 config,把每个 agent 转成 langgraph 图或 ACP 映射。

        规则:
            * ``supervisor`` / 禁用的 agent → 跳过
            * ``acp_mode=true`` 的 agent → 记入 ``acp_agents`` (延迟实例化)
            * 配置了 ``tools`` 的 agent → 用对应工具创建 langgraph 图
            * ``direct`` 永远兜底存在,即使 config 没声明
        """
        cm = get_config_manager()
        agents_config = cm.get_agents()
        tool_map = {t.name: t for t in TOOLS}
        for agent_id, cfg in agents_config.items():
            if agent_id == "supervisor" or not cfg.get("enabled", True):
                continue
            # ACP 模式 —— 记映射,不在这里实例化 (避免启动时拖慢)
            if cfg.get("acp_mode"):
                self.acp_agents[agent_id] = cfg.get("acp_cli_id", agent_id)
                continue
            # 选工具
            tool_names = cfg.get("tools", [])
            if not tool_names and agent_id == "direct":
                agent_tools = list(tool_map.values())
            elif tool_names:
                agent_tools = [tool_map[n] for n in tool_names if n in tool_map]
            else:
                # 没声明 tools 且非 direct → 跳过
                continue
            if not agent_tools:
                continue
            # 解析 agent 专属模型 (可与 supervisor 不同)
            agent_model = _models.resolve_model(
                self.config,
                model_override=cfg.get("model"),
                temperature=cfg.get("temperature"),
                max_tokens=cfg.get("max_tokens"),
            )
            self.sub_agents[agent_id] = create_agent(
                agent_model,
                tools=agent_tools,
                system_prompt=cfg.get("system_prompt", "You are a helpful assistant."),
                name=agent_id,
            )
        # direct 兜底 —— 即使 config 里没有,也注册一个
        if "direct" not in self.sub_agents:
            self.sub_agents["direct"] = create_agent(
                _models.resolve_model(self.config),
                tools=list(tool_map.values()),
                system_prompt="You are a helpful assistant. Complete the task directly.",
                name="direct",
            )

    # ── 直接回复文本清洗 ──────────────────────────────────────

    @staticmethod
    def _clean_direct_response(task: str) -> str:
        """去掉 ``Reply to user:`` / ``Reply:`` / ``Answer:`` 等 LLM 残留前缀。"""
        for prefix in _DIRECT_PREFIXES:
            if task.startswith(prefix):
                return task[len(prefix):]
        return task

    # ── 主入口 ──────────────────────────────────────────────────

    async def run(
        self,
        task: str,
        history: list[dict] | None = None,
        summary: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """执行一次完整编排,流式产出事件。

        阶段划分
        --------
        1. **Plan** —— 由 :class:`Planner` 生成 ``thinking_*`` / ``plan`` 事件
        2. **Dispatch** —— 解析 plan,逐个步骤派发,产出 ``task_update`` / ``message`` / ``tool_call``
        3. **Summarize** (可选) —— 多步骤时调用 :mod:`summarizer` 生成 ``summary``
        4. **Metrics** —— 最后发 ``metrics`` / ``done``

        参数
        ----
        task: 用户当前输入
        history: 之前对话历史 (Message.to_frontend_dict 形态)
        summary: session 摘要 (来自压缩),可空
        """
        start_time = time.time()
        # ── 1. Plan 阶段 ────────────────────────────────────────
        plan_text = ""
        async for event in self.planner.stream(task, history, summary=summary):
            yield event
            if event["type"] == "plan":
                plan_text = event.get("data", "")
        # ── 2. 解析 plan 文本为步骤 ──────────────────────────────
        valid_agents = set(self.sub_agents.keys()) | set(self.acp_agents.keys())
        steps = self.planner.parse_plan(plan_text, valid_agents)
        if not steps:
            # 兜底:plan 解析失败 → 当作 direct 处理
            steps = [{"agent": "direct", "task": plan_text.strip() or task}]
        # ── 3. 单步 direct 走"快路径" (省去 dispatcher/summarizer) ──
        if all(s["agent"] == "direct" for s in steps):
            clean = self._clean_direct_response(steps[0]["task"])
            yield make_message("supervisor", clean)
            yield make_metrics("supervisor", {
                "elapsed_ms": int((time.time() - start_time) * 1000),
                "agent_calls": 0,
                "tokens": {},
            })
            yield make_done()
            return
        # ── 4. 多步派发 + 累积 token / 结果 ────────────────────
        agent_calls = 0
        token_usage: dict[str, dict[str, int]] = {}
        results: list[dict[str, str]] = []
        for step in steps:
            agent_name = step["agent"]
            subtask = step["task"]
            agent_calls += 1
            agent_start = time.time()
            # 工厂选择 Local / ACP dispatcher
            dispatcher = make_dispatcher(agent_name, self.sub_agents, self.acp_agents)
            agent_content = ""
            async for event in dispatcher.stream(agent_name, subtask, results):
                yield event
                # 仅累积"本 step 自己的 message",避免抓到 supervisor message
                if event["type"] == "message" and event.get("agent_name") == agent_name:
                    agent_content = event.get("data", "")
            # 估算 token —— 没有真实计数时,粗略用 ``len(text)*2`` 顶替
            agent_ms = int((time.time() - agent_start) * 1000)
            token_usage[agent_name] = {
                "input": len(subtask) * 2,
                "output": len(agent_content) * 2,
                "ms": agent_ms,
            }
            results.append({"agent": agent_name, "task": subtask, "result": agent_content})
            # 单个步骤完成 → 发 task_update(completed)
            yield make_task_update(
                "supervisor", agent_name, subtask, "completed"
            )
        # ── 5. 多 agent 综合 (仅当 results>1) ────────────────────
        if len(results) > 1:
            async for event in summarize_stream(self.model, task, results):
                yield event
        # ── 6. Metrics + done (收尾) ─────────────────────────────
        yield make_metrics("supervisor", {
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "agent_calls": agent_calls,
            "tokens": token_usage,
        })
        yield make_done()
