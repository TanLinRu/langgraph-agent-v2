"""Subgraph Factory — build compiled LangGraph StateGraphs from workflow configs.

Each workflow in workflows.json is converted to a CompiledStateGraph that
can be used as a standalone subgraph. A wrapper node function handles
state mapping between parent GraphState and subgraph SubGraphState.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import START, StateGraph
from langgraph.types import StreamWriter, interrupt

from src.agent.agent import Agent
from src.agent.config import AgentConfig
from src.agent.events import make_message, make_thinking_done, make_thinking_start
from src.agent.orchestrator.planner import AgentResult, SubGraphState

logger = logging.getLogger(__name__)


# ── State mapping helpers ─────────────────────────────────────


def parent_to_sub(parent_state: Any) -> SubGraphState:
    """Map parent GraphState to workflow SubGraphState (sub_ prefix)."""
    return SubGraphState(
        sub_task=getattr(parent_state, "task", ""),
        sub_history=getattr(parent_state, "history", []),
        sub_history_summary=getattr(parent_state, "history_summary", ""),
        sub_session_id=getattr(parent_state, "session_id", ""),
        sub_task_id=getattr(parent_state, "task_id", ""),
        sub_max_steps=getattr(parent_state, "max_steps", 20),
        sub_max_revisions=getattr(parent_state, "max_revisions", 3),
    )


def sub_to_parent(sub_state: SubGraphState) -> dict:
    """Map SubGraphState updates back to parent GraphState dict."""
    result: dict[str, Any] = {}
    if sub_state.sub_results:
        result["results"] = sub_state.sub_results
    if sub_state.sub_errors:
        result["errors"] = sub_state.sub_errors
    return result


# ── Subgraph builder ─────────────────────────────────────────


def build_workflow_subgraph(wf_config: dict, config: AgentConfig | None = None) -> StateGraph:
    """Convert a workflow config dict into a compiled LangGraph StateGraph.

    Uses SubGraphState (sub_ prefix) to isolate state keys from the parent graph.
    """
    builder = StateGraph(SubGraphState)
    nodes = wf_config.get("nodes", [])
    edges = wf_config.get("edges", [])

    # Register all nodes
    for node in nodes:
        node_id = node["id"]
        node_type = node.get("type", "agent")
        fn = _make_node_fn(node_id, node_type, node.get("config", {}), config)
        builder.add_node(node_id, fn)

    # Find start node (no incoming edges)
    incoming: set[str] = {e["to"] for e in edges}
    start_nodes = [n["id"] for n in nodes if n["id"] not in incoming]
    if start_nodes:
        builder.add_edge(START, start_nodes[0])

    # Wire edges
    for edge in edges:
        from_node = edge["from"]
        to_node = edge["to"]

        # Check if the target is a condition node — get its branch targets
        target_cfg = _find_node(nodes, to_node)
        if target_cfg and target_cfg.get("type") == "condition":
            branches = target_cfg.get("config", {}).get("branches", {})
            mapping = {k: v for k, v in branches.items()}
            builder.add_conditional_edges(from_node, lambda s: s, mapping)
        else:
            builder.add_edge(from_node, to_node)

    return builder.compile()


def _find_node(nodes: list[dict], node_id: str) -> dict | None:
    for n in nodes:
        if n["id"] == node_id:
            return n
    return None


def _make_node_fn(
    node_id: str,
    node_type: str,
    node_config: dict,
    agent_config: AgentConfig | None,
) -> Any:
    if node_type == "agent":
        return _make_agent_node(node_id, node_config, agent_config)
    elif node_type == "approval":
        return _make_approval_node(node_id, node_config)
    elif node_type == "condition":
        return _make_condition_node(node_id, node_config)
    elif node_type == "finish":
        return _make_finish_node(node_id)
    else:
        logger.warning("Unknown workflow node type: %s", node_type)
        return _make_finish_node(node_id)


def _make_agent_node(node_id: str, node_config: dict, agent_config: AgentConfig | None) -> Any:
    agent_type = node_config.get("agent_type", "single")
    agent_id = node_config.get("agent_id", "")
    task_template = node_config.get("task_template", "{task}")

    async def agent_node(state: SubGraphState, writer: StreamWriter) -> dict:
        task = task_template.replace("{task}", state.sub_task)
        for key, val in (state.sub_results or {}).items():
            task = task.replace("{" + key + "}", val.result if hasattr(val, "result") else str(val))

        writer(make_thinking_start(agent_id or node_id))

        if agent_type == "single":
            agent = Agent(agent_config or AgentConfig())
            history = _build_history(state)
            result_content = ""
            async for event in agent.run(task, history=history, summary=state.sub_history_summary):
                writer(event)
                if event.get("type") == "message":
                    result_content = event.get("data", "")
            writer(make_thinking_done(agent_id or node_id))

            results = dict(state.sub_results or {})
            results[node_id] = AgentResult(agent=agent_id or node_id, task=task, result=result_content)
            return {"sub_results": results}

        elif agent_type == "multi":
            from src.agent.orchestrator.core import Orchestrator
            orch = Orchestrator(agent_config or AgentConfig())
            result_content = ""
            async for event in orch.run(task, history=_build_history(state), summary=state.sub_history_summary):
                writer(event)
                if event.get("type") in ("message", "summary"):
                    result_content = event.get("data", "")
            writer(make_thinking_done(agent_id or node_id))

            results = dict(state.sub_results or {})
            results[node_id] = AgentResult(agent=agent_id or node_id, task=task, result=result_content)
            return {"sub_results": results}

        elif agent_type == "acp":
            try:
                from src.agent.acp_agent import get_acp_agent
                acp = get_acp_agent(agent_id)
                if acp:
                    result_content = ""
                    async for event in acp.stream(state.sub_session_id or "", task):
                        writer(event)
                        if event.get("type") == "message":
                            result_content = event.get("data", "")
                else:
                    result_content = ""
            except ImportError:
                result_content = ""
            writer(make_thinking_done(agent_id or node_id))

            results = dict(state.sub_results or {})
            results[node_id] = AgentResult(agent=agent_id or node_id, task=task, result=result_content)
            return {"sub_results": results}

        return {}

    return agent_node


def _make_approval_node(node_id: str, node_config: dict) -> Any:
    message = node_config.get("message", "Please approve to continue")

    async def approval_node(state: SubGraphState, writer: StreamWriter) -> dict:
        writer(make_message("approval", f"[Approval Required] {message}"))
        writer({
            "type": "workflow_interrupted",
            "data": {
                "node_id": node_id,
                "message": message,
                "results_so_far": {k: v.result if hasattr(v, "result") else v for k, v in (state.sub_results or {}).items()},
            },
        })
        decision = interrupt({
            "action": "approval",
            "node_id": node_id,
            "question": message,
        })
        return {"sub_review_decision": str(decision)}

    return approval_node


def _make_condition_node(node_id: str, node_config: dict) -> Any:
    condition_expr = node_config.get("condition", "")
    branches = node_config.get("branches", {})

    async def condition_node(state: SubGraphState) -> dict:
        results = state.sub_results or {}
        condition_result = "default"
        for key, val in results.items():
            val_str = val.result if hasattr(val, "result") else str(val)
            if condition_expr in val_str:
                condition_result = key
                break
        return {"sub_current_step_idx": branches.get(condition_result, branches.get("default", ""))}

    return condition_node


def _make_finish_node(node_id: str) -> Any:
    async def finish_node(state: SubGraphState, writer: StreamWriter) -> dict:
        writer(make_message("workflow", f"[Workflow Complete] Node '{node_id}' finished"))
        return {}

    return finish_node


def _build_history(state: SubGraphState) -> list:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    history = []
    if state.sub_history:
        for msg in state.sub_history:
            if isinstance(msg, dict):
                role = msg.get("type") or msg.get("role", "user")
                content = msg.get("content", "")
                if content:
                    if role in ("user", "human"):
                        history.append(HumanMessage(content=content))
                    elif role in ("assistant", "ai"):
                        history.append(AIMessage(content=content))
                    elif role == "system":
                        history.append(SystemMessage(content=content))
    return history
