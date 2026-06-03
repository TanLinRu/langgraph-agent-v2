"""Session persistence — stores conversation history per session in SQLite."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langchain_core.messages import BaseMessage

from src.agent.message import Message

_DB_PATH = Path("memory/sessions.db")

# Keep this many recent messages after compaction
_KEEP_RECENT = 5


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)
    for col, dtype, default in [
        ("user_id", "TEXT", "DEFAULT 'default'"),
        ("title", "TEXT", "DEFAULT ''"),
        ("summary", "TEXT", "DEFAULT ''"),
        ("compacted_at", "TIMESTAMP", "DEFAULT NULL"),
        ("status", "TEXT", "DEFAULT 'active'"),
        ("acp_session_id", "TEXT", "DEFAULT ''"),
        ("project_path", "TEXT", "DEFAULT ''"),
        ("metrics", "TEXT", "DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass
    for col, dtype, default in [
        ("thinking", "TEXT", "DEFAULT ''"),
        ("compacted", "INTEGER", "DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            session_id TEXT,
            called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            task TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            state TEXT DEFAULT NULL,
            started_at REAL DEFAULT NULL,
            ended_at REAL DEFAULT NULL,
            elapsed_ms INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_updates_session ON task_updates(session_id)")
    conn.commit()
    return conn


def create_session(user_id: str = "default", title: str = "", project_path: str = "") -> str:
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
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row is not None


def load_messages(session_id: str) -> list[Message]:
    """Load non-compacted messages as Message objects."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_call_id, name FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [Message.from_db_row(row) for row in rows]


def load_history(session_id: str) -> list[BaseMessage]:
    """Load non-compacted messages for LLM context (converted to langchain)."""
    return [m.to_langchain() for m in load_messages(session_id)]


def save_turn(
    session_id: str,
    user_message: str,
    assistant_content: str,
    thinking: str = "",
    tool_calls: str = "",
    name: str = "",
) -> None:
    conn = _get_conn()
    if not session_exists(session_id):
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, 'human', ?)",
        (session_id, user_message),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, thinking, tool_calls, name) VALUES (?, 'ai', ?, ?, ?, ?)",
        (session_id, assistant_content, thinking, tool_calls, name),
    )
    row = conn.execute("SELECT title FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row and not row[0]:
        title = user_message[:50].replace("\n", " ")
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (title, session_id),
        )
    conn.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def load_history_with_meta(session_id: str) -> list[dict]:
    """Load ALL messages (including compacted) with metadata for frontend restore."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, session_id, created_at, role, content, thinking, tool_calls, compacted, name FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [Message.from_db_row_verbose(row).to_frontend_dict() for row in rows]


def save_message(
    session_id: str,
    role: str,
    content: str,
    thinking: str = "",
    tool_calls: str = "",
    name: str = "",
) -> None:
    """Save a single message (not a turn pair). Used for orchestration intermediate messages."""
    conn = _get_conn()
    if not session_exists(session_id):
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    msg = Message(role=role, content=content, thinking=thinking or None, name=name or None)
    if tool_calls:
        try:
            msg.tool_calls = json.loads(tool_calls) if isinstance(tool_calls, str) else tool_calls
        except (json.JSONDecodeError, TypeError):
            pass
    role_p, content_p, tc_p, thinking_p, name_p = msg.to_db_params()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, tool_calls, thinking, name) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, role_p, content_p, tc_p, thinking_p, name_p),
    )
    if role == "human":
        row = conn.execute("SELECT title FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row and not row[0]:
            title = content[:50].replace("\n", " ")
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (title, session_id),
            )
    conn.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def get_session_summary(session_id: str) -> str:
    conn = _get_conn()
    row = conn.execute("SELECT summary FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def save_task_update(
    session_id: str,
    agent: str,
    task: str,
    status: str,
    state: str | None = None,
    started_at: float | None = None,
    ended_at: float | None = None,
    elapsed_ms: int | None = None,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO task_updates (session_id, agent, task, status, state, started_at, ended_at, elapsed_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, agent, task, status, state, started_at, ended_at, elapsed_ms),
    )
    conn.commit()
    conn.close()


def load_task_updates(session_id: str) -> list[dict]:
    """Load the latest task_update per (agent, task) — dedup keeps the most recent row."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT agent, task, status, state, started_at, ended_at, elapsed_ms
        FROM task_updates
        WHERE session_id = ?
          AND id IN (SELECT MAX(id) FROM task_updates WHERE session_id = ? GROUP BY agent, task)
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


