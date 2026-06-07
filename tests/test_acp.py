"""Tests for ACP event parsing, content integrity, and downstream guards."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agent.acp.client import (
    _extract_content_text,
    _extract_tool_result,
    _is_garbled,
    _repair_content,
)

# ── _extract_content_text ─────────────────────────────────────


class TestExtractContentText:
    def test_content_array(self):
        raw = [
            {"type": "content", "content": {"type": "text", "text": "hello"}},
            {"type": "content", "content": {"type": "text", "text": " world"}},
        ]
        assert _extract_content_text(raw) == "hello\n world"

    def test_single_dict(self):
        assert _extract_content_text({"type": "text", "text": "hi"}) == "hi"

    def test_empty_list(self):
        assert _extract_content_text([]) == ""

    def test_non_text_types_skipped(self):
        raw = [
            {"type": "content", "content": {"type": "image", "url": "..."}},
            {"type": "content", "content": {"type": "text", "text": "only text"}},
        ]
        assert _extract_content_text(raw) == "only text"


# ── _repair_content ──────────────────────────────────────────


class TestRepairContent:
    def test_null_bytes_stripped(self):
        result = _repair_content("hel\x00lo")
        assert result == "hello"

    def test_unmatched_fence_truncated(self):
        text = "before\n```python\ncode\n```\nafter\n```\nincomplete"
        result = _repair_content(text)
        assert result == "before\n```python\ncode\n```\nafter"

    def test_no_fence_untouched(self):
        text = "just normal text\nwith multiple lines"
        assert _repair_content(text) == text

    def test_truncated_long_last_line(self):
        text = "normal text. " + "x" * 600
        result = _repair_content(text)
        assert len(result) < 550

    def test_empty_string(self):
        assert _repair_content("") == ""


# ── _is_garbled ──────────────────────────────────────────────


class TestIsGarbled:
    def test_null_bytes(self):
        assert _is_garbled("hel\x00lo") is True

    def test_low_printable_ratio(self):
        assert _is_garbled("abc\x01\x02\x03\x04\x05") is True

    def test_broken_marker_comment(self):
        assert _is_garbled("//\nnormal text") is True

    def test_broken_marker_star(self):
        assert _is_garbled("/*  \nnormal text") is True

    def test_clean_text_not_garbled(self):
        assert _is_garbled("Hello world. This is clean text.") is False

    def test_code_not_garbled(self):
        text = "def foo():\n    return 42\n// this is a code comment"
        assert _is_garbled(text) is False

    def test_empty_string(self):
        assert _is_garbled("") is False


# ── _extract_tool_result ─────────────────────────────────────


class TestExtractToolResult:
    def test_from_content_array(self):
        content = [
            {"type": "content", "content": {"type": "text", "text": "result line 1"}},
            {"type": "content", "content": {"type": "text", "text": "result line 2"}},
        ]
        result = _extract_tool_result(content, {"output": ""})
        assert "result line 1" in result
        assert "result line 2" in result

    def test_from_raw_output_fallback(self):
        result = _extract_tool_result([], {"output": "fallback output"})
        assert result == "fallback output"

    def test_repair_applied(self):
        content = [{"type": "content", "content": {"type": "text", "text": "hel\x00lo"}}]
        result = _extract_tool_result(content, {})
        assert result == "hello"

    def test_empty_inputs(self):
        assert _extract_tool_result([], {}) == ""


# ── _parse_notification ──────────────────────────────────────


class TestParseNotification:
    def make_msg(self, session_update: str, **update_kw) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "ses_test",
                "update": {"sessionUpdate": session_update, **update_kw},
            },
        }

    def test_agent_thought_chunk(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg("agent_thought_chunk", content={"type": "text", "text": " hello"})
        events = client._parse_notification(msg)
        assert len(events) == 1
        assert events[0].type == "thinking"
        assert events[0].data == " hello"

    def test_agent_message_chunk(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg("agent_message_chunk", content={"type": "text", "text": "reply"})
        events = client._parse_notification(msg)
        assert len(events) == 1
        assert events[0].type == "message"
        assert events[0].data == "reply"

    def test_tool_call_pending_new_protocol(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg(
            "tool_call",
            toolCallId="call_001",
            title="read",
            kind="read",
            rawInput={"filePath": "/tmp"},
            status="pending",
            locations=[{"path": "/tmp"}],
        )
        events = client._parse_notification(msg)
        assert len(events) == 1
        assert events[0].type == "tool_call"
        data = events[0].data
        assert data["name"] == "read"
        assert data["kind"] == "read"
        assert data["tool_call_id"] == "call_001"
        assert data["status"] == "pending"
        assert data["args"] == {"filePath": "/tmp"}
        assert data["locations"] == [{"path": "/tmp"}]

    def test_tool_call_backward_compat_old_fields(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg(
            "tool_call",
            toolName="old_tool",
            input={"x": 1},
            status="pending",
        )
        events = client._parse_notification(msg)
        assert len(events) == 1
        assert events[0].data["name"] == "old_tool"
        assert events[0].data["args"] == {"x": 1}

    def test_tool_call_update_in_progress(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg(
            "tool_call_update",
            toolCallId="call_001",
            title="read",
            kind="read",
            status="in_progress",
            locations=[{"path": "/tmp"}],
            rawInput={"filePath": "/tmp"},
        )
        events = client._parse_notification(msg)
        assert len(events) == 1
        data = events[0].data
        assert data["name"] == "read"
        assert data["status"] == "running"
        assert data["locations"] == [{"path": "/tmp"}]

    def test_tool_call_update_completed(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg(
            "tool_call_update",
            toolCallId="call_001",
            title="grep",
            kind="search",
            status="completed",
            content=[
                {"type": "content", "content": {"type": "text", "text": "line1\nline2"}},
            ],
            rawOutput={"output": "should not use"},
        )
        events = client._parse_notification(msg)
        assert len(events) == 1
        data = events[0].data
        assert data["name"] == "grep"
        assert data["status"] == "completed"
        assert "line1" in data["result"]
        assert data["tool_call_id"] == "call_001"

    def test_tool_call_update_error(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg(
            "tool_call_update",
            toolCallId="call_001",
            title="bash",
            status="error",
            error="Permission denied",
        )
        events = client._parse_notification(msg)
        assert len(events) == 1
        assert events[0].type == "error"
        assert "bash" in events[0].data
        assert "Permission denied" in events[0].data

    def test_usage_update(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg(
            "usage_update",
            used=1000,
            size=8000,
            cost={"amount": 0.01, "currency": "USD"},
        )
        events = client._parse_notification(msg)
        assert len(events) == 1
        assert events[0].type == "metrics"
        assert events[0].data["context_used"] == 1000

    def test_plan(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg("plan", plan="Step 1: do X")
        events = client._parse_notification(msg)
        assert len(events) == 1
        assert events[0].type == "plan"

    def test_ignored_update_types(self):
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        for typ in ("available_commands_update", "current_mode_update", "session_info_update"):
            msg = self.make_msg(typ)
            events = client._parse_notification(msg)
            assert len(events) == 0, f"{typ} should be ignored"

    def test_garbled_thought_logged(self):
        """Garbled content triggers warning but data is preserved (no loss)."""
        from src.agent.acp.client import ACPNativeClient

        client = ACPNativeClient("test_cmd")
        msg = self.make_msg("agent_thought_chunk", content={"type": "text", "text": "hel\x00lo"})
        with patch("src.agent.acp.client.logger.warning") as mock_warn:
            events = client._parse_notification(msg)
        assert len(events) == 1
        assert events[0].type == "thinking"
        assert events[0].data == "hel\x00lo"
        mock_warn.assert_called_once()


# ── _is_output_unreadable (orchestrator/tools.py) ────────────


class TestIsOutputUnreadable:
    @pytest.fixture(autouse=True)
    def _import(self):
        from src.agent.orchestrator.tools import _is_output_unreadable

        self._check = _is_output_unreadable

    def test_empty(self):
        assert self._check("") is True
        assert self._check("   ") is True
        assert self._check("short") is True

    def test_garbled_high_broken_ratio(self):
        text = "//broken\nnormal line\n//another\nand another\n//\n//\n"
        assert self._check(text) is True

    def test_valid_output(self):
        text = "def foo():\n    return 42\n\nprint(foo())"
        assert self._check(text) is False

    def test_code_with_comments_not_garbled(self):
        text = "// This is a comment\nlet x = 1;\n// Another comment\nlet y = 2;"
        assert self._check(text) is False
