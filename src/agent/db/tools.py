"""工具用量与度量 (Tool Usage & Metrics)。

模块职责
--------
1. ``tool_usage`` 表 —— 记录每次工具调用,用于审计/统计
2. ``sessions.metrics`` 列 —— 记录编排性能快照 (消耗毫秒 / token)
3. ``get_tool_usage_stats`` —— 聚合工具使用频率,供前端统计面板
"""

from __future__ import annotations

import json

from src.agent.db.connection import _get_conn


def record_tool_usage(tool_name: str, session_id: str | None = None) -> None:
    """记录一次工具调用。"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO tool_usage (tool_name, session_id) VALUES (?, ?)",
        (tool_name, session_id),
    )
    conn.commit()
    conn.close()


def get_tool_usage_stats() -> list[dict]:
    """聚合所有会话的工具调用频率。

    返回值
    ------
    ``[{name, usage(次数), lastUsed}, ...]``
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT tool_name, COUNT(*) as count, MAX(called_at) as last_used "
        "FROM tool_usage GROUP BY tool_name"
    ).fetchall()
    conn.close()
    return [
        {"name": r[0], "usage": r[1], "lastUsed": r[2]}
        for r in rows
    ]


def save_metrics(session_id: str, metrics_json: str) -> None:
    """保存编排性能快照到会话记录。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET metrics = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE session_id = ?",
        (metrics_json, session_id),
    )
    conn.commit()
    conn.close()


def load_metrics(session_id: str) -> dict | None:
    """读取会话的性能快照。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT metrics FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
    return None
