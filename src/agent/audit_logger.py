"""Structured audit trail for errors and tool executions.

Log file naming: {scenario_code}-{yyyy-MM-dd_HH-mm-ss}.jsonl
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_AUDIT_DIR = Path("memory/audit")


def _get_audit_path(scenario_code: str = "general") -> Path:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    return _AUDIT_DIR / f"{scenario_code}-{ts}.jsonl"


def log_audit_event(
    trace_id: str,
    event_type: str,
    severity: str,
    context: dict | None = None,
    scenario_code: str = "general",
) -> None:
    """Write a structured audit entry.

    Args:
        trace_id: Unique trace identifier.
        event_type: Category of event (e.g. 'llm_call', 'tool_exec', 'error').
        severity: 'info', 'warning', 'error', 'critical'.
        context: Arbitrary key-value context.
        scenario_code: Business scenario code prefix for the log file name
                       (e.g. 'chat', 'orchestrate', 'compress').
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "event_type": event_type,
        "severity": severity,
        "scenario_code": scenario_code,
        "context": context or {},
    }
    audit_path = _get_audit_path(scenario_code)
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.debug("audit: %s -> %s", scenario_code, audit_path.name)
