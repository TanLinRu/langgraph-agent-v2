import tiktoken
from langchain_core.messages import BaseMessage


def count_tokens(messages: list[BaseMessage], model: str = "gpt-4o") -> int:
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    total = 0
    for msg in messages:
        total += 4  # message overhead
        if isinstance(msg.content, str):
            total += len(enc.encode(msg.content))
        elif isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, dict) and "text" in part:
                    total += len(enc.encode(part["text"]))
    return total


def deduplicate_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    seen: set[str] = set()
    result = []
    for msg in messages:
        key = f"{msg.type}:{msg.content[:100] if isinstance(msg.content, str) else str(msg.content)[:100]}"
        if key not in seen:
            seen.add(key)
            result.append(msg)
    return result
