import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

# ── Error Classification ────────────────────────────────────────


class ErrorType(str, Enum):
    RECOVERABLE = "recoverable"
    FATAL = "fatal"
    SYSTEM = "system"
    VALIDATION = "validation"


class ErrorLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Error Envelope ──────────────────────────────────────────────


@dataclass
class ErrorEnvelope:
    error_code: str
    error_type: ErrorType
    message: str
    retryable: bool
    retry_after_ms: int = 0
    trace_id: str = ""
    context_snapshot: dict = field(default_factory=dict)
    fallback_action: str = ""
    error_level: ErrorLevel = ErrorLevel.MEDIUM
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tool_name: str = ""
    step: int = 0

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "error_type": self.error_type.value,
            "message": self.message,
            "retryable": self.retryable,
            "retry_after_ms": self.retry_after_ms,
            "trace_id": self.trace_id,
            "context_snapshot": self.context_snapshot,
            "fallback_action": self.fallback_action,
            "error_level": self.error_level.value,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "step": self.step,
        }


class StructuredAgentError(Exception):
    """Exception carrying an ErrorEnvelope."""

    def __init__(
        self,
        error_code: str,
        error_type: ErrorType,
        message: str,
        retryable: bool = False,
        **kwargs,
    ) -> None:
        self.envelope = ErrorEnvelope(
            error_code=error_code,
            error_type=error_type,
            message=message,
            retryable=retryable,
            **kwargs,
        )
        super().__init__(message)


# ── Error Handler ───────────────────────────────────────────────


class AgentErrorHandler:
    @staticmethod
    async def handle_context_overflow(
        error: Exception,
        messages: list[BaseMessage],
        compressor,
    ) -> list[BaseMessage]:
        clipped = AgentErrorHandler._clip_tail_tool_messages(messages, keep=3)
        return await compressor.compress(clipped)

    @staticmethod
    def handle_tool_error(error: Exception, tool_call_id: str, tool_name: str = "") -> ToolMessage:
        return ToolMessage(
            content=f"Tool execution failed: {error}",
            tool_call_id=tool_call_id,
            name=tool_name,
        )

    @staticmethod
    def handle_dangling_tool_calls(messages: list[BaseMessage]) -> list[BaseMessage]:
        result = []
        pending_tool_call_ids: set[str] = set()

        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    pending_tool_call_ids.add(tc["id"])
            elif isinstance(msg, ToolMessage) and msg.tool_call_id:
                pending_tool_call_ids.discard(msg.tool_call_id)
            result.append(msg)

        for tc_id in pending_tool_call_ids:
            result.append(
                ToolMessage(
                    content="[Tool call cancelled - no response]",
                    tool_call_id=tc_id,
                )
            )
        return result

    @staticmethod
    def _clip_tail_tool_messages(messages: list[BaseMessage], keep: int = 3) -> list[BaseMessage]:
        pairs: list[tuple[int | None, int]] = []
        ai_idx_map: dict[str, int] = {}

        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    ai_idx_map[tc["id"]] = i
            elif isinstance(msg, ToolMessage) and msg.tool_call_id:
                ai_idx = ai_idx_map.get(msg.tool_call_id)
                pairs.append((ai_idx, i))

        if len(pairs) <= keep:
            return messages

        to_remove: set[int] = set()
        for _, tool_idx in pairs[:-keep]:
            to_remove.add(tool_idx)

        return [m for i, m in enumerate(messages) if i not in to_remove]


# ── Retry Handler ───────────────────────────────────────────────


class RetryHandler:
    def __init__(self, max_retries: int = 3, initial_delay: float = 1.0, backoff_factor: float = 2.0) -> None:
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor

    async def execute_with_retry(self, func, *args, **kwargs):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = self.initial_delay * (self.backoff_factor ** attempt)
                    await asyncio.sleep(delay)
        raise last_error


# RetryConfig presets
LLMRetryConfig = RetryHandler(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
ToolRetryConfig = RetryHandler(max_retries=3, initial_delay=0.5, backoff_factor=2.0)
SupervisorRetryConfig = RetryHandler(max_retries=2, initial_delay=1.0, backoff_factor=2.0)


# ── Circuit Breaker ─────────────────────────────────────────────


class CircuitBreaker:
    """In-memory circuit breaker for LLM and tool calls."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = "closed"  # closed, open, half-open
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> str:
        if self._state == "open":
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = "half-open"
                self._success_count = 0
        return self._state

    def record_success(self) -> None:
        if self.state == "half-open":
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = "closed"
                self._failure_count = 0
        else:
            self._failure_count = 0

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"

    def allow_request(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half-open":
            return True
        return False


# Global instances
llm_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0, success_threshold=2)
tool_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0, success_threshold=2)
