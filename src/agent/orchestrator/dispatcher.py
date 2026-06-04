"""Dispatcher — 执行阶段 (Orchestrator 的"手脚层")。

把 Planner 输出的 (agent, task) 步骤分派给 sub-agent。

设计: 两个 Dispatcher 类 + 工厂,统一 async def stream() 接口。
"""

from __future__ import annotations

import logging
import time
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

_FALLBACK_DONE_MSG = "by {agent_id} done"


# ── 公共辅助 ────────────────────────────────────────────────────


def _emit_message_or_fallback(agent_id: str, content: str):
    stripped = content.strip()
    if stripped and not is_punctuation_only(stripped):
        return make_message(agent_id, content)
    if not stripped:
        return make_message(agent_id, _FALLBACK_DONE_MSG.format(agent_id=agent_id))
    return None


# ── LocalDispatcher ──────────────────────────────────────────────


class LocalDispatcher:
    """把 step 分派给本地 langgraph sub-agent。"""

    def __init__(self, sub_agents: dict[str, Any]):
        self.sub_agents = sub_agents

    async def stream(
        self,
        agent_id: str,
        task: str,
        previous_results: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield make_task_update("supervisor", agent_id, task, "running")
        graph = self.sub_agents.get(agent_id)
        if graph is None:
            yield make_message(agent_id, f"Unknown agent: {agent_id}")
            return
        agent_content = ""
        try:
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=task)]},
                {"recursion_limit": 200},
                version="v2",
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    reasoning = chunk.additional_kwargs.get("reasoning_content")
                    if reasoning:
                        yield make_thinking(agent_id, reasoning)
                    elif chunk.content:
                        agent_content += chunk.content
                elif kind == "on_tool_start":
                    yield make_tool_call(
                        agent_id,
                        [{"name": event["name"], "args": event["data"].get("input", {})}],
                    )
        except Exception as e:
            logger.error("[LocalDispatcher] agent %s error: %s", agent_id, e)
            agent_content = f"Agent error: {e}"
        msg = _emit_message_or_fallback(agent_id, agent_content)
        if msg is not None:
            yield msg


# ── ACPDispatcher ───────────────────────────────────────────────


class ACPDispatcher:
    """把 step 分派给 ACP (Agent Client Protocol) 外部 CLI agent。"""

    def __init__(self, acp_agents: dict[str, str]):
        self.acp_agents = acp_agents

    async def stream(
        self,
        agent_id: str,
        task: str,
        previous_results: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        from src.agent.acp_agent import get_acp_agent

        yield make_task_update("supervisor", agent_id, task, "running")

        connect_start = time.time()
        yield make_thinking(agent_id, "正在连接...")

        cli_id = self.acp_agents.get(agent_id, agent_id)
        context = ""
        if previous_results:
            context = "Previous results:\n" + "\n".join(
                f"- {r['agent']}: {r['result'][:200]}" for r in previous_results
            )

        acp = get_acp_agent(cli_id)
        agent_content = ""
        connect_ms = int((time.time() - connect_start) * 1000)
        logger.info("[ACPDispatcher] %s connected in %dms", agent_id, connect_ms)

        async for event in acp.run(task, context=context):
            event["agent_name"] = agent_id
            yield event
            if event.get("type") == "message":
                chunk = event.get("data", "")
                if chunk:
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
    if agent_id in acp_agents:
        return ACPDispatcher(acp_agents)
    return LocalDispatcher(sub_agents)
