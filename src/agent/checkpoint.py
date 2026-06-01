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
        ("status", "TEXT", "DEFAULT 'active'"),
        ("acp_session_id", "TEXT", "DEFAULT ''"),
        ("project_path", "TEXT", "DEFAULT ''"),
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
    # Tool usage tracking
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            session_id TEXT,
            called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Agent configuration
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'helper',
            desc TEXT DEFAULT '',
            tools TEXT DEFAULT '[]',
            system_prompt TEXT DEFAULT '',
            model TEXT DEFAULT NULL,
            temperature REAL DEFAULT NULL,
            max_tokens INTEGER DEFAULT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # CLI tools configuration
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_clis (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            command TEXT NOT NULL,
            args TEXT DEFAULT '[]',
            timeout INTEGER DEFAULT 120,
            desc TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    # Seed default agents if empty
    _seed_default_agents(conn)
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
    # Auto-title: use first user message (truncated)
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
        "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (summary, session_id),
    )
    conn.commit()
    conn.close()
    return marked


def list_sessions(user_id: str | None = None, ttl_hours: int = 0) -> list[dict]:
    conn = _get_conn()
    # Ensure duration_ms column exists
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
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def record_tool_usage(tool_name: str, session_id: str | None = None) -> None:
    """Record a tool usage event for analytics."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO tool_usage (tool_name, session_id) VALUES (?, ?)",
        (tool_name, session_id),
    )
    conn.commit()
    conn.close()


def update_session_status(session_id: str, status: str) -> None:
    """Update session status (processing/completed/active)."""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (status, session_id),
    )
    conn.commit()
    conn.close()


def get_acp_session_id(session_id: str) -> str | None:
    """Get ACP session ID for a chat session, or None."""
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
    """Store ACP session ID for a chat session."""
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
    """Rename a session."""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (title, session_id),
    )
    conn.commit()
    conn.close()


def update_session_project_path(session_id: str, project_path: str) -> None:
    """Set the project path for a session."""
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
    """Store execution duration for a session."""
    conn = _get_conn()
    # Add duration column if missing
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
    """Get aggregated tool usage statistics."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT tool_name, COUNT(*) as count, MAX(called_at) as last_used FROM tool_usage GROUP BY tool_name"
    ).fetchall()
    conn.close()
    return [
        {"name": r[0], "usage": r[1], "lastUsed": r[2]}
        for r in rows
    ]


# ── Agent Configuration CRUD ─────────────────────────────────────

_DEFAULT_AGENTS = [
    {"id": "supervisor", "name": "Supervisor", "type": "supervisor", "desc": "Session orchestration and task dispatch",
     "tools": "[]", "system_prompt": "You are a supervisor that coordinates multiple agents to complete tasks."},
    {"id": "coder", "name": "Coder", "type": "coder", "desc": "Code generation, debugging, and refactoring",
     "tools": '["execute_code","read_file","write_file","search_files"]', "system_prompt": "You are a coding expert. Write and execute code to solve problems. Think step by step."},
    {"id": "researcher", "name": "Researcher", "type": "researcher", "desc": "Information retrieval and file search",
     "tools": '["search_files","list_directory","read_file"]', "system_prompt": "You are a research expert. Search and analyze files to find information."},
    {"id": "analyst", "name": "Analyst", "type": "analyst", "desc": "Data analysis and reporting",
     "tools": '["execute_code","read_file","search_files"]', "system_prompt": "You are a data analyst. Process data and generate insights."},
    {"id": "direct", "name": "Direct", "type": "direct", "desc": "Direct assistant for simple tasks",
     "tools": '["execute_code","read_file","write_file","list_directory","search_files"]', "system_prompt": "You are a helpful assistant. Complete the task directly."},
    {"id": "helper", "name": "Helper", "type": "helper", "desc": "Daily assistant tasks",
     "tools": "[]", "system_prompt": "You are a helpful daily assistant."},
    {"id": "opencode", "name": "OpenCode", "type": "opencode", "desc": "External AI coding agent (opencode CLI)",
     "tools": '["read_file","write_file","search_files","list_directory","dispatch_cli","list_available_clis"]',
     "system_prompt": (
         "You are an OpenCode agent — a wrapper around the external opencode CLI coding assistant. "
         "Your primary tool is `dispatch_cli` with `cli_name=\"opencode\"`. "
         "When given a coding task:\n"
         "1. First read relevant files to understand the codebase context\n"
         "2. Build a detailed prompt that includes file paths, code snippets, and specific requirements\n"
         "3. Call dispatch_cli with the assembled prompt to get opencode's analysis\n"
         "4. Review and present the results clearly\n"
         "Always include file paths and code context in your dispatch_cli prompts for best results."
     )},
    {"id": "claude-agent", "name": "Claude Agent", "type": "claude-agent", "desc": "External AI coding agent (Claude Code CLI)",
     "tools": '["read_file","write_file","search_files","list_directory","dispatch_cli","list_available_clis"]',
     "system_prompt": (
         "You are a Claude Code agent — a wrapper around the external claude CLI coding assistant. "
         "Your primary tool is `dispatch_cli` with `cli_name=\"claude\"`. "
         "When given a coding task:\n"
         "1. First read relevant files to understand the codebase context\n"
         "2. Build a detailed prompt that includes file paths, code snippets, and specific requirements\n"
         "3. Call dispatch_cli with the assembled prompt to get Claude's analysis\n"
         "4. Review and present the results clearly\n"
         "Always include file paths and code context in your dispatch_cli prompts for best results."
     )},
]


