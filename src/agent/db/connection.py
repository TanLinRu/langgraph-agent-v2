"""数据库连接与 Schema 管理 (Connection & Schema)。

模块职责
--------
提供单模块统一入口 ``_get_conn()``,负责:

1. 创建 ``memory/sessions.db`` (路径下的目录自动创建)
2. 定义 4 张核心表:
   - ``sessions`` — 会话元信息
   - ``messages`` — 消息逐条记录
   - ``tool_usage`` — 工具调用审计
   - ``task_updates`` — 子任务状态跟踪
3. 执行渐进式 Migration (ALTER TABLE ADD COLUMN),不破坏旧版 DB

为什么独立成模块:
    所有查询都需要先获取 conn,集中管理连接逻辑和 schema 版本,
    避免每个 db 子模块各自复制 create table 逻辑。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_DB_PATH = Path("memory/sessions.db")


def _get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接,自动迁移表结构。

    幂等安全 —— 重复调用不会重建已存在的表或列。
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))

    # ── 核心表 ──────────────────────────────────────────────
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

    # ── 渐进式 Migration: sessions 表 ──────────────────────
    for col, dtype, default in [
        ("user_id", "TEXT", "DEFAULT 'default'"),
        ("title", "TEXT", "DEFAULT ''"),
        ("summary", "TEXT", "DEFAULT ''"),
        ("compacted_at", "TIMESTAMP", "DEFAULT NULL"),
        ("status", "TEXT", "DEFAULT 'active'"),
        ("acp_session_id", "TEXT", "DEFAULT ''"),
        ("project_path", "TEXT", "DEFAULT ''"),
        ("metrics", "TEXT", "DEFAULT NULL"),
        ("audit_summary", "TEXT", "DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass  # 列已存在不报错

    # ── 渐进式 Migration: messages 表 ──────────────────────
    for col, dtype, default in [
        ("thinking", "TEXT", "DEFAULT ''"),
        ("compacted", "INTEGER", "DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass

    # ── 辅助 Migration: duration_ms ────────────────────────
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN duration_ms INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    conn.commit()
    return conn
