"""Supervisor — multi-agent orchestrator using JSON-based configuration."""

import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.models import resolve_model
from src.agent.tools import TOOLS

logger = logging.getLogger(__name__)

# Plan parsing regex: matches "- agent_name: description" (with optional bold)
_PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)


class CustomSupervisor:
    """Supervisor with think→plan→dispatch→summarize flow.

    Reads agent configuration from config/agents.json with hot reload support.
    Each sub-agent can have its own model, temperature, and max_tokens.
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.cm = get_config_manager()
        self.model = resolve_model(config)  # Global model for supervisor planning
        self.tool_map = {t.name: t for t in TOOLS}
        self._build_agents()

    def _build_agents(self) -> None:
        """Build sub-agent graphs from JSON configuration."""
        agents_config = self.cm.get_agents()
        self.agents: dict[str, Any] = {}
        self.acp_agents: dict[str, dict] = {}  # ACP agent configs (not LangChain agents)

        for agent_id, cfg in agents_config.items():
            # Skip supervisor (orchestrator) and disabled agents
            if agent_id == "supervisor" or not cfg.get("enabled", True):
                continue

            # Check if this is an ACP agent
            if cfg.get("acp_mode"):
                self.acp_agents[agent_id] = cfg
                logger.info("[Supervisor] registered ACP agent: %s (cli=%s)", agent_id, cfg.get("acp_cli_id"))
                continue

            # Get tools from config
            tool_names = cfg.get("tools", [])
            if not tool_names and agent_id == "direct":
                # Direct agent gets all tools
                agent_tools = list(self.tool_map.values())
            elif tool_names:
                agent_tools = [self.tool_map[n] for n in tool_names if n in self.tool_map]
            else:
                logger.warning("[Supervisor] agent %s has no tools, skipping", agent_id)
                continue

            if not agent_tools:
                logger.warning("[Supervisor] agent %s has no valid tools, skipping", agent_id)
                continue

            # Get system prompt from config
            system_prompt = cfg.get("system_prompt", "You are a helpful assistant.")

            # Resolve model with per-agent overrides
            agent_model = resolve_model(
                self.config,
                model_override=cfg.get("model"),
                temperature=cfg.get("temperature"),
                max_tokens=cfg.get("max_tokens"),
            )

            self.agents[agent_id] = create_agent(
                agent_model, tools=agent_tools,
                system_prompt=system_prompt,
                name=agent_id,
            )
            logger.info("[Supervisor] built agent: %s with tools: %s", agent_id, [t.name for t in agent_tools])

        # Ensure direct agent exists as fallback
        if "direct" not in self.agents:
            all_tools = list(self.tool_map.values())
            self.agents["direct"] = create_agent(
                resolve_model(self.config), tools=all_tools,
                system_prompt="You are a helpful assistant. Complete the task directly.",
                name="direct",
            )

    async def run(self, task: str) -> AsyncIterator[dict[str, Any]]:
        """Run the supervisor flow: think → plan → dispatch → summarize."""
        from src.agent.prompts.system_prompt import SUPERVISOR_PROMPT

        start_time = time.time()
        agent_calls = 0
        token_usage: dict[str, dict[str, int]] = {}

        # ── Phase 1: Think + Plan ──────────────────────────────────
        yield {"type": "thinking_start", "agent_name": "supervisor"}

        plan_messages = [
            {"role": "system", "content": SUPERVISOR_PROMPT},
            {"role": "user", "content": task},
        ]

        # Log supervisor request
        logger.info("=" * 80)
        logger.info("[SUPERVISOR REQUEST] task=%s", task[:200])
        logger.info("[SUPERVISOR REQUEST] model=%s/%s", self.config.model_provider, self.config.model_name)
        logger.info("[SUPERVISOR REQUEST] messages=%d", len(plan_messages))
        for i, msg in enumerate(plan_messages):
            logger.info("  [%d] %s: %s", i, msg["role"], msg["content"][:300] + "..." if len(msg["content"]) > 300 else msg["content"])
        logger.info("=" * 80)

        thinking_content = ""
        plan_text = ""
        _t0 = time.time()

        async for chunk in self.model.astream(plan_messages):
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                thinking_content += reasoning
                yield {"type": "thinking", "data": reasoning, "agent_name": "supervisor"}
            if chunk.content:
                plan_text += chunk.content
                if not reasoning:
                    yield {"type": "thinking", "data": chunk.content, "agent_name": "supervisor"}

        yield {"type": "thinking_done", "agent_name": "supervisor"}

        # Log supervisor response
        _elapsed = time.time() - _t0
        logger.info("-" * 40 + " SUPERVISOR RESPONSE " + "-" * 40)
        logger.info("[SUPERVISOR RESPONSE] elapsed=%.2fs", _elapsed)
        logger.info("[SUPERVISOR RESPONSE] thinking_len=%d", len(thinking_content))
        logger.info("[SUPERVISOR RESPONSE] plan_len=%d", len(plan_text))
        logger.info("[SUPERVISOR RESPONSE] plan: %s", plan_text[:500] + "..." if len(plan_text) > 500 else plan_text)
        logger.info("=" * 80)

        # ── Phase 2: Parse Plan ────────────────────────────────────
        # Get valid agent IDs from config (both LangChain and ACP agents)
        valid_agents = set(self.agents.keys()) | set(self.acp_agents.keys())
        steps = self._parse_plan(plan_text, valid_agents)

        if not steps:
            yield {"type": "message", "data": plan_text, "agent_name": "supervisor"}
            yield {"type": "done"}
            return

        # Direct-answer shortcut: all steps are "direct" agent,
        # skip sub-agent dispatch and answer directly.
        if all(s["agent"] == "direct" for s in steps):
            yield {"type": "message", "data": plan_text, "agent_name": "supervisor"}
            elapsed_ms = int((time.time() - start_time) * 1000)
            yield {
                "type": "metrics",
                "data": {"elapsed_ms": elapsed_ms, "agent_calls": 0, "tokens": {}},
                "agent_name": "supervisor",
            }
            yield {"type": "done"}
            return

        yield {"type": "plan", "data": plan_text, "agent_name": "supervisor"}

        # ── Phase 3: Dispatch to Sub-agents ────────────────────────
        results: list[dict[str, str]] = []

        for step in steps:
            agent_name = step["agent"]
            subtask = step["task"]
            agent_calls += 1

            yield {
                "type": "task_update",
                "data": {"agent": agent_name, "task": subtask, "status": "running"},
                "agent_name": "supervisor",
            }

            agent_start = time.time()
            agent_content = ""

            # ── ACP Agent ──
            if agent_name in self.acp_agents:
                logger.info("-" * 40 + " ACP AGENT REQUEST " + "-" * 40)
                logger.info("[ACP] agent=%s task=%s", agent_name, subtask[:200])

                try:
                    from src.agent.acp_agent import get_acp_agent
                    # acp_cli_id in agents.json maps to acp_agents.json key
                    acp_id = self.acp_agents[agent_name].get("acp_cli_id", agent_name)
                    acp = get_acp_agent(acp_id)

                    # Build context from previous results
                    context = ""
                    if results:
                        context = "Previous results:\n" + "\n".join(
                            f"- {r['agent']}: {r['result'][:200]}" for r in results
                        )

                    async for event in acp.run(subtask, context=context):
                        event["agent_name"] = agent_name
                        yield event
                        if event["type"] == "message":
                            chunk = event.get("data", "")
                            if chunk:
                                # Append; ACP agents sometimes emit a trailing punctuation
                                # chunk (e.g. ".") that would otherwise overwrite the whole
                                # accumulated content. If the new chunk is just punctuation
                                # and we already have substantive content, skip it.
                                stripped_chunk = chunk.strip()
                                is_punct_chunk = bool(stripped_chunk) and all(
                                    c in ".,!?;:。！？；：、 \n\t" for c in stripped_chunk
                                )
                                if is_punct_chunk and len(agent_content.strip()) > 20:
                                    continue
                                agent_content += chunk
                        elif event["type"] == "error":
                            agent_content = f"Error: {event.get('data', '')}"

                except Exception as e:
                    logger.error("[ACP] agent error: %s", e)
                    agent_content = f"ACP agent error: {e}"

            # ── Standard LangChain Agent ──
            elif agent_name in self.agents:
                agent_graph = self.agents[agent_name]

                logger.info("-" * 40 + " SUB-AGENT REQUEST " + "-" * 40)
                logger.info("[SUB-AGENT] agent=%s task=%s", agent_name, subtask[:200])

                async for event in agent_graph.astream_events(
                    {"messages": [HumanMessage(content=subtask)]}, version="v2"
                ):
                    kind = event["event"]

                    if kind == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        reasoning = chunk.additional_kwargs.get("reasoning_content")
                        if reasoning:
                            yield {"type": "thinking", "data": reasoning, "agent_name": agent_name}
                        elif chunk.content:
                            agent_content += chunk.content

                    elif kind == "on_tool_start":
                        yield {
                            "type": "tool_call",
                            "data": [{"name": event["name"], "args": event["data"].get("input", {})}],
                            "agent_name": agent_name,
                        }
            else:
                agent_content = f"Unknown agent: {agent_name}"

            agent_ms = int((time.time() - agent_start) * 1000)

            logger.info("[SUB-AGENT RESPONSE] agent=%s elapsed=%dms content_len=%d", agent_name, agent_ms, len(agent_content))
            logger.info("[SUB-AGENT RESPONSE] content: %s", agent_content[:500] + "..." if len(agent_content) > 500 else agent_content)
            token_usage[agent_name] = {"input": len(subtask) * 2, "output": len(agent_content) * 2, "ms": agent_ms}

            results.append({"agent": agent_name, "task": subtask, "result": agent_content})

            # Emit sub-agent content as a message event for the UI.
            # Skip empty/punctuation-only payloads — they produce meaningless assistant bubbles.
            stripped = agent_content.strip()
            is_punct_only = bool(stripped) and all(c in ".,!?;:。！？；：、 \n\t" for c in stripped)
            if stripped and not is_punct_only:
                yield {
                    "type": "message",
                    "data": agent_content,
                    "agent_name": agent_name,
                }
            elif not stripped:
                # No content captured (e.g. tool-only execution) — emit a brief completion marker
                # so the UI can show "done" state for the agent bubble.
                yield {
                    "type": "message",
                    "data": f"由 {agent_name} 完成",
                    "agent_name": agent_name,
                }

            yield {
                "type": "task_update",
                "data": {"agent": agent_name, "task": subtask, "status": "completed"},
                "agent_name": "supervisor",
            }

        # ── Phase 4: Summarize (multi-agent only) ──────────────────
        if len(results) > 1:
            results_text = "\n\n".join(
                f"**{r['agent']}** ({r['task']}):\n{r['result']}" for r in results
            )
            summary_prompt = [
                {"role": "system", "content": "You are a supervisor. Summarize the results from your team concisely."},
                {"role": "user", "content": f"Task: {task}\n\nResults:\n{results_text}\n\nProvide a concise summary."},
            ]
            summary = ""
            async for chunk in self.model.astream(summary_prompt):
                if chunk.content:
                    summary += chunk.content
            yield {"type": "summary", "data": summary, "agent_name": "supervisor"}

        # ── Emit final metrics ─────────────────────────────────────
        elapsed_ms = int((time.time() - start_time) * 1000)
        yield {
            "type": "metrics",
            "data": {
                "elapsed_ms": elapsed_ms,
                "agent_calls": agent_calls,
                "tokens": token_usage,
            },
            "agent_name": "supervisor",
        }

        yield {"type": "done"}

    def _parse_plan(self, plan_text: str, valid_agents: set[str]) -> list[dict[str, str]]:
        """Parse plan text into list of {agent, task} dicts."""
        results = []
        for m in _PLAN_RE.finditer(plan_text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            if agent_name in valid_agents:
                results.append({"agent": agent_name, "task": task})
        return results


def create_default_supervisor(config: AgentConfig) -> CustomSupervisor:
    """Factory function to create the default supervisor."""
    return CustomSupervisor(config)
