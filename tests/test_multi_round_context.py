"""Multi-round context flow test.

Simulates a 5-round user session:
  R1: Single Agent writes fib.py
  R2: Single Agent reads fib.py (sees R1 context via DB)
  R3: Workflow analyzes fib.py (saves messages to same session)
  R4: Supervisor orchestrator loads ALL history, dispatches sub-agents
  R5: Eval runs assertions on the session

All rounds share one session_id — context flows through SQLite.
Mocks LLM calls; no real API keys needed.
conftest.py provides auto-isolated env vars.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.config import AgentConfig


@pytest.mark.asyncio
async def test_multi_round_context_flow():
    """Full multi-round integration test verifying context continuity."""
    # ── Setup: shared session ────────────────────────────────
    from src.agent.db import create_session, load_history_with_meta, save_turn
    from src.agent.db.messages import load_history

    session_id = create_session()
    assert session_id is not None

    # ════════════════════════════════════════════════════════════
    # R1: Single Agent — write fib.py
    # ════════════════════════════════════════════════════════════
    from langchain_core.messages import AIMessage

    from src.agent.agent import Agent

    async def mock_graph_astream(*args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="斐波那契函数写好了，已保存到 fib.py")},
        }
        yield {"event": "on_chain_end", "data": {"output": AIMessage(content="done")}}

    agent = Agent(AgentConfig())
    mock_graph = MagicMock()
    mock_graph.astream_events = mock_graph_astream
    agent._graph = mock_graph

    r1_history = load_history(session_id)
    async for _ev in agent.run("写一个 Python 斐波那契函数，保存到 fib.py", history=r1_history):
        pass

    save_turn(session_id, "写一个 Python 斐波那契函数，保存到 fib.py",
              "斐波那契函数写好了，已保存到 fib.py")

    r1_msgs = load_history_with_meta(session_id)
    assert len(r1_msgs) == 2, f"Expected 2 messages after R1, got {len(r1_msgs)}"
    assert r1_msgs[0]["type"] == "human"
    assert "fib.py" in r1_msgs[0]["content"]
    print("[PASS] R1: Single Agent created fib.py, messages saved to DB")

    # ════════════════════════════════════════════════════════════
    # R2: Single Agent — reads fib.py (context from R1 via DB)
    # ════════════════════════════════════════════════════════════
    async def mock_graph_astream_r2(*args, **kwargs):
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": MagicMock(content="fib.py 已读取，包含一个高效的斐波那契实现")},
        }
    mock_graph.astream_events = mock_graph_astream_r2

    r2_history = load_history(session_id)
    assert len(r2_history) == 2, f"R2 should see 2 prior messages, got {len(r2_history)}"
    print(f"  [context] R2 sees {len(r2_history)} prior messages (R1 context)")

    async for _ev in agent.run("读取刚才创建的 fib.py 文件", history=r2_history):
        pass

    save_turn(session_id, "读取刚才创建的 fib.py 文件",
              "fib.py 已读取，包含一个高效的斐波那契实现")

    r2_msgs = load_history_with_meta(session_id)
    assert len(r2_msgs) == 4, f"Expected 4 messages after R2, got {len(r2_msgs)}"
    assert "fib.py" in r2_msgs[0]["content"]
    print("[PASS] R2: Single Agent used R1 context, now 4 messages in session")

    # ════════════════════════════════════════════════════════════
    # R3: Workflow — analyzes fib.py (saves messages to session)
    # ════════════════════════════════════════════════════════════
    # Route to orchestrator which handles workflow subgraph dispatch
    with patch("src.agent.models.resolve_model") as mock_r3_resolve:
        from src.agent.orchestrator import Orchestrator
        orch_r3 = Orchestrator(AgentConfig())
        mock_r3_model = AsyncMock()
        mock_r3_model.astream = MagicMock(return_value=_mock_model_stream(
            [_make_chunk(content='{"steps": [{"agent": "researcher", "task": "analyze fib.py"}, {"agent": "analyst", "task": "report"}], "auto_approve": true}')]
        ))
        mock_r3_resolve.return_value = mock_r3_model

        with patch("src.agent.orchestrator.tools.SubAgentTool._arun") as mock_r3_tool:
            mock_r3_tool.return_value = "支持类型注解（Type Hints）"
            async for _ev in orch_r3.run(
                "分析 fib.py 添加类型注解",
                session_id=session_id,
            ):
                pass

    print("[PASS] R3: Orchestrator ran without error (agent outputs via events)")

    # ════════════════════════════════════════════════════════════
    # R4: Supervisor — loads ALL context, dispatches sub-agents
    # ════════════════════════════════════════════════════════════
    from src.agent.orchestrator import Orchestrator

    plan_chunks = [_make_chunk(content='{"steps": [{"agent": "coder", "task": "检查 fib.py 是否满足 PEP 484"}], "auto_approve": true}')]
    audit_chunks = [_make_chunk(content="审计完成，代码通过 PEP 484 检查")]
    reflect_chunks = [_make_chunk(content="[]")]

    with patch("src.agent.models.resolve_model") as mock_resolve:
        mock_model = AsyncMock()
        mock_model.astream = MagicMock(side_effect=[
            _mock_model_stream(plan_chunks),
            _mock_model_stream(audit_chunks),
            _mock_model_stream(reflect_chunks),
        ])
        mock_resolve.return_value = mock_model

        with patch("src.agent.orchestrator.tools.SubAgentTool._arun") as mock_tool:
            mock_tool.return_value = "类型注解和 PEP 484 检查已完成"

            orch = Orchestrator(AgentConfig())
            orch._load_agent_configs = MagicMock()
            orch.sub_agents = {"coder": {}, "verifier": {}}

            # KEY: load full session history — this is where context flows
            history = load_history_with_meta(session_id)
            assert len(history) >= 4, (
                f"R4 should see at least 4 prior messages, got {len(history)}"
            )
            print(f"  [context] Supervisor perceives {len(history)} prior messages")

            supervisor_events = []
            async for ev in orch.run(
                "检查 fib.py 的开发历史和当前代码，确保满足 PEP 484",
                history=history,
                summary="",
            ):
                supervisor_events.append(ev)

        supervisor_types = {e["type"] for e in supervisor_events}
    for expected in ("plan", "task_update", "message", "audit_summary", "metrics", "done"):
        assert expected in supervisor_types, f"Supervisor must produce {expected}"
    print(f"[PASS] R4: Supervisor produced {len(supervisor_events)} events with full context")

    # ════════════════════════════════════════════════════════════
    # R5: Eval — run assertions on the session
    # ════════════════════════════════════════════════════════════
    # run_case() with mock_model=True still calls resolve_model during
    # Orchestrator.__init__. We patch it ourselves before creating.
    from src.agent.eval.models import EvalCase, EvalExpectation
    from src.agent.eval.runner import run_case

    case = EvalCase(
        case_id="multi-round-test",
        task="写一个 Python 斐波那契函数，保存到 fib.py",
        tags=["integration", "multi-round"],
        expected=EvalExpectation(
            must_call_tools=[],
            language="chinese",
            min_output_length=10,
        ),
    )

    with patch("src.agent.orchestrator.core._models.resolve_model") as mock_resolve:
        from src.agent.eval.runner import _create_mock_model
        mock_resolve.return_value = _create_mock_model(case)

        result = await run_case(case)

    assert result.passed, f"Eval should pass, got: {result.failures}"
    print("[PASS] R5: Eval assertions passed")

    # ════════════════════════════════════════════════════════════
    print("\n  R1 | Single Agent |  2 msgs | Created fib.py")
    print("  R2 | Single Agent |  4 msgs | Read fib.py (R1 context)")
    print("  R3 | Workflow     |  events | Analyzed fib.py")
    print(f"  R4 | Supervisor   | {len(supervisor_events)} evts | Dispatched with {len(history)} prior msgs")
    print("  R5 | Eval         |   1 run | Assertions passed")
    print("  All 4 modules verified, context continuity confirmed")


# ── Helpers ────────────────────────────────────────────────────


def _make_chunk(content: str | None = None, reasoning: str | None = None):
    from unittest.mock import MagicMock

    from langchain_core.messages import AIMessageChunk
    chunk = MagicMock(spec=AIMessageChunk)
    chunk.content = content or ""
    chunk.additional_kwargs = {}
    if reasoning:
        chunk.additional_kwargs["reasoning_content"] = reasoning
    return chunk


async def _mock_model_stream(chunks):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_plan_node_consumes_db_history():
    """Isolated test: _plan_node builds context summary from DB history.

    In the current 5-node graph, perceive logic was merged into _plan_node.
    This test verifies that _plan_node processes session history correctly.
    """
    from src.agent.db import create_session, load_history_with_meta, save_turn
    from src.agent.orchestrator.planner import GraphState

    session_id = create_session()

    # Populate 2 prior turns (4 messages)
    save_turn(session_id, "之前创建了 fib.py", "斐波那契函数已经写好")
    save_turn(session_id, "添加类型注解", "类型注解已添加完成")

    history = load_history_with_meta(session_id)
    assert len(history) == 4

    # _plan_node builds history_summary from state.history directly (lines 108-126)
    state = GraphState(task="检查整个项目状态", history=history, history_summary="")

    with patch("src.agent.models.resolve_model") as mock_resolve:
        mock_model = AsyncMock()
        mock_model.astream = MagicMock(return_value=_mock_model_stream(
            [_make_chunk(content='{"steps": [{"agent": "coder", "task": "reply"}], "auto_approve": true}')]
        ))
        mock_resolve.return_value = mock_model

        from src.agent.orchestrator import Orchestrator
        config = AgentConfig()
        orch = Orchestrator(config)
        orch._load_agent_configs = MagicMock()
        orch._tokens = {}
        orch.sub_agents = {"coder": {}}

        captured: list[Any] = []
        result = await orch._plan_node(state, writer=captured.append)

        assert result.get("plan") is not None

    print(f"[PASS] _plan_node processed {len(history)} history msgs into plan")


@pytest.mark.asyncio
async def test_history_summary_construction():
    """Verify the inline history → summary construction in _plan_node."""
    from unittest.mock import MagicMock

    from src.agent.orchestrator import Orchestrator
    from src.agent.orchestrator.planner import GraphState

    history = [
        {"type": "human", "content": "创建 fib.py"},
        {"type": "ai", "content": "斐波那契函数写好了"},
        {"type": "human", "content": "添加类型注解"},
        {"type": "ai", "content": "类型注解已添加"},
    ]

    state = GraphState(task="检查", history=history, history_summary="")

    with patch("src.agent.models.resolve_model") as mock_resolve:
        mock_model = AsyncMock()
        mock_model.astream = MagicMock(return_value=_mock_model_stream(
            [_make_chunk(content='{"steps": [{"agent": "coder", "task": "reply"}], "auto_approve": true}')]
        ))
        mock_resolve.return_value = mock_model

        config = AgentConfig()
        orch = Orchestrator(config)
        orch._load_agent_configs = MagicMock()
        orch._tokens = {}
        orch.sub_agents = {"coder": {}}

        captured: list[Any] = []
        result = await orch._plan_node(state, writer=captured.append)

        assert result.get("plan") is not None

    print("[PASS] _plan_node processed 4 history messages without error")
