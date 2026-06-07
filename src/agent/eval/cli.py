from __future__ import annotations

import logging

from src.agent.eval.analyzer import run_full_analysis
from src.agent.eval.case_builder import build_from_sessions
from src.agent.eval.models import EvalCase, EvalRun
from src.agent.eval.runner import run_case, run_cases
from src.agent.eval.storage import (
    get_latest_run,
    get_pass_rate,
    list_cases,
    list_suggestions,
    load_case,
)

logger = logging.getLogger(__name__)


def format_eval_list() -> str:
    cases = list_cases()
    if not cases:
        return "No eval cases. Use `/eval build` to create from historical sessions."

    lines = [f"Eval cases ({len(cases)}):"]
    for c in cases:
        latest = get_latest_run(c.case_id)
        badge = "✅" if (latest and latest.passed) else "❌" if latest else "⬜"
        tags = ", ".join(c.tags) if c.tags else "untagged"
        lines.append(f"  {badge} {c.case_id} [{tags}]")
    return "\n".join(lines)


def format_eval_run(run: EvalRun, case: EvalCase | None = None) -> str:
    label = case.case_id if case else run.case_id
    status = "✅ PASSED" if run.passed else "❌ FAILED"
    lines = [f"[{label}] {status}  (task_id: {run.task_id[:8]}...)"]
    for f in run.failures:
        icon = "✅" if f.passed else "❌"
        lines.append(f"  {icon} {f.assertion}: {f.detail}")
    if run.metrics_snapshot:
        ms = run.metrics_snapshot
        lines.append(f"  ⏱ {ms.get('elapsed_ms', '?')}ms  tokens: {ms.get('tokens', {})}")
    return "\n".join(lines)


async def handle_eval_command(args: str | None) -> str:
    """Process /eval commands.

    Subcommands:
        list       — List all cases with latest status
        run        — Run all cases
        run <id>   — Run a single case
        build      — Build cases from historical sessions
        analyze    — Run 5-dimension analysis
        trend      — Show pass rate trend
    """
    parts = (args or "").strip().split()
    cmd = parts[0].lower() if parts else "list"

    if cmd == "list" or cmd == "ls":
        return format_eval_list()

    if cmd == "run":
        if len(parts) > 1:
            case_id = parts[1]
            case = load_case(case_id)
            if not case:
                return f"Unknown case: {case_id}"
            run = await run_case(case, {"triggered_by": "cli"})
            return format_eval_run(run, case)
        else:
            cases = list_cases()
            if not cases:
                return "No cases to run. Use `/eval build` first."
            results = await run_cases(cases, {"triggered_by": "cli"})
            passed = sum(1 for r in results if r.passed)
            lines = [f"Ran {len(results)} cases: {passed} passed, {len(results) - passed} failed"]
            for r in results:
                c = next((c for c in cases if c.case_id == r.case_id), None)
                lines.append(format_eval_run(r, c))
            return "\n".join(lines)

    if cmd == "build":
        built = build_from_sessions(max_sessions=50)
        if not built:
            return "No new cases could be built. All sessions may already have cases."
        return f"Built {len(built)} new cases from historical sessions."

    if cmd == "analyze":
        drafts = await run_full_analysis()
        if not drafts:
            return "No actionable suggestions found."
        lines = [f"Generated {len(drafts)} suggestions:"]
        for d in drafts:
            lines.append(f"  [{d.dimension}] {d.target}: {d.suggested_value}  (conf: {d.confidence:.0%})")
        return "\n".join(lines)

    if cmd == "trend":
        rate = get_pass_rate(days=7)
        if rate["total"] == 0:
            return "No eval runs in the last 7 days."
        return (f"7-day pass rate: {rate['passed']}/{rate['total']} ({rate['rate']:.1%})\n"
                f"  passed: {rate['passed']}, failed: {rate['failed']}")

    if cmd == "suggestions":
        suggestions = list_suggestions()
        if not suggestions:
            return "No active suggestions."
        lines = [f"Active suggestions ({len(suggestions)}):"]
        for s in suggestions:
            lines.append(f"  [{s.dimension}] (conf: {s.confidence:.0%}) {s.target}: {s.suggested_value}")
        return "\n".join(lines)

    return ("Usage: /eval [list|run [case_id]|build|analyze|trend|suggestions]\n"
            "  list       — List all cases\n"
            "  run        — Run all cases\n"
            "  run <id>   — Run a single case\n"
            "  build      — Build cases from historical sessions\n"
            "  analyze    — Run 5-dimension analysis\n"
            "  trend      — Show 7-day pass rate\n"
            "  suggestions— List active optimization suggestions")
