"""AgentNode — lightweight LLM call wrapper for graph nodes.

Each node in the StateGraph can be configured as an AgentNode:
reads agent config (system_prompt, model override, temperature)
from config/agents.json and handles thinking events + token tracking.
Uses StreamWriter instead of queue for event emission.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import StreamWriter

from src.agent import models as _models
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.events import make_thinking, make_thinking_done, make_thinking_start


class AgentNode:
    """Lightweight LLM call wrapper: emits thinking_start/thinking/thinking_done + tracks tokens.

    Usage:
        agent = AgentNode("supervisor", config)
        response = await agent.call("your user message", writer)
    """

    def __init__(self, agent_id: str, config: AgentConfig):
        self.agent_id = agent_id
        cfg = get_config_manager().get_agents().get(agent_id, {})
        self.model = _models.resolve_model(
            config,
            model_override=cfg.get("model"),
            temperature=cfg.get("temperature"),
            max_tokens=cfg.get("max_tokens"),
        )
        self.system_prompt = cfg.get("system_prompt", "")

    async def call(
        self,
        user_message: str,
        writer: StreamWriter,
        system_prompt: str | None = None,
    ) -> str:
        """Call the LLM with system prompt + user message.

        Args:
            user_message: The user/content message to send.
            writer: StreamWriter for emitting events.
            system_prompt: Optional override for the agent's configured system_prompt.

        Returns:
            The full LLM response text.
        """
        prompt = system_prompt or self.system_prompt
        writer(make_thinking_start(self.agent_id))

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ]

        response = ""
        async for chunk in self.model.astream(messages):
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                writer(make_thinking(self.agent_id, reasoning[:500]))
            if chunk.content:
                response += chunk.content

        writer(make_thinking_done(self.agent_id))
        return response
