from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


@dataclass
class Message:
    role: str
    content: str = ''
    thinking: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    compacted: bool = False
    id: Optional[int] = None
    session_id: Optional[str] = None
    created_at: Optional[str] = None

    def to_langchain(self) -> BaseMessage:
        if self.role == 'human':
            return HumanMessage(content=self.content)
        if self.role == 'ai':
            extra: dict[str, Any] = {}
            if self.tool_calls:
                extra['tool_calls'] = self.tool_calls
            return AIMessage(
                content=self.content, additional_kwargs=extra,
                id=self.tool_call_id, name=self.name,
            )
        if self.role == 'tool':
            return ToolMessage(
                content=self.content, tool_call_id=self.tool_call_id or '', name=self.name,
            )
        return HumanMessage(content=self.content)

    @classmethod
    def from_langchain(cls, msg: BaseMessage) -> Message:
        if isinstance(msg, HumanMessage):
            return cls(role='human', content=msg.content)
        if isinstance(msg, AIMessage):
            return cls(
                role='ai', content=msg.content,
                tool_calls=msg.additional_kwargs.get('tool_calls'),
                tool_call_id=msg.id, name=msg.name,
            )
        if isinstance(msg, ToolMessage):
            return cls(
                role='tool', content=msg.content,
                tool_call_id=msg.tool_call_id, name=msg.name,
            )
        return cls(role='human', content=msg.content)

    def to_frontend_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {'type': self.role, 'content': self.content or ''}
        if self.thinking:
            d['thinking'] = self.thinking
        if self.tool_calls:
            d['tool_calls'] = self.tool_calls
        if self.name:
            d['name'] = self.name
        if self.compacted:
            d['compacted'] = True
        if self.id is not None:
            d['id'] = self.id
        if self.session_id is not None:
            d['session_id'] = self.session_id
        if self.created_at is not None:
            d['created_at'] = self.created_at
        return d

    @classmethod
    def from_frontend_dict(cls, d: dict[str, Any]) -> Message:
        role = d.get('type') or d.get('role', 'human')
        return cls(
            role=role, content=d.get('content', ''),
            thinking=d.get('thinking'), tool_calls=d.get('tool_calls'), name=d.get('name'),
        )

    @classmethod
    def from_db_row(cls, row) -> Message:
        role, content, tool_calls_json, tool_call_id, name = row
        tool_calls = None
        if tool_calls_json:
            try:
                tool_calls = json.loads(tool_calls_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls(role=role, content=content, tool_calls=tool_calls, tool_call_id=tool_call_id, name=name)

    @classmethod
    def from_db_row_verbose(cls, row) -> Message:
        row_tuple = tuple(row)
        if len(row_tuple) >= 9:
            role, content, thinking, tool_calls_json, compacted, name, msg_id, session_id, created_at = row_tuple[:9]
        else:
            padded = row_tuple + (None,) * (9 - len(row_tuple))
            role, content, thinking, tool_calls_json, compacted, name, msg_id, session_id, created_at = padded
        tool_calls = None
        if tool_calls_json:
            try:
                tool_calls = json.loads(tool_calls_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls(
            id=msg_id, session_id=session_id, created_at=created_at,
            role=role, content=content, thinking=thinking,
            tool_calls=tool_calls, name=name, compacted=bool(compacted),
        )

    def to_db_params(self) -> tuple[str, str, str, str, str]:
        return (
            self.role, self.content,
            json.dumps(self.tool_calls, ensure_ascii=False) if self.tool_calls else '',
            self.thinking or '', self.name or '',
        )
