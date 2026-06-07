"""Orchestrator — 5-node LangGraph StateGraph (plan→wait→dispatch→synthesize→reflect).

Uses astream() with stream_mode=['values','custom','messages'] and
StreamWriter for custom events. Workflows are compiled subgraphs.
Persistence via SqliteSaver.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.types import Command, StreamWriter, interrupt

from src.agent import models as _models
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.events import (
    make_audit_summary,
    make_done,
    make_error,
    make_message,
    make_metrics,
    make_plan,
    make_task_update,
    make_thinking,
    make_thinking_done,
    make_thinking_start,
)
from src.agent.orchestrator.agent_node import AgentNode
from src.agent.orchestrator.planner import (
    AgentResult,
    AntiPattern,
    GraphState,
    Plan,
    Step,
    build_agent_descriptions,
    build_step_context,
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
from src.agent.workflow.graph_config_manager import get_graph_config_manager
from src.agent.workflow.subgraph_factory import (
    build_workflow_subgraph,
    parent_to_sub,
    sub_to_parent,
)

logger = logging.getLogger(__name__)

_CHECKPOINT_DB = "memory/langgraph_checkpoints.db"
_THREAD_CACHE: dict[str, dict[str, Any]] = {}

# Register Plan/AgentResult for msgpack checkpoint serialization
allowed_msgpack_modules: set[Any] = set()
allowed_msgpack_modules.add(Plan)
allowed_msgpack_modules.add(AgentResult)


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) * 1.5))


def _is_echo_output(task: str, result: str) -> bool:
    task_clean = task.strip().lower()
    result_clean = result.strip().lower()
    if len(task_clean) < 10:
        return False
    if task_clean not in result_clean:
        return False
    return len(result_clean) < len(task_clean) * 3


class Orchestrator:
    """多 agent 编排器 — 5-node StateGraph with subgraph workflows."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.model = _models.resolve_model(config)
        self.sub_agents: dict[str, dict] = {}
        self.acp_agents: dict[str, str] = {}
        self._tokens: dict[str, dict[str, int]] = {}
        self._agent_calls: int = 0
        self._load_agent_configs()

    def _track_tokens(self, agent: str, input_text: str, output_text: str, elapsed_ms: int | float):
        prev = self._tokens.get(agent, {})
        self._tokens[agent] = {
            "input": prev.get("input", 0) + _estimate_tokens(input_text),
            "output": prev.get("output", 0) + _estimate_tokens(output_text),
            "ms": prev.get("ms", 0) + int(elapsed_ms),
        }
        self._agent_calls += 1

    def _log_llm_request(self, label: str, messages: list[dict], extra: dict | None = None):
        """Log full LLM request context for debugging."""
        est_tokens = _estimate_tokens(" ".join(str(m.get("content", "")) for m in messages))
        logger.info("=" * 60 + " LLM REQUEST " + "=" * 60)
        logger.info("[LLM-REQ] %s | model=%s | messages=%d | est_tokens=%d",
                     label, getattr(self.model, 'model_name', '?'), len(messages), est_tokens)
        for i, m in enumerate(messages):
            role = m.get("role", "?")
            content = str(m.get("content", ""))
            logger.info("[LLM-REQ] [%d] %s (%d chars):\n%s", i, role, len(content), content)
        if extra:
            logger.info("[LLM-REQ] extra: %s", json.dumps(extra, ensure_ascii=False))
        logger.info("=" * 60 + " END REQUEST " + "=" * 58)

    def _log_llm_response(self, label: str, response_text: str, elapsed: float):
        """Log full LLM response for debugging."""
        est_tokens = _estimate_tokens(response_text)
        logger.info("[LLM-RESP] %s | elapsed=%.2fs | chars=%d | est_tokens=%d",
                     label, elapsed, len(response_text), est_tokens)
        logger.info("[LLM-RESP] content:\n%s", response_text)

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

    # ── Node: Plan ───────────────────────────────────────────

    async def _plan_node(self, state: GraphState, writer: StreamWriter) -> dict:
        task = state.task
        constraints = state.constraints or load_constraints()

        parts: list[str] = []
        if state.history:
            for msg in state.history:
                if isinstance(msg, dict):
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if content:
                        parts.append(f"[{role}] {content}")
        if state.results:
            parts.append("")
            parts.append("[Previous cycle agent outputs]")
            for r in state.results.values():
                label = f"[{r.agent}] task: {r.task}"
                snippet = (r.result[:1000] + "...") if len(r.result) > 1000 else r.result
                parts.append(f"{label}\n{snippet}")
                if r.error:
                    parts.append(f"  error: {r.error}")
        history_summary = "\n".join(parts) if parts else f"Task: {task}"

        writer(make_thinking_start("supervisor"))

        agent_descriptions = build_agent_descriptions()
        experiences = load_experiences()

        feedback_section = ""
        if state.review_feedback:
            feedback_section = f"\nUser revision feedback:\n{state.review_feedback}\n"

        constraints_section = ""
        if constraints:
            constraints_section = "\nConstraints from prior sessions:\n" + "\n".join(f"- {c}" for c in constraints)

        # Inject workflow descriptions for LLM-aware step generation
        wf_descs = self._build_workflow_descriptions()
        prompt = SUPERVISOR_PLAN_PROMPT_V2.format(
            agent_descriptions=agent_descriptions,
            experiences=experiences if experiences else "No prior experiences.",
            constraints=constraints_section,
            feedback=feedback_section,
        )
        if wf_descs:
            prompt = prompt + f"\n\nAvailable workflows:\n{wf_descs}"

        messages = [{"role": "system", "content": prompt}]
        if history_summary:
            messages.append({"role": "user", "content": f"Context:\n{history_summary}\n\nTask: {task}"})
        else:
            messages.append({"role": "user", "content": f"Task: {task}"})

        node_start = time.time()
        plan_text = ""
        thinking_accum = ""
        writer(make_thinking("supervisor", "正在分析任务并制定计划..."))
        self._log_llm_request("plan", messages, {"workflows": wf_descs, "task": task})
        async for chunk in self.model.astream(messages):
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                thinking_accum += reasoning
                reasoning_text = "".join(thinking_accum.split(".")[-2:]) if "." in thinking_accum else thinking_accum
                writer(make_thinking("supervisor", reasoning_text[:500]))
            if chunk.content:
                plan_text += chunk.content
        elapsed = time.time() - node_start
        self._log_llm_response("plan", plan_text, elapsed)

        input_text = " ".join(str(m.get("content", "")) for m in messages)
        self._track_tokens("supervisor", input_text, plan_text, time.time() - node_start)

        writer(make_thinking_done("supervisor"))

        plan = self._parse_plan_json(plan_text)

        if plan.direct_reply:
            writer(make_message("supervisor", plan.direct_reply))
            return {"plan": plan, "direct_reply": plan.direct_reply, "history_summary": history_summary}

        plan_display = self._format_plan_display(plan)
        writer(make_plan(
            "supervisor", plan_display,
            steps=[s.model_dump() for s in plan.steps],
            plan_json=plan.model_dump_json(),
        ))

        return {"plan": plan, "history_summary": history_summary}

    def _build_workflow_descriptions(self) -> str:
        try:
            gcm = get_graph_config_manager()
            workflows = gcm.get_enabled_graphs()
            if not workflows:
                return ""
            lines: list[str] = []
            for wf in workflows:
                wf_id = wf.get("id", "")
                name = wf.get("name", wf_id)
                desc = wf.get("description", "")
                nodes = wf.get("nodes", [])
                node_names = [n.get("name", n.get("id", "")) for n in nodes if n.get("type") != "finish"]
                steps_desc = " → ".join(node_names) if node_names else ""
                lines.append(f"- **workflow:{wf_id}**: {name}")
                lines.append(f"  用途: {desc}")
                if steps_desc:
                    lines.append(f"  流程: {steps_desc}")
                lines.append("  优势: 自动传递上下文、内置审批门控、状态持久化")
            return "\n".join(lines)
        except Exception:
            return ""

    # ── Node: Wait (interrupt point) ─────────────────────────

    async def _wait_node(self, state: GraphState, writer: StreamWriter) -> dict:
        plan_json = state.plan.model_dump() if state.plan else {}
        writer(make_plan(
            "supervisor", "",
            steps=plan_json.get("steps", []),
            plan_json=json.dumps(plan_json, ensure_ascii=False),
        ))
        interrupt({"plan": plan_json})
        return {}

    # ── Node: Dispatch (routing engine) ───────────────────────

    async def _dispatch_node(self, state: GraphState, writer: StreamWriter) -> Command:
        plan = state.plan
        if not plan or not plan.steps:
            return Command(goto="synthesize")

        executed = set(state.executed_indices)
        tasks = plan.steps

        for i, s in enumerate(tasks):
            idx = str(i)
            if idx in executed:
                continue
            if all(d in executed for d in s.depends_on):
                target = s.agent
                logger.info("[Dispatch] step[%d] → %s | task: %s | depends_on: %s",
                             i, target, s.task, s.depends_on)
                if target in self.acp_agents or target in self.sub_agents:
                    return Command(goto=target, update={"current_step_idx": idx})
                if target.startswith("workflow:"):
                    wf_node = f"wf_{target.split(':', 1)[1]}"
                    return Command(goto=wf_node, update={"current_step_idx": idx})
                logger.warning("[Dispatch] unknown agent %s, skipping", target)
                executed.add(idx)
                return Command(goto="dispatch", update={"executed_indices": list(executed)})

        return Command(goto="synthesize")

    # ── Generic agent execution node ─────────────────────────

    async def _run_step_node(self, state: GraphState, writer: StreamWriter) -> dict:
        step_idx = state.current_step_idx
        if not step_idx or not state.plan:
            return {}

        tasks = state.plan.steps
        try:
            step = tasks[int(step_idx)]
        except (IndexError, ValueError):
            return {"errors": state.errors + [f"Invalid step index: {step_idx}"]}

        agent_name = step.agent
        history_summary = state.history_summary
        step_index_map = {str(i): s for i, s in enumerate(tasks)}

        logger.info("[RunStep] step[%s] agent=%s | task: %s",
                     step_idx, agent_name, step.task)
        writer(make_task_update("supervisor", agent_name, step.task, "running"))
        agent_start = time.time()
        step_context = build_step_context(step, step_index_map, state.results, history_summary)
        logger.info("[RunStep] step[%s] context (%d chars):\n%s",
                     step_idx, len(step_context), step_context)

        try:
            if agent_name in self.acp_agents:
                tool = ACPSubAgentTool(
                    agent_id=agent_name, acp_cli_id=self.acp_agents[agent_name], context=step_context,
                )
                result_text = await tool._arun(step.task)
            elif agent_name in self.sub_agents:
                tool = SubAgentTool(agent_id=agent_name, config=self.config, context=step_context)
                result_text = await tool._arun(step.task)
            else:
                return {"errors": state.errors + [f"Unknown agent: {agent_name}"]}
        except Exception as e:
            logger.error("[Dispatch] agent %s error: %s", agent_name, e)
            writer(make_task_update("supervisor", agent_name, step.task, "failed"))
            results = dict(state.results)
            results[agent_name] = AgentResult(agent=agent_name, task=step.task, result="", error=str(e))
            executed = list(set(state.executed_indices) | {step_idx})
            return {"results": results, "errors": state.errors + [str(e)], "executed_indices": executed}

        if not result_text.strip():
            logger.warning("[Dispatch] agent %s returned empty result", agent_name)
            writer(make_error(agent_name, f"Agent {agent_name} returned no output"))
            writer(make_task_update("supervisor", agent_name, step.task, "failed"))
            results = dict(state.results)
            results[agent_name] = AgentResult(agent=agent_name, task=step.task, result="", error="Agent returned no output")
            executed = list(set(state.executed_indices) | {step_idx})
            return {"results": results, "errors": state.errors + ["Empty result"], "executed_indices": executed}

        if _is_echo_output(step.task, result_text):
            logger.warning("[Dispatch] agent %s echoed task instead of executing", agent_name)
            writer(make_error(agent_name, f"Agent {agent_name} repeated the task instead of executing it"))
            writer(make_task_update("supervisor", agent_name, step.task, "failed"))
            results = dict(state.results)
            results[agent_name] = AgentResult(agent=agent_name, task=step.task, result="", error="Agent echoed task")
            executed = list(set(state.executed_indices) | {step_idx})
            return {"results": results, "errors": state.errors + ["Echo output"], "executed_indices": executed}

        elapsed = int((time.time() - agent_start) * 1000)
        self._track_tokens(agent_name, step.task, result_text, elapsed)
        writer(make_message(agent_name, result_text))
        writer(make_task_update("supervisor", agent_name, step.task, "completed"))

        results = dict(state.results)
        results[agent_name] = AgentResult(agent=agent_name, task=step.task, result=result_text, elapsed_ms=elapsed)
        executed = list(set(state.executed_indices) | {step_idx})
        return {"results": results, "executed_indices": executed}

    # ── Node: Synthesize ─────────────────────────────────────

    async def _synthesize_node(self, state: GraphState, writer: StreamWriter) -> dict:
        task = state.task
        results = state.results

        if not results:
            review_decision = "reject"
            return {"review_decision": review_decision, "review_feedback": "No results to review"}

        results_text = "\n\n".join(
            f"**{r.agent}** ({r.task}):\n{r.result[:2000]}"
            for r in results.values()
        )
        prompt = AUDITOR_PROMPT.format(task=task, results=results_text)

        node_start = time.time()
        self._log_llm_request("auditor", [{"role": "user", "content": prompt}],
                              {"task": task, "result_agents": list(results.keys())})
        auditor = AgentNode("auditor", self.config)
        review_text = await auditor.call(prompt, writer)
        elapsed = time.time() - node_start
        self._log_llm_response("auditor", review_text, elapsed)

        self._track_tokens("auditor", prompt, review_text, elapsed)

        agent_outputs = {r.agent: r.result for r in results.values()}
        writer(make_audit_summary("auditor", review_text, agent_outputs=agent_outputs))

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

    async def _reflect_node(self, state: GraphState, writer: StreamWriter) -> dict:
        plan_text = state.plan.model_dump_json() if state.plan else ""
        results_text = json.dumps(
            {k: {"result": v.result[:200], "error": v.error} for k, v in (state.results or {}).items()},
            ensure_ascii=False,
        )

        messages_text = ""
        if state.session_id and state.task_id:
            from src.agent.orchestrator.planner import load_messages_for_reflect
            messages_text = load_messages_for_reflect(
                session_id=state.session_id,
                task_id=state.task_id,
                max_messages=100,
            )

        prompt = REFLECT_PROMPT.format(
            task=state.task,
            plan=plan_text,
            results=results_text,
            errors=json.dumps(state.errors, ensure_ascii=False),
            review_decision=state.review_decision,
            messages=messages_text or "No messages available.",
        )
        messages = [{"role": "user", "content": prompt}]

        reflect_text = ""
        node_start = time.time()
        self._log_llm_request("reflect", messages, {"task": state.task})
        async for chunk in self.model.astream(messages):
            if chunk.content:
                reflect_text += chunk.content
        elapsed = time.time() - node_start
        self._log_llm_response("reflect", reflect_text, elapsed)

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
        if state.direct_reply:
            return "__end__"
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

    # ── Plan JSON parser ────────────────────────────────────

    @staticmethod
    def _parse_plan_json(plan_text: str) -> Plan:
        clean = plan_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1] if "\n" in clean else clean
            clean = clean.rsplit("```", 1)[0] if "```" in clean else clean
            clean = clean.strip()

        if not clean.startswith("{"):
            brace = clean.find("{")
            if brace >= 0:
                clean = clean[brace:]
                close = clean.rfind("}")
                if close >= 0:
                    clean = clean[: close + 1]

        if clean.startswith("{"):
            try:
                raw_dict = json.loads(clean)
                for s in raw_dict.get("steps", []):
                    s["depends_on"] = [str(d) for d in s.get("depends_on", [])]
                return Plan(**raw_dict)
            except Exception:
                pass

        steps = Orchestrator._parse_plan_fallback(plan_text)
        m = re.search(r'"reasoning"\s*:\s*"([^"]+)"', plan_text)
        reasoning = m.group(1) if m else ""
        return Plan(steps=steps, reasoning=reasoning)

    @staticmethod
    def _parse_plan_fallback(plan_text: str) -> list[Step]:
        results: list[Step] = []
        pattern = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)
        for m in pattern.finditer(plan_text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            results.append(Step(agent=agent_name, task=task))
        return results

    @staticmethod
    def _format_plan_display(plan: Plan) -> str:
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

    async def _build_graph(self):
        builder = StateGraph(GraphState)

        # Core graph nodes
        builder.add_node("plan", self._plan_node)
        builder.add_node("wait", self._wait_node)
        builder.add_node("dispatch", self._dispatch_node)

        # Register each sub-agent as an individual node
        for agent_id in self.sub_agents:
            builder.add_node(agent_id, self._run_step_node)

        # Register each ACP agent as an individual node
        for agent_id in self.acp_agents:
            builder.add_node(agent_id, self._run_step_node)

        # Register workflow subgraphs (wrapped for state mapping)
        try:
            gcm = get_graph_config_manager()
            for wf in gcm.get_enabled_graphs():
                wf_id = wf.get("id", "")
                subgraph = build_workflow_subgraph(wf, self.config)

                async def _wf_wrapper(state: GraphState, writer: StreamWriter, _sg=subgraph, _id=wf_id) -> dict:
                    sub_state = parent_to_sub(state)
                    sub_config = {"configurable": {"thread_id": f"wf_{_id}_{uuid.uuid4().hex[:8]}"}}
                    final: Any = None
                    async for mode, data in _sg.astream(sub_state, sub_config, stream_mode=["values", "custom"]):
                        if mode == "custom" and isinstance(data, dict) and data.get("type"):
                            writer(data)
                        elif mode == "values":
                            final = data
                    return sub_to_parent(final) if final else {}

                builder.add_node(f"wf_{wf_id}", _wf_wrapper)
                builder.add_edge(f"wf_{wf_id}", "dispatch")
        except Exception as e:
            logger.warning("Failed to register workflow subgraphs: %s", e)

        builder.add_node("synthesize", self._synthesize_node)
        builder.add_node("reflect", self._reflect_node)

        # Entry point
        builder.set_entry_point("plan")

        # Plan → dispatch/wait/end
        builder.add_conditional_edges(
            "plan",
            self._route_from_plan,
            {"dispatch": "dispatch", "wait": "wait", "__end__": "__end__"},
        )
        builder.add_edge("wait", "dispatch")

        # Dispatch → agent nodes (dynamic routing via Command)
        all_agent_targets = set(self.sub_agents.keys()) | set(self.acp_agents.keys())
        for agent_id in all_agent_targets:
            builder.add_edge(agent_id, "dispatch")

        # Dispatch → synthesize (when no more steps)
        builder.add_edge("dispatch", "synthesize")

        # Synthesize → reflect/plan/end
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

        from pathlib import Path

        import aiosqlite
        Path(_CHECKPOINT_DB).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(_CHECKPOINT_DB)
        checkpointer = AsyncSqliteSaver(conn)
        return builder.compile(checkpointer=checkpointer)

    # ── Event stream adapter ─────────────────────────────────

    async def _stream_events(
        self,
        graph_app: Any,
        initial: GraphState | Command,
        config: dict,
    ) -> AsyncIterator[dict[str, Any]]:
        """Core event loop: drives graph via astream and maps to SSE.

        Yields:
            Our SSE event dicts (same format as before).
        """
        async for ns, mode, data in graph_app.astream(
            initial,
            config,
            stream_mode=["values", "custom"],
            subgraphs=True,
        ):
            if mode == "custom":
                yield data
            elif mode == "values":
                pass  # Interrupt detection handled by run() after stream ends

    # ── Main Entry ───────────────────────────────────────────

    async def run(
        self,
        task: str,
        history: list[dict] | None = None,
        summary: str = "",
        task_id: str = "",
        session_id: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        start_time = time.time()
        self._tokens = {}
        self._agent_calls = 0
        graph_app = await self._build_graph()

        initial = GraphState(
            task=task,
            history=history or [],
            history_summary=summary or "",
            task_id=task_id,
            session_id=session_id,
        )

        thread_id = str(uuid.uuid4())
        thread_config = {"configurable": {"thread_id": thread_id}}

        # Drive the graph to completion
        async for event in self._stream_events(graph_app, initial, thread_config):
            yield event

        # Check for interrupt
        state = await graph_app.aget_state(thread_config)
        if state.next:
            plan_data = state.values.get("plan")
            plan_json = plan_data.model_dump() if hasattr(plan_data, "model_dump") else None
            _THREAD_CACHE[thread_id] = {"graph": graph_app, "config": thread_config}
            yield make_interrupt(data={
                "thread_id": thread_id,
                "plan": plan_json,
            })
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
        task_id: str = "",
        session_id: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        cache_entry = _THREAD_CACHE.get(thread_id)
        if not cache_entry:
            raise ValueError(f"No interrupted thread: {thread_id}")

        graph_app = cache_entry["graph"]
        thread_config = cache_entry["config"]
        self._tokens = {}
        self._agent_calls = 0

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

        async for event in self._stream_events(graph_app, cmd, thread_config):
            yield event

        yield make_metrics("supervisor", {
            "elapsed_ms": 0,
            "agent_calls": self._agent_calls,
            "tokens": self._tokens,
        })
        yield make_done()
        _THREAD_CACHE.pop(thread_id, None)


# Need to import make_interrupt at module level for use in _stream_events
from src.agent.events import make_interrupt  # noqa: E402, F811
