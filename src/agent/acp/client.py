"""Native ACP (Agent Client Protocol) client — JSON-RPC 2.0 over stdio.

Connects to `opencode acp` for persistent agent sessions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import traceback
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ACPEvent:
    type: str
    data: Any = None
    session_id: str = ""


# ── Content Integrity Helpers ────────────────────────────────────


def _extract_content_text(content_raw: list | dict) -> str:
    """Extract plain text from ACP content array format."""
    if isinstance(content_raw, list):
        texts = []
        for item in content_raw:
            if isinstance(item, dict) and item.get("type") == "content":
                inner = item.get("content", {})
                if isinstance(inner, dict) and inner.get("type") == "text":
                    texts.append(inner.get("text", ""))
        return "\n".join(texts)
    elif isinstance(content_raw, dict) and content_raw.get("type") == "text":
        return content_raw.get("text", "")
    return ""


def _repair_content(text: str) -> str:
    """Repair common content integrity issues from chunk assembly failures."""
    if not text:
        return text
    if "\x00" in text:
        logger.warning("[ACP content] null bytes detected, stripping")
        text = text.replace("\x00", "")
    fence_count = text.count("```")
    if fence_count % 2 != 0:
        logger.warning("[ACP content] unmatched code fence (%d), truncating", fence_count)
        lines = text.split("\n")
        fence_indices = [i for i, line in enumerate(lines) if line.strip().startswith("```")]
        if fence_indices:
            last_fence = fence_indices[-1]
            text = "\n".join(lines[:last_fence])
    if text and not text.endswith("\n"):
        last_line = text.rsplit("\n", 1)[-1]
        if len(last_line) > 500:
            cut = text.rfind(". ", 0, len(text) - len(last_line) + 500)
            if cut > 0:
                text = text[:cut + 1]
    return text


def _is_garbled(text: str) -> bool:
    """Heuristic check for garbled/corrupted agent output (warn-only, no data loss)."""
    if not text:
        return False
    if "\x00" in text:
        return True
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
    if len(text) > 0 and printable / len(text) < 0.9:
        return True
    broken_markers = ["//", "/**", "/*"]
    for line in text.split("\n"):
        stripped = line.strip()
        if len(stripped) < 2:
            continue
        for marker in broken_markers:
            if stripped.startswith(marker) and not stripped.startswith(marker * 2):
                rest = stripped[len(marker):]
                if not any(c.isalpha() for c in rest):
                    return True
    return False


def _extract_tool_result(content_raw: list | dict, raw_output: dict) -> str:
    """Extract tool result text with integrity repair."""
    text = _extract_content_text(content_raw)
    if not text:
        output = raw_output.get("output", "")
        text = str(output) if output else ""
    return _repair_content(text)


# ── Native ACP Client ───────────────────────────────────────────


class ACPNativeClient:
    """Native ACP client using JSON-RPC 2.0 over stdio.

    Manages a persistent `opencode acp` subprocess.
    """

    def __init__(self, command: str, args: list[str] | None = None, timeout: int = 600):
        self.command = command
        self.args = args or []
        self.timeout = timeout
        self.proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._notification_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=0)
        self._connected = False
        self._initialized = False
        self._pending_permissions: dict[str, asyncio.Future] = {}
        self._last_event_time: float = 0.0

    async def connect(self, cwd: str | None = None):
        """Start `opencode acp` subprocess and initialize protocol."""
        all_args = ["acp"]
        if self.args:
            all_args.extend(self.args)
        if cwd:
            all_args.extend(["--cwd", cwd])

        cmd = self._resolve_command()
        logger.info("[ACPNative] starting: %s %s", cmd, " ".join(all_args))

        try:
            self.proc = await asyncio.create_subprocess_exec(
                cmd, *all_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(f"ACP command not found: {cmd}") from e

        self._connected = True
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())
        await self._initialize()

    def _resolve_command(self) -> str:
        cmd = self.command
        if sys.platform == "win32":
            import shutil
            full = shutil.which(cmd)
            if full:
                cmd = full
        return cmd

    async def _reader_loop(self):
        """Read JSON-RPC messages from stdout."""
        buf = b""
        try:
            while self._connected and self.proc and self.proc.stdout:
                try:
                    chunk = await self.proc.stdout.read(65536)
                except Exception:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        logger.warning("[ACPNative] failed to parse: %s", line[:200])
                        continue

                    logger.info("[ACPNative msg] <- %s", msg)
                    msg_id = msg.get("id")
                    if msg_id is not None and msg_id in self._pending:
                        logger.debug("[ACPNative] <- response id=%s", msg_id)
                        self._pending[msg_id].set_result(msg)
                    elif msg.get("method"):
                        logger.debug("[ACPNative] <- notification method=%s", msg.get("method"))
                        await self._notification_queue.put(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[ACPNative] reader error: %s", e)
        finally:
            self._connected = False

    async def _stderr_loop(self):
        """Log stderr output from the ACP process."""
        try:
            while self.proc and self.proc.stderr:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("[ACPNative:stderr] %s", text)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("[ACPNative] stderr reader done: %s", e)

    async def _send_request(self, method: str, params: dict | None = None) -> dict[str, Any]:
        """Send JSON-RPC request and wait for response."""
        self._request_id += 1
        req_id = self._request_id
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            req["params"] = params

        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        await self._write(req)

        try:
            result = await asyncio.wait_for(future, timeout=self.timeout)
            if "error" in result:
                err = result["error"]
                logger.warning("[ACPNative] request '%s' error: %s", method, json.dumps(err, ensure_ascii=False))
                raise RuntimeError(f"ACP error [{err.get('code', '?')}]: {err.get('message', '')}")
            r: dict[str, Any] = result.get("result", {})
            return r
        except asyncio.TimeoutError:
            raise TimeoutError(f"ACP request '{method}' timed out after {self.timeout}s")
        finally:
            self._pending.pop(req_id, None)

    async def _send_notification(self, method: str, params: dict | None = None):
        """Send JSON-RPC notification (no response expected)."""
        req: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            req["params"] = params
        await self._write(req)

    async def _send_response(self, req_id: int, result: Any = None, error: dict | None = None):
        """Send JSON-RPC response."""
        resp: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
        if error:
            resp["error"] = error
        else:
            resp["result"] = result
        await self._write(resp)

    async def _write(self, msg: dict[str, Any]):
        """Write a JSON-RPC message to stdin."""
        if not self.proc or not self.proc.stdin:
            raise ConnectionError("ACP not connected")
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        self.proc.stdin.write(data)
        await self.proc.stdin.drain()

    async def _initialize(self):
        """Perform ACP handshake."""
        result = await self._send_request("initialize", {
            "protocolVersion": 1.0,
            "clientInfo": {"name": "langgraph-agent-v2", "version": "1.0"},
            "capabilities": {},
        })
        self._initialized = True
        caps = result.get("agentCapabilities", {})
        logger.info("[ACPNative] initialized: caps=%s", json.dumps(caps, ensure_ascii=False)[:200])

    async def create_session(self, cwd: str) -> str:
        """Create a new ACP session, return session_id."""
        result = await self._send_request("session/new", {
            "cwd": os.path.abspath(cwd),
            "mcpServers": [],
        })
        sid: str = result["sessionId"]
        logger.info("[ACPNative] session created: %s", sid)
        return sid

    async def load_session(self, session_id: str, cwd: str) -> dict:
        """Load an existing ACP session by replaying history."""
        result = await self._send_request("session/load", {
            "sessionId": session_id,
            "cwd": os.path.abspath(cwd),
            "mcpServers": [],
        })
        logger.info("[ACPNative] session loaded: %s", session_id)
        return result

    async def prompt(self, session_id: str, message: str) -> AsyncIterator[ACPEvent]:
        """Send a prompt and stream ACP events with 5s polling, permission handling."""
        self._request_id += 1
        req_id = self._request_id
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": message}],
            },
        }
        future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        await self._write(req)

        self._last_event_time = asyncio.get_event_loop().time()
        idle_timeout = self.timeout + 60

        try:
            while True:
                notification_task = asyncio.create_task(self._notification_queue.get())
                done, pending = await asyncio.wait(
                    [notification_task, future],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=5,
                )

                now = asyncio.get_event_loop().time()

                if future in done:
                    notification_task.cancel()
                    result = future.result()
                    try:
                        if "error" in result:
                            err = result["error"]
                            logger.warning("[ACPNative] prompt error: %s", json.dumps(err, ensure_ascii=False))
                            yield ACPEvent(type="error", data=err.get("message", str(err)))
                        else:
                            resp = result.get("result", {})
                            usage = resp.get("usage", {})
                            if usage:
                                yield ACPEvent(type="metrics", data={
                                    "total_tokens": usage.get("totalTokens", 0),
                                    "input_tokens": usage.get("inputTokens", 0),
                                    "output_tokens": usage.get("outputTokens", 0),
                                    "reasoning_tokens": usage.get("thoughtTokens", 0),
                                    "cached_read": usage.get("cachedReadTokens", 0),
                                    "cached_write": usage.get("cachedWriteTokens", 0),
                                })
                    except Exception as e:
                        logger.error("[ACPNative] result parse error: %s\n%s", e, traceback.format_exc())
                        logger.error("[ACPNative] raw result: %s", json.dumps(result, ensure_ascii=False)[:500])
                    break

                if notification_task in done:
                    notification = notification_task.result()
                    self._last_event_time = now
                    try:
                        for event in self._parse_notification(notification):
                            if event.type == "permission_request":
                                yield event
                            else:
                                yield event
                    except Exception as e:
                        logger.error("[ACPNative] notification parse error: %s\n%s", e, traceback.format_exc())
                        logger.error("[ACPNative] raw notification: %s", json.dumps(notification, ensure_ascii=False)[:500])

                elif (now - self._last_event_time) > idle_timeout:
                    logger.warning("[ACPNative] idle timeout after %ds", idle_timeout)
                    yield ACPEvent(type="error", data=f"Idle timeout after {idle_timeout}s")
                    await self._send_notification("session/cancel", {"sessionId": session_id})
                    break

        except TimeoutError:
            logger.warning("[ACPNative] prompt timed out after %ds", self.timeout)
            yield ACPEvent(type="error", data=f"Timeout after {self.timeout}s")
            await self._send_notification("session/cancel", {"sessionId": session_id})
        except asyncio.CancelledError:
            await self._send_notification("session/cancel", {"sessionId": session_id})
            raise

        yield ACPEvent(type="done")

    # ── Tool Execution ───────────────────────────────────────

    async def _execute_tool(self, session_id: str, tool_call: dict) -> dict:
        """Execute a tool call and return the result."""
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})

        if tool_name in ("read", "read_file"):
            return await self._tool_read(tool_args)
        elif tool_name in ("write", "write_file"):
            return await self._tool_write(tool_args)
        elif tool_name in ("edit", "edit_file"):
            return await self._tool_edit(tool_args)
        elif tool_name in ("bash", "execute_code"):
            return await self._tool_bash(tool_args)
        elif tool_name in ("glob", "search_files"):
            return await self._tool_glob(tool_args)
        elif tool_name in ("grep", "search_text"):
            return await self._tool_grep(tool_args)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _tool_read(self, args: dict) -> dict:
        return {"result": f"[read] {args.get('path', '?')}"}

    async def _tool_write(self, args: dict) -> dict:
        return {"result": f"[write] {args.get('path', '?')} ({len(args.get('content', ''))} chars)"}

    async def _tool_edit(self, args: dict) -> dict:
        return {"result": f"[edit] {args.get('path', '?')}"}

    async def _tool_bash(self, args: dict) -> dict:
        return {"result": f"[bash] {args.get('command', '')[:200]}"}

    async def _tool_glob(self, args: dict) -> dict:
        return {"result": f"[glob] pattern={args.get('pattern', '?')}"}

    async def _tool_grep(self, args: dict) -> dict:
        return {"result": f"[grep] pattern={args.get('pattern', '?')}"}

    # ── Notification Parsing ─────────────────────────────────

    def _parse_notification(self, msg: dict) -> list[ACPEvent]:
        """Parse a session/update notification into ACPEvents."""
        events: list[ACPEvent] = []
        params = msg.get("params", {})
        if not isinstance(params, dict):
            return events
        session_id = params.get("sessionId", "")
        update = params.get("update", {})
        if not isinstance(update, dict):
            return events
        update_type = update.get("sessionUpdate", "")

        content_raw = update.get("content", [])
        content_list = content_raw if isinstance(content_raw, list) else [content_raw]
        content_text = "".join(c.get("text", "") for c in content_list if isinstance(c, dict) and c.get("type") == "text")

        if update_type == "agent_message_chunk":
            if content_text:
                if _is_garbled(content_text):
                    logger.warning("[ACP] garbled message chunk: %r", content_text[:100])
                events.append(ACPEvent(type="message", data=content_text, session_id=session_id))

        elif update_type == "agent_thought_chunk":
            if content_text:
                if _is_garbled(content_text):
                    logger.warning("[ACP] garbled thought chunk: %r", content_text[:100])
                events.append(ACPEvent(type="thinking", data=content_text, session_id=session_id))

        elif update_type == "tool_call":
            # Real ACP protocol: initial tool call (status=pending only)
            tool_call_id = update.get("toolCallId", "")
            name = update.get("title", update.get("toolName", ""))
            kind = update.get("kind", "")
            raw_input = update.get("rawInput", update.get("input", {}))
            status = update.get("status", "pending")
            locations = update.get("locations", [])
            if status == "pending":
                events.append(ACPEvent(type="tool_call", data={
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "kind": kind,
                    "args": raw_input,
                    "status": "pending",
                    "locations": locations,
                }, session_id=session_id))

        elif update_type == "tool_call_update":
            tool_call_id = update.get("toolCallId", "")
            name = update.get("title", update.get("toolName", ""))
            kind = update.get("kind", "")
            status = update.get("status", "")
            raw_input = update.get("rawInput", {})
            raw_output = update.get("rawOutput", {})
            if status == "in_progress":
                events.append(ACPEvent(type="tool_call", data={
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "kind": kind,
                    "status": "running",
                    "locations": update.get("locations", []),
                    "args": raw_input,
                }, session_id=session_id))
            elif status == "completed":
                result_text = _extract_tool_result(update.get("content", []), raw_output)
                events.append(ACPEvent(type="tool_call", data={
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "kind": kind,
                    "result": result_text,
                    "status": "completed",
                }, session_id=session_id))
            elif status == "error":
                error_msg = update.get("error", "Unknown error")
                events.append(ACPEvent(type="error",
                    data=f"Tool '{name}' failed: {error_msg}",
                    session_id=session_id))

        elif update_type == "usage_update":
            used = update.get("used", 0)
            size = update.get("size", 0)
            cost = update.get("cost", {})
            events.append(ACPEvent(type="metrics", data={
                "context_used": used,
                "context_size": size,
                "cost": cost.get("amount", 0),
                "currency": cost.get("currency", "USD"),
            }, session_id=session_id))

        elif update_type == "plan":
            events.append(ACPEvent(type="plan", data=str(update.get("plan", "")), session_id=session_id))

        elif update_type == "permission_request":
            events.append(ACPEvent(type="permission_request", data={
                "req_id": update.get("reqId", ""),
                "toolCall": {
                    "name": update.get("toolName", ""),
                    "args": update.get("input", {}),
                },
                "options": update.get("options", []),
            }, session_id=session_id))

        elif update_type in ("available_commands_update", "current_mode_update", "session_info_update"):
            pass

        return events

    # ── Permission ───────────────────────────────────────────

    async def resolve_permission(self, req_id: str, option_id: str) -> None:
        """Resolve a permission request by sending the chosen option."""
        fut = self._pending_permissions.get(req_id)
        if fut:
            fut.set_result(option_id)
        await self._send_notification("permission/response", {
            "reqId": req_id,
            "optionId": option_id,
        })

    async def cancel(self, session_id: str):
        """Cancel an active prompt (notification, no response)."""
        await self._send_notification("session/cancel", {"sessionId": session_id})

    async def close_session(self, session_id: str):
        """Close an ACP session."""
        try:
            await self._send_request("session/close", {"sessionId": session_id})
        except Exception as e:
            logger.warning("[ACPNative] error closing session %s: %s", session_id, e)

    async def disconnect(self):
        """Disconnect from the ACP process."""
        self._connected = False
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
        if self.proc:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.proc.kill()
                    await asyncio.wait_for(self.proc.wait(), timeout=3)
                except (asyncio.TimeoutError, ProcessLookupError):
                    pass
            except Exception:
                pass
            self.proc = None
        logger.info("[ACPNative] disconnected")
