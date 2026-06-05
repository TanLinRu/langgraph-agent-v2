"""Debug script to check routing behavior."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessageChunk

def _make_chunk(content=None, reasoning=None):
    chunk = MagicMock(spec=AIMessageChunk)
    chunk.content = content or ''
    chunk.additional_kwargs = {}
    if reasoning:
        chunk.additional_kwargs['reasoning_content'] = reasoning
    return chunk

async def _mock_model_stream(chunks):
    for chunk in chunks:
        yield chunk

with patch("src.agent.models.resolve_model") as mock_resolve:
    mock_model = AsyncMock()
    mock_model.astream = MagicMock(side_effect=[
        _mock_model_stream([_make_chunk(content='{"steps": [{"agent": "direct", "task": "reply"}], "auto_approve": true}')]),
        _mock_model_stream([_make_chunk(content='Audit OK. approve')]),
        _mock_model_stream([_make_chunk(content='[]')]),
    ])
    mock_resolve.return_value = mock_model

    with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
        mock_tool.return_value = "hello world"

        from src.agent.config import AgentConfig
        from src.agent.orchestrator import Orchestrator
        from src.agent.orchestrator.planner import GraphState, Plan

        config = AgentConfig()
        orch = Orchestrator(config)

        async def run():
            events = []
            async for event in orch.run("test"):
                events.append(event["type"])
                if event["type"] == "plan":
                    print("PLAN EVENT:", event.get("data", "")[:100])
                if event["type"] == "interrupt":
                    print("INTERRUPT EVENT:", event.get("data", {}))
            print("Event types:", events)
            print("Count:", len(events))

        asyncio.run(run())
