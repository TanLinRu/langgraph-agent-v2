import asyncio

import pytest

from src.agent.event_bus import EventBus


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    bus = EventBus()
    q = bus.subscribe("stream1")
    await bus.publish("stream1", "message", "hello", agent_name="coder")
    event = await asyncio.wait_for(q.get(), timeout=1)
    assert event["type"] == "message"
    assert event["data"] == "hello"
    assert event["agent_name"] == "coder"


@pytest.mark.asyncio
async def test_multiple_subscribers():
    bus = EventBus()
    q1 = bus.subscribe("s1")
    q2 = bus.subscribe("s1")
    await bus.publish("s1", "test", "data")
    e1 = await asyncio.wait_for(q1.get(), timeout=1)
    e2 = await asyncio.wait_for(q2.get(), timeout=1)
    assert e1["data"] == "data"
    assert e2["data"] == "data"


@pytest.mark.asyncio
async def test_unsubscribe():
    bus = EventBus()
    q = bus.subscribe("s1")
    bus.unsubscribe("s1", q)
    await bus.publish("s1", "test", "data")
    assert q.empty()


def test_format_sse():
    bus = EventBus()
    sse = bus.format_sse({"type": "message", "data": "hello"})
    assert sse.startswith("data: ")
    assert sse.endswith("\n\n")
    assert '"message"' in sse


@pytest.mark.asyncio
async def test_isolated_streams():
    bus = EventBus()
    q1 = bus.subscribe("s1")
    q2 = bus.subscribe("s2")
    await bus.publish("s1", "msg", "for_s1")
    e1 = await asyncio.wait_for(q1.get(), timeout=1)
    assert e1["data"] == "for_s1"
    assert q2.empty()
