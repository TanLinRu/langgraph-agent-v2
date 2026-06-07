"""Command Dispatcher - Parse and dispatch / commands.

This module handles user input parsing, dispatching / commands to appropriate
handlers, and falling back to direct Agent response for non-command messages.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from src.agent.agent import Agent
from src.agent.config import AgentConfig
from src.agent.events import make_done, make_error, make_message
from src.agent.workflow.context_manager import ContextManager
from src.agent.workflow.graph_config_manager import get_graph_config_manager

logger = logging.getLogger(__name__)


class CommandDispatcher:
    """Command dispatcher for / command parsing and execution."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self._agent: Agent | None = None
        self._commands = {
            "/compact": self._handle_compact,
            "/clear": self._handle_clear,
            "/new": self._handle_new,
            "/workflow": self._handle_workflow,
            "/wf": self._handle_workflow,  # Short alias
            "/eval": self._handle_eval,
        }

    def _get_agent(self) -> Agent:
        """Get or create Agent instance."""
        if self._agent is None:
            self._agent = Agent(self.config)
        return self._agent

    async def dispatch(
        self,
        session_id: str,
        user_message: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Dispatch user message to appropriate handler.

        Args:
            session_id: Session identifier
            user_message: User input message

        Yields:
            SSE events
        """
        # Load session context
        session_context = await ContextManager.load_session_context(session_id)

        # Check if message starts with /
        if user_message.startswith("/"):
            parts = user_message.split(maxsplit=2)
            cmd = parts[0].lower()

            # Get command arguments
            args = parts[1] if len(parts) > 1 else None
            params = parts[2] if len(parts) > 2 else ""

            if cmd in self._commands:
                async for event in self._commands[cmd](
                    session_id, args, params, session_context
                ):
                    yield event
                    await ContextManager.update_session(session_id, event)
                return
            else:
                # Unknown command
                yield make_error(f"Unknown command: {cmd}", session_id)
                return

        # Non-command: direct Agent response
        async for event in self._direct_response(session_id, user_message, session_context):
            yield event
            await ContextManager.update_session(session_id, event)

    async def _direct_response(
        self,
        session_id: str,
        message: str,
        context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Call Agent for direct response.

        Args:
            session_id: Session identifier
            message: User message
            context: Session context

        Yields:
            SSE events from Agent
        """
        agent = self._get_agent()

        # Convert history to LangChain messages
        from langchain_core.messages import AIMessage, HumanMessage
        history = []
        for msg in context.get("history", []):
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "human" or role == "user":
                history.append(HumanMessage(content=content))
            elif role == "ai" or role == "assistant":
                history.append(AIMessage(content=content))

        async for event in agent.run(
            message,
            history=history,
            summary=context.get("summary", ""),
        ):
            yield event

    async def _handle_workflow(
        self,
        session_id: str,
        graph_id: str | None,
        params: str,
        context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Handle /workflow command.

        Args:
            session_id: Session identifier
            graph_id: Workflow graph identifier
            params: Additional parameters (task description)
            context: Session context

        Yields:
            SSE events from workflow execution
        """
        # Handle special subcommands
        if graph_id == "list":
            async for event in self._list_workflows():
                yield event
            return

        if graph_id == "status":
            async for event in self._workflow_status(session_id):
                yield event
            return

        # Require graph_id for execution
        if not graph_id:
            yield make_error("Please specify workflow ID. Example: /workflow data_analysis", session_id)
            return

        # Route to orchestrator, which handles workflow subgraph dispatch
        from src.agent.orchestrator import Orchestrator
        task = params or context.get("summary", "") or f"Execute workflow: {graph_id}"
        history = context.get("history", [])
        summary = context.get("summary", "")
        orch = Orchestrator(self.config)
        async for event in orch.run(task, history=history, summary=summary, session_id=session_id):
            yield event

    async def _list_workflows(self) -> AsyncIterator[dict[str, Any]]:
        """List available workflows.

        Yields:
            SSE events with workflow list
        """
        graph_config_manager = get_graph_config_manager()
        workflows = graph_config_manager.get_enabled_graphs()

        if not workflows:
            yield make_message("system", "No workflows available")
            yield make_done()
            return

        lines = ["Available workflows:"]
        for wf in workflows:
            desc = wf.get("description", "")
            nodes_count = len(wf.get("nodes", []))
            lines.append(f"  - {wf['id']}: {wf.get('name', wf['id'])} ({nodes_count} nodes)")
            if desc:
                lines.append(f"    {desc}")

        yield make_message("system", "\n".join(lines))
        yield make_done()

    async def _workflow_status(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        """Show current workflow status.

        Args:
            session_id: Session identifier

        Yields:
            SSE events with workflow status
        """
        from src.agent.orchestrator.core import _THREAD_CACHE
        wf_lines = []
        for tid, entry in _THREAD_CACHE.items():
            try:
                state = entry["graph"].get_state(entry["config"])
                wf_lines.append(f"Thread: {tid[:8]}...")
                wf_lines.append(f"  Status: {'interrupted' if state.next else 'running'}")
                if state.next:
                    wf_lines.append(f"  Paused at: {', '.join(state.next)}")
            except Exception:
                continue

        if not wf_lines:
            yield make_message("system", "No active workflow")
        else:
            yield make_message("system", "\n".join(wf_lines))
        yield make_done()

    async def _handle_eval(
        self,
        session_id: str,
        args: str | None,
        params: str,
        context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Handle /eval command — regression testing and analysis.

        Subcommands:
            list       — List cases with latest status
            run        — Run all cases
            run <id>   — Run a single case
            build      — Build cases from historical sessions
            analyze    — Run 5-dimension analysis
            trend      — Show pass rate trend
            suggestions— List active optimization suggestions
        """
        from src.agent.eval.cli import handle_eval_command
        result = await handle_eval_command(args)
        yield make_message("system", result)
        yield make_done()

    async def _handle_compact(
        self,
        session_id: str,
        args: str | None,
        params: str,
        context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Handle /compact command - compress session context.

        Args:
            session_id: Session identifier

        Yields:
            SSE events
        """
        from src.agent.db.compact import compact_session

        yield make_message("system", "Compressing session context...")

        # Run compression
        summary = compact_session(session_id, keep=5)

        yield make_message("system", f"Context compressed. Summary: {summary[:200]}...")
        yield make_done()

    async def _handle_clear(
        self,
        session_id: str,
        args: str | None,
        params: str,
        context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Handle /clear command - clear all messages in current session.

        Args:
            session_id: Session identifier

        Yields:
            SSE events
        """
        from src.agent.db.messages import clear_session_messages

        yield make_message("system", "Clearing messages...")

        # Clear messages in current session (not delete the session)
        clear_session_messages(session_id)

        yield make_message("system", "Messages cleared.")
        yield make_done()

    async def _handle_new(
        self,
        session_id: str,
        args: str | None,
        params: str,
        context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Handle /new command - start new session.

        Yields:
            SSE events
        """
        from src.agent.db.sessions import create_session

        new_session_id = create_session()
        yield make_message("system", f"New session created: {new_session_id}")
        yield make_done()


# Global singleton
_command_dispatcher: CommandDispatcher | None = None


def get_command_dispatcher(config: AgentConfig | None = None) -> CommandDispatcher:
    """Get the global CommandDispatcher instance."""
    global _command_dispatcher
    if _command_dispatcher is None:
        _command_dispatcher = CommandDispatcher(config)
    return _command_dispatcher
