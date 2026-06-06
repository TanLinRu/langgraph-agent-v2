"""Orchestrator — 6-node LangGraph StateGraph (perceive→plan→wait→dispatch→synthesize→reflect).

Replaces the old 3-node supervisor→execute→review graph.
Supports interrupt/resume via langgraph.types.interrupt() + Command().
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt

from src.agent import models as _models
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.orchestrator._events import (
    make_audit_summary,
    make_done,
    make_error,
    make_message,
    make_metrics,
    make_plan,
    make_summary,
    make_task_update,
    make_thinking,
    make_thinking_done,
    make_thinking_start,
)
from src.agent.orchestrator.planner import (
    AntiPattern,
    AgentResult,
    GraphState,
    Plan,
    Step,
    build_agent_descriptions,
    load_constraints,
    load_experiences,
    save_anti_pattern,
)
from src.agent.orchestrator.tools import ACPSubAgentTool, SubAgentTool
from src.agent.prompts.system_prompt import (
    AUDITOR_PROMPT,
    REFLECT_PROMPT,
    SUPERVISOR_PLAN_PROMPT_V2,
)

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) * 1.5))


def _is_echo_output(task: str, result: str) -> bool:
    """Heuristic: result merely echoes the task verbatim instead of executing it."""
    task_clean = task.strip().lower()
    result_clean = result.strip().lower()
    if len(task_clean) < 10:
        return False
    if task_clean not in result_clean:
        return False
    # Result contains the task verbatim and isn't substantially longer
    return len(result_clean) < len(task_clean) * 3


class Orchestrator:
    """多 agent 编排器 — StateGraph 6 节点版本。"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.model = _models.resolve_model(config)
        self.sub_agents: dict[str, dict] = {}
        self.acp_agents: dict[str, str] = {}
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._tokens: dict[str, dict[str, int]] = {}
        self._agent_calls: int = 0
        self._memory_provider: Any = None
        self._interrupted_threads: dict[str, Any] = {}
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

    # ── Node: Perceive ───────────────────────────────────────

    async def _perceive_node(self, state: GraphState) -> dict:
        await self.queue.put(make_thinking_start("supervisor"))

        history = state.history or []
        task = state.task

        parts: list[str] = []
        if history:
            for msg in history:
                if isinstance(msg, dict):
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if content:
                        parts.append(f"[{role}] {content}")

        # Append prior-cycle agent results so re-dispatched agents
        # (after revision) know what was already attempted.
        if state.results:
            parts.append("")
            parts.append("[Previous cycle agent outputs]")
            for r in state.results.values():
                label = f"[{r.agent}] task: {r.task}"
                snippet = (r.result[:1000] + "...") if len(r.result) > 1000 else r.result
                parts.append(f"{label}\n{snippet}")
                if r.error:
                    parts.append(f"  error: {r.error}")

        summary_text = "\n".join(parts) if parts else f"Task: {task}"

        await self.queue.put(make_thinking("supervisor", "Context perception complete"))
        await self.queue.put(make_thinking_done("supervisor"))

        return {"history_summary": summary_text}

    # ── Node: Plan ───────────────────────────────────────────

    async def _plan_node(self, state: GraphState) -> dict:
        task = state.task
        history_summary = state.history_summary
        constraints = state.constraints or load_constraints()

        await self.queue.put(make_thinking_start("supervisor"))

        agent_descriptions = build_agent_descriptions()
        experiences = load_experiences()

        feedback_section = ""
        if state.review_feedback:
            feedback_section = f"\nUser revision feedback:\n{state.review_feedback}\n"

        constraints_section = ""
        if constraints:
            constraints_section = "\nConstraints from prior sessions:\n" + "\n".join(f"- {c}" for c in constraints)

        prompt = SUPERVISOR_PLAN_PROMPT_V2.format(
            agent_descriptions=agent_descriptions,
            experiences=experiences if experiences else "No prior experiences.",
            constraints=constraints_section,
            feedback=feedback_section,
        )

        messages = [{"role": "system", "content": prompt}]
        if history_summary:
            messages.append({"role": "user", "content": f"Context:\n{history_summary}\n\nTask: {task}"})
        else:
            messages.append({"role": "user", "content": f"Task: {task}"})

        node_start = time.time()
        plan_text = ""
        thinking_accum = ""
        await self.queue.put(make_thinking("supervisor", "正在生成执行计划..."))
        for i, m in enumerate(messages):
            logger.info("[LLM] supervisor plan messages[%d] (%s): %.2000s",
                         i, m.get("role", "?"), m.get("content", ""))
        async for chunk in self.model.astream(messages):
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                thinking_accum += reasoning
                reasoning_text = "".join(thinking_accum.split(".")[-2:]) if "." in thinking_accum else thinking_accum
                await self.queue.put(make_thinking("supervisor", reasoning_text[:500]))
            if chunk.content:
                plan_text += chunk.content
        logger.info("[LLM] supervisor plan response (%d chars): %.2000s", len(plan_text), plan_text)

        input_text = " ".join(str(m.get("content", "")) for m in messages)
        prev = self._tokens.get("supervisor", {})
        self._tokens["supervisor"] = {
            "input": prev.get("input", 0) + _estimate_tokens(input_text),
            "output": prev.get("output", 0) + _estimate_tokens(plan_text),
            "ms": prev.get("ms", 0) + int((time.time() - node_start) * 1000),
        }

        await self.queue.put(make_thinking_done("supervisor"))

        # Extract JSON object from plan text (may be wrapped in markdown / fences)
        clean = plan_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1] if "\n" in clean else clean
            clean = clean.rsplit("```", 1)[0] if "```" in clean else clean
            clean = clean.strip()

        plan: Plan | None = None
        if not clean.startswith("{"):
            import re
            brace = clean.find("{")
            if brace >= 0:
                clean = clean[brace:]
                close = clean.rfind("}")
                if close >= 0:
                    clean = clean[: close + 1]

        if clean.startswith("{"):
            try:
                import json as _json
                raw_dict = _json.loads(clean)
                for s in raw_dict.get("steps", []):
                    s["depends_on"] = [str(d) for d in s.get("depends_on", [])]
                plan = Plan(**raw_dict)
            except Exception:
                plan = None

        if plan is None:
            steps = self._parse_plan_fallback(plan_text)
            import re as _re
            m = _re.search(r'"reasoning"\s*:\s*"([^"]+)"', plan_text)
            reasoning = m.group(1) if m else ""
            plan = Plan(steps=steps, reasoning=reasoning)

        plan_display = self._format_plan_display(plan)
        await self.queue.put(make_plan(
            "supervisor", plan_display,
            steps=[s.model_dump() for s in plan.steps],
        ))

        return {"plan": plan}

    # ── Node: Wait (interrupt point) ─────────────────────────

    async def _wait_node(self, state: GraphState) -> dict:
        plan_json = state.plan.model_dump() if state.plan else {}
        interrupt({"plan": plan_json})
        return {}

    # ── Node: Dispatch ───────────────────────────────────────

    async def _dispatch_node(self, state: GraphState) -> dict:
        plan = state.plan
        if not plan or not plan.steps:
            return {"results": {}, "errors": ["No plan steps to execute"]}

        tasks = plan.steps
        history_summary = state.history_summary
        valid_agents = set(self.sub_agents.keys()) | set(self.acp_agents.keys())
        results: dict[str, AgentResult] = {}
        errors: list[str] = []
        # depends_on are step indices (e.g. "0", "1"), not agent names
        step_index_map = {str(i): s for i, s in enumerate(tasks)}

        def _build_step_context(step: Step) -> str:
            dep_parts: list[str] = []
            for dep_idx in step.depends_on:
                dep_step = step_index_map.get(dep_idx)
                if not dep_step:
                    continue
                dep_name = dep_step.agent
                dep_result = results.get(dep_name)
                if dep_result and dep_result.result:
                    snippet = (dep_result.result[:2000] + "...") if len(dep_result.result) > 2000 else dep_result.result
                    dep_parts.append(
                        f"[Upstream: {dep_name}]\n"
                        f"Task: {dep_result.task}\n"
                        f"Output:\n{snippet}"
                    )
            dep_section = "\n\n".join(dep_parts)
            if dep_section and history_summary:
                return f"{history_summary}\n\n--- Dependency Results ---\n{dep_section}"
            if dep_section:
                return f"Dependency Results:\n{dep_section}"
            return history_summary

        async def _run_step(step: Step) -> AgentResult:
            agent_name = step.agent
            if agent_name not in valid_agents:
                logger.warning("[Dispatch] unknown agent %s, skipping", agent_name)
                return AgentResult(agent=agent_name, task=step.task, result="", error=f"Unknown agent: {agent_name}")

            await self.queue.put(
                make_task_update("supervisor", agent_name, step.task, "running")
            )

            agent_start = time.time()
            step_context = _build_step_context(step)
            try:
                if agent_name in self.acp_agents:
                    tool = ACPSubAgentTool(
                        agent_id=agent_name,
                        acp_cli_id=self.acp_agents[agent_name],
                        context=step_context,
                    )
                else:
                    tool = SubAgentTool(
                        agent_id=agent_name,
                        config=self.config,
                        context=step_context,
                    )
                result_text = await tool._arun(step.task)
            except Exception as e:
                logger.error("[Dispatch] agent %s error: %s", agent_name, e)
                await self.queue.put(
                    make_task_update("supervisor", agent_name, step.task, "failed")
                )
                return AgentResult(agent=agent_name, task=step.task, result="", error=str(e))

            if not result_text.strip():
                logger.warning("[Dispatch] agent %s returned empty result", agent_name)
                await self.queue.put(
                    make_error(agent_name, f"Agent {agent_name} returned no output")
                )
                await self.queue.put(
                    make_task_update("supervisor", agent_name, step.task, "failed")
                )
                return AgentResult(agent=agent_name, task=step.task, result="", error="Agent returned no output")

            if _is_echo_output(step.task, result_text):
                logger.warning("[Dispatch] agent %s echoed task instead of executing", agent_name)
                await self.queue.put(
                    make_error(agent_name, f"Agent {agent_name} repeated the task instead of executing it")
                )
                await self.queue.put(
                    make_task_update("supervisor", agent_name, step.task, "failed")
                )
                return AgentResult(agent=agent_name, task=step.task, result="", error="Agent echoed task, did not execute")

            elapsed = int((time.time() - agent_start) * 1000)
            prev_tokens = self._tokens.get(agent_name, {})
            self._tokens[agent_name] = {
                "input": prev_tokens.get("input", 0) + _estimate_tokens(step.task),
                "output": prev_tokens.get("output", 0) + _estimate_tokens(result_text),
                "ms": prev_tokens.get("ms", 0) + elapsed,
            }

            self._agent_calls += 1
            await self.queue.put(make_message(agent_name, result_text))
            await self.queue.put(
                make_task_update("supervisor", agent_name, step.task, "completed")
            )
            return AgentResult(agent=agent_name, task=step.task, result=result_text, elapsed_ms=elapsed)

        # Build DAG from depends_on (indices "0", "1", ...)
        executed_indices: set[str] = set()
        while len(executed_indices) < len(tasks):
            batch: list[tuple[int, Step]] = []
            for i, s in enumerate(tasks):
                idx = str(i)
                if idx in executed_indices:
                    continue
                if all(d in executed_indices for d in s.depends_on):
                    batch.append((i, s))
            if not batch:
                batch = [(i, s) for i, s in enumerate(tasks) if str(i) not in executed_indices]
                if not batch:
                    break

            batch_results = await asyncio.gather(*[_run_step(s) for _, s in batch], return_exceptions=True)
            for (idx, step), r in zip(batch, batch_results):
                if isinstance(r, Exception):
                    errors.append(str(r))
                elif isinstance(r, AgentResult):
                    results[r.agent] = r
                    if r.error:
                        errors.append(f"{r.agent}: {r.error}")
                    executed_indices.add(str(idx))

        return {"results": results, "errors": errors}

    # ── Node: Synthesize ─────────────────────────────────────

    async def _synthesize_node(self, state: GraphState) -> dict:
        task = state.task
        results = state.results
        errors = state.errors

        if not results:
            review_decision = "reject"
            return {"review_decision": review_decision, "review_feedback": "No results to review"}

        results_text = "\n\n".join(
            f"**{r.agent}** ({r.task}):\n{r.result[:2000]}"
            for r in results.values()
        )
        prompt = AUDITOR_PROMPT.format(task=task, results=results_text)

        node_start = time.time()
        review_text = ""
        logger.info("[LLM] review request: %.2000s", prompt)
        async for chunk in self.model.astream([{"role": "user", "content": prompt}]):
            if chunk.content:
                review_text += chunk.content
        logger.info("[LLM] review response (%d chars): %.2000s", len(review_text), review_text)

        prev = self._tokens.get("review", {})
        self._tokens["review"] = {
            "input": prev.get("input", 0) + _estimate_tokens(prompt),
            "output": prev.get("output", 0) + _estimate_tokens(review_text),
            "ms": prev.get("ms", 0) + int((time.time() - node_start) * 1000),
        }

        agent_outputs = {r.agent: r.result for r in results.values()}
        await self.queue.put(make_audit_summary("supervisor", review_text, agent_outputs=agent_outputs))

        review_lower = review_text.lower()
        if "reject" in review_lower:
            review_decision = "reject"
        elif "revise" in review_lower:
            review_decision = "revise"
        else:
            review_decision = "approve"

        return {
            "review_decision": review_decision,
            "review_feedback": review_text,
        }

    # ── Node: Reflect ────────────────────────────────────────

    async def _reflect_node(self, state: GraphState) -> dict:
        plan_text = state.plan.model_dump_json() if state.plan else ""
        results_text = json.dumps(
            {k: {"result": v.result[:200], "error": v.error} for k, v in (state.results or {}).items()},
            ensure_ascii=False,
        )
        prompt = REFLECT_PROMPT.format(
            task=state.task,
            plan=plan_text,
            results=results_text,
            errors=json.dumps(state.errors, ensure_ascii=False),
            review_decision=state.review_decision,
        )

        reflect_text = ""
        logger.info("[LLM] reflect request: %.2000s", prompt)
        async for chunk in self.model.astream([{"role": "user", "content": prompt}]):
            if chunk.content:
                reflect_text += chunk.content
        logger.info("[LLM] reflect response (%d chars): %.2000s", len(reflect_text), reflect_text)

        try:
            patterns_data = json.loads(reflect_text)
            if isinstance(patterns_data, list):
                for item in patterns_data:
                    ap = AntiPattern(**item)
                    save_anti_pattern(ap)
        except Exception:
            pass

        constraints = load_constraints()
        return {"anti_patterns": [], "constraints": constraints}

    # ── Routing ──────────────────────────────────────────────

    def _route_from_plan(self, state: GraphState) -> str:
        if state.plan and (state.plan.auto_approve or len(state.plan.steps) <= 1):
            return "dispatch"
        return "wait"

    def _route_from_synthesize(self, state: GraphState) -> str:
        decision = state.review_decision
        state.step_count = getattr(state, "step_count", 0) + 1

        if decision == "revise" and state.step_count >= state.max_revisions:
            return "approve"
        if state.step_count >= state.max_steps:
            return "approve"

        if decision == "reject":
            return "reject"
        if decision == "revise":
            return "revise"
        return "approve"

    # ── Fallback plan parser ─────────────────────────────────

    @staticmethod
    def _parse_plan_fallback(plan_text: str) -> list[Step]:
        import re
        results: list[Step] = []
        pattern = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)
        for m in pattern.finditer(plan_text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            results.append(Step(agent=agent_name, task=task))
        return results

    # ── Plan display formatting ──────────────────────────────

    @staticmethod
    def _format_plan_display(plan: Plan) -> str:
        """将结构化 Plan 渲染为可读的 Markdown (中文),包含流程、推理、产物。"""
        parts: list[str] = []
        parts.append("## 📋 执行计划\n")
        for i, step in enumerate(plan.steps):
            deps = f" (依赖: {', '.join(step.depends_on)})" if step.depends_on else ""
            parts.append(f"### {i + 1}. **{step.agent}**{deps}")
            parts.append(f"{step.task}\n")
        if plan.reasoning:
            parts.append("---\n")
            parts.append(f"### 💡 推理说明\n{plan.reasoning}")
        return "\n".join(parts)

    # ── Graph Construction ───────────────────────────────────

    def _build_graph(self):
        builder = StateGraph(GraphState)

        builder.add_node("perceive", self._perceive_node)
        builder.add_node("plan", self._plan_node)
        builder.add_node("wait", self._wait_node)
        builder.add_node("dispatch", self._dispatch_node)
        builder.add_node("synthesize", self._synthesize_node)
        builder.add_node("reflect", self._reflect_node)

        builder.set_entry_point("perceive")
        builder.add_edge("perceive", "plan")
        builder.add_conditional_edges(
            "plan",
            self._route_from_plan,
            {"dispatch": "dispatch", "wait": "wait"},
        )
        builder.add_edge("wait", "dispatch")
        builder.add_edge("dispatch", "synthesize")
        builder.add_conditional_edges(
            "synthesize",
            self._route_from_synthesize,
            {
                "approve": "reflect",
                "revise": "plan",
                "reject": "__end__",
            },
        )
        builder.add_edge("reflect", "__end__")

        checkpointer = MemorySaver()
        return builder.compile(checkpointer=checkpointer)

    # ── Main Entry ───────────────────────────────────────────

    async def run(
        self,
        task: str,
        history: list[dict] | None = None,
        summary: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        start_time = time.time()
        self.queue = asyncio.Queue()
        graph_app = self._build_graph()

        initial = GraphState(
            task=task,
            history=history or [],
            history_summary=summary or "",
        )

        thread_id = str(uuid.uuid4())
        thread_config = {"configurable": {"thread_id": thread_id}}

        run_task = asyncio.create_task(
            graph_app.ainvoke(initial, config=thread_config)
        )

        final_state = None
        interrupted = False
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
                final_state = done_fut.result()
                if isinstance(final_state, dict) and "__interrupt__" in final_state:
                    interrupted = True
                    plan_data = final_state.get("plan")
                    plan_json = plan_data.model_dump() if isinstance(plan_data, Plan) else None
                    self._interrupted_threads[thread_id] = graph_app
                    yield {"type": "interrupt", "data": {
                        "thread_id": thread_id,
                        "plan": plan_json,
                    }}
                break
            if queue_fut in done:
                yield await queue_fut

        if interrupted:
            return

        elapsed = int((time.time() - start_time) * 1000)
        yield make_metrics("supervisor", {
            "elapsed_ms": elapsed,
            "agent_calls": self._agent_calls,
            "tokens": self._tokens,
        })
        yield make_done()

    # ── Resume ───────────────────────────────────────────────

    async def resume(
        self,
        thread_id: str,
        decision: str,
        feedback: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        graph_app = self._interrupted_threads.get(thread_id)
        if not graph_app:
            raise ValueError(f"No interrupted thread: {thread_id}")

        thread_config = {"configurable": {"thread_id": thread_id}}
        self.queue = asyncio.Queue()

        if decision == "approve":
            cmd = Command(resume="approved")
        elif decision == "revise":
            graph_app.update_state(thread_config, {
                "plan": None,
                "review_feedback": feedback,
            })
            cmd = Command(resume="revised")
        elif decision == "reject":
            graph_app.update_state(thread_config, {
                "review_decision": "reject",
            })
            cmd = Command(resume="rejected")
        else:
            raise ValueError(f"Unknown decision: {decision}")

        run_task = asyncio.create_task(
            graph_app.ainvoke(cmd, config=thread_config)
        )

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
                done_fut.result()  # propagate any exception
                break
            if queue_fut in done:
                yield await queue_fut

        yield make_metrics("supervisor", {
            "elapsed_ms": 0,
            "agent_calls": self._agent_calls,
            "tokens": self._tokens,
        })
        yield make_done()
        self._interrupted_threads.pop(thread_id, None)
