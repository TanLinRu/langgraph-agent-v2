from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from src.agent.db.connection import _get_conn
from src.agent.eval.models import EvalCase, EvalExpectation
from src.agent.eval.storage import list_cases, save_case

logger = logging.getLogger(__name__)


def build_from_sessions(
    max_sessions: int = 20,
    min_messages: int = 2,
    tags: list[str] | None = None,
) -> list[EvalCase]:
    """Extract eval cases from historical sessions in SQLite."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT session_id, audit_summary "
        "FROM sessions WHERE status = 'active' "
        "ORDER BY updated_at DESC LIMIT ?",
        (max_sessions,),
    ).fetchall()

    existing = {c.case_id for c in list_cases()}
    built: list[EvalCase] = []

    for row in rows:
        session_id = row[0]
        audit_summary = row[1] or ""

        msgs = conn.execute(
            "SELECT role, content, tool_calls, name FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()

        if len(msgs) < min_messages:
            continue

        task = _extract_task(msgs)
        if not task:
            continue

        case_id = f"hist-{session_id[:8]}"
        if case_id in existing:
            continue

        expected = _infer_expectation(msgs, audit_summary)
        tags_list = list(tags or []) + ["auto-generated"]

        case = EvalCase(
            case_id=case_id,
            task=task,
            tags=tags_list,
            expected=expected,
            source_type="historical",
            source_session_id=session_id,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        save_case(case)
        built.append(case)
        existing.add(case_id)

    conn.close()
    logger.info("[EVAL] built %d cases from sessions", len(built))
    return built


def build_from_session(
    session_id: str,
    tags: list[str] | None = None,
) -> EvalCase | None:
    """Build a single eval case from a specific session ID."""
    conn = _get_conn()
    msgs = conn.execute(
        "SELECT role, content, tool_calls, name FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()

    if len(msgs) < 2:
        logger.warning("[EVAL] session %s has < 2 messages, skipping", session_id)
        return None

    task = _extract_task(msgs)
    if not task:
        logger.warning("[EVAL] no human task found in session %s", session_id)
        return None

    # Load audit_summary for inference
    conn2 = _get_conn()
    row = conn2.execute(
        "SELECT audit_summary FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn2.close()
    audit_summary = row[0] if row else ""

    expected = _infer_expectation(msgs, audit_summary)
    case_id = f"manual-{session_id[:8]}"

    # Overwrite if already exists
    case = EvalCase(
        case_id=case_id,
        task=task,
        tags=list(tags or []) + ["auto-generated"],
        expected=expected,
        source_type="manual",
        source_session_id=session_id,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    save_case(case)
    logger.info("[EVAL] built case %s from session %s", case_id, session_id)
    return case


def _extract_task(msgs: list) -> str:
    """Extract the first human message as the task."""
    for m in msgs:
        role = m[0]
        content = m[1] or ""
        if role == "human" and content.strip():
            return content.strip()
    return ""


def _is_valid_tool_name(name: str) -> bool:
    if not name:
        return False
    if "\\" in name or "/" in name:
        return False
    if name.startswith("."):
        return False
    return True


def _infer_expectation(
    msgs: list,
    audit_summary: str,
) -> EvalExpectation:
    """Heuristically infer expected values from historical data."""
    tools_used: set[str] = set()
    total_text = ""
    plan_agents: set[str] = set()

    for m in msgs:
        role = m[0]
        content = m[1] or ""
        tool_calls_raw = m[2] or ""
        name = m[3] or ""

        if role == "ai":
            total_text += content

        if tool_calls_raw:
            try:
                tcs = json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
                for tc in tcs:
                    if isinstance(tc, dict):
                        tn = tc.get("name") or tc.get("tool_name", "")
                        if _is_valid_tool_name(tn):
                            tools_used.add(tn)
            except (json.JSONDecodeError, TypeError):
                pass

        if name and name not in ("plan", "summary", "thinking"):
            plan_agents.add(name)

    # Language detection
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", total_text))
    language = "chinese" if chinese_chars > len(total_text) * 0.05 else None

    return EvalExpectation(
        must_call_tools=list(tools_used) if tools_used else [],
        language=language,
        min_output_length=max(0, len(total_text) - 100),
        plan_agents=list(plan_agents),
    )
