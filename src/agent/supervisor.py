import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage
from langchain.agents import create_agent

from src.agent.config import AgentConfig
from src.agent.models import resolve_model
from src.agent.tools import TOOLS

logger = logging.getLogger(__name__)

# Plan parsing regex: matches "- agent_name: description" (with optional bold)
_PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)

# Tool subsets per agent
_CODER_TOOLS = ["execute_code", "read_file", "write_file"]
_RESEARCHER_TOOLS = ["search_files", "list_directory", "read_file"]
_ANALYST_TOOLS = ["execute_code", "read_file", "search_files"]


def _extract_code(text: str) -> str:
    """Extract code from fenced blocks, backticks, or plain text."""
    # Try fenced code block first
    m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Try inline backticks
    m = re.search(r"`([^`]+)`", text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _parse_plan(plan_text: str) -> list[dict[str, str]]:
    """Parse plan text into list of {agent, task} dicts."""
    results = []
    for m in _PLAN_RE.finditer(plan_text):
        agent_name = m.group(1).lower().strip("*")
        task = m.group(2).strip()
        if agent_name in ("coder", "researcher", "analyst", "direct"):
            results.append({"agent": agent_name, "task": task})
    return results


class CustomSupervisor:
    """Supervisor with think→plan→dispatch→summarize flow.

    Uses LangChain native APIs:
    - model.astream() for supervisor thinking/planning
    - create_react_agent + astream_events for sub-agent streaming
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.model = resolve_model(config)
        self.tool_map = {t.name: t for t in TOOLS}
        self._build_agents()

    def _build_agents(self) -> None:
        """Build sub-agent graphs with specialized tool sets."""
        coder_tools = [self.tool_map[n] for n in _CODER_TOOLS if n in self.tool_map]
        researcher_tools = [self.tool_map[n] for n in _RESEARCHER_TOOLS if n in self.tool_map]
        analyst_tools = [self.tool_map[n] for n in _ANALYST_TOOLS if n in self.tool_map]
        # direct agent has all tools — decides itself whether to use them
        all_tools = list(self.tool_map.values())

        self.agents: dict[str, Any] = {
            "coder": create_agent(
                self.model, tools=coder_tools,
                system_prompt="You are a coding expert. Write and execute code to solve problems. Think step by step.",
                name="coder",
            ),
            "researcher": create_agent(
                self.model, tools=researcher_tools,
                system_prompt="You are a research expert. Search and analyze files to find information.",
                name="researcher",
            ),
            "analyst": create_agent(
                self.model, tools=analyst_tools,
                system_prompt="You are a data analyst. Process data and generate insights.",
                name="analyst",
            ),
            "direct": create_agent(
                self.model, tools=all_tools,
                system_prompt="You are a helpful assistant. Complete the task directly. Use tools only if needed (e.g., run code, read files). For simple questions or confirmations, respond directly without tools.",
                name="direct",
            ),
        }

    async def run(self, task: str) -> AsyncIterator[dict[str, Any]]:
        """Run the supervisor flow: think → plan → dispatch → summarize."""
        from src.agent.prompts.system_prompt import SUPERVISOR_PROMPT

        # ── Phase 1: Think + Plan ──────────────────────────────────
        yield {"type": "thinking_start", "agent_name": "supervisor"}

        plan_messages = [
            {"role": "system", "content": SUPERVISOR_PROMPT},
            {"role": "user", "content": task},
        ]

        thinking_content = ""
        plan_text = ""

        async for chunk in self.model.astream(plan_messages):
            # Extract reasoning_content (ChatDeepSeek auto-populates)
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                thinking_content += reasoning
                yield {"type": "thinking", "data": reasoning, "agent_name": "supervisor"}
            if chunk.content:
                plan_text += chunk.content
                # Also yield content as thinking for models without reasoning_content
                if not reasoning:
                    yield {"type": "thinking", "data": chunk.content, "agent_name": "supervisor"}

        yield {"type": "thinking_done", "agent_name": "supervisor"}

        # ── Phase 2: Parse Plan ────────────────────────────────────
        steps = _parse_plan(plan_text)

        if not steps:
            # No valid plan — treat entire response as direct answer
            yield {"type": "message", "data": plan_text, "agent_name": "supervisor"}
            yield {"type": "done"}
            return

        yield {"type": "plan", "data": plan_text, "agent_name": "supervisor"}

        # ── Phase 3: Dispatch to Sub-agents ────────────────────────
        results: list[dict[str, str]] = []

        for step in steps:
            agent_name = step["agent"]
            subtask = step["task"]

            agent_graph = self.agents.get(agent_name)
            if not agent_graph:
                results.append({"agent": agent_name, "task": subtask, "result": f"Unknown agent: {agent_name}"})
                continue

            # Stream sub-agent execution via astream_events
            agent_content = ""
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

            results.append({"agent": agent_name, "task": subtask, "result": agent_content})
            yield {"type": "message", "data": agent_content, "agent_name": agent_name}

        # ── Phase 4: Summarize (skip if single agent) ──────────────
        if len(results) == 1:
            # Single agent — skip summarize, result already yielded
            pass
        else:
            # Multiple agents — generate summary
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

        yield {"type": "done"}


def create_default_supervisor(config: AgentConfig) -> CustomSupervisor:
    """Factory function to create the default supervisor."""
    return CustomSupervisor(config)
