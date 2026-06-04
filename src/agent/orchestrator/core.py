"""Orchestrator — 3 节点 LangGraph StateGraph (Supervisor → Execute → Review).

替换旧的过程式流水线 (Planner → Dispatcher → Summarizer)。

事件桥接: 节点函数将事件压入 asyncio.Queue, run() 并发消费并 yield。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph

from src.agent import models as _models
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.orchestrator._events import (
    make_audit_summary,
    make_done,
    make_message,
    make_metrics,
    make_plan,
    make_task_update,
    make_thinking,
    make_thinking_done,
    make_thinking_start,
)
from src.agent.orchestrator.planner import (
    build_agent_descriptions,
    load_experiences,
    save_experiences,
)
from src.agent.orchestrator.tools import ACPSubAgentTool, SubAgentTool
from src.agent.prompts.system_prompt import AUDITOR_PROMPT, SUPERVISOR_PLAN_PROMPT

logger = logging.getLogger(__name__)

_PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)


class GraphState(TypedDict):
    messages: list[BaseMessage]
    plan_text: str
    steps: list[dict]
    results: list[dict]
    errors: list[dict]
    review: str


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) * 1.5))


class Orchestrator:
    """多 agent 编排器 — StateGraph 3 节点版本。"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.model = _models.resolve_model(config)
        self.sub_agents: dict[str, dict] = {}
        self.acp_agents: dict[str, str] = {}
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._tokens: dict[str, dict[str, int]] = {}
        self._load_agent_configs()

    def _load_agent_configs(self):
        cm = get_config_manager()
        agents_config = cm.get_agents()
        for agent_id, cfg in agents_config.items():
            if agent_id == "supervisor" or not cfg.get("enabled", True):
                continue
            if cfg.get("acp_mode"):
                self.acp_agents[agent_id] = cfg.get("acp_cli_id", agent_id)
            else:
                self.sub_agents[agent_id] = cfg
        if "direct" not in self.sub_agents:
            self.sub_agents["direct"] = {}

    # ── Supervisor Node ────────────────────────────────────────

    async def _supervisor_node_impl(self, state: GraphState) -> dict:
        task = state["messages"][-1].content if state["messages"] else ""
        await self.queue.put(make_thinking_start("supervisor"))

        agent_descriptions = build_agent_descriptions()
        experiences = load_experiences()
        prompt = SUPERVISOR_PLAN_PROMPT.format(
            agent_descriptions=agent_descriptions,
            experiences=experiences if experiences else "No prior experiences.",
        )

        messages = [{"role": "system", "content": prompt}]
        for msg in state["messages"][:-1]:
            role = "user" if msg.type == "human" else "assistant"
            messages.append({"role": role, "content": str(msg.content)})
        messages.append({"role": "user", "content": task})

        node_start = time.time()
        plan_text = ""
        async for chunk in self.model.astream(messages):
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                await self.queue.put(make_thinking("supervisor", reasoning))
            if chunk.content:
                plan_text += chunk.content

        input_text = " ".join(str(m.get("content", "")) for m in messages)
        self._tokens["supervisor"] = {
            "input": _estimate_tokens(input_text),
            "output": _estimate_tokens(plan_text),
            "ms": int((time.time() - node_start) * 1000),
        }

        await self.queue.put(make_thinking_done("supervisor"))
        await self.queue.put(make_plan("supervisor", plan_text))

        steps = self._parse_plan(plan_text)
        return {"plan_text": plan_text, "steps": steps}

    # ── Execute Node ───────────────────────────────────────────

    async def _execute_node_impl(self, state: GraphState) -> dict:
        results: list[dict] = []
        errors: list[dict] = []
        task = state["messages"][-1].content if state["messages"] else ""
        valid_agents = set(self.sub_agents.keys()) | set(self.acp_agents.keys())

        steps = state.get("steps", [])
        if not steps:
            steps = [{"agent": "direct", "task": task.strip()}]

        for step in steps:
            agent_name = step["agent"]
            subtask = step["task"]
            if agent_name not in valid_agents:
                logger.warning("[Execute] unknown agent %s, skipping", agent_name)
                continue

            await self.queue.put(make_task_update("supervisor", agent_name, subtask, "running"))

            agent_start = time.time()
            try:
                if agent_name in self.acp_agents:
                    tool = ACPSubAgentTool(
                        agent_id=agent_name, acp_cli_id=self.acp_agents[agent_name]
                    )
                else:
                    tool = SubAgentTool(agent_id=agent_name, config=self.config)
                result_text = await tool._arun(subtask)
            except Exception as e:
                logger.error("[Execute] agent %s error: %s", agent_name, e)
                errors.append({"agent": agent_name, "task": subtask, "error": str(e)})
                await self.queue.put(
                    make_task_update("supervisor", agent_name, subtask, "failed")
                )
                continue

            self._tokens[agent_name] = {
                "input": _estimate_tokens(subtask),
                "output": _estimate_tokens(result_text),
                "ms": int((time.time() - agent_start) * 1000),
            }

            results.append({"agent": agent_name, "task": subtask, "result": result_text})
            await self.queue.put(make_message(agent_name, result_text))
            await self.queue.put(
                make_task_update("supervisor", agent_name, subtask, "completed")
            )

        return {"results": results, "errors": errors}

    # ── Review Node ────────────────────────────────────────────

    async def _review_node_impl(self, state: GraphState) -> dict:
        task = state["messages"][-1].content if state["messages"] else ""
        results = state.get("results", [])

        if not results:
            review_msg = "No agents were executed. All steps were skipped or failed."
            self._tokens["review"] = {"input": 0, "output": _estimate_tokens(review_msg), "ms": 0}
            await self.queue.put(make_audit_summary("supervisor", review_msg))
            return {"review": "no_results"}

        results_text = "\n\n".join(
            f"**{r['agent']}** ({r['task']}):\n{r['result'][:500]}" for r in results
        )
        prompt = AUDITOR_PROMPT.format(task=task, results=results_text)

        node_start = time.time()
        review_text = ""
        async for chunk in self.model.astream([{"role": "user", "content": prompt}]):
            if chunk.content:
                review_text += chunk.content

        save_experiences(task, results, review_text)
        self._tokens["review"] = {
            "input": _estimate_tokens(prompt),
            "output": _estimate_tokens(review_text),
            "ms": int((time.time() - node_start) * 1000),
        }
        await self.queue.put(make_audit_summary("supervisor", review_text))
        return {"review": review_text}

    # ── Plan Parser ────────────────────────────────────────────

    @staticmethod
    def _parse_plan(plan_text: str) -> list[dict]:
        results: list[dict] = []
        for m in _PLAN_RE.finditer(plan_text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            results.append({"agent": agent_name, "task": task})
        return results

    # ── Graph Construction ─────────────────────────────────────

    def _build_graph(self):
        graph = StateGraph(GraphState)

        async def supervisor_node(state: GraphState) -> dict:
            return await self._supervisor_node_impl(state)

        async def execute_node(state: GraphState) -> dict:
            return await self._execute_node_impl(state)

        async def review_node(state: GraphState) -> dict:
            return await self._review_node_impl(state)

        graph.add_node("supervisor", supervisor_node)
        graph.add_node("execute", execute_node)
        graph.add_node("review", review_node)
        graph.add_edge("supervisor", "execute")
        graph.add_edge("execute", "review")
        graph.add_conditional_edges(
            "review",
            lambda s: "end" if s.get("review") else "execute",
        )
        graph.set_entry_point("supervisor")
        return graph.compile()

    # ── Main Entry ─────────────────────────────────────────────

    async def run(
        self,
        task: str,
        history: list[dict] | None = None,
        summary: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        start_time = time.time()
        self.queue = asyncio.Queue()
        graph_app = self._build_graph()

        messages: list[BaseMessage] = []
        if summary:
            messages.append(
                SystemMessage(content=f"[Previous Conversation Summary]\n{summary}")
            )
        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "human":
                    messages.append(HumanMessage(content=content))
                else:
                    from langchain_core.messages import AIMessage
                    messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=task))

        initial_state: GraphState = {
            "messages": messages,
            "plan_text": "",
            "steps": [],
            "results": [],
            "errors": [],
            "review": "",
        }

        run_task = asyncio.create_task(graph_app.ainvoke(initial_state))

        while True:
            done_fut = asyncio.ensure_future(run_task)
            get_coro = self.queue.get()
            queue_fut = asyncio.ensure_future(get_coro)

            pending = {done_fut, queue_fut}
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

            if done_fut in done:
                queue_fut.cancel()
                while not self.queue.empty():
                    yield await self.queue.get()
                break

            if queue_fut in done:
                evt = await queue_fut
                yield evt

        elapsed_ms = int((time.time() - start_time) * 1000)
        final = initial_state
        yield make_metrics("supervisor", {
            "elapsed_ms": elapsed_ms,
            "agent_calls": len(final.get("results", [])),
            "tokens": self._tokens,
        })
        yield make_done()
