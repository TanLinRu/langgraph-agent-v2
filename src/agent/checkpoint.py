"""Session persistence — stores conversation history per session in SQLite."""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

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
    # Auto-migrate: add new columns if missing
    for col, dtype, default in [
        ("user_id", "TEXT", "DEFAULT 'default'"),
        ("title", "TEXT", "DEFAULT ''"),
        ("summary", "TEXT", "DEFAULT ''"),
        ("compacted_at", "TIMESTAMP", "DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass  # column already exists
    # Auto-migrate messages table
    for col, dtype, default in [
        ("thinking", "TEXT", "DEFAULT ''"),
        ("compacted", "INTEGER", "DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def _serialize_message(msg: BaseMessage) -> dict:
    entry = {"role": msg.type, "content": msg.content}
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        entry["tool_calls"] = json.dumps(msg.tool_calls, ensure_ascii=False)
    if hasattr(msg, "tool_call_id") and msg.tool_call_id:
        entry["tool_call_id"] = msg.tool_call_id
    if hasattr(msg, "name") and msg.name:
        entry["name"] = msg.name
    return entry


def _deserialize_message(row: tuple) -> BaseMessage:
    role, content, tool_calls_json, tool_call_id, name = row
    if role == "human":
        return HumanMessage(content=content)
    elif role == "ai":
        tool_calls = json.loads(tool_calls_json) if tool_calls_json else []
        # Ensure each tool_call has required 'id' field
        for i, tc in enumerate(tool_calls):
            if isinstance(tc, dict) and "id" not in tc:
                tc["id"] = f"call_{i}"
        return AIMessage(content=content, tool_calls=tool_calls)
    elif role == "tool":
        return ToolMessage(content=content, tool_call_id=tool_call_id or "", name=name or "")
    return HumanMessage(content=content)


def create_session(user_id: str = "default", title: str = "") -> str:
    session_id = str(uuid.uuid4())
    conn = _get_conn()
    conn.execute(
        "INSERT INTO sessions (session_id, user_id, title) VALUES (?, ?, ?)",
        (session_id, user_id, title),
    )
    conn.commit()
    conn.close()
    return session_id


def session_exists(session_id: str) -> bool:
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row is not None


def load_history(session_id: str) -> list[BaseMessage]:
    """Load non-compacted messages for LLM context."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_call_id, name FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [_deserialize_message(row) for row in rows]


def save_turn(
    session_id: str,
    user_message: str,
    assistant_content: str,
    thinking: str = "",
    tool_calls: str = "",
) -> None:
    conn = _get_conn()
    if not session_exists(session_id):
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, 'human', ?)",
        (session_id, user_message),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, thinking, tool_calls) VALUES (?, 'ai', ?, ?, ?)",
        (session_id, assistant_content, thinking, tool_calls),
    )
    conn.commit()
    conn.close()


def load_history_with_meta(session_id: str) -> list[dict]:
    """Load ALL messages (including compacted) with metadata for frontend restore."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, thinking, tool_calls, compacted, name FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    result = []
    for role, content, thinking, tool_calls_json, compacted, name in rows:
        entry: dict = {"type": role, "content": content or ""}
        if thinking:
            entry["thinking"] = thinking
        if tool_calls_json:
            try:
                entry["tool_calls"] = json.loads(tool_calls_json)
            except (json.JSONDecodeError, TypeError):
                pass
        if compacted:
            entry["compacted"] = True
        if name:
            entry["name"] = name
        result.append(entry)
    return result


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
    conn.execute(
        "INSERT INTO messages (session_id, role, content, thinking, tool_calls, name) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, role, content, thinking, tool_calls, name),
    )
    # Auto-title: use first user message (truncated)
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


def compact_session(session_id: str, summary: str) -> int:
    """Mark old messages as compacted (keep in DB but exclude from LLM context).

    Returns the number of messages marked as compacted.
    """
    conn = _get_conn()
    # Count total non-compacted messages
    row = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? AND compacted = 0", (session_id,)
    ).fetchone()
    total = row[0] if row else 0

    if total <= _KEEP_RECENT:
        # Nothing to compact, just save summary
        conn.execute(
            "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (summary, session_id),
        )
        conn.commit()
        conn.close()
        return 0

    # Mark all but the most recent _KEEP_RECENT messages as compacted
    conn.execute(
        """UPDATE messages SET compacted = 1 WHERE session_id = ? AND compacted = 0 AND id NOT IN (
            SELECT id FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id DESC LIMIT ?
        )""",
        (session_id, session_id, _KEEP_RECENT),
    )
    marked = total - _KEEP_RECENT

    conn.execute(
        "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (summary, session_id),
    )
    conn.commit()
    conn.close()
    return marked


def list_sessions(user_id: str | None = None, ttl_hours: int = 0) -> list[dict]:
    conn = _get_conn()
    query = "SELECT session_id, user_id, title, created_at, updated_at, summary, compacted_at FROM sessions"
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
        }
        for r in rows
    ]


def delete_session(session_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
