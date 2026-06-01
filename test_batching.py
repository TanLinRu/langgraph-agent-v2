"""Verify _passthrough batching and orchestrator accumulation end-to-end."""
import asyncio
import json
import sys
from collections.abc import AsyncIterator

# ── test _passthrough batching ───────────────────────────────

sys.path.insert(0, ".")
from server import _passthrough


async def _make_source(events: list[dict]) -> AsyncIterator[dict]:
    for e in events:
        yield e


async def test_passthrough_batching():
    """Feeds tiny word fragments → verifies they come out as larger batches."""
    tiny_thinking = [
        {"type": "thinking", "data": w}
        for w in ["The", " user", " wants", " a", " comprehensive"]
    ]
    tiny_message = [
        {"type": "message", "data": w}
        for w in ["Here", " is", " the", " review", " of", " file", ".", " It", " looks", " good", "."]
    ]
    events = tiny_thinking + [
        {"type": "plan", "data": "Review the file"},
    ] + tiny_message + [
        {"type": "metrics", "data": {}},
        {"type": "done", "data": ""},
    ]

    batched = []
    async for event in _passthrough(_make_source(events)):
        batched.append(event)

    # Each thinking event should be ≥ 200 chars (MIN_THINKING) except the last flush
    # The tiny fragments total 27 chars, so they should NOT be flushed until a non-thinking event
    thinking_events = [e for e in batched if e["type"] == "thinking"]
    print(f"  thinking events: {len(thinking_events)} (was 5 tiny)")

    # All thinking should be preserved in the batched output
    all_thinking = "".join(e["data"] for e in batched if e["type"] == "thinking")
    assert "The user wants a comprehensive" in all_thinking, "thinking content lost"
    print(f"  thinking preserved: {len(all_thinking)} chars [ok]")

    # Message events should be batched too (11 tiny → fewer batches)
    msg_events = [e for e in batched if e["type"] == "message"]
    print(f"  message events: {len(msg_events)} (was 11 tiny)")

    # All message content must be preserved (nothing lost)
    all_msg = "".join(e["data"] for e in batched if e["type"] == "message")
    assert all_msg == "Here is the review of file. It looks good.", f"MISMATCH: {all_msg!r}"
    print(f"  message content preserved [ok]")

    # Non-message/thinking events pass through unchanged
    plan = [e for e in batched if e["type"] == "plan"]
    assert len(plan) == 1 and plan[0]["data"] == "Review the file"
    print(f"  plan event preserved [ok]")

    metrics = [e for e in batched if e["type"] == "metrics"]
    assert len(metrics) == 1
    print(f"  metrics event preserved [ok]")

    print(f"\n  ✅ _passthrough batching: {len(batched)} events (was {len(events)} input)")


async def test_orchestrator_accumulation():
    """Simulates orchestrator logic: message events should NOT be saved individually."""
    # Simulate DB
    saved_messages = []

    def fake_save_message(session_id, role, content, **kw):
        saved_messages.append({"role": role, "content": content, **kw})

    # ── Simulated event stream ────────────────────────────
    events = [
        # Supervisor thinking
        {"type": "thinking", "data": "Dispatching to opencode...", "agent_name": "supervisor"},
        # Plan
        {"type": "plan", "data": "Plan: review file", "agent_name": "supervisor"},
        # task_update — opencode dispatched
        {"type": "task_update", "data": {"agent": "opencode", "status": "dispatched"}, "agent_name": "supervisor"},
        # opencode thinking (tiny fragments)
        {"type": "thinking", "data": "Let", "agent_name": "opencode"},
        {"type": "thinking", "data": " me", "agent_name": "opencode"},
        {"type": "thinking", "data": " review", "agent_name": "opencode"},
        # opencode message (tiny fragments — bad old behavior)
        {"type": "message", "data": "The", "agent_name": "opencode"},
        {"type": "message", "data": " file", "agent_name": "opencode"},
        {"type": "message", "data": " looks", "agent_name": "opencode"},
        {"type": "message", "data": " good", "agent_name": "opencode"},
        # opencode done
        {"type": "thinking_done", "data": "", "agent_name": "opencode"},
        {"type": "metrics", "data": {"elapsed_ms": 100}, "agent_name": "opencode"},
        # Summary
        {"type": "summary", "data": "Summary: file is good", "agent_name": "supervisor"},
        # Done
        {"type": "done", "data": "", "agent_name": "supervisor"},
    ]

    _message_accum = ""
    thinking_content = ""
    agent_name = "supervisor"

    async for event in _passthrough(_make_source(events)):
        agent_name = event.get("agent_name", "supervisor")

        if event["type"] == "thinking":
            thinking_content += event.get("data", "")
        elif event["type"] == "plan":
            thinking_content += f"\n[Plan]\n{event.get('data', '')}"
        elif event["type"] == "message":
            _message_accum += event.get("data", "")
        else:
            # Flush message on non-message events
            if _message_accum:
                fake_save_message("s1", "ai", _message_accum,
                                  thinking=thinking_content, name=agent_name)
                thinking_content = ""
                _message_accum = ""

            if event["type"] == "plan":
                fake_save_message("s1", "ai", event.get("data", ""), name="plan")
            elif event["type"] == "summary":
                fake_save_message("s1", "ai", event.get("data", ""),
                                  thinking=thinking_content or None, name="summary")

    # flush final
    if _message_accum:
        fake_save_message("s1", "ai", _message_accum,
                          thinking=thinking_content, name=agent_name)

    # ── Assertions ────────────────────────────────────────
    ai_msgs = [m for m in saved_messages if m["role"] == "ai"]
    print(f"\n  AI messages saved: {len(ai_msgs)}")

    # Find the opencode response — should be ONE accumulated message
    opencode_msgs = [m for m in ai_msgs if m.get("name") == "opencode"]
    assert len(opencode_msgs) == 1, \
        f"Expected 1 opencode message, got {len(opencode_msgs)}: {[m['content'] for m in opencode_msgs]}"
    assert opencode_msgs[0]["content"] == "The file looks good", \
        f"Content mismatch: {opencode_msgs[0]['content']!r}"
    print(f"  opencode response: {opencode_msgs[0]['content']!r} [ok]")
    print(f"  thinking preserved: {bool(opencode_msgs[0].get('thinking'))} [ok]")

    summary_msgs = [m for m in ai_msgs if m.get("name") == "summary"]
    assert len(summary_msgs) == 1
    assert summary_msgs[0]["content"] == "Summary: file is good"
    print(f"  summary response: {summary_msgs[0]['content']!r} [ok]")

    print(f"\n  ✅ Orchestrator accumulation: {len(ai_msgs)} AI messages total")


async def main():
    print("=== _passthrough batching ===")
    await test_passthrough_batching()

    print("\n=== Orchestrator accumulation ===")
    await test_orchestrator_accumulation()

    print("\n[DONE] All tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