def _seed_default_agents(conn: sqlite3.Connection) -> None:
    """Insert default agents if the agents table is empty."""
    row = conn.execute("SELECT COUNT(*) FROM agents").fetchone()
    if row and row[0] > 0:
        return
    for a in _DEFAULT_AGENTS:
        conn.execute(
            "INSERT INTO agents (id, name, type, desc, tools, system_prompt) VALUES (?, ?, ?, ?, ?, ?)",
            (a["id"], a["name"], a["type"], a["desc"], a["tools"], a["system_prompt"]),
        )
    conn.commit()


def list_agents() -> list[dict]:
    """List all agent configurations."""
    conn = _get_conn()
    rows = conn.execute("SELECT id, name, type, desc, tools, system_prompt, model, temperature, max_tokens, enabled FROM agents ORDER BY id").fetchall()
    conn.close()
    return [
        {
            "id": r[0], "name": r[1], "type": r[2], "desc": r[3],
            "tools": json.loads(r[4]) if r[4] else [],
            "system_prompt": r[5] or "", "model": r[6], "temperature": r[7],
            "max_tokens": r[8], "enabled": bool(r[9]),
        }
        for r in rows
    ]


def get_agent(agent_id: str) -> dict | None:
    """Get a single agent configuration."""
    conn = _get_conn()
    row = conn.execute("SELECT id, name, type, desc, tools, system_prompt, model, temperature, max_tokens, enabled FROM agents WHERE id = ?", (agent_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "name": row[1], "type": row[2], "desc": row[3],
        "tools": json.loads(row[4]) if row[4] else [],
        "system_prompt": row[5] or "", "model": row[6], "temperature": row[7],
        "max_tokens": row[8], "enabled": bool(row[9]),
    }


def upsert_agent(agent_id: str, data: dict) -> None:
    """Create or update an agent configuration."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO agents (id, name, type, desc, tools, system_prompt, model, temperature, max_tokens, enabled, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, type=excluded.type, desc=excluded.desc,
            tools=excluded.tools, system_prompt=excluded.system_prompt,
            model=excluded.model, temperature=excluded.temperature,
            max_tokens=excluded.max_tokens, enabled=excluded.enabled,
            updated_at=CURRENT_TIMESTAMP
    """, (
        agent_id, data.get("name", ""), data.get("type", "helper"),
        data.get("desc", ""), json.dumps(data.get("tools", []), ensure_ascii=False),
        data.get("system_prompt", ""), data.get("model"), data.get("temperature"),
        data.get("max_tokens"), 1 if data.get("enabled", True) else 0,
    ))
    conn.commit()
    conn.close()


def delete_agent(agent_id: str) -> None:
    """Delete an agent configuration."""
    conn = _get_conn()
    conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    conn.commit()
    conn.close()


# ── CLI Tools CRUD ────────────────────────────────────────────────

_DEFAULT_CLIS = [
    {"id": "opencode", "name": "OpenCode", "command": "opencode", "args": '["--print"]', "timeout": 120, "desc": "OpenCode CLI coding assistant"},
    {"id": "claude", "name": "Claude Code", "command": "claude", "args": '["-p"]', "timeout": 120, "desc": "Claude Code CLI"},
]


def _seed_default_clis(conn: sqlite3.Connection) -> None:
    """Insert default CLIs if the table is empty."""
    row = conn.execute("SELECT COUNT(*) FROM agent_clis").fetchone()
    if row and row[0] > 0:
        return
    for c in _DEFAULT_CLIS:
        conn.execute(
            "INSERT INTO agent_clis (id, name, command, args, timeout, desc) VALUES (?, ?, ?, ?, ?, ?)",
            (c["id"], c["name"], c["command"], c["args"], c["timeout"], c["desc"]),
        )
    conn.commit()


def list_clis() -> list[dict]:
    """List all CLI tool configurations."""
    conn = _get_conn()
    _seed_default_clis(conn)
    rows = conn.execute("SELECT id, name, command, args, timeout, desc, enabled FROM agent_clis ORDER BY id").fetchall()
    conn.close()
    return [
        {
            "id": r[0], "name": r[1], "command": r[2],
            "args": json.loads(r[3]) if r[3] else [],
            "timeout": r[4], "desc": r[5], "enabled": bool(r[6]),
        }
        for r in rows
    ]


def get_cli(cli_id: str) -> dict | None:
    """Get a single CLI configuration."""
    conn = _get_conn()
    row = conn.execute("SELECT id, name, command, args, timeout, desc, enabled FROM agent_clis WHERE id = ?", (cli_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "name": row[1], "command": row[2],
        "args": json.loads(row[3]) if row[3] else [],
        "timeout": row[4], "desc": row[5], "enabled": bool(row[6]),
    }


def upsert_cli(cli_id: str, data: dict) -> None:
    """Create or update a CLI configuration."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO agent_clis (id, name, command, args, timeout, desc, enabled, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, command=excluded.command, args=excluded.args,
            timeout=excluded.timeout, desc=excluded.desc, enabled=excluded.enabled,
            updated_at=CURRENT_TIMESTAMP
    """, (
        cli_id, data.get("name", ""), data.get("command", ""),
        json.dumps(data.get("args", []), ensure_ascii=False),
        data.get("timeout", 120), data.get("desc", ""),
        1 if data.get("enabled", True) else 0,
    ))
    conn.commit()
    conn.close()


def delete_cli(cli_id: str) -> None:
    """Delete a CLI configuration."""
    conn = _get_conn()
    conn.execute("DELETE FROM agent_clis WHERE id = ?", (cli_id,))
    conn.commit()
    conn.close()
