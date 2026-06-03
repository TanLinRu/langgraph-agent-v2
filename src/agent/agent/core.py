"""Agent —— 单 Agent ReAct 执行核心。

模块职责
--------
封装 LangGraph ``create_react_agent`` 构建的单 Agent 循环,
提供 ``run()`` 异步生成器,将模型流逐事件转发给前端。

典型使用
--------
>>> from src.agent.config import AgentConfig
>>> from src.agent.agent import Agent
>>> agent = Agent(AgentConfig())
>>> async for event in agent.run("写个 Hello World"):
...     print(event["type"])

与 :class:`Orchestrator` 的关系:
    * ``Agent`` 是纯单 Agent 执行器,无计划/派发/综合阶段
    * ``Orchestrator`` 内部使用 ``langchain.create_agent`` 构建子 Agent,
      不直接使用本类 (但两者都依赖相同的 ``create_agent``/``TOOLS`` 基础设施)
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError

from src.agent.audit_logger import log_audit_event
from src.agent.config import AgentConfig
from src.agent.context._helpers import count_tokens
from src.agent.context.compression import ContextCompressor
from src.agent.models import resolve_model
from src.agent.orchestrator._events import (
    make_done,
    make_error,
    make_message,
    make_metrics,
    make_thinking,
    make_thinking_done,
    make_thinking_start,
    make_tool_call,
)
from src.agent.tools import TOOLS

logger = logging.getLogger(__name__)

# 文件路径提取正则 —— 从模型输出中识别代码库文件引用
_FILE_PATH_RE = re.compile(r'(?:src|docs|tests|ui|memory|skills)[/\\][\w./\\-]+\.\w+')
_CODE_FILE_RE = re.compile(r'[\w-]+\.(?:py|ts|js|vue|html|json|md|toml|yaml)')


def _ts() -> str:
    """毫秒级时间戳,用于 SSE 追踪日志。"""
    return f"{time.time():.3f}"


def _extract_file_refs(content: str) -> list[str]:
    """从文本中提取文件路径引用。"""
    return list(set(_FILE_PATH_RE.findall(content) + _CODE_FILE_RE.findall(content)))


class Agent:
    """单 Agent 执行器。

    基于 ``create_react_agent`` 构建 ReAct 循环,自动处理
    "LLM 调用 → 工具执行 → 再次调用 LLM → 直到无 tool_calls" 的迭代。

    属性
    ----
    config: ``AgentConfig``
    model:  底层 LLM 实例
    tools:  工具列表 (``TOOLS``)
    compressor: 上下文压缩器 (``ContextCompressor``)
    agent_graph: 编译后的 LangGraph ``StateGraph``
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.model = resolve_model(config)
        self.tools = TOOLS
        self.compressor = ContextCompressor(config)
        self.agent_graph = create_agent(
            self.model,
            tools=self.tools,
            system_prompt=self._get_system_prompt(),
        )

    # ── Prompt 构建 ──────────────────────────────────────────

    def _get_system_prompt(self) -> str:
        from src.agent.prompts.system_prompt import SYSTEM_PROMPT
        from src.agent.skills import get_skills_prompt

        skills_prompt = get_skills_prompt()
        return SYSTEM_PROMPT.format(
            skills=f"\n\n{skills_prompt}" if skills_prompt else "",
            memory_context="",
        )

    def _build_messages(
        self,
        user_input: str,
        memory_context: str = "",
        history: list[BaseMessage] | None = None,
        summary: str = "",
    ) -> list[BaseMessage]:
        """组装 LLM 消息列表。

        策略:
            * 如果提供了 summary 或 memory_context,在 history 前插入 SystemMessage
            * 不额外创建 system prompt (``create_agent`` 已注入)
        """
        context_parts = []
        if summary:
            context_parts.append(
                "[Previous Conversation Summary]\nThe following is a summary "
                "of earlier conversation that has been compacted. "
                "Use this context to understand the user's ongoing work:\n\n"
                f"{summary}"
            )
        if memory_context:
            context_parts.append(f"[Memory Context]\n{memory_context}")

        messages: list[BaseMessage] = []
        if context_parts:
            messages.append(SystemMessage(content="\n\n".join(context_parts)))
        messages.extend(history or [])
        messages.append(HumanMessage(content=user_input))
        return messages

    # ── 日志 ────────────────────────────────────────────────

    def _log_request(
        self,
        label: str,
        messages: list[BaseMessage],
        extra: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> None:
        """记录 LLM 请求日志 (内容 + 审计事件)。"""
        token_count = count_tokens(messages)
        threshold = int(self.config.max_tokens * self.config.compression_threshold)

        logger.info("=" * 80)
        logger.info("[LLM REQUEST] %s | trace_id=%s", label, trace_id)
        logger.info(
            "[LLM REQUEST] model=%s/%s base_url=%s",
            self.config.model_provider,
            self.config.model_name,
            self.config.openai_base_url,
        )
        logger.info(
            "[LLM REQUEST] messages=%d tokens~%d/%d(compress_at_%d) tools=%d",
            len(messages),
            token_count,
            self.config.max_tokens,
            threshold,
            len(self.tools),
        )
        logger.info("[LLM REQUEST] tools=%s", [t.name for t in self.tools])
        logger.info("-" * 40 + " MESSAGE LIST " + "-" * 40)
        for i, msg in enumerate(messages):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            logger.info("  [%d] type=%s len=%d", i, msg.type, len(content))
            if msg.type == "system":
                logger.info(
                    "  [%d] system: %s",
                    i,
                    content[:500] + "..." if len(content) > 500 else content,
                )
            elif msg.type == "human":
                logger.info(
                    "  [%d] user: %s",
                    i,
                    content[:500] + "..." if len(content) > 500 else content,
                )
            elif msg.type == "ai":
                logger.info(
                    "  [%d] assistant: %s",
                    i,
                    content[:500] + "..." if len(content) > 500 else content,
                )
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        logger.info(
                            "  [%d]   -> tool_call: %s(%s)",
                            i,
                            tc["name"],
                            json.dumps(tc["args"], ensure_ascii=False)[:200],
                        )
            elif msg.type == "tool":
                logger.info(
                    "  [%d] tool[%s]: %s",
                    i,
                    getattr(msg, "name", "?"),
                    content[:300] + "..." if len(content) > 300 else content,
                )
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

    def _log_response(
        self,
        label: str,
        content: str,
        thinking: str = "",
        elapsed: float = 0,
        trace_id: str = "",
    ) -> None:
        """记录 LLM 响应日志。"""
        logger.info("-" * 40 + " LLM RESPONSE " + "-" * 40)
        logger.info(
            "[LLM RESPONSE] %s | trace_id=%s | elapsed=%.2fs",
            label,
            trace_id,
            elapsed,
        )
        if thinking:
            logger.info("[LLM RESPONSE] thinking_len=%d", len(thinking))
            logger.info(
                "[LLM RESPONSE] thinking_preview: %s",
                thinking[:300] + "..." if len(thinking) > 300 else thinking,
            )
        logger.info("[LLM RESPONSE] content_len=%d", len(content))
        logger.info(
            "[LLM RESPONSE] content: %s",
            content[:500] + "..." if len(content) > 500 else content,
        )
        logger.info("=" * 80)

    # ── 主入口 ──────────────────────────────────────────────

    async def run(
        self,
        user_input: str,
        memory_context: str = "",
        history: list[BaseMessage] | None = None,
        summary: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """执行单轮对话,流式产出事件。

        事件顺序:
            1. ``thinking_start`` (仅当有 ``reasoning_content`` 时)
            2. ``thinking`` × N  (推理增量)
            3. ``thinking_done``  (推理结束)
            4. ``tool_call`` × N (每调用一次工具)
            5. ``message``       (最终模型回复)
            6. ``metrics``       (性能数据)
            7. ``error``         (可选,仅 ``GraphRecursionError`` 时)
            8. ``done``          (流结束)
        """
        trace_id = str(uuid.uuid4())
        messages = self._build_messages(user_input, memory_context, history, summary=summary)

        # 上下文压缩
        compressed = False
        if self.compressor.should_compress(messages):
            compress_summary, recent = await self.compressor.compress(messages[1:])
            if summary:
                compress_summary = f"{summary}\n\n---\n\n{compress_summary}"
            messages = self._build_messages(
                user_input, memory_context, recent, summary=compress_summary
            )
            compressed = True
            logger.info(
                "[Compress] triggered: token_threshold=%d, kept_recent=%d",
                int(self.config.max_tokens * self.config.compression_threshold),
                len(recent),
            )

        self._log_request("agent", messages, {"compressed": compressed}, trace_id=trace_id)

        thinking_started = False
        content_parts: list[str] = []
        _event_count = 0
        _t0 = time.time()

        try:
            async for event in self.agent_graph.astream_events(
                {"messages": messages},
                {"recursion_limit": 200},
                version="v2",
            ):
                kind = event["event"]

                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    reasoning = chunk.additional_kwargs.get("reasoning_content")
                    if reasoning:
                        if not thinking_started:
                            yield make_thinking_start("agent")
                            thinking_started = True
                            _event_count += 1
                            logger.info("[SSE-TRACE] %s thinking_start emitted", _ts())
                        yield make_thinking("agent", reasoning)
                        _event_count += 1
                    elif chunk.content:
                        content_parts.append(chunk.content)

                elif kind == "on_tool_start":
                    yield make_tool_call(
                        "agent",
                        [{"name": event["name"], "args": event["data"].get("input", {})}],
                    )
                    _event_count += 1

        except GraphRecursionError:
            logger.warning(
                "[AGENT] GraphRecursionError: too many tool calls, yielding error event"
            )
            yield make_error("agent", "工具调用次数过多，已终止。请简化问题或分步提问。")

        if thinking_started:
            yield make_thinking_done("agent")

        _elapsed = time.time() - _t0
        final_content = "".join(content_parts)

        # 提取文件引用
        file_refs = _extract_file_refs(final_content)

        self._log_response("agent", final_content, elapsed=_elapsed, trace_id=trace_id)
        logger.info(
            "[SSE-TRACE] %s agent done: %d events, %.2fs elapsed, content_len=%d",
            _ts(),
            _event_count,
            _elapsed,
            len(final_content),
        )

        yield make_message("agent", final_content, file_refs=file_refs if file_refs else [])

        yield make_metrics("agent", {
            "elapsed_ms": int(_elapsed * 1000),
            "agent_calls": 1,
            "tokens": {
                "agent": {
                    "input": len(user_input) * 2,
                    "output": len(final_content) * 2,
                    "ms": int(_elapsed * 1000),
                }
            },
        })

        yield make_done()

    async def run_stream(
        self,
        user_input: str,
        memory_context: str = "",
        history: list[BaseMessage] | None = None,
    ) -> AsyncIterator[str]:
        """JSON 包装的 ``run()``,用于旧版 HTTP 响应兼容。"""
        async for event in self.run(user_input, memory_context, history):
            yield json.dumps(event, ensure_ascii=False)



