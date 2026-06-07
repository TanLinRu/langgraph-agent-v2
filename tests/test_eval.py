from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.agent.db.connection import _get_conn
from src.agent.eval.assertions import (
    check_content_contains,
    check_content_not_contain,
    check_language,
    check_output_length,
    check_plan_agents,
    check_plan_steps,
    check_tool_called,
    check_tool_not_called,
    run_assertions,
)
from src.agent.eval.models import EvalCase, EvalExpectation, EvalResultItem, EvalRun, EvalSuggestion, SuggestionDraft

# ── Models ────────────────────────────────────────────────────────────


class TestModels:
    def test_eval_expectation_defaults(self):
        e = EvalExpectation()
        assert e.must_call_tools == []
        assert e.language == "chinese"
        assert e.min_output_length == 0
        assert e.forbid_hallucinated_refs is False

    def test_eval_case_minimal(self):
        c = EvalCase(case_id="test-1", task="Hello")
        assert c.source_type == "manual"
        assert c.case_id == "test-1"

    def test_eval_run(self):
        r = EvalRun(task_id="t1", case_id="c1", passed=True)
        assert r.passed is True
        assert r.task_id == "t1"

    def test_eval_suggestion(self):
        s = EvalSuggestion(dimension="prompt", target="verifier", confidence=0.8)
        assert s.dimension == "prompt"
        assert s.dismissed is False

    def test_suggestion_draft(self):
        d = SuggestionDraft(
            dimension="agent", target="coder", current_value="0.7",
            suggested_value="0.3", reasoning="too many errors",
            evidence=[{"failures": 5}], confidence=0.9,
        )
        assert d.confidence == 0.9


# ── Assertions ────────────────────────────────────────────────────────


class TestCheckToolCalled:
    def test_found(self):
        events = [{"type": "tool_call", "data": [{"name": "execute_code"}]}]
        r = check_tool_called(events, ["execute_code"])
        assert r.passed is True

    def test_not_found(self):
        events = [{"type": "tool_call", "data": [{"name": "read_file"}]}]
        r = check_tool_called(events, ["execute_code"])
        assert r.passed is False

    def test_no_tool_events(self):
        events = [{"type": "message", "data": "hello"}]
        r = check_tool_called(events, ["execute_code"])
        assert r.passed is False


class TestCheckToolNotCalled:
    def test_forbidden_not_called(self):
        events = [{"type": "tool_call", "data": [{"name": "execute_code"}]}]
        r = check_tool_not_called(events, ["write_file"])
        assert r.passed is True

    def test_forbidden_called(self):
        events = [{"type": "tool_call", "data": [{"name": "write_file"}]}]
        r = check_tool_not_called(events, ["write_file"])
        assert r.passed is False


class TestCheckLanguage:
    def test_no_constraint(self):
        r = check_language([], None)
        assert r.passed is True

    def test_chinese(self):
        events = [{"type": "message", "data": "你好 world 中文测试"}]
        r = check_language(events, "chinese")
        assert r.passed is True

    def test_not_chinese(self):
        events = [{"type": "message", "data": "hello world this is english"}]
        r = check_language(events, "chinese")
        assert r.passed is False

    def test_other_language_skipped(self):
        events = [{"type": "message", "data": "hello world"}]
        r = check_language(events, "english")
        assert r.passed is True


class TestCheckOutputLength:
    def test_within_bounds(self):
        events = [{"type": "message", "data": "a" * 50}]
        r = check_output_length(events, 10, 100)
        assert r.passed is True

    def test_too_short(self):
        events = [{"type": "message", "data": "hi"}]
        r = check_output_length(events, 10, 100)
        assert r.passed is False

    def test_too_long(self):
        events = [{"type": "message", "data": "a" * 200}]
        r = check_output_length(events, 0, 100)
        assert r.passed is False


class TestCheckContentContains:
    def test_all_found(self):
        events = [{"type": "message", "data": "hello world python test"}]
        r = check_content_contains(events, ["python", "test"])
        assert r.passed is True

    def test_missing(self):
        events = [{"type": "message", "data": "hello world"}]
        r = check_content_contains(events, ["python"])
        assert r.passed is False

    def test_no_contraint(self):
        r = check_content_contains([], [])
        assert r.passed is True


