import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from src.agent.audit_logger import log_audit_event
from src.agent.config import AgentConfig
from src.agent.context.compression import ContextCompressor
from src.agent.models import resolve_model
from src.agent.tools import TOOLS

logger = logging.getLogger(__name__)

# File path extraction patterns
_FILE_PATH_RE = re.compile(r'(?:src|docs|tests|ui|memory|skills)[/\\][\w./\\-]+\.\w+')
_CODE_FILE_RE = re.compile(r'[\w-]+\.(?:py|ts|js|vue|html|json|md|toml|yaml)')


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

        logger.info("=" * 80)
        logger.info("[LLM REQUEST] %s | trace_id=%s", label, trace_id)
        logger.info("[LLM REQUEST] model=%s/%s base_url=%s", self.config.model_provider, self.config.model_name, self.config.openai_base_url)
        logger.info("[LLM REQUEST] messages=%d tokens~%d/%d(compress_at_%d) tools=%d",
                     len(messages), token_count, self.config.max_tokens, threshold, len(self.tools))
        logger.info("[LLM REQUEST] tools=%s", [t.name for t in self.tools])
        logger.info("-" * 40 + " MESSAGE LIST " + "-" * 40)
        for i, msg in enumerate(messages):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Log full content for debugging, not truncated
            logger.info("  [%d] type=%s len=%d", i, msg.type, len(content))
            if msg.type == "system":
                logger.info("  [%d] system: %s", i, content[:500] + "..." if len(content) > 500 else content)
            elif msg.type == "human":
                logger.info("  [%d] user: %s", i, content[:500] + "..." if len(content) > 500 else content)
            elif msg.type == "ai":
                logger.info("  [%d] assistant: %s", i, content[:500] + "..." if len(content) > 500 else content)
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        logger.info("  [%d]   -> tool_call: %s(%s)", i, tc["name"], json.dumps(tc["args"], ensure_ascii=False)[:200])
            elif msg.type == "tool":
                logger.info("  [%d] tool[%s]: %s", i, getattr(msg, 'name', '?'), content[:300] + "..." if len(content) > 300 else content)
        logger.info("=" * 80)

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

    def _log_response(self, label: str, content: str, thinking: str = "", elapsed: float = 0, trace_id: str = "") -> None:
        logger.info("-" * 40 + " LLM RESPONSE " + "-" * 40)
        logger.info("[LLM RESPONSE] %s | trace_id=%s | elapsed=%.2fs", label, trace_id, elapsed)
        if thinking:
            logger.info("[LLM RESPONSE] thinking_len=%d", len(thinking))
            logger.info("[LLM RESPONSE] thinking_preview: %s", thinking[:300] + "..." if len(thinking) > 300 else thinking)
        logger.info("[LLM RESPONSE] content_len=%d", len(content))
        logger.info("[LLM RESPONSE] content: %s", content[:500] + "..." if len(content) > 500 else content)
        logger.info("=" * 80)

    def _build_messages(self, user_input: str, memory_context: str = "",
                        history: list[BaseMessage] | None = None,
                        summary: str = "") -> list[BaseMessage]:
        # Don't create a separate SystemMessage — create_agent already injects one.
        # Instead, prepend summary/memory as a system-level context message only if needed.
        context_parts = []
        if summary:
            context_parts.append(f"[Previous Conversation Summary]\nThe following is a summary of earlier conversation that has been compacted. Use this context to understand the user's ongoing work:\n\n{summary}")
        if memory_context:
            context_parts.append(f"[Memory Context]\n{memory_context}")

        messages: list[BaseMessage] = []
        if context_parts:
            # Insert as a system message BEFORE history (but after create_agent's own system prompt)
            messages.append(SystemMessage(content="\n\n".join(context_parts)))

        messages.extend(history or [])
        messages.append(HumanMessage(content=user_input))
        return messages

    async def run(self, user_input: str, memory_context: str = "",
                  history: list[BaseMessage] | None = None,
                  summary: str = "") -> AsyncIterator[dict[str, Any]]:
        trace_id = str(uuid.uuid4())
        messages = self._build_messages(user_input, memory_context, history, summary=summary)

        # 上下文压缩
        compressed = False
        if self.compressor.should_compress(messages):
            compress_summary, recent = await self.compressor.compress(messages[1:])
            # Merge with existing summary if any
            if summary:
                compress_summary = f"{summary}\n\n---\n\n{compress_summary}"
            messages = self._build_messages(user_input, memory_context, recent, summary=compress_summary)
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
        final_content = "".join(content_parts)

        # Log LLM response
        thinking_text = ""
        for msg in messages:
            if hasattr(msg, 'thinking') and msg.thinking:
                thinking_text += msg.thinking
        self._log_response("agent", final_content, thinking=thinking_content if 'thinking_content' in dir() else "", elapsed=_elapsed, trace_id=trace_id)

        logger.info(
            "[SSE-TRACE] %s agent done: %d events, %.2fs elapsed, content_len=%d",
            _ts(), _event_count, _elapsed, len(final_content),
        )

        # Extract file references from content
        file_refs = list(set(_FILE_PATH_RE.findall(final_content) + _CODE_FILE_RE.findall(final_content)))

        yield {
            "type": "message",
            "data": final_content,
            "file_refs": file_refs if file_refs else [],
        }

        # Emit metrics
        yield {
            "type": "metrics",
            "data": {
                "elapsed_ms": int(_elapsed * 1000),
                "agent_calls": 1,
                "tokens": {
                    "agent": {
                        "input": len(user_input) * 2,
                        "output": len(final_content) * 2,
                        "ms": int(_elapsed * 1000),
                    }
                },
            },
        }

        yield {"type": "done"}

    async def run_stream(self, user_input: str, memory_context: str = "", history: list[BaseMessage] | None = None) -> AsyncIterator[str]:
        async for event in self.run(user_input, memory_context, history):
            yield json.dumps(event, ensure_ascii=False)
