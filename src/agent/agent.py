import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import openai
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.audit_logger import log_audit_event
from src.agent.config import AgentConfig
from src.agent.context.compression import ContextCompressor
from src.agent.context.tool_result_manager import truncate_result
from src.agent.models import resolve_model
from src.agent.tools import TOOLS

logger = logging.getLogger(__name__)


def _ts() -> str:
    """Millisecond-precision timestamp for SSE tracing."""
    return f"{time.time():.3f}"


class Agent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.llm = resolve_model(config)
        self.tools = TOOLS
        self.tool_map = {t.name: t for t in self.tools}
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        self.compressor = ContextCompressor(config)

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

        # Structured log
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

        # Audit trail
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

    @staticmethod
    def _messages_to_openai(messages: list[BaseMessage]) -> list[dict]:
        """Convert LangChain messages to OpenAI API format."""
        result = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                d: dict[str, Any] = {"role": "assistant", "content": msg.content}
                if msg.tool_calls:
                    d["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["args"], ensure_ascii=False)},
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(d)
            elif isinstance(msg, ToolMessage):
                result.append({"role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content})
        return result

    def _get_raw_client(self) -> openai.AsyncOpenAI:
        """Get raw OpenAI async client for streaming with reasoning_content support."""
        return openai.AsyncOpenAI(
            api_key=self.config.openai_api_key,
            base_url=self.config.openai_base_url,
        )

    async def _stream_raw(self, messages: list[BaseMessage]) -> AsyncIterator[dict[str, Any]]:
        """Stream via raw OpenAI client, yielding thinking/content/tool_call events."""
        client = self._get_raw_client()
        openai_messages = self._messages_to_openai(messages)
        tools_spec = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.args_schema.schema() if hasattr(t, "args_schema") and t.args_schema else {"type": "object", "properties": {}},
                },
            }
            for t in self.tools
        ]

        extra = {}
        if self.config.enable_thinking:
            extra["enable_thinking"] = True

        stream = await client.chat.completions.create(
            model=self.config.model_name,
            messages=openai_messages,
            tools=tools_spec if tools_spec else None,
            stream=True,
            extra_body=extra if extra else None,
        )

        thinking_started = False
        content_parts: list[str] = []
        tool_calls_map: dict[int, dict] = {}
        _chunk_count = 0
        _event_count = 0
        _t0 = time.time()

        async for chunk in stream:
            _chunk_count += 1
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if not thinking_started:
                    yield {"type": "thinking_start"}
                    thinking_started = True
                    _event_count += 1
                    logger.info("[SSE-TRACE] %s thinking_start emitted (chunk #%d)", _ts(), _chunk_count)
                yield {"type": "thinking", "data": reasoning}
                _event_count += 1

            if delta.content:
                content_parts.append(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {"id": "", "name": "", "arguments": ""}
                    entry = tool_calls_map[idx]
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            entry["name"] = tc.function.name
                        if tc.function.arguments:
                            entry["arguments"] += tc.function.arguments

        if thinking_started:
            yield {"type": "thinking_done"}

        _elapsed = time.time() - _t0
        logger.info(
            "[SSE-TRACE] %s stream_raw done: %d chunks, %d events, %.2fs elapsed, content_len=%d",
            _ts(), _chunk_count, _event_count, _elapsed, sum(len(p) for p in content_parts),
        )

        content = "".join(content_parts)
        tool_calls = []
        for idx in sorted(tool_calls_map):
            entry = tool_calls_map[idx]
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": entry["id"], "name": entry["name"], "args": args})

        response = AIMessage(content=content, tool_calls=tool_calls if tool_calls else [])
        yield {"type": "_response", "data": response}

    async def _astream_with_thinking(self, messages: list[BaseMessage]) -> AsyncIterator[dict[str, Any]]:
        """Stream LLM response, yielding thinking events."""
        async for event in self._stream_raw(messages):
            yield event

    async def run(self, user_input: str, memory_context: str = "", history: list[BaseMessage] | None = None) -> AsyncIterator[dict[str, Any]]:
        trace_id = str(uuid.uuid4())
        system_msg = self._build_system_message(memory_context)
        messages = [system_msg] + (history or []) + [HumanMessage(content=user_input)]

        # Compress before first call if history makes messages too long
        compressed = False
        if self.compressor.should_compress(messages):
            summary, recent = await self.compressor.compress(messages[1:])  # skip system msg
            system_msg = self._build_system_message(memory_context, summary)
            messages = [system_msg] + recent
            compressed = True
            logger.info("[Compress] triggered on 1st call: token_threshold=%d, kept_recent=%d", int(self.config.max_tokens * self.config.compression_threshold), len(recent))

        self._log_request("1st call", messages, {"compressed": compressed}, trace_id=trace_id)

        # Stream first call with thinking support
        response: AIMessage | None = None
        _run_event_count = 0
        async for event in self._astream_with_thinking(messages):
            if event["type"] == "_response":
                response = event["data"]
            else:
                _run_event_count += 1
                logger.info("[SSE-TRACE] %s run() yielding #%d: type=%s len=%d", _ts(), _run_event_count, event["type"], len(str(event.get("data", ""))))
                yield event
        logger.info("[SSE-TRACE] %s run() 1st-call stream done: %d events yielded", _ts(), _run_event_count)

        if response and response.tool_calls:
            yield {"type": "tool_call", "data": [{"name": tc["name"], "args": tc["args"]} for tc in response.tool_calls]}
            messages.append(response)

            for tool_call in response.tool_calls:
                tool_fn = self.tool_map.get(tool_call["name"])
                if tool_fn:
                    try:
                        result = await tool_fn.ainvoke(tool_call["args"])
                    except Exception as e:
                        result = f"Error: {e}"
                    result_str = truncate_result(tool_call["name"], str(result))
                    messages.append(
                        ToolMessage(content=result_str, tool_call_id=tool_call["id"], name=tool_call["name"])
                    )

            # Check if compression is needed before final call
            compressed = False
            if self.compressor.should_compress(messages):
                summary, recent = await self.compressor.compress(messages[1:])
                system_msg = self._build_system_message(memory_context, summary)
                messages = [system_msg] + recent
                compressed = True
                logger.info("[Compress] triggered on 2nd call: token_threshold=%d, kept_recent=%d", int(self.config.max_tokens * self.config.compression_threshold), len(recent))

            self._log_request("2nd call", messages, {"compressed": compressed}, trace_id=trace_id)

            # Stream second call with thinking support
            final: AIMessage | None = None
            async for event in self._astream_with_thinking(messages):
                if event["type"] == "_response":
                    final = event["data"]
                else:
                    yield event

            yield {"type": "message", "data": final.content if final else ""}
        else:
            yield {"type": "message", "data": response.content if response else ""}

        yield {"type": "done"}

    async def run_stream(self, user_input: str, memory_context: str = "", history: list[BaseMessage] | None = None) -> AsyncIterator[str]:
        async for event in self.run(user_input, memory_context, history):
            yield json.dumps(event, ensure_ascii=False)
