"""ACP Agent — wraps an external agent (OpenCode, Claude Code) for use in the supervisor system.

Uses persistent native ACP protocol with run-mode fallback.
"""

import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from src.agent.acp_client import ACPClient
from src.agent.checkpoint import get_acp_session_id, update_acp_session_id
from src.agent.config_manager import get_config_manager

logger = logging.getLogger(__name__)


class ACPAgent:
    """Wraps an external agent with a persistent ACP connection.

    Maintains one ACPNativeClient connection per agent. Each run() call
    creates a new ACP session for isolation.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.cm = get_config_manager()
        self._client: ACPClient | None = None

    def _get_config(self) -> dict:
        """Get ACP agent configuration from acp_agents.json."""
        agent = self.cm.get_acp_agent(self.agent_id)
        if not agent:
            raise ValueError(f"ACP agent not found in config: {self.agent_id}")
        return agent

    async def _ensure_client(self) -> ACPClient:
        """Get or create the persistent ACP client."""
        if self._client is None:
            cfg = self._get_config()
            cwd = cfg.get("cwd", ".")
            if not os.path.isabs(cwd):
                cwd = os.path.abspath(cwd)
            self._client = ACPClient(
                command=cfg.get("command", self.agent_id),
                args=cfg.get("args", []),
                timeout=cfg.get("timeout", 600),
                cwd=cwd,
            )
            try:
                await self._client.connect()
            except Exception as e:
                logger.warning("[ACP] initial connect failed, will use fallback: %s", e)
        return self._client

    async def run(self, task: str, context: str = "", session_id: str = "") -> AsyncIterator[dict[str, Any]]:
        """Run a task via external agent, yielding SSE-compatible events.
        
        If session_id (chat session ID) is provided, tries to restore the
        corresponding ACP session from checkpoint for context continuity.
        """
        start_time = time.time()
        _event_count = 0

        client = await self._ensure_client()

        full_prompt = f"Context:\n{context}\n\n---\n\nTask: {task}" if context else task

        # Try to reuse existing ACP session for this chat session
        existing_acp_sid = get_acp_session_id(session_id) if session_id else None
        session_acp_id = existing_acp_sid or ""

        try:
            async for acp_event in client.run(full_prompt, acp_session_id=existing_acp_sid):
                _event_count += 1
                session_acp_id = acp_event.session_id or session_acp_id

                if acp_event.type == "thinking":
                    yield {"type": "thinking", "data": acp_event.data, "agent_name": self.agent_id}
                elif acp_event.type == "tool_call":
                    tool_data = acp_event.data if isinstance(acp_event.data, dict) else {}
                    if not tool_data.get("name"):
                        continue
                    yield {
                        "type": "tool_call",
                        "data": [tool_data],
                        "agent_name": self.agent_id,
                    }
                elif acp_event.type == "message":
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    yield {
                        "type": "message",
                        "data": acp_event.data,
                        "agent_name": self.agent_id,
                        "file_refs": _extract_file_refs(str(acp_event.data)),
                        "acp_session_id": session_acp_id or None,
                    }
                elif acp_event.type == "metrics":
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    data = acp_event.data if isinstance(acp_event.data, dict) else {}
                    yield {
                        "type": "metrics",
                        "data": {
                            "elapsed_ms": elapsed_ms,
                            "agent_calls": 1,
                            "tokens": {
                                self.agent_id: {
                                    "input": data.get("input_tokens", 0),
                                    "output": data.get("output_tokens", 0),
                                    "reasoning": data.get("reasoning_tokens", 0),
                                    "total": data.get("total_tokens", 0),
                                    "ms": elapsed_ms,
                                }
                            },
                            "cost": data.get("cost", 0),
                            "context_used": data.get("context_used", 0),
                            "context_size": data.get("context_size", 0),
                        },
                        "agent_name": self.agent_id,
                        "acp_session_id": session_acp_id or None,
                    }
                elif acp_event.type == "error":
                    yield {"type": "error", "data": str(acp_event.data), "agent_name": self.agent_id}
                elif acp_event.type == "done":
                    break

        except Exception as e:
            logger.error("[ACP] agent error: %s", e, exc_info=True)
            yield {"type": "error", "data": f"ACP agent error: {e}", "agent_name": self.agent_id}

        # Save ACP session → chat session mapping for reuse
        if session_id and session_acp_id:
            update_acp_session_id(session_id, session_acp_id)
            logger.info("[ACP] session mapping: chat=%s acp=%s", session_id, session_acp_id)

        # Signal thinking done so frontend can reset thinking state
        yield {"type": "thinking_done", "agent_name": self.agent_id}

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info("[ACP] agent=%s completed: %d events, %dms, acp_session=%s",
                    self.agent_id, _event_count, elapsed_ms, session_acp_id or "-")


def _extract_file_refs(text: str) -> list[str]:
    """Extract file paths from text."""
    import re
    patterns = [
        re.compile(r'(?:src|docs|tests|ui|memory|config)[/\\][\w./\\-]+\.\w+'),
        re.compile(r'[\w-]+\.(?:py|ts|js|vue|html|json|md|toml|yaml)'),
    ]
    refs = set()
    for p in patterns:
        refs.update(p.findall(text))
    return list(refs)


# ── ACP Agent Manager ──────────────────────────────────────────

_acp_agents: dict[str, ACPAgent] = {}


def get_acp_agent(agent_id: str) -> ACPAgent:
    """Get or create an ACP agent instance."""
    if agent_id not in _acp_agents:
        _acp_agents[agent_id] = ACPAgent(agent_id)
    return _acp_agents[agent_id]


async def cleanup_all_acp_agents():
    """Cleanup all agent connections (disconnect ACP clients)."""
    for agent_id, agent in list(_acp_agents.items()):
        try:
            if agent._client:
                await agent._client.disconnect()
        except Exception as e:
            logger.warning("[ACP] cleanup error for %s: %s", agent_id, e)
    _acp_agents.clear()
