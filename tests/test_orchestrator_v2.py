"""Tests for v2 Orchestrator — Pydantic models, 6-node graph, interrupt/resume."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessageChunk

from src.agent.config import AgentConfig
from src.agent.orchestrator.planner import (
    AgentResult,
    AntiPattern,
    GraphState,
    Plan,
    Step,
    load_constraints,
    save_anti_pattern,
)

# ── Helpers ─────────────────────────────────────────────────────


def _make_chunk(content: str | None = None, reasoning: str | None = None):
    chunk = MagicMock(spec=AIMessageChunk)
    chunk.content = content or ""
    chunk.additional_kwargs = {}
    if reasoning:
        chunk.additional_kwargs["reasoning_content"] = reasoning
    return chunk


async def _mock_model_stream(chunks):
    for chunk in chunks:
        yield chunk


# ── Pydantic Model Tests ───────────────────────────────────────


class TestPlanModel:
    def test_step_serde(self):
        step = Step(agent="coder", task="write code")
        d = step.model_dump()
        assert d["agent"] == "coder"
        assert d["task"] == "write code"
        assert d["depends_on"] == []

    def test_plan_serde(self):
        plan = Plan(
            steps=[Step(agent="researcher", task="search"), Step(agent="coder", task="implement", depends_on=["researcher"])],
            reasoning="Need research first",
        )
        d = plan.model_dump()
        assert len(d["steps"]) == 2
        assert d["steps"][1]["depends_on"] == ["researcher"]

    def test_plan_auto_approve_default_false(self):
        plan = Plan(steps=[Step(agent="direct", task="reply")])
        assert plan.auto_approve is False

    def test_agent_result(self):
        ar = AgentResult(agent="coder", task="write", result="code")
        assert ar.error == ""
        assert ar.elapsed_ms == 0

    def test_graph_state_defaults(self):
        gs = GraphState(task="test")
        assert gs.history == []
        assert gs.plan is None
        assert gs.results == {}
        assert gs.step_count == 0

    def test_anti_pattern_serde(self):
        ap = AntiPattern(label="plan_drift", task="test", agent="supervisor", what_happened="drifted", suggestion="check context")
        d = ap.model_dump()
        assert d["severity"] == "medium"
        assert d["label"] == "plan_drift"

    def test_anti_pattern_save_and_load(self):
        import os
        os.makedirs("memory", exist_ok=True)
        ap = AntiPattern(label="plan_drift", task="test task", agent="supervisor", what_happened="drifted", suggestion="check first")
        save_anti_pattern(ap)
        constraints = load_constraints()
        assert any("check first" in c for c in constraints)

    def test_parse_plan_fallback(self):
        from src.agent.orchestrator.core import Orchestrator
        steps = Orchestrator._parse_plan_fallback("- coder: write code\n- researcher: search")
        assert len(steps) == 2
        assert steps[0].agent == "coder"
        assert steps[1].agent == "researcher"


# ── Orchestrator Init ───────────────────────────────────────────


class TestOrchestratorInitV2:
    def test_init_with_mock_model(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = MagicMock()
            mock_resolve.return_value = mock_model

            from src.agent.orchestrator import Orchestrator

            config = AgentConfig()
            orch = Orchestrator(config)
            assert isinstance(orch.sub_agents, dict)
            assert "coder" in orch.sub_agents

    @pytest.mark.asyncio
    async def test_build_graph_has_5_nodes(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = MagicMock()
            mock_resolve.return_value = mock_model

            from src.agent.orchestrator import Orchestrator

            config = AgentConfig()
            orch = Orchestrator(config)
            graph = await orch._build_graph()
            assert "perceive" not in graph.nodes
            assert "plan" in graph.nodes
            assert "wait" in graph.nodes
            assert "dispatch" in graph.nodes
            assert "synthesize" in graph.nodes
            assert "reflect" in graph.nodes


# ── Orchestrator Run ────────────────────────────────────────────


class TestOrchestratorRunV2:
    @pytest.mark.asyncio
    async def test_run_produces_all_events(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([_make_chunk(content='{"steps": [{"agent": "coder", "task": "reply"}], "auto_approve": true}')]),
                _mock_model_stream([_make_chunk(content="All OK.")]),
                _mock_model_stream([_make_chunk(content="[]")]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
                mock_tool.return_value = "done"

                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("test task"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "thinking_start" in types
                assert "plan" in types
                assert "task_update" in types
                assert "message" in types
                assert "audit_summary" in types
                assert "metrics" in types
                assert "done" in types

    @pytest.mark.asyncio
    async def test_events_in_correct_order(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([_make_chunk(content='{"steps": [{"agent": "coder", "task": "reply"}], "auto_approve": true}')]),
                _mock_model_stream([_make_chunk(content="Audit OK.")]),
                _mock_model_stream([_make_chunk(content="[]")]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
                mock_tool.return_value = "implemented"

                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("implement feature"):
                    events.append(event)

                types = [e["type"] for e in events]
                plan_idx = types.index("plan")
                audit_idx = types.index("audit_summary")
                done_idx = types.index("done")
                assert plan_idx < audit_idx
                assert audit_idx < done_idx

    @pytest.mark.asyncio
    async def test_dispatch_node_error_handling(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([_make_chunk(content='{"steps": [{"agent": "coder", "task": "reply"}], "auto_approve": true}')]),
                _mock_model_stream([_make_chunk(content="Audit OK.")]),
                _mock_model_stream([_make_chunk(content="[]")]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
                mock_tool.side_effect = RuntimeError("fail")

                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("implement"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "task_update" in types
                assert "done" in types

    @pytest.mark.asyncio
    async def test_dispatch_node_skips_unknown_agent(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([_make_chunk(content='{"steps": [{"agent": "unknown_agent", "task": "do stuff"}], "auto_approve": true}')]),
                _mock_model_stream([_make_chunk(content="No results")]),
                _mock_model_stream([_make_chunk(content="[]")]),
            ])
            mock_resolve.return_value = mock_model

            from src.agent.orchestrator import Orchestrator

            config = AgentConfig()
            orch = Orchestrator(config)

            events = []
            async for event in orch.run("do stuff"):
                events.append(event)

            types = [e["type"] for e in events]
            assert "plan" in types
            assert "done" in types

    @pytest.mark.asyncio
    async def test_audit_summary_contains_results(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([_make_chunk(content='{"steps": [{"agent": "coder", "task": "reply"}], "auto_approve": true}')]),
                _mock_model_stream([_make_chunk(content="Audit: looks good.")]),
                _mock_model_stream([_make_chunk(content="[]")]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
                mock_tool.return_value = "def foo(): pass"

                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("write code"):
                    events.append(event)

                audit_events = [e for e in events if e["type"] == "audit_summary"]
                assert len(audit_events) >= 1

# ── Interrupt / Resume Tests ────────────────────────────────────


class TestInterruptResume:
    @pytest.mark.asyncio
    async def test_interrupt_detected_on_plan(self):
        """Verify run() detects __interrupt__ and yields interrupt event."""
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_resolve.return_value = mock_model

            from src.agent.orchestrator import Orchestrator

            config = AgentConfig()
            orch = Orchestrator(config)

            # Mock the graph to simulate interrupt
            mock_graph = MagicMock()
            # astream returns async iterator that yields nothing
            mock_astream_result = MagicMock()
            mock_astream_result.__aiter__.return_value = mock_astream_result
            mock_astream_result.__anext__.side_effect = StopAsyncIteration
            mock_graph.astream = MagicMock(return_value=mock_astream_result)
            mock_graph.aget_state = AsyncMock()
            mock_state = MagicMock()
            mock_state.next = ("wait",)
            mock_graph.aget_state.return_value = mock_state

            # Trigger via _build_graph mock
            with patch.object(orch, "_build_graph", return_value=mock_graph):
                events = []
                async for event in orch.run("test"):
                    events.append(event)

                interrupt_events = [e for e in events if e["type"] == "interrupt"]
                assert len(interrupt_events) == 1
                assert "thread_id" in interrupt_events[0]["data"]

    @pytest.mark.asyncio
    async def test_resume_invalid_thread_id(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = MagicMock()
            mock_resolve.return_value = mock_model

            from src.agent.orchestrator import Orchestrator

            config = AgentConfig()
            orch = Orchestrator(config)

            with pytest.raises(ValueError, match="No interrupted thread"):
                async for _ in orch.resume("invalid-thread-id", "approve"):
                    pass

    @pytest.mark.asyncio
    async def test_resume_unknown_decision(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = MagicMock()
            mock_resolve.return_value = mock_model

            from src.agent.orchestrator import Orchestrator
            from src.agent.orchestrator.core import _THREAD_CACHE

            config = AgentConfig()
            orch = Orchestrator(config)
            mock_graph = MagicMock()
            _THREAD_CACHE["test-thread"] = {"graph": mock_graph, "config": {}}

            with pytest.raises(ValueError, match="Unknown decision"):
                async for _ in orch.resume("test-thread", "invalid"):
                    pass


# ── Event Type Tests ────────────────────────────────────────────


class TestEventTypes:
    def test_interrupt_event_type_registered(self):
        from src.agent.events import EventType
        assert EventType.INTERRUPT == "interrupt"
        assert "interrupt" in EventType.all()

    def test_make_interrupt_event(self):
        from src.agent.events import make_interrupt
        evt = make_interrupt(data={"thread_id": "abc", "plan": None})
        assert evt["type"] == "interrupt"
        assert evt["data"]["thread_id"] == "abc"

    def test_orchestrator_events_re_exports_interrupt(self):
        from src.agent.events import make_interrupt
        evt = make_interrupt()
        assert evt["type"] == "interrupt"

    def test_permission_request_event_type_registered(self):
        from src.agent.events import EventType
        assert EventType.PERMISSION_REQUEST == "permission_request"
        assert "permission_request" in EventType.all()

    def test_make_permission_request_event(self):
        from src.agent.events import make_permission_request
        evt = make_permission_request(
            agent_name="opencode",
            data={"req_id": "r1", "toolCall": {"name": "write_file"}, "options": []},
        )
        assert evt["type"] == "permission_request"
        assert evt["agent_name"] == "opencode"
        assert evt["data"]["req_id"] == "r1"

    def test_orchestrator_events_re_exports_permission_request(self):
        from src.agent.events import make_permission_request
        evt = make_permission_request()
        assert evt["type"] == "permission_request"
