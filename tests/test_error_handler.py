
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.error_handler import (
    AgentErrorHandler,
    CircuitBreaker,
    ErrorEnvelope,
    ErrorLevel,
    ErrorType,
    RetryHandler,
    StructuredAgentError,
    llm_circuit_breaker,
    tool_circuit_breaker,
)


def test_error_envelope_to_dict():
    env = ErrorEnvelope(
        error_code="TEST_001",
        error_type=ErrorType.RECOVERABLE,
        message="test error",
        retryable=True,
        error_level=ErrorLevel.MEDIUM,
        tool_name="execute_code",
    )
    d = env.to_dict()
    assert d["error_type"] == "recoverable"
    assert d["error_level"] == "medium"
    assert d["message"] == "test error"
    assert d["tool_name"] == "execute_code"
    assert d["error_code"] == "TEST_001"


def test_structured_agent_error():
    err = StructuredAgentError(
        error_code="FATAL_001",
        error_type=ErrorType.FATAL,
        message="fatal error",
        retryable=False,
        error_level=ErrorLevel.CRITICAL,
    )
    assert str(err) == "fatal error"
    assert err.envelope.error_type == ErrorType.FATAL
    assert err.envelope.error_level == ErrorLevel.CRITICAL


def test_handle_tool_error():
    msg = AgentErrorHandler.handle_tool_error(ValueError("bad"), "tc-1", "execute_code")
    assert isinstance(msg, ToolMessage)
    assert "bad" in msg.content
    assert msg.tool_call_id == "tc-1"


def test_handle_dangling_tool_calls():
    msgs = [
        HumanMessage(content="do something"),
        AIMessage(content="", tool_calls=[{"id": "tc-1", "name": "tool", "args": {}}]),
    ]
    result = AgentErrorHandler.handle_dangling_tool_calls(msgs)
    tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "tc-1"


def test_handle_dangling_tool_calls_no_dangle():
    msgs = [
        AIMessage(content="", tool_calls=[{"id": "tc-1", "name": "tool", "args": {}}]),
        ToolMessage(content="ok", tool_call_id="tc-1"),
    ]
    result = AgentErrorHandler.handle_dangling_tool_calls(msgs)
    tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert "cancelled" not in tool_msgs[0].content


@pytest.mark.asyncio
async def test_retry_handler_success():
    handler = RetryHandler(max_retries=3, initial_delay=0.01, backoff_factor=1.0)
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError("fail")
        return "ok"

    result = await handler.execute_with_retry(flaky)
    assert result == "ok"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_handler_exhausted():
    handler = RetryHandler(max_retries=2, initial_delay=0.01, backoff_factor=1.0)

    async def always_fail():
        raise ValueError("always fail")

    with pytest.raises(ValueError, match="always fail"):
        await handler.execute_with_retry(always_fail)


def test_circuit_breaker_closed():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
    assert cb.state == "closed"
    assert cb.allow_request() is True


def test_circuit_breaker_opens():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow_request() is False


def test_circuit_breaker_half_open():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.001)
    cb.record_failure()
    assert cb.state == "open"
    import time
    time.sleep(0.01)
    assert cb.allow_request() is True
    assert cb.state == "half-open"


def test_circuit_breaker_resets():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    cb._state = "closed"
    cb._failure_count = 0
    assert cb.state == "closed"
    assert cb.allow_request() is True


def test_global_instances():
    assert llm_circuit_breaker is not None
    assert tool_circuit_breaker is not None
    assert llm_circuit_breaker.failure_threshold == 5