class TestCheckContentNotContain:
    def test_forbidden_not_found(self):
        events = [{"type": "message", "data": "safe content"}]
        r = check_content_not_contain(events, ["danger"])
        assert r.passed is True

    def test_forbidden_found(self):
        events = [{"type": "message", "data": "danger content here"}]
        r = check_content_not_contain(events, ["danger"])
        assert r.passed is False


class TestCheckPlanSteps:
    def test_exact_match(self):
        events = [{"type": "plan", "steps": [{"agent": "a"}, {"agent": "b"}]}]
        r = check_plan_steps(events, 2)
        assert r.passed is True

    def test_wrong_count(self):
        events = [{"type": "plan", "steps": [{"agent": "a"}]}]
        r = check_plan_steps(events, 3)
        assert r.passed is False

    def test_no_plan_event(self):
        r = check_plan_steps([{"type": "message"}], 1)
        assert r.passed is False

    def test_no_constraint(self):
        r = check_plan_steps([], None)
        assert r.passed is True


class TestCheckPlanAgents:
    def test_all_present(self):
        events = [{"type": "plan", "steps": [{"agent": "coder"}, {"agent": "researcher"}]}]
        r = check_plan_agents(events, ["coder", "researcher"])
        assert r.passed is True

    def test_missing_agent(self):
        events = [{"type": "plan", "steps": [{"agent": "coder"}]}]
        r = check_plan_agents(events, ["coder", "analyst"])
        assert r.passed is False


class TestRunAssertions:
    def test_empty_expected(self):
        r = run_assertions([], EvalExpectation())
        # language check runs because default is "chinese"; empty text passes (no error)
        assert all(res.passed for res in r)

    def test_all_checks(self):
        events = [
            {"type": "plan", "steps": [{"agent": "coder"}]},
            {"type": "tool_call", "data": [{"name": "execute_code"}]},
            {"type": "message", "data": "你好这里是中文测试"},
        ]
        exp = EvalExpectation(
            must_call_tools=["execute_code"],
            must_not_call_tools=["write_file"],
            language="chinese",
            min_output_length=5,
            plan_steps=1,
            plan_agents=["coder"],
            must_contain=["中文"],
            must_not_contain=["malware"],
        )
        results = run_assertions(events, exp)
        for r in results:
            assert r.passed is True, f"{r.assertion}: {r.detail}"

    def test_mixed_results(self):
        events = [{"type": "message", "data": "hello"}]
        exp = EvalExpectation(
            must_call_tools=["execute_code"],
            language="chinese",
            min_output_length=100,
        )
        results = run_assertions(events, exp)
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 2, f"Expected at least 2 failures, got {len(failed)}"


# ── Storage (DB-dependent) ────────────────────────────────────────────


