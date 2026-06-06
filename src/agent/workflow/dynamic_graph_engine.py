"""Dynamic Graph Engine - Execute workflow graphs with node orchestration.

This module provides the core execution engine for dynamic workflow graphs,
calling existing Agent/Orchestrator/ACP as node executors.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage

from src.agent.agent import Agent
from src.agent.config import AgentConfig
from src.agent.orchestrator._events import (
    make_done,
    make_error,
    make_message,
    make_metrics,
    make_task_update,
    make_thinking_done,
    make_thinking_start,
)
from src.agent.orchestrator.core import Orchestrator
from src.agent.workflow.checkpoint_manager import CheckpointManager
from src.agent.workflow.context_manager import ContextManager

logger = logging.getLogger(__name__)


class DynamicGraphEngine:
    """Dynamic workflow graph execution engine."""

    def __init__(self, graph_config: dict[str, Any], config: AgentConfig | None = None):
        self.graph_config = graph_config
        self.config = config or AgentConfig()
        self.graph_id = graph_config.get("id", "unknown")
        self.nodes = graph_config.get("nodes", [])
        self.edges = graph_config.get("edges", [])

        # Build node lookup
        self._node_map: dict[str, dict[str, Any]] = {n["id"]: n for n in self.nodes}

        # Build edge map: from_node -> [to_nodes]
        self._edge_map: dict[str, list[str]] = {}
        for edge in self.edges:
            from_node = edge.get("from")
            to_node = edge.get("to")
            if from_node and to_node:
                if from_node not in self._edge_map:
                    self._edge_map[from_node] = []
                self._edge_map[from_node].append(to_node)

        # Find start node (node with no incoming edges)
        all_to_nodes = {edge.get("to") for edge in self.edges}
        self._start_nodes = [n["id"] for n in self.nodes if n["id"] not in all_to_nodes]

        # Execution metrics
        self._start_time: float = 0.0
        self._step_count: int = 0

    async def execute(
        self,
        session_id: str,
        workflow_context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute workflow graph.

        Args:
            session_id: Session identifier
            workflow_context: Workflow context with task, history, etc.

        Yields:
            SSE events
        """
        self._start_time = time.time()
        state = workflow_context.copy()

        # Emit workflow start
        yield make_task_update(
            agent_name=self.graph_id,
            task_agent=self.graph_id,
            task=f"Starting workflow: {self.graph_config.get('name', self.graph_id)}",
            status="running",
        )

        # Execute from start nodes
        try:
            for start_node_id in self._start_nodes:
                async for event in self._execute_from_node(session_id, state, start_node_id):
                    yield event

            # Workflow complete
            elapsed_ms = int((time.time() - self._start_time) * 1000)
            yield make_metrics(
                agent_name=self.graph_id,
                metrics={
                    "elapsed_ms": elapsed_ms,
                    "agent_calls": self._step_count,
                    "tokens": {},
                },
            )
            yield make_message(
                agent_name="workflow",
                data=f"[Workflow Complete] {self.graph_config.get('name', self.graph_id)} finished",
            )
            yield make_done()

            # Clear checkpoint
            await CheckpointManager.clear(session_id)

        except Exception as e:
            logger.error("[DynamicGraphEngine] workflow error: %s", e)
            yield make_error(agent_name=self.graph_id, error=f"Workflow error: {e}")

            # Save error state
            state["error"] = str(e)
            await CheckpointManager.save(session_id, state)

    async def _execute_from_node(
        self,
        session_id: str,
        state: dict[str, Any],
        node_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute graph starting from a specific node.

        Args:
            session_id: Session identifier
            state: Current workflow state
            node_id: Starting node identifier

        Yields:
            SSE events
        """
        current_node_id = node_id

        while current_node_id:
            # Check if interrupted (waiting for approval)
            if state.get("is_interrupted"):
                logger.info("[DynamicGraphEngine] workflow interrupted at node %s", current_node_id)
                yield make_task_update(
                    agent_name=self.graph_id,
                    task_agent=current_node_id,
                    task="Waiting for approval",
                    status="waiting",
                )
                return

            # Get node config
            node = self._node_map.get(current_node_id)
            if not node:
                logger.error("[DynamicGraphEngine] unknown node: %s", current_node_id)
                yield make_error(agent_name=self.graph_id, error=f"Unknown node: {current_node_id}")
                return

            # Update state
            state["current_node"] = current_node_id
            self._step_count += 1

            # Emit node start
            yield make_task_update(
                agent_name=self.graph_id,
                task_agent=current_node_id,
                task=f"Executing node: {node.get('name', current_node_id)}",
                status="running",
            )

            # Execute node
            try:
                async for event in self._execute_node(session_id, state, node):
                    yield event

                # Emit node complete
                yield make_task_update(
                    agent_name=self.graph_id,
                    task_agent=current_node_id,
                    task=f"Node complete: {node.get('name', current_node_id)}",
                    status="completed",
                )

                # Save checkpoint after each node
                yield {
                    "type": "node_complete",
                    "state": state,
                    "node_id": current_node_id,
                }

            except Exception as e:
                logger.error("[DynamicGraphEngine] node error: %s - %s", current_node_id, e)
                yield make_error(agent_name=self.graph_id, error=f"Node error: {current_node_id} - {e}")
                return

            # Get next nodes
            next_nodes = self._edge_map.get(current_node_id, [])
            if not next_nodes:
                # No more edges, end this path
                break

            # For now, execute first next node (can extend for parallel execution)
            current_node_id = next_nodes[0]

    async def _execute_node(
        self,
        session_id: str,
        state: dict[str, Any],
        node: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a single node.

        Args:
            session_id: Session identifier
            state: Current workflow state
            node: Node configuration

        Yields:
            SSE events
        """
        node_type = node.get("type", "agent")

        if node_type == "agent":
            async for event in self._execute_agent_node(session_id, state, node):
                yield event

        elif node_type == "approval":
            async for event in self._execute_approval_node(session_id, state, node):
                yield event

        elif node_type == "finish":
            # Finish node - just emit completion message
            yield make_message(
                f"[Finish] Workflow completed at {node.get('name', 'finish')}",
                agent_name="workflow",
            )

        elif node_type == "condition":
            # Condition node - route based on condition
            async for event in self._execute_condition_node(session_id, state, node):
                yield event

        else:
            yield make_error(agent_name=self.graph_id, error=f"Unknown node type: {node_type}")

    async def _execute_agent_node(
        self,
        session_id: str,
        state: dict[str, Any],
        node: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute agent node - call existing Agent/Orchestrator/ACP.

        Args:
            session_id: Session identifier
            state: Current workflow state
            node: Node configuration

        Yields:
            SSE events
        """
        node_config = node.get("config", {})
        agent_type = node_config.get("agent_type", "single")
        agent_id = node_config.get("agent_id", "")

        # Build node context
        node_context = ContextManager.build_node_context(state, node)

        # Build task from template
        task = node_context.get("task", state.get("task", ""))

        # Emit thinking start
        yield make_thinking_start(agent_id or node["id"])

        try:
            if agent_type == "single":
                # Call single Agent
                agent = Agent(self.config)
                history = self._build_history(state)

                result_content = ""
                async for event in agent.run(
                    task,
                    history=history,
                    summary=state.get("summary", ""),
                ):
                    yield event
                    if event.get("type") == "message":
                        result_content = event.get("data", "")

                # Store result
                state["results"][node["id"]] = {
                    "content": result_content,
                    "agent_id": agent_id,
                }

            elif agent_type == "multi":
                # Call Orchestrator
                orchestrator = Orchestrator(self.config)
                history = self._build_history(state)

                result_content = ""
                async for event in orchestrator.run(
                    task,
                    history=history,
                    summary=state.get("summary", ""),
                ):
                    yield event
                    if event.get("type") == "message" or event.get("type") == "summary":
                        result_content = event.get("data", "")

                # Store result
                state["results"][node["id"]] = {
                    "content": result_content,
                    "agent_type": "multi",
                }

            elif agent_type == "acp":
                # Call ACP agent
                async for event in self._execute_acp_node(session_id, state, node):
                    yield event

            else:
                yield make_error(agent_name=self.graph_id, error=f"Unknown agent_type: {agent_type}")

        finally:
            yield make_thinking_done(agent_id or node["id"])

    async def _execute_acp_node(
        self,
        session_id: str,
        state: dict[str, Any],
        node: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute ACP agent node.

        Args:
            session_id: Session identifier
            state: Current workflow state
            node: Node configuration

        Yields:
            SSE events
        """
        node_config = node.get("config", {})
        acp_agent_id = node_config.get("agent_id", "")

        # Import ACP agent wrapper
        try:
            from src.agent.acp_agent import get_acp_agent

            acp_agent = get_acp_agent(acp_agent_id)
            if not acp_agent:
                yield make_error(agent_name=self.graph_id, error=f"ACP agent '{acp_agent_id}' not found")
                return

            task = ContextManager.build_node_context(state, node).get("task", "")

            async for event in acp_agent.stream(session_id, task):
                yield event
                if event.get("type") == "message":
                    state["results"][node["id"]] = {
                        "content": event.get("data", ""),
                        "agent_id": acp_agent_id,
                        "acp": True,
                    }

        except ImportError:
            yield make_error(agent_name=self.graph_id, error="ACP agent module not available")

    async def _execute_approval_node(
        self,
        session_id: str,
        state: dict[str, Any],
        node: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute approval node - pause workflow for human approval.

        Args:
            session_id: Session identifier
            state: Current workflow state
            node: Node configuration

        Yields:
            SSE events
        """
        node_config = node.get("config", {})
        approval_message = node_config.get("message", "Please approve to continue")

        # Set interrupted state
        state["is_interrupted"] = True
        state["pending_approval"] = {
            "node_id": node["id"],
            "message": approval_message,
            "results_so_far": state.get("results", {}),
        }

        # Save checkpoint
        await CheckpointManager.save(session_id, state)

        # Emit approval request
        yield make_message(
            agent_name="approval",
            data=f"[Approval Required] {approval_message}",
        )
        yield {
            "type": "workflow_interrupted",
            "state": state,
            "pending_approval": state["pending_approval"],
        }

    async def _execute_condition_node(
        self,
        session_id: str,
        state: dict[str, Any],
        node: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute condition node - route based on condition.

        Args:
            session_id: Session identifier
            state: Current workflow state
            node: Node configuration

        Yields:
            SSE events
        """
        node_config = node.get("config", {})
        condition_expr = node_config.get("condition", "")
        branches = node_config.get("branches", {})

        # Evaluate condition (simple string matching for now)
        # Can extend to support more complex expressions
        condition_result = "default"

        # Check results for condition match
        results = state.get("results", {})
        for key, value in results.items():
            if condition_expr in str(value):
                condition_result = key
                break

        # Get branch node
        next_node_id = branches.get(condition_result, branches.get("default"))

        if next_node_id:
            # Update edge map temporarily for this execution
            state["_condition_next"] = next_node_id
            yield make_message(
                f"[Condition] Routing to {next_node_id}",
                agent_name="condition",
            )
        else:
            yield make_message(
                "[Condition] No matching branch, ending workflow",
                agent_name="condition",
            )

    def _build_history(self, state: dict[str, Any]) -> list[HumanMessage]:
        """Build LangChain history from state.

        Args:
            state: Workflow state

        Returns:
            List of LangChain messages
        """
        from langchain_core.messages import AIMessage, HumanMessage

        history = []
        for msg in state.get("history", []):
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("human", "user"):
                history.append(HumanMessage(content=content))
            elif role in ("ai", "assistant"):
                history.append(AIMessage(content=content))

        return history
