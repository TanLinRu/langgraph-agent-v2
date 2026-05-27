import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import chromadb

from src.agent.config import AgentConfig


class MemoryManager:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        Path(config.memory_db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(config.memory_db_path, check_same_thread=False)
        self._init_db()
        self.chroma = chromadb.PersistentClient(path=config.chroma_path)

    def _init_db(self) -> None:
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_namespace ON memories(namespace)")
        self.db.commit()

    def store(self, key: str, content: str, namespace: str = "default") -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.db.execute(
            "SELECT id FROM memories WHERE namespace = ? AND key = ?", (namespace, key)
        ).fetchone()

        if existing:
            self.db.execute(
                "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
                (content, now, existing[0]),
            )
        else:
            self.db.execute(
                "INSERT INTO memories (id, namespace, key, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), namespace, key, content, now, now),
            )
        self.db.commit()

        try:
            collection = self.chroma.get_or_create_collection(namespace)
            doc_id = f"{namespace}:{key}"
            collection.upsert(ids=[doc_id], documents=[content], metadatas=[{"key": key}])
        except Exception:
            pass

    def retrieve(self, query: str, namespace: str = "default", top_k: int = 5) -> list[dict]:
        try:
            collection = self.chroma.get_collection(namespace)
            results = collection.query(query_texts=[query], n_results=top_k)
            items = []
            for i, doc in enumerate(results["documents"][0] if results["documents"] else []):
                items.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                })
            return items
        except Exception:
            return []

    def list_memories(self, namespace: str = "default") -> list[dict]:
        rows = self.db.execute(
            "SELECT key, content, created_at, updated_at FROM memories WHERE namespace = ? ORDER BY updated_at DESC",
            (namespace,),
        ).fetchall()
        return [{"key": r[0], "content": r[1], "created_at": r[2], "updated_at": r[3]} for r in rows]

    def delete(self, key: str, namespace: str = "default") -> None:
        self.db.execute("DELETE FROM memories WHERE namespace = ? AND key = ?", (namespace, key))
        self.db.commit()
        try:
            collection = self.chroma.get_collection(namespace)
            collection.delete(ids=[f"{namespace}:{key}"])
        except Exception:
            pass

    def inject_context(self, query: str, namespace: str = "default", top_k: int = 3) -> str:
        memories = self.retrieve(query, namespace, top_k)
        if not memories:
            return ""
        lines = [m["content"] for m in memories]
        return "\n".join(lines)

    def close(self) -> None:
        self.db.close()
        self.chroma = None
