"""Dispatcher —— 执行阶段 (Orchestrator 的"手脚层")。

模块职责
--------
把 Planner 输出的 ``(agent, task)`` 步骤真正分派给 sub-agent 执行。

设计模式
--------
引入两个独立的 Dispatcher 类,统一接口 ``async def stream(...)``:

* :class:`LocalDispatcher` —— 调用本地 langgraph sub-agent 图
* :class:`ACPDispatcher`    —— 走 ACP (Agent Client Protocol) 协议,
  与 ``acp_agent.get_acp_agent(cli_id)`` 通信

为什么拆两个:
    * 本地图和 ACP 的事件流形态完全不同,混在一起会引入大量 if-else
    * 本地图 ``astream_events`` 给出 ``on_chat_model_stream`` / ``on_tool_start``;
      ACP 给的是 ``thinking`` / ``message`` 高层事件
    * 拆开后,未来要新增"远程 HTTP dispatcher" / "Python-only dispatcher"
      都不必动 LocalDispatcher
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage

from src.agent._utils import is_punctuation_only
from src.agent.orchestrator._events import (
    make_message,
    make_task_update,
    make_thinking,
    make_tool_call,
)

logger = logging.getLogger(__name__)

# 当 sub-agent 没有产出任何有意义文本时,使用这个兜底消息
# 原因:langgraph 的 ``astream_events`` 经常只触发 ``on_tool_start`` 而
# 不输出 content,前端需要一个占位消息来代表"这个 agent 跑完了"
_FALLBACK_DONE_MSG = "by {agent_id} done"


# ── 公共辅助 ────────────────────────────────────────────────────


def _emit_message_or_fallback(agent_id: str, content: str):
    """根据 content 是否"有意义",决定发 ``message`` 还是发兜底消息。

    有意义的标准 (与前端体验保持一致):
        * 非空
        * 不是纯标点 (例如 ``.`` / ``,`` / ``...``)

    为什么这样设计:
        sub-agent 有时会因为 thinking 残留一个空消息;如果原样发出,前端
        会渲染一个空气泡,影响观感。
    """
    stripped = content.strip()
    if stripped and not is_punctuation_only(stripped):
        return make_message(agent_id, content)
    if not stripped:
        return make_message(agent_id, _FALLBACK_DONE_MSG.format(agent_id=agent_id))
    return None  # 纯标点 —— 静默丢弃


# ── LocalDispatcher ──────────────────────────────────────────────


class LocalDispatcher:
    """把 step 分派给本地 langgraph sub-agent。

    适用场景:
        普通的 ReAct agent (langchain ``create_agent`` 构造的图)。

    行为契约:
        * 第一个事件是 ``task_update`` 状态 ``running``
        * 中间可能有 N 个 ``thinking`` / ``tool_call`` 事件
        * 最后一定发一个 ``message`` (有内容则发真实内容,否则发兜底)
    """

    def __init__(self, sub_agents: dict[str, Any]):
        # ``sub_agents`` 是 ``Orchestrator.sub_agents`` (agent_id → compiled graph)
        self.sub_agents = sub_agents

    async def stream(
        self,
        agent_id: str,
        task: str,
        previous_results: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # 1. 通知前端"任务开始 running"
        yield make_task_update("supervisor", agent_id, task, "running")
        # 2. 未知 agent —— 立即报错退出,不让前端空等
        graph = self.sub_agents.get(agent_id)
        if graph is None:
            yield make_message(agent_id, f"Unknown agent: {agent_id}")
            return
        # 3. 累积 agent 文本输出 + 转发 thinking/tool_call 事件
        agent_content = ""
        try:
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=task)]}, version="v2"
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    reasoning = chunk.additional_kwargs.get("reasoning_content")
                    if reasoning:
                        yield make_thinking(agent_id, reasoning)
                    elif chunk.content:
                        # 推理只走 ``reasoning_content``;content 才是真正要累积的输出
                        agent_content += chunk.content
                elif kind == "on_tool_start":
                    yield make_tool_call(
                        agent_id,
                        [{"name": event["name"], "args": event["data"].get("input", {})}],
                    )
        except Exception as e:
            # 单个 sub-agent 崩溃不影响 orchestrator 整体流程
            # 错误内容会以 message 事件呈现给用户
            logger.error("[LocalDispatcher] agent %s error: %s", agent_id, e)
            agent_content = f"Agent error: {e}"
        # 4. 兜底:如果 agent 没产出任何 message,补一个占位
        msg = _emit_message_or_fallback(agent_id, agent_content)
        if msg is not None:
            yield msg


# ── ACPDispatcher ───────────────────────────────────────────────


class ACPDispatcher:
    """把 step 分派给 ACP (Agent Client Protocol) 外部 CLI agent。

    适用场景:
        ``config/acp_agents.json`` 中声明的 agent (如 opencode、claude-agent)。
        它们运行在独立进程,通过 stdio JSON-RPC 通信。

    行为契约:
        * 第一个事件是 ``task_update`` 状态 ``running``
        * 中间事件由 ACP 决定,直接透传 (event type 不变,只覆写 ``agent_name``)
        * 兜底逻辑与 LocalDispatcher 一致
    """

    def __init__(self, acp_agents: dict[str, str]):
        # ``acp_agents`` 是 ``Orchestrator.acp_agents`` (agent_id → cli_id)
        self.acp_agents = acp_agents

    async def stream(
        self,
        agent_id: str,
        task: str,
        previous_results: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # 延迟 import —— ACP 模块较重,只在需要时分派
        from src.agent.acp_agent import get_acp_agent

        yield make_task_update("supervisor", agent_id, task, "running")
        # 把上游累积的"先前结果"作为 context 喂给 ACP,实现链式协作
        context = ""
        if previous_results:
            context = "Previous results:\n" + "\n".join(
                f"- {r['agent']}: {r['result'][:200]}" for r in previous_results
            )
        acp = get_acp_agent(self.acp_agents[agent_id])
        agent_content = ""
        async for event in acp.run(task, context=context):
            # ACP 事件用 agent_id (我方) 替换 cli_id (对方),让前端归一
            event["agent_name"] = agent_id
            yield event
            # 只累积 message 事件;thinking 事件不计入最终输出
            if event.get("type") == "message":
                chunk = event.get("data", "")
                if chunk:
                    # 标点-only 增量在已累积超过 20 字时丢弃,避免标点干扰最终输出
                    if is_punctuation_only(chunk.strip()) and len(agent_content.strip()) > 20:
                        continue
                    agent_content += chunk
            elif event.get("type") == "error":
                agent_content = f"Error: {event.get('data', '')}"
        msg = _emit_message_or_fallback(agent_id, agent_content)
        if msg is not None:
            yield msg


# ── Dispatcher 工厂 ──────────────────────────────────────────────


def make_dispatcher(
    agent_id: str,
    sub_agents: dict[str, Any],
    acp_agents: dict[str, str],
) -> LocalDispatcher | ACPDispatcher:
    """根据 agent_id 决定用 Local 还是 ACP dispatcher。

    为什么写成工厂:
        保持 Orchestrator.run() 内部代码"一个 loop 走遍所有 agent"的形式,
        不必每轮都 if-else 判断。
    """
    if agent_id in acp_agents:
        return ACPDispatcher(acp_agents)
    return LocalDispatcher(sub_agents)
