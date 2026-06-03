"""对话压缩 (Compaction)。

模块职责
--------
实现 ``compact_session()`` —— 把早期消息标记为 ``compacted=1``,
统计 + 摘要写入 sessions 表,但保留原始消息行不删除。

为什么标记而不是删除:
    前端 restore 时需要看到所有历史消息 (包括已压缩的),
    只是 LLM context 构建时跳过 ``compacted=1`` 的消息。

与 ``src.agent.context.compression.py`` 的关系:
    * ``compression.py`` —— 负责"是否压缩"的判断 + 生成摘要文本
    * ``db/compact.py`` —— 负责"具体执行"DB 标记 + 摘要入库
"""

from __future__ import annotations

from src.agent.db.connection import _get_conn

# 默认保留最近 5 条非压缩消息
_KEEP_RECENT = 5


def compact_session(
    session_id: str,
    summary: str,
    keep: int | None = None,
) -> int:
    """压缩会话:标记旧消息为 ``compacted=1``,写入摘要。

    参数
    ----
    keep: 保留多少条非压缩消息;默认 ``_KEEP_RECENT``

    返回值
    ------
    被标记为 compacted 的消息条数。0 表示无需压缩。
    """
    keep_n = _KEEP_RECENT if keep is None else keep
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? AND compacted = 0",
        (session_id,),
    ).fetchone()
    total = row[0] if row else 0

    if total <= keep_n:
        # 消息不够多,只更新摘要,不压缩任何消息
        conn.execute(
            "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP "
            "WHERE session_id = ?",
            (summary, session_id),
        )
        conn.commit()
        conn.close()
        return 0

    # 标记旧消息为 compacted,保留最新 keep_n 条
    conn.execute(
        """UPDATE messages SET compacted = 1
           WHERE session_id = ? AND compacted = 0
             AND id NOT IN (
                 SELECT id FROM messages
                 WHERE session_id = ? AND compacted = 0
                 ORDER BY id DESC LIMIT ?
             )""",
        (session_id, session_id, keep_n),
    )
    marked = total - keep_n

    conn.execute(
        "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP "
        "WHERE session_id = ?",
        (summary, session_id),
    )
    conn.commit()
    conn.close()
    return marked
