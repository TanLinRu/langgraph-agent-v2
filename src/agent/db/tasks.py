"""任务更新 CRUD (Task Updates)。

模块职责
--------
围绕 ``task_updates`` 表的所有操作,记录每个子任务的 ``pending → running → completed/failed`` 状态流转。

去重规则
--------
本模块最重要的设计:``load_task_updates`` 使用 ``GROUP BY agent, task``
去重,只保留同组合的最后一行 (``MAX(id)``),确保前端看到的是最新状态。
"""

from __future__ import annotations

import time

from src.agent.db.connection import _get_conn


def save_task_update(
    session_id: str,
    agent: str,
    task: str,
    status: str,
    state: str | None = None,
    started_at: float | None = None,
    ended_at: float | None = None,
    elapsed_ms: int | None = None,
    task_id: str = "",
) -> None:
    """写入一条任务状态变更记录 (追加,不修改历史)。"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO task_updates "
        "(session_id, agent, task, status, state, started_at, ended_at, elapsed_ms, task_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, agent, task, status, state, started_at, ended_at, elapsed_ms, task_id),
    )
    conn.commit()
    conn.close()


def load_task_updates(session_id: str) -> list[dict]:
    """加载最新 (去重后) 的任务状态列表。

    返回值
    ------
    ``[{agent, task, status, state, started_at, ended_at, elapsed_ms}]``
    """
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT agent, task, status, state, started_at, ended_at, elapsed_ms
        FROM task_updates
        WHERE session_id = ?
          AND id IN (
              SELECT MAX(id) FROM task_updates
              WHERE session_id = ? GROUP BY agent, task
          )
        ORDER BY id
        """,
        (session_id, session_id),
    ).fetchall()
    conn.close()
    return [
        {
            "agent": r[0],
            "task": r[1],
            "status": r[2],
            "state": r[3],
            "started_at": r[4],
            "ended_at": r[5],
            "elapsed_ms": r[6],
        }
        for r in rows
    ]


def delete_task_updates(session_id: str) -> None:
    """删除某一会话的全部任务更新记录。"""
    conn = _get_conn()
    conn.execute("DELETE FROM task_updates WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def reconcile_session_tasks(session_id: str) -> None:
    """将 session 中 running/pending 的任务标记为 failed（用于会话恢复）。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE task_updates SET status = 'failed', ended_at = ? "
        "WHERE session_id = ? AND status IN ('running', 'pending')",
        (time.time(), session_id),
    )
    conn.commit()
    conn.close()


def delete_task_updates_for_sessions(session_ids: list[str]) -> None:
    """批量删除指定会话列表的任务更新记录。"""
    if not session_ids:
        return
    conn = _get_conn()
    placeholders = ",".join("?" for _ in session_ids)
    conn.execute(
        f"DELETE FROM task_updates WHERE session_id IN ({placeholders})",
        tuple(session_ids),
    )
    conn.commit()
    conn.close()
