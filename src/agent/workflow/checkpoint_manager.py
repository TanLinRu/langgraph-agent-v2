"""Checkpoint Manager - Workflow state persistence and recovery.

This module manages workflow execution checkpoints, binding them to sessions
for persistence and recovery.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Checkpoint database path
_CHECKPOINT_DB_PATH = Path("memory/workflow_checkpoints.db")


def _get_checkpoint_conn() -> sqlite3.Connection:
    """Get checkpoint database connection with auto-migration."""
    _CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_CHECKPOINT_DB_PATH))

    # Create checkpoints table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            state TEXT NOT NULL,
            status TEXT DEFAULT 'running',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON workflow_checkpoints(session_id)")

    # Add columns via migration
    for col, dtype, default in [
        ("node_id", "TEXT", "DEFAULT NULL"),
        ("is_interrupted", "INTEGER", "DEFAULT 0"),
        ("pending_approval", "TEXT", "DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE workflow_checkpoints ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    conn.commit()
    return conn


class CheckpointManager:
    """Manages workflow execution checkpoints."""

    @staticmethod
    async def save(session_id: str, state: dict[str, Any]) -> int:
        """Save workflow checkpoint.

        Args:
            session_id: Session identifier
            state: Workflow state dict

        Returns:
            Checkpoint ID
        """
        conn = _get_checkpoint_conn()
        graph_id = state.get("graph_id", "")
        current_node = state.get("current_node")
        is_interrupted = state.get("is_interrupted", False)
        pending_approval = state.get("pending_approval")

        # Serialize state
        state_json = json.dumps(state, ensure_ascii=False)

        # Check if checkpoint exists for this session
        existing = conn.execute(
            "SELECT id FROM workflow_checkpoints WHERE session_id = ? AND graph_id = ?",
            (session_id, graph_id)
        ).fetchone()

        if existing:
            # Update existing checkpoint
            conn.execute(
                "UPDATE workflow_checkpoints SET state = ?, node_id = ?, "
                "is_interrupted = ?, pending_approval = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (state_json, current_node, int(is_interrupted),
                 json.dumps(pending_approval) if pending_approval else None,
                 existing[0])
            )
            checkpoint_id = existing[0]
        else:
            # Create new checkpoint
            conn.execute(
                "INSERT INTO workflow_checkpoints "
                "(session_id, graph_id, state, node_id, is_interrupted, pending_approval) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, graph_id, state_json, current_node,
                 int(is_interrupted),
                 json.dumps(pending_approval) if pending_approval else None)
            )
            checkpoint_id = conn.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0]

        conn.commit()
        conn.close()
        logger.info("[CheckpointManager] saved checkpoint %d for session %s", checkpoint_id, session_id)
        return checkpoint_id

    @staticmethod
    async def get_latest(session_id: str) -> dict[str, Any] | None:
        """Get latest checkpoint for a session.

        Args:
            session_id: Session identifier

        Returns:
            Checkpoint dict or None if not found
        """
        conn = _get_checkpoint_conn()
        row = conn.execute(
            "SELECT id, graph_id, state, node_id, is_interrupted, pending_approval, status "
            "FROM workflow_checkpoints WHERE session_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (session_id,)
        ).fetchone()
        conn.close()

        if not row:
            return None

        try:
            state = json.loads(row[2])
        except json.JSONDecodeError:
            state = {}

        return {
            "checkpoint_id": row[0],
            "graph_id": row[1],
            "state": state,
            "current_node": row[3],
            "is_interrupted": bool(row[4]),
            "pending_approval": json.loads(row[5]) if row[5] else None,
            "status": row[6],
        }

    @staticmethod
    async def get_by_graph(session_id: str, graph_id: str) -> dict[str, Any] | None:
        """Get checkpoint for specific graph.

        Args:
            session_id: Session identifier
            graph_id: Graph identifier

        Returns:
            Checkpoint dict or None if not found
        """
        conn = _get_checkpoint_conn()
        row = conn.execute(
            "SELECT id, state, node_id, is_interrupted, pending_approval, status "
            "FROM workflow_checkpoints WHERE session_id = ? AND graph_id = ?",
            (session_id, graph_id)
        ).fetchone()
        conn.close()

        if not row:
            return None

        try:
            state = json.loads(row[1])
        except json.JSONDecodeError:
            state = {}

        return {
            "checkpoint_id": row[0],
            "state": state,
            "current_node": row[2],
            "is_interrupted": bool(row[3]),
            "pending_approval": json.loads(row[4]) if row[4] else None,
            "status": row[5],
        }

    @staticmethod
    async def update_status(checkpoint_id: int, status: str) -> None:
        """Update checkpoint status.

        Args:
            checkpoint_id: Checkpoint identifier
            status: New status (running, completed, interrupted, error)
        """
        conn = _get_checkpoint_conn()
        conn.execute(
            "UPDATE workflow_checkpoints SET status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (status, checkpoint_id)
        )
        conn.commit()
        conn.close()

    @staticmethod
    async def clear(session_id: str) -> None:
        """Clear checkpoint for a session (workflow completed).

        Args:
            session_id: Session identifier
        """
        conn = _get_checkpoint_conn()
        conn.execute(
            "DELETE FROM workflow_checkpoints WHERE session_id = ?",
            (session_id,)
        )
        conn.commit()
        conn.close()
        logger.info("[CheckpointManager] cleared checkpoint for session %s", session_id)

    @staticmethod
    async def list_pending_approvals() -> list[dict[str, Any]]:
        """List all checkpoints waiting for approval.

        Returns:
            List of checkpoints with pending_approval
        """
        conn = _get_checkpoint_conn()
        rows = conn.execute(
            "SELECT session_id, graph_id, state, pending_approval "
            "FROM workflow_checkpoints WHERE is_interrupted = 1 AND pending_approval IS NOT NULL"
        ).fetchall()
        conn.close()

        return [
            {
                "session_id": row[0],
                "graph_id": row[1],
                "state": json.loads(row[2]) if row[2] else {},
                "pending_approval": json.loads(row[3]) if row[3] else {},
            }
            for row in rows
        ]

    @staticmethod
    async def approve(session_id: str, approved: bool = True) -> None:
        """Approve or reject pending approval.

        Args:
            session_id: Session identifier
            approved: True to approve, False to reject
        """
        conn = _get_checkpoint_conn()
        conn.execute(
            "UPDATE workflow_checkpoints SET is_interrupted = 0, "
            "pending_approval = NULL, status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE session_id = ? AND is_interrupted = 1",
            ("approved" if approved else "rejected", session_id)
        )
        conn.commit()
        conn.close()
        logger.info("[CheckpointManager] approval %s for session %s",
                    "approved" if approved else "rejected", session_id)
