import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain.agents import create_agent

from src.agent.audit_logger import log_audit_event
from src.agent.config import AgentConfig
from src.agent.context.compression import ContextCompressor
from src.agent.models import resolve_model
from src.agent.tools import TOOLS

logger = logging.getLogger(__name__)


def _ts() -> str:
    """Millisecond-precision timestamp for SSE tracing."""
    return f"{time.time():.3f}"


class Agent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.model = resolve_model(config)
        self.tools = TOOLS
        self.compressor = ContextCompressor(config)
        # 使用 LangGraph 原生 create_react_agent 构建 ReAct 循环
        # 自动处理：LLM 调用 → 工具执行 → 再次调用 LLM → 直到无 tool_calls
        self.agent_graph = create_agent(
            self.model,
            tools=self.tools,
            system_prompt=self._get_system_prompt(),
        )

    def _get_system_prompt(self) -> str:
        from src.agent.prompts.system_prompt import SYSTEM_PROMPT
        from src.agent.skills import get_skills_prompt

        skills_prompt = get_skills_prompt()
        return SYSTEM_PROMPT.format(
            skills=f"\n\n{skills_prompt}" if skills_prompt else "",
            memory_context="",
        )

    def _build_system_message(self, memory_context: str = "", summary: str = "") -> SystemMessage:
        from src.agent.prompts.system_prompt import SYSTEM_PROMPT
        from src.agent.skills import get_skills_prompt

        parts = []
        if summary:
            parts.append(f"[Conversation History]\n{summary}")
        if memory_context:
            parts.append(f"[Memory Context]\n{memory_context}")

        extra = "\n\n".join(parts)
        skills_prompt = get_skills_prompt()
        content = SYSTEM_PROMPT.format(
            skills=f"\n\n{skills_prompt}" if skills_prompt else "",
            memory_context=f"\n\n{extra}" if extra else "",
        )
        return SystemMessage(content=content)

    def _log_request(self, label: str, messages: list[BaseMessage], extra: dict[str, Any] | None = None, trace_id: str = "") -> None:
        from src.agent.context._helpers import count_tokens

        token_count = count_tokens(messages)
        threshold = int(self.config.max_tokens * self.config.compression_threshold)

        logger.info(
            "[LLM Request] %s | model=%s/%s messages=%d tokens~%d/%d(compress_at_%d) tools=%s",
            label, self.config.model_provider, self.config.model_name,
            len(messages), token_count, self.config.max_tokens, threshold,
            [t.name for t in self.tools],
        )
        for i, msg in enumerate(messages):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            preview = content[:200] + "..." if len(content) > 200 else content
            logger.info("  [%d] %s: %s", i, msg.type, preview)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    logger.info("       -> tool_call: %s(%s)", tc["name"], tc["args"])

        log_audit_event(
            trace_id=trace_id or str(uuid.uuid4()),
            event_type="llm_request",
            severity="info",
            scenario_code="chat",
            context={
                "label": label,
                "model": f"{self.config.model_provider}/{self.config.model_name}",
                "base_url": self.config.openai_base_url,
                "message_count": len(messages),
                "token_count": token_count,
                "max_tokens": self.config.max_tokens,
                "compress_threshold": threshold,
                "tools": [t.name for t in self.tools],
                "extra": extra or {},
            },
        )

    def _build_messages(self, user_input: str, memory_context: str = "",
                        history: list[BaseMessage] | None = None,
                        summary: str = "") -> list[BaseMessage]:
        system_msg = self._build_system_message(memory_context, summary)
        return [system_msg] + (history or []) + [HumanMessage(content=user_input)]

    async def run(self, user_input: str, memory_context: str = "",
                  history: list[BaseMessage] | None = None) -> AsyncIterator[dict[str, Any]]:
        trace_id = str(uuid.uuid4())
        messages = self._build_messages(user_input, memory_context, history)

        # 上下文压缩
        compressed = False
        if self.compressor.should_compress(messages):
            summary, recent = await self.compressor.compress(messages[1:])
            messages = self._build_messages(user_input, memory_context, recent, summary)
            compressed = True
            logger.info("[Compress] triggered: token_threshold=%d, kept_recent=%d",
                        int(self.config.max_tokens * self.config.compression_threshold), len(recent))

        self._log_request("agent", messages, {"compressed": compressed}, trace_id=trace_id)

        # 使用 LangGraph 原生 astream_events 流式处理 ReAct 循环
        thinking_started = False
        content_parts: list[str] = []
        _event_count = 0
        _t0 = time.time()

        async for event in self.agent_graph.astream_events({"messages": messages}, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                # reasoning_content 通过 ChatDeepSeek 自动提取到 additional_kwargs
                reasoning = chunk.additional_kwargs.get("reasoning_content")
                if reasoning:
                    if not thinking_started:
                        yield {"type": "thinking_start"}
                        thinking_started = True
                        _event_count += 1
                        logger.info("[SSE-TRACE] %s thinking_start emitted", _ts())
                    yield {"type": "thinking", "data": reasoning}
                    _event_count += 1
                elif chunk.content:
                    content_parts.append(chunk.content)

            elif kind == "on_tool_start":
                yield {
                    "type": "tool_call",
                    "data": [{"name": event["name"], "args": event["data"].get("input", {})}],
                }
                _event_count += 1

        if thinking_started:
            yield {"type": "thinking_done"}

        _elapsed = time.time() - _t0
        logger.info(
            "[SSE-TRACE] %s agent done: %d events, %.2fs elapsed, content_len=%d",
            _ts(), _event_count, _elapsed, sum(len(p) for p in content_parts),
        )

        yield {"type": "message", "data": "".join(content_parts)}
        yield {"type": "done"}

    async def run_stream(self, user_input: str, memory_context: str = "", history: list[BaseMessage] | None = None) -> AsyncIterator[str]:
        async for event in self.run(user_input, memory_context, history):
            yield json.dumps(event, ensure_ascii=False)
