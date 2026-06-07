"""会话 CRUD (Sessions)。

模块职责
--------
围绕 ``sessions`` 表的所有增删改查操作。

注意:
    消息体本身的写入在 :mod:`db.messages` 模块。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from src.agent.db.connection import _get_conn


def create_session(
    user_id: str = "default",
    title: str = "",
    project_path: str = "",
) -> str:
    """创建新会话,返回 ``session_id``。"""
    session_id = str(uuid.uuid4())
    conn = _get_conn()
    conn.execute(
        "INSERT INTO sessions (session_id, user_id, title, project_path) VALUES (?, ?, ?, ?)",
        (session_id, user_id, title, project_path),
    )
    conn.commit()
    conn.close()
    return session_id


def session_exists(session_id: str) -> bool:
    """检查会话是否存在。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return row is not None


def delete_session(session_id: str) -> None:
    """删除会话及关联的所有消息 / 任务更新。

    级联: ``messages`` + ``task_updates`` 按 session_id 清理。
    """
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM task_updates WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def list_sessions(
    user_id: str | None = None,
    ttl_hours: int = 0,
) -> list[dict]:
    """列出会话,按 ``updated_at DESC`` 排序。

    参数
    ----
    user_id: 按用户过滤;None 表示不过滤
    ttl_hours: >0 时只返回该小时数内的会话
    """
    conn = _get_conn()
    query = (
        "SELECT session_id, user_id, title, created_at, updated_at, summary, "
        "compacted_at, status, COALESCE(duration_ms, 0), "
        "COALESCE(acp_session_id, ''), COALESCE(project_path, ''), "
        "COALESCE(audit_summary, '') "
        "FROM sessions"
    )
    params: list = []
    conditions: list[str] = []
    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)
    if ttl_hours > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()
        conditions.append("updated_at > ?")
        params.append(cutoff)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY updated_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [
        {
            "session_id": r[0],
            "user_id": r[1],
            "title": r[2],
            "created_at": r[3],
            "updated_at": r[4],
            "summary": r[5] or "",
            "compacted_at": r[6],
            "status": r[7] or "active",
            "duration_ms": r[8] or 0,
            "acp_session_id": r[9] or "",
            "project_path": r[10] or "",
            "audit_summary": r[11] or "",
        }
        for r in rows
    ]


def rename_session(session_id: str, title: str) -> None:
    """重命名会话。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (title, session_id),
    )
    conn.commit()
    conn.close()


def get_session_summary(session_id: str) -> str:
    """获取会话的历史摘要 (由压缩阶段写入)。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT summary FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def save_audit_summary(session_id: str, text: str) -> None:
    """持久化审计摘要。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET audit_summary = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (text, session_id),
    )
    conn.commit()
    conn.close()


def get_audit_summary(session_id: str) -> str:
    """获取持久化的审计摘要。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT audit_summary FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def update_session_status(session_id: str, status: str) -> None:
    """更新会话状态 (active / completed / error)。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (status, session_id),
    )
    conn.commit()
    conn.close()


def get_session_project_path(session_id: str) -> str:
    """获取会话的工作目录路径。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT project_path FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def update_session_project_path(session_id: str, project_path: str) -> None:
    """更新会话的工作目录路径。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET project_path = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (project_path, session_id),
    )
    conn.commit()
    conn.close()


def update_session_duration(session_id: str, duration_ms: int) -> None:
    """更新会话累计时长 (毫秒)。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET duration_ms = ? WHERE session_id = ?",
        (duration_ms, session_id),
    )
    conn.commit()
    conn.close()


def get_acp_session_id(session_id: str) -> str | None:
    """获取关联的 ACP session ID。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT acp_session_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def update_acp_session_id(session_id: str, acp_session_id: str) -> None:
    """绑定 ACP session ID 到会话。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET acp_session_id = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (acp_session_id, session_id),
    )
    conn.commit()
    conn.close()


def save_plan(session_id: str, plan_json: str) -> None:
    """持久化 plan 结构到 sessions.plan。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET plan = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (plan_json, session_id),
    )
    conn.commit()
    conn.close()


def save_audit_outputs(session_id: str, agent_outputs_json: str) -> None:
    """持久化 agent_outputs 到 sessions.audit_outputs。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET audit_outputs = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (agent_outputs_json, session_id),
    )
    conn.commit()
    conn.close()