class TestStorage:
    def _count_rows(self, table: str) -> int:
        conn = _get_conn()
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        conn.close()
        return row[0]

    def test_save_and_load_case(self):
        from src.agent.eval.storage import delete_case, list_cases, load_case, save_case
        c = EvalCase(
            case_id="stest-1", task="Test task", tags=["auto"],
            expected=EvalExpectation(must_call_tools=["read_file"]),
            source_type="test", updated_at=datetime.now(timezone.utc).isoformat(),
        )
        save_case(c)
        loaded = load_case("stest-1")
        assert loaded is not None
        assert loaded.case_id == "stest-1"
        assert loaded.expected.must_call_tools == ["read_file"]
        cases = list_cases()
        assert any(cc.case_id == "stest-1" for cc in cases)
        delete_case("stest-1")
        assert load_case("stest-1") is None

    def test_save_and_list_runs(self):
        from src.agent.eval.storage import get_latest_run, list_runs, save_run
        run = EvalRun(
            task_id="rtest-1", case_id="rcase-1", passed=False,
            failures=[EvalResultItem(assertion="tool_call", passed=False, detail="not found")],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        save_run(run)
        runs = list_runs("rcase-1")
        assert any(r.task_id == "rtest-1" for r in runs)
        latest = get_latest_run("rcase-1")
        assert latest is not None

    def test_save_suggestion(self):
        from src.agent.eval.storage import list_suggestions, save_suggestion
        draft = SuggestionDraft(
            dimension="prompt", target="verifier", current_value="old",
            suggested_value="new", reasoning="test", evidence=[{"x": 1}], confidence=0.8,
        )
        sid = save_suggestion(draft)
        assert sid > 0
        suggestions = list_suggestions()
        assert any(s.id == sid for s in suggestions)

    def test_get_pass_rate(self):
        from src.agent.eval.storage import get_pass_rate
        rate = get_pass_rate(days=7)
        assert isinstance(rate["total"], int)
        assert isinstance(rate["rate"], float)


# ── Runner ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRunner:
    async def test_run_case_success(self):
        from src.agent.eval.runner import run_case

        case = EvalCase(
            case_id="runtest-1", task="Do something",
            expected=EvalExpectation(must_call_tools=["read_file"], language=None),
        )

        # Mock orchestrator to yield events
        mock_events = [
            {"type": "tool_call", "data": [{"name": "read_file"}]},
            {"type": "message", "data": "done"},
            {"type": "metrics", "data": {"elapsed_ms": 500, "tokens": {"total": 100}}},
        ]

        async def mock_orch_run(*args, **kwargs):
            for ev in mock_events:
                yield ev

        with patch("src.agent.eval.runner.Orchestrator", autospec=True) as mock_orch_cls:
            mock_orch_instance = mock_orch_cls.return_value
            mock_orch_instance.run = mock_orch_run
            result = await run_case(case)

        assert result is not None
        assert result.passed is True
        assert result.case_id == "runtest-1"

    async def test_run_case_failure(self):
        from src.agent.eval.runner import run_case

        case = EvalCase(
            case_id="runtest-2", task="Write code",
            expected=EvalExpectation(must_call_tools=["execute_code"]),
        )

        async def mock_orch_run(*args, **kwargs):
            yield {"type": "message", "data": "I cannot do this"}
            yield {"type": "metrics", "data": {}}

        with patch("src.agent.eval.runner.Orchestrator", autospec=True) as mock_orch_cls:
            mock_orch_instance = mock_orch_cls.return_value
            mock_orch_instance.run = mock_orch_run
            result = await run_case(case)

        assert result.passed is False

    async def test_run_case_error(self):
        from src.agent.eval.runner import run_case

        case = EvalCase(case_id="runtest-3", task="Crash")

        async def mock_orch_run(*args, **kwargs):
            raise RuntimeError("orchestrator crash")
            yield  # pragma: no cover

        with patch("src.agent.eval.runner.Orchestrator", autospec=True) as mock_orch_cls:
            mock_orch_instance = mock_orch_cls.return_value
            mock_orch_instance.run = mock_orch_run
            result = await run_case(case)

        assert result.passed is False
        assert any("runner_error" in f.assertion for f in result.failures)


# ── Case Builder ──────────────────────────────────────────────────────


class TestCaseBuilder:
    def test_extract_task(self):
        from src.agent.eval.case_builder import _extract_task
        msgs = [
            ("system", "You are a helpful assistant", "", ""),
            ("human", "Hello, make a plan", "", ""),
            ("ai", "Here is my plan", "", ""),
        ]
        task = _extract_task(msgs)
        assert task == "Hello, make a plan"

    def test_extract_task_no_human(self):
        from src.agent.eval.case_builder import _extract_task
        msgs = [("ai", "I will help", "", "")]
        task = _extract_task(msgs)
        assert task == ""

    def test_infer_expectation_with_tools(self):
        from src.agent.eval.case_builder import _infer_expectation
        msgs = [
            ("human", "Write python code", '[]', ""),
            ("ai", "Here is the code", '[{"name": "execute_code"}]', "coder"),
            ("ai", "Check the output", '[{"name": "read_file"}]', "researcher"),
        ]
        exp = _infer_expectation(msgs, "")
        assert "execute_code" in exp.must_call_tools
        assert "read_file" in exp.must_call_tools
        assert exp.language is None  # no chinese chars

    def test_infer_expectation_filters_file_path_names(self):
        """ACP tool_call_update completed events embed file paths as 'name'."""
        from src.agent.eval.case_builder import _infer_expectation
        msgs = [
            ("human", "What model vendors exist", "", ""),
            ("ai", "", '[{"name": "read", "kind": "read", "status": "pending"}, {"name": "glob", "kind": "glob", "status": "pending"}]', "opencode"),
            ("ai", "", '[{"tool_call_id":"x","name":"src\\\\agent\\\\config.py","kind":"read","result":"...","status":"completed"}]', "opencode"),
            ("ai", "", '[{"name": "glob", "kind": "glob", "status": "pending"}, {"name": "read", "kind": "read", "status": "pending"}]', "opencode"),
            ("ai", "", '[{"tool_call_id":"y","name":".env.example","kind":"read","result":"...","status":"completed"}]', "opencode"),
            ("ai", "", '[{"name": "search", "kind": "search", "status": "pending"}]', "opencode"),
        ]
        exp = _infer_expectation(msgs, "")
        assert "read" in exp.must_call_tools
        assert "glob" in exp.must_call_tools
        assert "search" in exp.must_call_tools
        assert r"src\agent\config.py" not in exp.must_call_tools
        assert ".env.example" not in exp.must_call_tools
        assert "opencode" not in exp.must_call_tools

    def test_is_valid_tool_name(self):
        from src.agent.eval.case_builder import _is_valid_tool_name
        assert _is_valid_tool_name("read") is True
        assert _is_valid_tool_name("execute_code") is True
        assert _is_valid_tool_name("search") is True
        assert _is_valid_tool_name(r"src\agent\config.py") is False
        assert _is_valid_tool_name("config/agents.json") is False
        assert _is_valid_tool_name(".env.example") is False
        assert _is_valid_tool_name("") is False
        assert _is_valid_tool_name(None) is False  # type: ignore


# ── Analyzer ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAnalyzer:
    async def test_analyze_prompt_no_data(self):
        from src.agent.eval.analyzer import _analyze_prompt
        drafts = _analyze_prompt(7)
        assert drafts == []

    async def test_full_analysis_empty(self):
        from src.agent.eval.analyzer import run_full_analysis
        drafts = await run_full_analysis(days=7)
        assert isinstance(drafts, list)

    async def test_analyze_skill_zero_usage(self):
        from src.agent.eval.analyzer import _analyze_skill
        drafts = _analyze_skill(7)
        assert isinstance(drafts, list)


# ── Config snapshot ───────────────────────────────────────────────────


class TestRunnerConfig:
    async def test_run_case_persists_config(self):
        from src.agent.eval.runner import run_case
        case = EvalCase(
            case_id="cfgtest-1", task="test",
            expected=EvalExpectation(language=None),
        )

        async def mock_orch_run(*args, **kwargs):
            yield {"type": "message", "data": "ok"}
            yield {"type": "metrics", "data": {}}

        with patch("src.agent.eval.runner.Orchestrator", autospec=True) as mock_orch_cls:
            mock_orch_instance = mock_orch_cls.return_value
            mock_orch_instance.run = mock_orch_run
            result = await run_case(case, config_override={"triggered_by": "cli"})

        assert result.config_snapshot.get("triggered_by") == "cli"

    async def test_mock_model_flag(self):
        from src.agent.eval.runner import run_case
        case = EvalCase(
            case_id="mocktest-1", task="test",
            expected=EvalExpectation(language=None),
        )

        async def mock_orch_run(*args, **kwargs):
            yield {"type": "message", "data": "ok"}
            yield {"type": "metrics", "data": {}}

        with patch("src.agent.eval.runner.Orchestrator", autospec=True) as mock_orch_cls:
            mock_orch_instance = mock_orch_cls.return_value
            mock_orch_instance.run = mock_orch_run
            result = await run_case(case, mock_model=True)

        assert result.passed is True
