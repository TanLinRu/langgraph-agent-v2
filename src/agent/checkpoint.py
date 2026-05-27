"""Session persistence — stores conversation history per session in SQLite."""

import json
import sqlite3
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

_DB_PATH = Path("memory/sessions.db")


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
        return AIMessage(content=content, tool_calls=tool_calls)
    elif role == "tool":
        return ToolMessage(content=content, tool_call_id=tool_call_id or "", name=name or "")
    return HumanMessage(content=content)


def create_session() -> str:
    session_id = str(uuid.uuid4())
    conn = _get_conn()
    conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.commit()
    conn.close()
    return session_id


def session_exists(session_id: str) -> bool:
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row is not None


def load_history(session_id: str) -> list[BaseMessage]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_call_id, name FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [_deserialize_message(row) for row in rows]


def save_turn(session_id: str, user_message: str, assistant_content: str) -> None:
    conn = _get_conn()
    if not session_exists(session_id):
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, 'human', ?)",
        (session_id, user_message),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, 'ai', ?)",
        (session_id, assistant_content),
    )
    conn.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def list_sessions() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT session_id, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [{"session_id": r[0], "created_at": r[1], "updated_at": r[2]} for r in rows]


def delete_session(session_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