def delete_task_updates_for_sessions(session_ids: list[str]) -> None:
    """Bulk delete task_updates for a list of session_ids."""
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


def save_metrics(session_id: str, metrics_json: str) -> None:
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN metrics TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "UPDATE sessions SET metrics = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (metrics_json, session_id),
    )
    conn.commit()
    conn.close()


def load_metrics(session_id: str) -> dict | None:
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN metrics TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    row = conn.execute("SELECT metrics FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def delete_task_updates(session_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM task_updates WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def compact_session(session_id: str, summary: str, keep: int | None = None) -> int:
    """Mark old messages as compacted (keep in DB but exclude from LLM context).

    Returns the number of messages marked as compacted.
    """
    keep_n = _KEEP_RECENT if keep is None else keep
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? AND compacted = 0", (session_id,)
    ).fetchone()
    total = row[0] if row else 0

    if total <= keep_n:
        conn.execute(
            "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (summary, session_id),
        )
        conn.commit()
        conn.close()
        return 0

    conn.execute(
        """UPDATE messages SET compacted = 1 WHERE session_id = ? AND compacted = 0 AND id NOT IN (
            SELECT id FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id DESC LIMIT ?
        )""",
        (session_id, session_id, keep_n),
    )
    marked = total - keep_n

    conn.execute(
        "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (summary, session_id),
    )
    conn.commit()
    conn.close()
    return marked


def list_sessions(user_id: str | None = None, ttl_hours: int = 0) -> list[dict]:
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN duration_ms INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    query = "SELECT session_id, user_id, title, created_at, updated_at, summary, compacted_at, status, COALESCE(duration_ms, 0), COALESCE(acp_session_id, ''), COALESCE(project_path, '') FROM sessions"
    params: list = []

    conditions = []
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
        }
        for r in rows
    ]


def delete_session(session_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM task_updates WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def record_tool_usage(tool_name: str, session_id: str | None = None) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO tool_usage (tool_name, session_id) VALUES (?, ?)",
        (tool_name, session_id),
    )
    conn.commit()
    conn.close()


def update_session_status(session_id: str, status: str) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (status, session_id),
    )
    conn.commit()
    conn.close()


def get_acp_session_id(session_id: str) -> str | None:
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN acp_session_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    cur = conn.execute("SELECT acp_session_id FROM sessions WHERE session_id = ?", (session_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def update_acp_session_id(session_id: str, acp_session_id: str) -> None:
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN acp_session_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "UPDATE sessions SET acp_session_id = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (acp_session_id, session_id),
    )
    conn.commit()
    conn.close()


def rename_session(session_id: str, title: str) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (title, session_id),
    )
    conn.commit()
    conn.close()


def update_session_project_path(session_id: str, project_path: str) -> None:
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN project_path TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "UPDATE sessions SET project_path = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (project_path, session_id),
    )
    conn.commit()
    conn.close()


def update_session_duration(session_id: str, duration_ms: int) -> None:
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN duration_ms INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "UPDATE sessions SET duration_ms = ? WHERE session_id = ?",
        (duration_ms, session_id),
    )
    conn.commit()
    conn.close()


def get_tool_usage_stats() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT tool_name, COUNT(*) as count, MAX(called_at) as last_used FROM tool_usage GROUP BY tool_name"
    ).fetchall()
    conn.close()
    return [
        {"name": r[0], "usage": r[1], "lastUsed": r[2]}
        for r in rows
    ]
