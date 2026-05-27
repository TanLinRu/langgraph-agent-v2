import asyncio
import json
from datetime import datetime, timezone
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, stream_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(stream_id, []).append(queue)
        return queue

    def unsubscribe(self, stream_id: str, queue: asyncio.Queue) -> None:
        queues = self._subscribers.get(stream_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._subscribers.pop(stream_id, None)

    async def publish(self, stream_id: str, event_type: str, data: Any, agent_name: str = "") -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": agent_name,
        }
        for queue in self._subscribers.get(stream_id, []):
            await queue.put(event)

    def format_sse(self, event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


event_bus = EventBus()
