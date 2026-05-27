from abc import ABC, abstractmethod


class BackendProtocol(ABC):
    """Abstract base for pluggable storage backends."""

    @abstractmethod
    def store(self, key: str, content: str, namespace: str = "default") -> None:
        """Store a memory entry."""

    @abstractmethod
    def retrieve(self, query: str, namespace: str = "default", top_k: int = 5) -> list[dict]:
        """Retrieve memories by query."""

    @abstractmethod
    def list_memories(self, namespace: str = "default") -> list[dict]:
        """List all memories in a namespace."""

    @abstractmethod
    def delete(self, key: str, namespace: str = "default") -> None:
        """Delete a memory entry."""
