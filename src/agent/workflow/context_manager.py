"""Context Manager - Unified session and workflow context management.

This module provides a unified interface for managing session context,
including history, summary, workflow state, and shared resources.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent.db.messages import load_history_with_meta, save_message
from src.agent.db.sessions import (
    get_session_project_path,
    get_session_summary,
    update_session_project_path,
    update_session_status,
)

logger = logging.getLogger(__name__)


# Context inheritance policy configuration
CONTEXT_POLICY = {
    # From session to workflow
    "inherit_from_session": {
        "history": True,       # Inherit message history
        "summary": True,       # Inherit session summary
        "project_path": True,  # Inherit working directory
        "metrics": False,      # Don't inherit metrics (workflow calculates independently)
    },
    # From workflow back to session
    "write_back_to_session": {
        "history": True,           # Add workflow messages to history
        "summary": True,           # Update session summary
        "task_updates": True,      # Record task updates
        "metrics": True,           # Merge execution metrics
        "graph_state": False,      # Don't write graph state (checkpoint stored separately)
    },
    # Workflow internal isolation
    "isolate_graph": {
        "results": True,           # Workflow results only visible within graph
        "step_count": True,        # Step count isolation
        "current_node": True,      # Current node isolation
    },
}


class ContextManager:
    """Unified context manager for session and workflow state."""

    @staticmethod
    async def load_session_context(session_id: str) -> dict[str, Any]:
        """Load complete session context.

        Args:
            session_id: Session identifier

        Returns:
            Complete context dict including history, summary, workflow state, etc.
        """
        # Load from database
        history = load_history_with_meta(session_id)
        summary = get_session_summary(session_id)
        project_path = get_session_project_path(session_id)

        return {
            "session_id": session_id,
            "history": history,
            "summary": summary,
            "project_path": project_path,
            "task_updates": [],
            "metrics": {},
            "audit_summary": "",
        }

    @staticmethod
    async def update_session(session_id: str, event: dict[str, Any]) -> None:
        """Update session context based on event.

        Args:
            session_id: Session identifier
            event: Event dict containing update data
        """
        event_type = event.get("type")

        if event_type == "message":
            # Save message to history
            content = event.get("data", "")
            agent_name = event.get("agent_name", "")
            role = "ai" if agent_name else "assistant"
            save_message(session_id, role, content, name=agent_name)

        elif event_type == "summary":
            # Update session summary
            content = event.get("data", "")
            save_message(session_id, "ai", content, name="workflow")

        elif event_type == "workflow_complete":
            update_session_status(session_id, "active")

        elif event_type == "workflow_interrupted":
            update_session_status(session_id, "waiting_approval")

        elif event_type == "error":
            # Log error and update status
            update_session_status(session_id, "error")
            save_message(session_id, "system", f"[Error] {event.get('data', '')}")

    @staticmethod
    def update_session_context(session_id: str, updates: dict[str, Any]) -> None:
        """Update session context with specific updates.

        Args:
            session_id: Session identifier
            updates: Dict of fields to update
        """
        if "project_path" in updates:
            update_session_project_path(session_id, updates["project_path"])

    @staticmethod
    def build_workflow_context(
        session_context: dict[str, Any],
        graph_id: str,
        task: str,
    ) -> dict[str, Any]:
        """Build workflow initial context from session context.

        Args:
            session_context: Loaded session context
            graph_id: Workflow graph identifier
            task: Task description from user

        Returns:
            Workflow context dict with inherited fields
        """
        workflow_context = {
            "session_id": session_context["session_id"],
            "graph_id": graph_id,
            "task": task,
            "results": {},
            "current_node": None,
            "step_count": 0,
            "is_interrupted": False,
            "pending_approval": None,
        }

        # Apply inheritance policy
        policy = CONTEXT_POLICY["inherit_from_session"]
        for field, should_inherit in policy.items():
            if should_inherit and field in session_context:
                workflow_context[field] = session_context[field]

        return workflow_context

    @staticmethod
    def build_node_context(
        workflow_context: dict[str, Any],
        node: dict[str, Any],
    ) -> dict[str, Any]:
        """Build node execution context from workflow context.

        Args:
            workflow_context: Current workflow state
            node: Node configuration

        Returns:
            Node context dict with task template applied
        """
        node_config = node.get("config", {})
        task_template = node_config.get("task_template", "{task}")

        # Format task from template
        task = task_template.format(
            task=workflow_context.get("task", ""),
            **workflow_context.get("results", {})
        )

        return {
            "session_id": workflow_context["session_id"],
            "task": task,
            "history": workflow_context.get("history", []),
            "summary": workflow_context.get("summary", ""),
            "project_path": workflow_context.get("project_path", ""),
            "node_id": node["id"],
            "agent_id": node_config.get("agent_id", ""),
            "agent_type": node_config.get("agent_type", "single"),
        }

    @staticmethod
    def merge_workflow_results(
        workflow_context: dict[str, Any],
        node_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge node execution result back to workflow context.

        Args:
            workflow_context: Current workflow state
            node_result: Node execution result

        Returns:
            Updated workflow context
        """
        # Accumulate results
        node_id = workflow_context.get("current_node")
        if node_id:
            workflow_context["results"][node_id] = node_result

        # Update step count
        workflow_context["step_count"] += 1

        return workflow_context
