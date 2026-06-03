from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.config import AgentConfig
from src.agent.context._helpers import count_tokens


class ContextCompressor:
    def __init__(self, config: AgentConfig) -> None:
        self.max_tokens = config.max_tokens
        self.threshold = config.compression_threshold
        self.keep_recent_turns = 3

    def should_compress(self, messages: list[BaseMessage]) -> bool:
        token_count = count_tokens(messages)
        return token_count > int(self.max_tokens * self.threshold)

    @staticmethod
    def extract_turns(messages: list[BaseMessage]) -> list[list[BaseMessage]]:
        """Group messages into turns (HumanMessage → AIMessage → tool/ToolMessage pairs)."""
        turns: list[list[BaseMessage]] = []
        current: list[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                if current:
                    turns.append(current)
                current = [msg]
            else:
                current.append(msg)
        if current:
            turns.append(current)
        return turns

    async def compress(self, messages: list[BaseMessage], llm=None, force: bool = False) -> tuple[str, list[BaseMessage]]:
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]
        if not non_system:
            return "", system_msgs
        turns = self.extract_turns(non_system)
        if not force and len(turns) <= self.keep_recent_turns:
            return "", system_msgs + non_system
        if len(turns) <= self.keep_recent_turns:
            return "", system_msgs + non_system
        old_turns = turns[:-self.keep_recent_turns]
        recent_turns = turns[-self.keep_recent_turns:]
        old_msgs = [m for turn in old_turns for m in turn]
        recent_msgs = [m for turn in recent_turns for m in turn]
        summary = await self._summarize(old_msgs, llm)
        return summary, system_msgs + recent_msgs

    async def _summarize(self, messages: list[BaseMessage], llm=None) -> str:
        if llm is None:
            return self._fallback_summary(messages)

        input_text = self._messages_to_text(messages)
        if len(input_text) > 30000:
            input_text = input_text[:15000] + "\n\n[... truncated ...]\n\n" + input_text[-15000:]

        summary_prompt = [
            SystemMessage(content=(
                "You are a conversation summarizer for a coding assistant. "
                "Create a structured summary of the conversation history below. "
                "Preserve these critical details:\n"
                "1. The user's original goal/task\n"
                "2. Key decisions and their rationale\n"
                "3. File paths, function names, and code structures discussed\n"
                "4. Tool results (code output, file contents, search results)\n"
                "5. Errors encountered and how they were resolved\n"
                "6. Open questions or pending tasks\n\n"
                "Format: Use bullet points grouped by topic. "
                "Keep the summary under 500 words. "
                "Do NOT include filler phrases like 'the user asked' or 'the assistant responded'."
            )),
            HumanMessage(content=f"Conversation to summarize:\n\n{input_text}"),
        ]
        response = await llm.ainvoke(summary_prompt)
        return response.content if isinstance(response.content, str) else str(response.content)

    def _fallback_summary(self, messages: list[BaseMessage]) -> str:
        parts = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 500:
                    content = content[:250] + " ... " + content[-250:]
                parts.append(f"[tool:{msg.name}] {content}")
            elif isinstance(msg, AIMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if msg.tool_calls:
                    calls = ", ".join(f"{tc['name']}({tc['args']})" for tc in msg.tool_calls)
                    parts.append(f"[assistant] Called: {calls}")
                if content:
                    if len(content) > 500:
                        content = content[:500] + "..."
                    parts.append(f"[assistant] {content}")
            elif isinstance(msg, HumanMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 500:
                    content = content[:500] + "..."
                parts.append(f"[user] {content}")
        return "\n".join(parts)

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
