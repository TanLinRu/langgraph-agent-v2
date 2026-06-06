"""消息 CRUD (Messages)。

模块职责
--------
围绕 ``messages`` 表的所有操作。

类型转换
--------
本模块使用 :class:`src.agent.message.Message` 数据类作为内部表示,
通过 ``Message.to_langchain()`` / ``Message.from_db_row()`` / 等
方法与 langchain ``BaseMessage`` / 前端 dict 做双向转换。

核心转换链路::

    DB row → Message.from_db_row() → Message → .to_langchain() → BaseMessage
    DB row → Message.from_db_row_verbose() → .to_frontend_dict() → frontend dict
    前端 dict / langchain msg → Message(...) → .to_db_params() → DB INSERT
"""

from __future__ import annotations

import json

from langchain_core.messages import BaseMessage

from src.agent.db.connection import _get_conn
from src.agent.db.sessions import session_exists
from src.agent.message import Message


def load_messages(session_id: str) -> list[Message]:
    """加载未被压缩的消息,返回 ``Message`` 对象列表。

    用于需要 Message 元信息的场景 (例如 LLM context 构造)。
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_call_id, name "
        "FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [Message.from_db_row(row) for row in rows]


def load_history(session_id: str) -> list[BaseMessage]:
    """加载未被压缩的消息,转换为 langchain ``BaseMessage``。

    用于 LLM context 组装 (兼容旧接口 ``langchain_core.messages``)。
    """
    return [m.to_langchain() for m in load_messages(session_id)]


def load_history_with_meta(session_id: str) -> list[dict]:
    """加载全部消息 (含已压缩),带元数据,用于前端 restore。

    返回 ``[Message.to_frontend_dict()]`` 列表。
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, session_id, created_at, role, content, thinking, "
        "tool_calls, compacted, name "
        "FROM messages WHERE session_id = ? ORDER BY id",
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
    """保存单条消息 (非 turn 对)。用于编排过程中间消息。

    如果 ``session_id`` 不存在则自动创建(兜底)；
    如果 role 是 ``human`` 且会话无标题,自动取前 50 字作为标题。
    """
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
        "INSERT INTO messages (session_id, role, content, tool_calls, thinking, name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, role_p, content_p, tc_p, thinking_p, name_p),
    )
    if role == "human":
        row = conn.execute(
            "SELECT title FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row and not row[0]:
            title = content[:50].replace("\n", " ")
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE session_id = ?",
                (title, session_id),
            )
    conn.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def save_turn(
    session_id: str,
    user_message: str,
    assistant_content: str,
    thinking: str = "",
    tool_calls: str = "",
    name: str = "",
) -> None:
    """保存一轮对话 (human + ai),自动处理标题生成。

    与 ``save_message`` 的区别:一次性写入 human/ai 两条,
    并自动将用户首条消息作为会话标题。
    """
    conn = _get_conn()
    if not session_exists(session_id):
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, 'human', ?)",
        (session_id, user_message),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, thinking, tool_calls, name) "
        "VALUES (?, 'ai', ?, ?, ?, ?)",
        (session_id, assistant_content, thinking, tool_calls, name),
    )
    row = conn.execute(
        "SELECT title FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
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


def clear_session_messages(session_id: str) -> None:
    """Clear all messages in a session (keep the session itself).

    Args:
        session_id: Session identifier
    """
    conn = _get_conn()
    conn.execute(
        "DELETE FROM messages WHERE session_id = ?",
        (session_id,),
    )
    # Also clear task_updates related to this session
    conn.execute(
        "DELETE FROM task_updates WHERE session_id = ?",
        (session_id,),
    )
    # Reset session title and summary
    conn.execute(
        "UPDATE sessions SET title = NULL, summary = NULL, updated_at = CURRENT_TIMESTAMP "
        "WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()
