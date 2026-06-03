import json
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from src.agent._utils import is_punctuation_only
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.models import resolve_model
from src.agent.tools import TOOLS

logger = logging.getLogger(__name__)

_PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)


class Orchestrator:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.model = resolve_model(config)
        self.sub_agents: dict[str, Any] = {}
        self.acp_agents: dict[str, str] = {}
        self._build_sub_agents()

    def _build_sub_agents(self):
        cm = get_config_manager()
        agents_config = cm.get_agents()
        tool_map = {t.name: t for t in TOOLS}
        for agent_id, cfg in agents_config.items():
            if agent_id == "supervisor" or not cfg.get("enabled", True):
                continue
            if cfg.get("acp_mode"):
                self.acp_agents[agent_id] = cfg.get("acp_cli_id", agent_id)
                continue
            tool_names = cfg.get("tools", [])
            if not tool_names and agent_id == "direct":
                agent_tools = list(tool_map.values())
            elif tool_names:
                agent_tools = [tool_map[n] for n in tool_names if n in tool_map]
            else:
                continue
            if not agent_tools:
                continue
            agent_model = resolve_model(
                self.config,
                model_override=cfg.get("model"),
                temperature=cfg.get("temperature"),
                max_tokens=cfg.get("max_tokens"),
            )
            self.sub_agents[agent_id] = create_agent(
                agent_model, tools=agent_tools,
                system_prompt=cfg.get("system_prompt", "You are a helpful assistant."),
                name=agent_id,
            )
        if "direct" not in self.sub_agents:
            agent_model = resolve_model(self.config)
            self.sub_agents["direct"] = create_agent(
                agent_model, tools=list(tool_map.values()),
                system_prompt="You are a helpful assistant. Complete the task directly.",
                name="direct",
            )

    async def run(self, task: str, history: list[dict] | None = None, summary: str = "") -> AsyncIterator[dict[str, Any]]:
        start_time = time.time()
        plan_text = ""
        async for event in self._plan(task, history, summary=summary):
            yield event
            if event["type"] == "plan":
                plan_text = event.get("data", "")
        valid_agents = set(self.sub_agents.keys()) | set(self.acp_agents.keys())
        steps = self._parse_plan(plan_text, valid_agents)
        if not steps:
            steps = [{"agent": "direct", "task": plan_text.strip() or task}]
        if all(s["agent"] == "direct" for s in steps):
            clean_response = self._clean_direct_response(steps[0]["task"])
            yield {"type": "message", "data": clean_response, "agent_name": "supervisor"}
            yield {"type": "metrics", "data": {"elapsed_ms": int((time.time() - start_time) * 1000), "agent_calls": 0, "tokens": {}}, "agent_name": "supervisor"}
            yield {"type": "done"}
            return
        agent_calls = 0
        token_usage: dict[str, dict[str, int]] = {}
        results: list[dict[str, str]] = []
        for step in steps:
            agent_name = step["agent"]
            subtask = step["task"]
            agent_calls += 1
            agent_start = time.time()
            agent_content = ""
            async for event in self._execute_step(agent_name, subtask, results):
                yield event
                if event["type"] == "message" and event.get("agent_name") == agent_name:
                    agent_content = event.get("data", "")
            agent_ms = int((time.time() - agent_start) * 1000)
            token_usage[agent_name] = {"input": len(subtask) * 2, "output": len(agent_content) * 2, "ms": agent_ms}
            results.append({"agent": agent_name, "task": subtask, "result": agent_content})
            yield {"type": "task_update", "data": {"agent": agent_name, "task": subtask, "status": "completed"}, "agent_name": "supervisor"}
        if len(results) > 1:
            results_text = "\n\n".join(f"**{r['agent']}** ({r['task']}):\n{r['result']}" for r in results)
            summary_prompt = [
                {"role": "system", "content": "You are a supervisor. Summarize the results from your team concisely."},
                {"role": "user", "content": f"Task: {task}\n\nResults:\n{results_text}\n\nProvide a concise summary."},
            ]
            summary = ""
            async for chunk in self.model.astream(summary_prompt):
                if chunk.content:
                    summary += chunk.content
            yield {"type": "summary", "data": summary, "agent_name": "supervisor"}
        yield {"type": "metrics", "data": {"elapsed_ms": int((time.time() - start_time) * 1000), "agent_calls": agent_calls, "tokens": token_usage}, "agent_name": "supervisor"}
        yield {"type": "done"}

    async def _plan(self, task: str, history: list[dict] | None = None, summary: str = "") -> AsyncIterator[dict[str, Any]]:
        from src.agent.prompts.system_prompt import SUPERVISOR_PROMPT_TEMPLATE
        cm = get_config_manager()
        agents_config = cm.get_agents()
        desc_lines, names = [], []
        for agent_id, cfg in agents_config.items():
            if agent_id == "supervisor" or not cfg.get("enabled", True):
                continue
            desc = cfg.get("desc", "")
            names.append(agent_id)
            desc_lines.append(f"- **{agent_id}**: {desc}" if desc else f"- **{agent_id}**")
        if "direct" not in names:
            names.append("direct")
            desc_lines.append("- **direct**: Direct reply for simple/single-step tasks")
        prompt = SUPERVISOR_PROMPT_TEMPLATE.format(
            agent_descriptions="\n".join(desc_lines), agent_names=", ".join(names),
        )
        yield {"type": "thinking_start", "agent_name": "supervisor"}
        system_content = prompt
        if summary:
            system_content += f"\n\n[Previous Conversation Summary]\n{summary}"
        messages = [{"role": "system", "content": system_content}]
        if history:
            for msg in history:
                role = "user" if msg.get("role") == "human" else "assistant"
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")
                if content or tool_calls:
                    text = content
                    if tool_calls:
                        calls_text = "; ".join(
                            f"{tc['name']}({json.dumps(tc.get('args', {}), ensure_ascii=False)})" for tc in tool_calls
                        )
                        text = (text + "\n") if text else ""
                        text += f"\n[Tool calls: {calls_text}]"
                    messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": task})
        plan_text = ""
        async for chunk in self.model.astream(messages):
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                yield {"type": "thinking", "data": reasoning, "agent_name": "supervisor"}
            if chunk.content:
                plan_text += chunk.content
        yield {"type": "thinking_done", "agent_name": "supervisor"}
        yield {"type": "plan", "data": plan_text, "agent_name": "supervisor"}

    async def _execute_step(self, agent_id: str, task: str, previous_results: list[dict[str, str]]) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "task_update", "data": {"agent": agent_id, "task": task, "status": "running"}, "agent_name": "supervisor"}
        agent_content = ""
        if agent_id in self.acp_agents:
            from src.agent.acp_agent import get_acp_agent
            acp = get_acp_agent(self.acp_agents[agent_id])
            context = ""
            if previous_results:
                context = "Previous results:\n" + "\n".join(f"- {r['agent']}: {r['result'][:200]}" for r in previous_results)
            async for event in acp.run(task, context=context):
                event["agent_name"] = agent_id
                yield event
                if event["type"] == "message":
                    chunk = event.get("data", "")
                    if chunk:
                        if is_punctuation_only(chunk.strip()) and len(agent_content.strip()) > 20:
                            continue
                        agent_content += chunk
                elif event["type"] == "error":
                    agent_content = f"Error: {event.get('data', '')}"
            stripped = agent_content.strip()
            if stripped and not is_punctuation_only(stripped):
                yield {"type": "message", "data": agent_content, "agent_name": agent_id}
            elif not stripped:
                yield {"type": "message", "data": f"by {agent_id} done", "agent_name": agent_id}
            return
        graph = self.sub_agents.get(agent_id)
        if graph is None:
            agent_content = f"Unknown agent: {agent_id}"
            yield {"type": "message", "data": agent_content, "agent_name": agent_id}
            return
        try:
            async for event in graph.astream_events({"messages": [HumanMessage(content=task)]}, version="v2"):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    reasoning = chunk.additional_kwargs.get("reasoning_content")
                    if reasoning:
                        yield {"type": "thinking", "data": reasoning, "agent_name": agent_id}
                    elif chunk.content:
                        agent_content += chunk.content
                elif kind == "on_tool_start":
                    yield {"type": "tool_call", "data": [{"name": event["name"], "args": event["data"].get("input", {})}], "agent_name": agent_id}
        except Exception as e:
            logger.error("[Orchestrator] agent %s error: %s", agent_id, e)
            agent_content = f"Agent error: {e}"
        stripped = agent_content.strip()
        if stripped and not is_punctuation_only(stripped):
            yield {"type": "message", "data": agent_content, "agent_name": agent_id}
        elif not stripped:
            yield {"type": "message", "data": f"by {agent_id} done", "agent_name": agent_id}

    @staticmethod
    def _clean_direct_response(task: str) -> str:
        for prefix in [
            "Reply to user: ", "Reply: ", "Answer: ",
        ]:
            if task.startswith(prefix):
                return task[len(prefix):]
        return task

    @staticmethod
    def _parse_plan(plan_text: str, valid_agents: set[str]) -> list[dict[str, str]]:
        results = []
        for m in _PLAN_RE.finditer(plan_text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            if agent_name in valid_agents:
                results.append({"agent": agent_name, "task": task})
        return results
