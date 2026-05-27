from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.config import AgentConfig
from src.agent.context._helpers import count_tokens


class ContextCompressor:
    def __init__(self, config: AgentConfig) -> None:
        self.max_tokens = config.max_tokens
        self.threshold = config.compression_threshold
        self.keep_recent = 5

    def should_compress(self, messages: list[BaseMessage]) -> bool:
        token_count = count_tokens(messages)
        return token_count > int(self.max_tokens * self.threshold)

    def extract_system_and_rest(self, messages: list[BaseMessage]) -> tuple[SystemMessage | None, list[BaseMessage]]:
        if messages and isinstance(messages[0], SystemMessage):
            return messages[0], messages[1:]
        return None, messages

    async def compress(self, messages: list[BaseMessage], llm=None) -> tuple[str, list[BaseMessage]]:
        if len(messages) <= self.keep_recent:
            return "", messages

        recent = messages[-self.keep_recent:]
        old = messages[:-self.keep_recent]

        summary = await self._summarize(old, llm)
        return summary, recent

    async def _summarize(self, messages: list[BaseMessage], llm=None) -> str:
        if llm is None:
            return self._fallback_summary(messages)

        summary_prompt = [
            SystemMessage(content=(
                "Summarize the following conversation history concisely. "
                "Preserve: key facts, decisions made, tool results, and any open questions. "
                "Use the format: [role] key points."
            )),
            HumanMessage(content=self._messages_to_text(messages)),
        ]
        response = await llm.ainvoke(summary_prompt)
        return response.content if isinstance(response.content, str) else str(response.content)

    def _fallback_summary(self, messages: list[BaseMessage]) -> str:
        parts = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 300:
                    content = content[:150] + " ... " + content[-150:]
                parts.append(f"[tool:{msg.name}] {content}")
            elif isinstance(msg, AIMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if msg.tool_calls:
                    calls = ", ".join(f"{tc['name']}({tc['args']})" for tc in msg.tool_calls)
                    parts.append(f"[assistant] Called: {calls}")
                elif content:
                    if len(content) > 300:
                        content = content[:300] + "..."
                    parts.append(f"[assistant] {content}")
            elif isinstance(msg, HumanMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 300:
                    content = content[:300] + "..."
                parts.append(f"[user] {content}")
        return "\n".join(parts[-15:])

    def _messages_to_text(self, messages: list[BaseMessage]) -> str:
        parts = []
        for msg in messages:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if isinstance(msg, ToolMessage):
                tc_id = msg.tool_call_id[:8] if msg.tool_call_id else "?"
                if len(content) > 500:
                    content = content[:250] + " ... " + content[-250:]
                parts.append(f"[tool:{msg.name} call_id={tc_id}] {content}")
            elif isinstance(msg, AIMessage):
                if msg.tool_calls:
                    calls = ", ".join(f"{tc['name']}({tc['args']})" for tc in msg.tool_calls)
                    parts.append(f"[assistant] Tool calls: {calls}")
                if content:
                    if len(content) > 500:
                        content = content[:500] + "..."
                    parts.append(f"[assistant] {content}")
            elif isinstance(msg, HumanMessage):
                if len(content) > 500:
                    content = content[:500] + "..."
                parts.append(f"[user] {content}")
        return "\n".join(parts)
