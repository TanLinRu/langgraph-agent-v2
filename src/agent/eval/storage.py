from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.agent.db.connection import _get_conn
from src.agent.eval.models import EvalCase, EvalExpectation, EvalResultItem, EvalRun, EvalSuggestion, SuggestionDraft

# ── eval_cases ──────────────────────────────────────────────────────


def save_case(case: EvalCase) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO eval_cases (case_id, task, tags, expected, source_type, source_session_id, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            case.case_id, case.task, json.dumps(case.tags, ensure_ascii=False),
            case.expected.model_dump_json(), case.source_type, case.source_session_id,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def load_case(case_id: str) -> EvalCase | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT case_id, task, tags, expected, source_type, source_session_id, updated_at "
        "FROM eval_cases WHERE case_id = ?", (case_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return EvalCase(
        case_id=row[0], task=row[1], tags=json.loads(row[2] or "[]"),
        expected=EvalExpectation(**json.loads(row[3])),
        source_type=row[4], source_session_id=row[5], updated_at=row[6] or "",
    )


def list_cases() -> list[EvalCase]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT case_id, task, tags, expected, source_type, source_session_id, updated_at "
        "FROM eval_cases ORDER BY updated_at DESC",
    ).fetchall()
    conn.close()
    return [
        EvalCase(
            case_id=r[0], task=r[1], tags=json.loads(r[2] or "[]"),
            expected=EvalExpectation(**json.loads(r[3])),
            source_type=r[4], source_session_id=r[5], updated_at=r[6] or "",
        )
        for r in rows
    ]


def delete_case(case_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM eval_cases WHERE case_id = ?", (case_id,))
    conn.execute("DELETE FROM eval_runs WHERE case_id = ?", (case_id,))
    conn.commit()
    conn.close()


# ── eval_runs ────────────────────────────────────────────────────────


def save_run(run: EvalRun) -> None:
    conn = _get_conn()
    cols = (
        "task_id, case_id, session_id, thread_id, passed, "
        "failures, metrics_snapshot, config_snapshot, "
        "triggered_by, created_at"
    )
    conn.execute(
        f"INSERT OR REPLACE INTO eval_runs ({cols}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.task_id, run.case_id, run.session_id, run.thread_id,
            int(run.passed), json.dumps([f.model_dump() for f in run.failures], ensure_ascii=False),
            json.dumps(run.metrics_snapshot, ensure_ascii=False) if run.metrics_snapshot else None,
            json.dumps(run.config_snapshot, ensure_ascii=False) if run.config_snapshot else None,
            run.triggered_by, run.created_at or datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def list_runs(case_id: str | None = None, limit: int = 20) -> list[EvalRun]:
    conn = _get_conn()
    if case_id:
        rows = conn.execute(
            "SELECT task_id, case_id, session_id, thread_id, passed, "
            "failures, metrics_snapshot, config_snapshot, "
            "triggered_by, created_at "
            "FROM eval_runs WHERE case_id = ? ORDER BY created_at DESC LIMIT ?",
            (case_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT task_id, case_id, session_id, thread_id, passed, "
            "failures, metrics_snapshot, config_snapshot, "
            "triggered_by, created_at "
            "FROM eval_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [_row_to_run(r) for r in rows]


def get_latest_run(case_id: str) -> EvalRun | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT task_id, case_id, session_id, thread_id, passed, "
        "failures, metrics_snapshot, config_snapshot, "
        "triggered_by, created_at "
        "FROM eval_runs WHERE case_id = ? ORDER BY created_at DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    conn.close()
    return _row_to_run(row) if row else None


def get_run_by_task_id(task_id: str) -> EvalRun | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT task_id, case_id, session_id, thread_id, passed, "
        "failures, metrics_snapshot, config_snapshot, "
        "triggered_by, created_at "
        "FROM eval_runs WHERE task_id = ?", (task_id,),
    ).fetchone()
    conn.close()
    return _row_to_run(row) if row else None


def get_runs_in_range(days: int = 7, case_id: str | None = None) -> list[EvalRun]:
    conn = _get_conn()
    if case_id:
        rows = conn.execute(
            "SELECT task_id, case_id, session_id, thread_id, passed, "
            "failures, metrics_snapshot, config_snapshot, "
            "triggered_by, created_at "
            "FROM eval_runs WHERE created_at > datetime('now', ?) AND case_id = ? ORDER BY created_at DESC",
            (f"-{days} days", case_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT task_id, case_id, session_id, thread_id, passed, "
            "failures, metrics_snapshot, config_snapshot, "
            "triggered_by, created_at "
            "FROM eval_runs WHERE created_at > datetime('now', ?) ORDER BY created_at DESC",
            (f"-{days} days",),
        ).fetchall()
    conn.close()
    return [_row_to_run(r) for r in rows]


def _row_to_run(r: Any) -> EvalRun:
    return EvalRun(
        task_id=r[0], case_id=r[1], session_id=r[2], thread_id=r[3],
        passed=bool(r[4]),
        failures=[EvalResultItem(**f) for f in json.loads(r[5] or "[]")],
        metrics_snapshot=json.loads(r[6]) if r[6] else {},
        config_snapshot=json.loads(r[7]) if r[7] else {},
        triggered_by=r[8], created_at=r[9] or "",
    )


def get_pass_rate(days: int = 7) -> dict[str, Any]:
    runs = get_runs_in_range(days)
    total = len(runs)
    if total == 0:
        return {"total": 0, "passed": 0, "failed": 0, "rate": 0.0}
    passed = sum(1 for r in runs if r.passed)
    return {"total": total, "passed": passed, "failed": total - passed, "rate": round(passed / total, 4)}


# ── eval_suggestions ─────────────────────────────────────────────────


def save_suggestion(draft: SuggestionDraft) -> int:
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO eval_suggestions "
        "(dimension, target, current_value, suggested_value, "
        "reasoning, evidence, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            draft.dimension, draft.target, draft.current_value, draft.suggested_value,
            draft.reasoning, json.dumps(draft.evidence, ensure_ascii=False),
            draft.confidence,
        ),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def list_suggestions(dimension: str | None = None, only_active: bool = True) -> list[EvalSuggestion]:
    conn = _get_conn()
    conditions = ["dismissed = 0"] if only_active else []
    params: list = []
    if dimension:
        conditions.append("dimension = ?")
        params.append(dimension)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"SELECT id, dimension, target, current_value, suggested_value, reasoning, evidence, confidence, "
        f"applied, applied_at, dismissed, created_at FROM eval_suggestions{where} ORDER BY confidence DESC",
        params,
    ).fetchall()
    conn.close()
    return [
        EvalSuggestion(
            id=r[0], dimension=r[1], target=r[2], current_value=r[3] or "",
            suggested_value=r[4] or "", reasoning=r[5] or "",
            evidence=json.loads(r[6]) if r[6] else [],
            confidence=r[7] or 0.0, applied=bool(r[8]),
            applied_at=r[9] or "", dismissed=bool(r[10]),
            created_at=r[11] or "",
        )
        for r in rows
    ]


def apply_suggestion(suggestion_id: int) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE eval_suggestions SET applied = 1, applied_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), suggestion_id),
    )
    conn.commit()
    conn.close()


def dismiss_suggestion(suggestion_id: int) -> None:
    conn = _get_conn()
    conn.execute("UPDATE eval_suggestions SET dismissed = 1 WHERE id = ?", (suggestion_id,))
    conn.commit()
    conn.close()
