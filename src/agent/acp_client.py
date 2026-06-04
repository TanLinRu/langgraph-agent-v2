"""ACP Client — communicates with external agents (OpenCode, Claude Code).

Dual-mode client:
1. Native ACP (primary): persistent JSON-RPC 2.0 over stdio via `opencode acp`
2. Run fallback: one-shot `opencode run --format json` subprocess

The native mode supports session management, streaming events, and token tracking.
"""

import asyncio
import json
import logging
import os
import shutil
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from src.agent.acp.client import ACPEvent, ACPNativeClient

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """Normalized event from external agent."""
    type: str  # "thinking" | "tool_call" | "message" | "metrics" | "plan" | "error" | "done" | "permission_request"
    data: Any = None
    agent_name: str = ""
    session_id: str = ""


class ACPClient:
    """Client for external agents — uses native ACP protocol with run fallback.

    Maintains a persistent connection to `opencode acp`. Each call to run()
    creates a new ACP session for isolation. If native mode fails, falls
    back to one-shot `opencode run --format json`.
    """

    def __init__(self, command: str, args: list[str] | None = None, timeout: int = 600, cwd: str | None = None):
        self.command = command
        self.args = args or []
        self.timeout = timeout
        self.cwd = os.path.abspath(cwd) if cwd else os.getcwd()
        self._native: ACPNativeClient | None = None
        self._connected = False
        self._active_session_id: str | None = None

    async def connect(self, message: str = ""):
        """Start persistent ACP connection.

        The message parameter is ignored in native mode (kept for backward compat).
        """
        await self._ensure_native()

    async def _ensure_native(self):
        """Ensure native ACP client is connected."""
        if self._native and self._connected:
            return
        self._native = ACPNativeClient(self.command, self.args, self.timeout)
        try:
            await self._native.connect(cwd=self.cwd)
            self._connected = True
            logger.info("[ACP] native connected, cwd=%s", self.cwd)
        except (FileNotFoundError, ConnectionError, RuntimeError, TimeoutError) as e:
            logger.warning("[ACP] native connect failed: %s", e)
            self._native = None
            self._connected = False
            raise

    async def run(self, message: str, acp_session_id: str | None = None) -> AsyncIterator[AgentEvent]:
        """Run a task via ACP. Yields AgentEvent objects.

        Tries native ACP first, optionally restoring an existing ACP session.
        Falls back to `opencode run` on failure.
        """
        if self._native and self._connected:
            try:
                async for event in self._run_native(message, acp_session_id=acp_session_id):
                    yield event
                return
            except Exception as e:
                logger.warning("[ACP] native run failed, falling back: %s", e)
                await self._disconnect_native()

        async for event in self._run_fallback(message):
            yield event

    async def _run_native(self, message: str, acp_session_id: str | None = None) -> AsyncIterator[AgentEvent]:
        """Run via native ACP protocol, reusing the active session across calls.
        The acp_session_id parameter is accepted for backward compatibility but ignored —
        sessions are tracked internally via _active_session_id.
        """
        assert self._native is not None
        if self._active_session_id:
            session_id = self._active_session_id
            logger.info("[ACP] reusing session: %s", session_id)
        else:
            session_id = await self._native.create_session(self.cwd)
            self._active_session_id = session_id
        try:
            async for acp_event in self._native.prompt(session_id, message):
                if acp_event.type == "done":
                    yield AgentEvent(type="done", session_id=session_id)
                    return
                mapped = self._map_acp_event(acp_event)
                if mapped:
                    yield mapped
        except asyncio.CancelledError:
            await self._native.cancel(session_id)
            raise
        except Exception:
            await self._native.cancel(session_id)
            raise
        # NOTE: session is NOT closed here — kept alive for reuse across calls.
        # Closed explicitly on disconnect().

    def _map_acp_event(self, event: ACPEvent) -> AgentEvent | None:
        """Map ACPEvent to AgentEvent."""
        if event.type == "message":
            return AgentEvent(type="message", data=event.data, session_id=event.session_id)
        elif event.type == "thinking":
            return AgentEvent(type="thinking", data=event.data, session_id=event.session_id)
        elif event.type == "tool_call":
            return AgentEvent(type="tool_call", data=event.data, session_id=event.session_id)
        elif event.type == "metrics":
            return AgentEvent(type="metrics", data=event.data, session_id=event.session_id)
        elif event.type == "plan":
            return AgentEvent(type="plan", data=event.data, session_id=event.session_id)
        elif event.type == "permission_request":
            return AgentEvent(type="permission_request", data=event.data, session_id=event.session_id)
        elif event.type == "error":
            return AgentEvent(type="error", data=event.data, session_id=event.session_id)
        return None

    async def _run_fallback(self, message: str) -> AsyncIterator[AgentEvent]:
        """Fallback: one-shot `opencode run --format json` subprocess."""
        logger.info("[ACP] using run fallback")
        cmd = self.command
        # Build run-mode args
        all_args = ["run", "--format", "json", "--dangerously-skip-permissions"]
        all_args.extend(self.args)
        all_args.append(message)

        # Resolve command path on Windows
        if sys.platform == 'win32':
            full_path = shutil.which(cmd)
            if full_path:
                cmd = full_path

        # .cmd/.bat files must go through cmd.exe /c (CreateProcess cannot run them directly)
        if sys.platform == 'win32' and (cmd.endswith('.cmd') or cmd.endswith('.bat')):
            all_args = ["/c", cmd] + all_args
            cmd = "cmd.exe"

        logger.info("[ACP:run] %s %s", cmd, " ".join(all_args[:5]) + "...")

        try:
            proc = await asyncio.create_subprocess_exec(
                cmd, *all_args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            yield AgentEvent(type="error", data=f"Command not found: {cmd}")
            yield AgentEvent(type="done")
            return

        assert proc.stdout is not None
        try:
            while True:
                line = await asyncio.wait_for(
                    proc.stdout.readline(),
                    timeout=self.timeout,
                )
                if not line:
                    break

                line_str = line.decode().strip()
                if not line_str:
                    continue

                try:
                    event = json.loads(line_str)
                    parsed = self._parse_run_event(event)
                    if parsed:
                        yield parsed
                except json.JSONDecodeError:
                    yield AgentEvent(type="message", data=line_str)

        except asyncio.TimeoutError:
            logger.warning("[ACP:run] timeout after %ds", self.timeout)
            yield AgentEvent(type="error", data=f"Timeout after {self.timeout}s")
        except asyncio.CancelledError:
            pass
        finally:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                proc.kill()
            except Exception:
                pass

        yield AgentEvent(type="done")

    def _parse_run_event(self, event: dict) -> AgentEvent | None:
        """Parse an OpenCode run-mode JSON event into AgentEvent."""
        event_type = event.get("type", "")
        part = event.get("part", {})

        if event_type == "step_start":
            return AgentEvent(type="thinking", data="[Step started]")

        elif event_type == "tool_use":
            tool_name = part.get("tool", "")
            state = part.get("state", {})
            status = state.get("status", "")
            if status == "completed":
                output = state.get("output", "")
                return AgentEvent(type="thinking", data=f"[{tool_name}] {str(output)[:300]}")
            else:
                return AgentEvent(type="tool_call", data={"name": tool_name, "args": state.get("input", {})})

        elif event_type == "text":
            text = part.get("text", "")
            if text:
                return AgentEvent(type="message", data=text)

        elif event_type == "step_finish":
            tokens = part.get("tokens", {})
            cost = part.get("cost", 0)
            return AgentEvent(type="metrics", data={
                "total_tokens": tokens.get("total", 0),
                "cost": cost,
            })

        elif event_type == "error":
            return AgentEvent(type="error", data=event.get("error", str(part)))

        return None

    async def disconnect(self):
        """Disconnect the native ACP client — closes active session then disconnects."""
        if self._native and self._connected and self._active_session_id:
            try:
                await self._native.close_session(self._active_session_id)
                logger.info("[ACP] closed session: %s", self._active_session_id)
            except Exception as e:
                logger.warning("[ACP] close_session error: %s", e)
            self._active_session_id = None
        await self._disconnect_native()

    async def _disconnect_native(self):
        if self._native:
            try:
                await self._native.disconnect()
            except Exception as e:
                logger.warning("[ACP] disconnect error: %s", e)
            self._native = None
        self._connected = False
        logger.info("[ACP] disconnected")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()
