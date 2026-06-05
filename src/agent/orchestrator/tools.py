"""Tool-based wrappers for sub-agent dispatch in the StateGraph.

Replaces the old LocalDispatcher / ACPDispatcher procedural interfaces
with LangChain BaseTool subclasses, so the execute_node can use
create_react_agent with standard tool-calling semantics.
"""

from __future__ import annotations

import logging

from langchain.tools import BaseTool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from src.agent import models as _models
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.tools import get_tools

logger = logging.getLogger(__name__)


class SubAgentTool(BaseTool):
    """Invoke a local sub-agent built via create_react_agent.

    Used inside the execute_node's ReAct loop.  Each call constructs a
    fresh sub-agent graph from the agent's config (tools, model, prompt).
    Supports context injection for perceived environment facts.
    """

    name: str = "sub_agent"
    description: str = "Dispatch a subtask to a specialized sub-agent"
    agent_id: str
    config: AgentConfig
    context: str = ""
    return_direct: bool = False

    def _run(self, task: str) -> str:
        raise NotImplementedError("Use _arun for async execution")

    async def _arun(self, task: str) -> str:
        """Execute a subtask via the sub-agent and return the result text."""
        cm = get_config_manager()
        agents_config = cm.get_agents()
        cfg = agents_config.get(self.agent_id, {})
        agent_tools = self._resolve_tools(cfg)

        agent_model = _models.resolve_model(
            self.config,
            model_override=cfg.get("model"),
            temperature=cfg.get("temperature"),
            max_tokens=cfg.get("max_tokens"),
        )
        system_prompt = cfg.get("system_prompt", "You are a helpful assistant.")
        if self.context:
            system_prompt += f"\n\n[Context]\n{self.context}"

        graph = create_react_agent(agent_model, tools=agent_tools, system_prompt=system_prompt)

        content_parts: list[str] = []
        directive = (
            "EXECUTE THE FOLLOWING TASK IMMEDIATELY. "
            "DO NOT repeat or paraphrase these instructions. "
            "DO NOT describe what you will do. "
            "Produce the actual output (answer, code, report) directly.\n\n"
            f"---\n{task}\n---"
        )
        try:
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=directive)]},
                {"recursion_limit": 200},
                version="v2",
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        content_parts.append(chunk.content)
        except Exception as e:
            logger.error("[SubAgentTool] agent %s error: %s", self.agent_id, e)
            return f"Agent error: {e}"

        return "".join(content_parts)

    def _resolve_tools(self, cfg: dict) -> list:
        tool_map = {t.name: t for t in get_tools()}
        tool_names = cfg.get("tools", [])
        if not tool_names and self.agent_id == "direct":
            return list(tool_map.values())
        return [tool_map[n] for n in tool_names if n in tool_map]


class ACPSubAgentTool(BaseTool):
    """Dispatch a subtask to an external ACP agent (opencode, claude, etc.).

    Uses get_acp_agent() for lazy-initialized persistent connections.
    Supports context injection for perceived environment facts.
    """

    name: str = "acp_sub_agent"
    description: str = "Dispatch a subtask to an external ACP agent"
    agent_id: str
    acp_cli_id: str
    context: str = ""
    return_direct: bool = False

    def _run(self, task: str) -> str:
        raise NotImplementedError("Use _arun for async execution")

    async def _arun(self, task: str) -> str:
        from src.agent.acp_agent import get_acp_agent

        acp = get_acp_agent(self.acp_cli_id)
        content_parts: list[str] = []
        async for event in acp.run(task, context=self.context):
            if event.get("type") == "message":
                chunk = event.get("data", "")
                if chunk:
                    content_parts.append(chunk)
            elif event.get("type") == "error":
                return f"Error: {event.get('data', '')}"
        return "".join(content_parts)
