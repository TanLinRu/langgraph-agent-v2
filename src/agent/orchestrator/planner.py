"""Planner —— 计划阶段 (Orchestrator 的"思考层")。

模块职责
--------
负责 Orchestrator 工作流的第一阶段:

1. **Prompt 构造** —— 从 config 拉取所有可用 agent,生成 ``SUPERVISOR_PROMPT``
   的填充字段 (``agent_descriptions`` / ``agent_names``)。
2. **History 转换** —— 把前端传入的 ``list[dict]`` 形式的对话历史
   (即 ``Message.to_frontend_dict()`` 输出) 转成 LLM 接受的
   ``list[{"role": "user/assistant", "content": str}]``。
3. **Plan 解析** —— 用 ``_PLAN_RE`` 正则从 LLM 输出的自然语言计划中
   抽取 ``(agent, task)`` 列表,只保留 valid_agents 中的项。
4. **流式 plan 输出** —— 把 LLM 的 thinking 增量、plan 文本以
   ``thinking_start`` / ``thinking`` / ``thinking_done`` / ``plan``
   事件的顺序 yield 给上游。

设计要点
--------
* Planner 是**有状态**的,持有 ``model`` (LLM) 和 ``config``,但不持有
  sub_agents (那是 Dispatcher 的事)。
* Planner 不修改传入的 ``history``,只读。
* ``parse_plan()`` 抽成 ``@staticmethod`` 方便单元测试。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from src.agent import models as _models
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.orchestrator._events import (  # noqa: F401  (re-exported)
    make_plan,
    make_thinking,
    make_thinking_done,
    make_thinking_start,
)
from src.agent.prompts.system_prompt import SUPERVISOR_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

# Plan 解析正则 —— 匹配 ``- agent: task`` / ``- **agent**: task`` / 中英文冒号
# 例子: ``- coder: 写代码`` / ``- **researcher**: 搜索文件`` / ``- analyst：分析数据``
_PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)


class Planner:
    """Plan 阶段封装,负责从用户输入生成可执行的 (agent, task) 列表。"""

    def __init__(self, config: AgentConfig):
        self.config = config
        # supervisor 自己用的模型 —— Plan LLM,可与 sub-agent 模型不同
        # 注意:用 _models.resolve_model() 而不是局部 from-import,确保
        # unittest.mock.patch("src.agent.models.resolve_model") 在所有消费者都生效
        self.model = _models.resolve_model(config)

    # ── Prompt 构造 ──────────────────────────────────────────────

    def _build_supervisor_prompt(self) -> str:
        """构造 supervisor system prompt。

        步骤:
            1. 遍历 ``get_config_manager().get_agents()``,收集所有启用的 agent 描述
            2. 兜底加入 ``direct`` (direct 永远可用,即使用户没在 config 里声明)
            3. 用 ``SUPERVISOR_PROMPT_TEMPLATE`` 填充两个占位符
        """
        cm = get_config_manager()
        agents_config = cm.get_agents()
        desc_lines: list[str] = []
        names: list[str] = []
        for agent_id, cfg in agents_config.items():
            # supervisor 自己跳过;disabled agent 也跳过
            if agent_id == "supervisor" or not cfg.get("enabled", True):
                continue
            desc = cfg.get("desc", "")
            names.append(agent_id)
            if desc:
                desc_lines.append(f"- **{agent_id}**: {desc}")
            else:
                desc_lines.append(f"- **{agent_id}**")
        # 兜底:direct 永远可选,即使 config 没声明
        if "direct" not in names:
            names.append("direct")
            desc_lines.append("- **direct**: Direct reply for simple/single-step tasks")
        return SUPERVISOR_PROMPT_TEMPLATE.format(
            agent_descriptions="\n".join(desc_lines),
            agent_names=", ".join(names),
        )

    # ── History 转换 ────────────────────────────────────────────

    @staticmethod
    def _convert_history(history: list[dict] | None) -> list[dict[str, str]]:
        """把前端格式 ``[{"role": "human", "content": "...", "tool_calls": [...]}]``
        转换为 LLM 接受的 ``[{"role": "user"|"assistant", "content": "..."}]``。

        转换规则:
            * ``"human"`` → ``"user"``;``"ai"`` / ``"assistant"`` → ``"assistant"``
            * tool_calls 序列化成内嵌文本 ``[Tool calls: name(args); name(args)]``
              (因为我们走的是普通 chat 接口,不是 tools API)
            * 空消息 (无 content 也无 tool_calls) 直接丢弃
        """
        if not history:
            return []
        converted: list[dict[str, str]] = []
        for msg in history:
            role = "user" if msg.get("role") == "human" else "assistant"
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls")
            # 没有 content 也没有 tool_calls 的空消息不喂给 LLM
            if not content and not tool_calls:
                continue
            text = content
            if tool_calls:
                # 把工具调用平铺成可读文本,让 LLM 看到历史调用过哪些工具
                calls_text = "; ".join(
                    f"{tc['name']}({json.dumps(tc.get('args', {}), ensure_ascii=False)})"
                    for tc in tool_calls
                )
                text = (text + "\n") if text else ""
                text += f"\n[Tool calls: {calls_text}]"
            converted.append({"role": role, "content": text})
        return converted

    # ── 主入口:流式生成 plan 事件 ────────────────────────────────

    async def stream(
        self,
        task: str,
        history: list[dict] | None = None,
        summary: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """流式生成 plan 阶段的事件。

        事件顺序:
            1. ``thinking_start``  (开始推理)
            2. ``thinking`` × N      (推理增量,0~N 个)
            3. ``thinking_done``     (推理结束)
            4. ``plan``              (完整 plan 文本)

        参数
        ----
        task: 用户当前轮次的输入
        history: 之前的对话历史,可空
        summary: session 级别的历史摘要 (来自上一轮压缩),可空
        """
        prompt = self._build_supervisor_prompt()
        yield make_thinking_start("supervisor")
        # 把 summary 追加到 system content 之后,作为隐式上下文
        system_content = prompt
        if summary:
            system_content += f"\n\n[Previous Conversation Summary]\n{summary}"
        # 组装 LLM 消息
        messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
        messages.extend(self._convert_history(history))
        messages.append({"role": "user", "content": task})
        # 累积 LLM 输出的 plan 文本,同时 forward thinking 增量
        plan_text = ""
        async for chunk in self.model.astream(messages):
            # DashScope/DeepSeek/GLM 等模型会输出推理内容到 ``reasoning_content``
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                yield make_thinking("supervisor", reasoning)
            if chunk.content:
                plan_text += chunk.content
        yield make_thinking_done("supervisor")
        yield make_plan("supervisor", plan_text)

    # ── Plan 解析 ────────────────────────────────────────────────

    @staticmethod
    def parse_plan(plan_text: str, valid_agents: set[str]) -> list[dict[str, str]]:
        """从 LLM 输出的自然语言 plan 中抽取 ``(agent, task)`` 列表。

        匹配规则:
            * 一行以 ``-`` 开头(可选),后跟 agent 名,后跟中英文冒号
            * agent 名可被 ``**`` 包裹 (Markdown 加粗)
            * 只保留 ``valid_agents`` 中的 agent (防止 LLM 幻觉出非法名)

        返回值
        ------
        ``[{"agent": "coder", "task": "..."}, ...]``
        """
        results: list[dict[str, str]] = []
        for m in _PLAN_RE.finditer(plan_text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            if agent_name in valid_agents:
                results.append({"agent": agent_name, "task": task})
        return results
