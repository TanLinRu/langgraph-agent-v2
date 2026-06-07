from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from src.agent.eval.assertions import run_assertions
from src.agent.eval.models import EvalCase, EvalResultItem, EvalRun
from src.agent.eval.storage import save_run
from src.agent.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


def _get_config():
    from src.agent.config import AgentConfig
    try:
        return AgentConfig()
    except Exception:
        return AgentConfig()


async def run_case(
    case: EvalCase,
    config_override: dict[str, Any] | None = None,
    mock_model: bool = False,
) -> EvalRun:
    """Run a single eval case through the orchestrator and assert."""
    task_id = str(uuid.uuid4())
    config = _get_config()
    cfg = dict(config_override or {})

    orchestrator = Orchestrator(config)
    events: list[dict[str, Any]] = []
    start = time.time()

    try:
        if mock_model:
            mock = _create_mock_model(case)
            with patch("src.agent.orchestrator.core._models.resolve_model", return_value=mock):
                async for ev in orchestrator.run(case.task):
                    ev["_captured_at"] = time.time()
                    events.append(ev)
        else:
            async for ev in orchestrator.run(case.task):
                ev["_captured_at"] = time.time()
                events.append(ev)

        failures = run_assertions(events, case.expected)

        session_id = _extract_session_id(events)
        thread_id = _extract_thread_id(events)
        metrics = _extract_metrics(events)
        passed = all(f.passed for f in failures)

        run = EvalRun(
            task_id=task_id,
            case_id=case.case_id,
            session_id=session_id,
            thread_id=thread_id,
            passed=passed,
            failures=failures,
            metrics_snapshot=metrics,
            config_snapshot=cfg,
            triggered_by=cfg.get("triggered_by", "manual"),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        save_run(run)
        n_failed = len([f for f in failures if not f.passed])
        logger.info("[EVAL] case=%s passed=%s failures=%d", case.case_id, passed, n_failed)
        return run

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        run = EvalRun(
            task_id=task_id,
            case_id=case.case_id,
            passed=False,
            failures=[EvalResultItem(assertion="runner_error", passed=False, detail=str(e))],
            metrics_snapshot={"elapsed_ms": elapsed, "error": str(e)},
            config_snapshot=cfg,
            triggered_by=cfg.get("triggered_by", "manual"),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        save_run(run)
        logger.error("[EVAL] case=%s error: %s", case.case_id, e)
        return run


async def run_cases(
    cases: list[EvalCase],
    config_override: dict[str, Any] | None = None,
    mock_model: bool = False,
    max_concurrent: int = 3,
) -> list[EvalRun]:
    """Run multiple cases sequentially (or concurrently with semaphore)."""
    results: list[EvalRun] = []
    for case in cases:
        run = await run_case(case, config_override, mock_model)
        results.append(run)
    return results


def _extract_session_id(events: list[dict]) -> str | None:
    for ev in events:
        sid = ev.get("session_id")
        if sid:
            return sid
    return None


def _extract_thread_id(events: list[dict]) -> str | None:
    for ev in events:
        if ev.get("type") == "interrupt":
            data = ev.get("data", {})
            if isinstance(data, dict):
                tid = data.get("thread_id")
                if tid:
                    return str(tid)
    return None


def _extract_metrics(events: list[dict]) -> dict[str, Any]:
    for ev in reversed(events):
        if ev.get("type") == "metrics":
            return ev.get("data", {}) or {}
    return {}


def _create_mock_model(case: EvalCase):
    """Create a mock model that returns a minimal valid plan for the case task."""
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.content = _build_mock_plan_text(case)
    mock_response.additional_kwargs = {"reasoning_content": "Mock reasoning for eval"}

    async def astream(*args, **kwargs):
        yield mock_response

    mock.astream = astream
    return mock


def _build_mock_plan_text(case: EvalCase) -> str:
    agents = case.expected.plan_agents or ["direct"]
    steps = []
    for i, agent in enumerate(agents):
        steps.append(f'  {{"agent": "{agent}", "task": "Handle part {i+1} of: {case.task[:50]}", "depends_on": []}}')
    steps_str = ",\n".join(steps)
    return f"""```json
{{
  "reasoning": "Mock plan for eval case {case.case_id}",
  "steps": [
{steps_str}
  ],
  "auto_approve": true
}}
```"""
