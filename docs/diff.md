# 项目差异文档 — langgraph-agent-v2

> 完整差异：基于 `diff/langgraph-agent-v2-main` 备份 → 当前项目。
> 另一 AI agent 可据此将备份逐步修改至当前状态。

## 文件变更总览

| 文件                                         | 变化                                    |
| -------------------------------------------- | --------------------------------------- |
| `src/agent/supervisor.py`                    | ❌ 删除，重构为 orchestrator.py          |
| `src/agent/graph.py`                         | ❌ 删除                                  |
| `src/agent/orchestrator.py`                  | ✨ 新增 — 替代 supervisor.py + graph.py  |
| `src/agent/message.py`                       | ✨ 新增 — Message 数据类                 |
| `src/agent/_utils.py`                        | ✨ 新增 — 共享工具函数                   |
| `server.py`                                  | 🔄 重构 — 导入、SSE 转发、端点、摘要注入 |
| `src/agent/checkpoint.py`                    | 🔄 修改 — Message 类化、去重、keep 参数  |
| `src/agent/context/compression.py`           | 🔄 修改 — force 参数、extract_turns      |
| `ui/src/utils/messageManager.ts`             | ✨ 新增 — 消息管理 composable            |
| `ui/src/stores/chat.ts`                      | 🔄 重构 — 委托 messageManager            |
| `ui/src/utils/api.ts`                        | 🔄 扩展 — 类型 + API 函数                |
| `ui/src/components/AgentTaskPanel.vue`       | ✨ 新增 — 任务状态面板                   |
| `ui/src/components/DirectoryTreeBrowser.vue` | ✨ 新增 — 文件树浏览                     |
| `config/acp_agents.json`                     | ✨ 新增                                  |
| `config/tools.json`                          | ✨ 新增                                  |
| `config/skills.json`                         | ✨ 新增                                  |
| `.env.example`                               | 🔄 修改 — 新增注释                       |
| `pyproject.toml`                             | 🔄 修改 — 新增 httpx, aiofiles           |

---

# 第一部分：新增文件（完整源码）

以下文件需从零创建。将代码块内容直接写入对应路径。

---

## 1. `src/agent/message.py`

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


@dataclass
class Message:
    role: str
    content: str = ''
    thinking: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    compacted: bool = False
    id: Optional[int] = None
    session_id: Optional[str] = None
    created_at: Optional[str] = None

    def to_langchain(self) -> BaseMessage:
        if self.role == 'human':
            return HumanMessage(content=self.content)
        if self.role == 'ai':
            extra: dict[str, Any] = {}
            if self.tool_calls:
                extra['tool_calls'] = self.tool_calls
            return AIMessage(
                content=self.content, additional_kwargs=extra,
                id=self.tool_call_id, name=self.name,
            )
        if self.role == 'tool':
            return ToolMessage(
                content=self.content, tool_call_id=self.tool_call_id or '', name=self.name,
            )
        return HumanMessage(content=self.content)

    @classmethod
    def from_langchain(cls, msg: BaseMessage) -> Message:
        if isinstance(msg, HumanMessage):
            return cls(role='human', content=msg.content)
        if isinstance(msg, AIMessage):
            return cls(
                role='ai', content=msg.content,
                tool_calls=msg.additional_kwargs.get('tool_calls'),
                tool_call_id=msg.id, name=msg.name,
            )
        if isinstance(msg, ToolMessage):
            return cls(
                role='tool', content=msg.content,
                tool_call_id=msg.tool_call_id, name=msg.name,
            )
        return cls(role='human', content=msg.content)

    def to_frontend_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {'type': self.role, 'content': self.content or ''}
        if self.thinking:
            d['thinking'] = self.thinking
        if self.tool_calls:
            d['tool_calls'] = self.tool_calls
        if self.name:
            d['name'] = self.name
        if self.compacted:
            d['compacted'] = True
        if self.id is not None:
            d['id'] = self.id
        if self.session_id is not None:
            d['session_id'] = self.session_id
        if self.created_at is not None:
            d['created_at'] = self.created_at
        return d

    @classmethod
    def from_frontend_dict(cls, d: dict[str, Any]) -> Message:
        role = d.get('type') or d.get('role', 'human')
        return cls(
            role=role, content=d.get('content', ''),
            thinking=d.get('thinking'), tool_calls=d.get('tool_calls'), name=d.get('name'),
        )

    @classmethod
    def from_db_row(cls, row) -> Message:
        role, content, tool_calls_json, tool_call_id, name = row
        tool_calls = None
        if tool_calls_json:
            try:
                tool_calls = json.loads(tool_calls_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls(role=role, content=content, tool_calls=tool_calls, tool_call_id=tool_call_id, name=name)

    @classmethod
    def from_db_row_verbose(cls, row) -> Message:
        role, content, thinking, tool_calls_json, compacted, name, msg_id, session_id, created_at = (
            row if len(row) >= 9 else (*row, None, None, None)
        )
        tool_calls = None
        if tool_calls_json:
            try:
                tool_calls = json.loads(tool_calls_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls(
            id=msg_id, session_id=session_id, created_at=created_at,
            role=role, content=content, thinking=thinking,
            tool_calls=tool_calls, name=name, compacted=bool(compacted),
        )

    def to_db_params(self) -> tuple[str, str, str, str, str]:
        return (
            self.role, self.content,
            json.dumps(self.tool_calls, ensure_ascii=False) if self.tool_calls else '',
            self.thinking or '', self.name or '',
        )
```

---

## 2. `src/agent/_utils.py`

```python
import re
from typing import Any

_FILE_PATH_RE = re.compile(r'(?:src|docs|tests|ui|memory|config|skills)[/\\][\w./\\-]+\.\w+')
_CODE_FILE_RE = re.compile(r'[\w-]+\.(?:py|ts|js|vue|html|json|md|toml|yaml)')

def extract_file_refs(text: str) -> list[str]:
    refs = set(_FILE_PATH_RE.findall(text))
    refs.update(_CODE_FILE_RE.findall(text))
    return sorted(refs)

def is_punctuation_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return all(c in ".,!?;:。！？；：、 \n\t...\xb7" for c in stripped)

SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
```

---

## 3. `src/agent/orchestrator.py`

```python
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
```

---

## 4. `ui/src/utils/messageManager.ts`

```typescript
import { ref, type Ref } from 'vue'
import type { ChatMessage } from './api'

export function useMessageManager() {
  const messages: Ref<ChatMessage[]> = ref([])

  function addUser(content: string): number {
    messages.value.push({ role: 'user', content })
    return messages.value.length - 1
  }

  function addSystem(content: string): number {
    messages.value.push({ role: 'system', content })
    return messages.value.length - 1
  }

  function addAssistant(agentName: string, opts?: {
    content?: string; thinking?: string; isThinking?: boolean;
    toolCalls?: any[]; planContent?: string
  }): number {
    const msg: ChatMessage = { role: 'assistant', content: opts?.content || '', agentName }
    if (opts?.thinking) msg.thinking = opts.thinking
    if (opts?.isThinking) msg.isThinking = true
    if (opts?.toolCalls) msg.toolCalls = opts.toolCalls
    if (opts?.planContent) msg.planContent = opts.planContent
    messages.value.push(msg)
    return messages.value.length - 1
  }

  function findAssistant(agentName: string): number {
    return messages.value.findLastIndex(m => m.role === 'assistant' && m.agentName === agentName)
  }

  function ensureAssistant(agentName: string): number {
    const idx = findAssistant(agentName)
    if (idx >= 0) return idx
    return addAssistant(agentName)
  }

  function appendContent(agentName: string, text: string): void {
    const idx = ensureAssistant(agentName)
    messages.value[idx].content = (messages.value[idx].content || '') + text
  }

  function appendThinking(agentName: string, text: string): void {
    const idx = ensureAssistant(agentName)
    messages.value[idx].thinking = (messages.value[idx].thinking || '') + text
  }

  function setThinking(agentName: string, isThinking: boolean): void {
    const idx = ensureAssistant(agentName)
    messages.value[idx].isThinking = isThinking
  }

  function resetThinking(agentName: string): void {
    const idx = ensureAssistant(agentName)
    messages.value[idx].thinking = ''
    messages.value[idx].isThinking = true
  }

  function mergeToolCalls(agentName: string, toolCalls: any[]): void {
    const prev = messages.value[messages.value.length - 1]
    if (prev && prev.role === 'assistant' && prev.agentName === agentName) {
      prev.toolCalls = [...(prev.toolCalls || []), ...toolCalls]
    } else {
      messages.value.push({ role: 'assistant', content: '', toolCalls, agentName })
    }
  }

  function addSummary(agentName: string, content: string): void {
    messages.value.push({ role: 'summary', content, agentName })
  }

  function addError(content: string): void {
    messages.value.push({ role: 'system', content: `[Error: ${content}]` })
  }

  function appendError(agentName: string, error: string): void {
    const idx = ensureAssistant(agentName)
    messages.value[idx].content = (messages.value[idx].content || '') + `\n\n[Error: ${error}]`
  }

  function setPlanContent(agentName: string, planContent: string): void {
    const idx = ensureAssistant(agentName)
    messages.value[idx].planContent = planContent
  }

  function transformHistory(raw: any[]): ChatMessage[] {
    const result: ChatMessage[] = []
    let lastPlan: ChatMessage | null = null
    for (const m of raw) {
      const role = m.type === 'ai' ? 'assistant' : m.type === 'human' ? 'user' : m.type
      const agentName = m.name || undefined
      if (m.name === 'plan') {
        result.push({ role: 'assistant', content: m.content || '', agentName: 'plan' })
        lastPlan = result[result.length - 1]
        continue
      }
      if (lastPlan && m.name === 'supervisor') {
        lastPlan.planContent = lastPlan.content
        lastPlan.content = m.content || ''
        lastPlan.agentName = 'supervisor'
        lastPlan.thinking = m.thinking || undefined
        lastPlan = null
        continue
      }
      if (lastPlan) lastPlan = null
      const prev = result.length > 0 ? result[result.length - 1] : null
      const isSameAgent = prev && prev.agentName === agentName && prev.role === role
      if (isSameAgent && m.tool_calls) {
        prev.toolCalls = [...(prev.toolCalls || []), ...m.tool_calls]; continue
      }
      if (isSameAgent && !prev.content && m.content) {
        prev.content = m.content || ''; continue
      }
      const chatMsg: ChatMessage = { role, content: m.content || '', agentName }
      if (m.thinking) chatMsg.thinking = m.thinking
      if (m.tool_calls) chatMsg.toolCalls = m.tool_calls
      result.push(chatMsg)
    }
    return result
  }

  function restore(raw: any[]): void { messages.value = transformHistory(raw) }
  function clear(): void { messages.value = [] }
  function removeSystem(prefix: string): void {
    messages.value = messages.value.filter(m => !(m.role === 'system' && m.content.startsWith(prefix)))
  }

  return {
    messages,
    addUser, addSystem, addAssistant, ensureAssistant, findAssistant,
    appendContent, appendThinking, setThinking, resetThinking,
    mergeToolCalls, addSummary, addError, appendError, setPlanContent,
    transformHistory, restore, clear, removeSystem,
  }
}
```

---

## 5. `ui/src/components/AgentTaskPanel.vue`

```vue
<script setup lang="ts">
import { computed } from 'vue'
import ConvAvatar from './ConvAvatar.vue'
import type { TaskUpdate, MetricsData } from '../utils/api'

const props = defineProps<{ tasks: TaskUpdate[]; metrics: MetricsData | null }>()

const AGENT_COLORS: Record<string, string> = {
  supervisor: '#818cf8', coder: '#34d399', researcher: '#fbbf24',
  analyst: '#fb7185', writer: '#f472b6', direct: '#60a5fa',
  helper: '#a78bfa', opencode: '#059669', 'claude-agent': '#d97706',
}
function color(agent: string): string { return AGENT_COLORS[agent] || 'var(--accent)' }
function formatElapsed(ms?: number): string {
  if (!ms || ms < 0) return ''
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60); const sec = s % 60
  if (m < 60) return `${m}m${sec.toString().padStart(2, '0')}s`
  const h = Math.floor(m / 60); const min = m % 60
  return `${h}h${min.toString().padStart(2, '0')}m${sec.toString().padStart(2, '0')}s`
}
const STATUS_LABELS: Record<string, string> = { pending: 'pending', running: 'running', completed: 'completed', failed: 'failed' }
function anim(t: TaskUpdate): 'breathe' | 'think' | 'work' {
  if (t.status === 'running') return 'work'
  if (t.status === 'pending') return 'think'
  return 'breathe'
}
function agentTokens(agent: string): { input: number; output: number } | null {
  if (!props.metrics?.tokens) return null
  const t = props.metrics.tokens[agent]
  return t ?? null
}
</script>

<template>
  <div class="agent-task-panel">
    <div v-for="(t, i) in tasks" :key="`${t.agent}::${t.task}::${i}`"
      :class="['task-row', t.status, t.state || '']"
      :style="{ '--agent-color': color(t.agent) }">
      <div class="task-avatar"><ConvAvatar :type="t.agent" :size="24" :animated="anim(t)" /></div>
      <div class="task-info">
        <div class="task-name-row">
          <span class="task-agent-name" :style="{ color: color(t.agent) }">{{ t.agent }}</span>
          <span v-if="t.elapsedMs" class="task-elapsed">{{ formatElapsed(t.elapsedMs) }}</span>
        </div>
        <div class="task-bar"><div :class="['task-bar-fill', t.status]"></div></div>
        <div class="task-meta-row">
          <span :class="['task-status', t.status]">{{ STATUS_LABELS[t.status] || t.status }}</span>
          <span v-if="agentTokens(t.agent)" class="task-tokens">
            {{ agentTokens(t.agent)!.input.toLocaleString() }} in &middot; {{ agentTokens(t.agent)!.output.toLocaleString() }} out
          </span>
        </div>
      </div>
    </div>
    <div v-if="tasks.length === 0" class="task-empty">No tasks</div>
  </div>
</template>

<style scoped>
.agent-task-panel { display: flex; flex-direction: column; gap: 2px; padding: 4px 0; }
.task-row { display: flex; align-items: flex-start; gap: 10px; padding: 8px 12px; font-size: 12px; color: var(--text-secondary); border-left: 3px solid transparent; transition: all 0.25s; }
.task-row.running { background: color-mix(in srgb, var(--agent-color, var(--accent)) 8%, transparent); border-left-color: var(--agent-color, var(--accent)); }
.task-row.completed { border-left-color: var(--color-green); }
.task-row.failed { border-left-color: var(--color-red); }
.task-avatar { width: 24px; height: 24px; flex-shrink: 0; margin-top: 2px; }
.task-info { flex: 1; min-width: 0; }
.task-name-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.task-agent-name { font-weight: 600; font-size: 12px; }
.task-elapsed { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 10px; color: var(--text-faint); flex-shrink: 0; }
.task-bar { height: 3px; background: var(--border-light); border-radius: 2px; overflow: hidden; margin: 4px 0; }
.task-bar-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }
.task-bar-fill.running { width: 70%; background: var(--agent-color, var(--accent)); animation: barPulse 1.2s ease-in-out infinite; }
.task-bar-fill.completed { width: 100%; background: var(--color-green); }
.task-bar-fill.failed { width: 30%; background: var(--color-red); }
@keyframes barPulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
.task-meta-row { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.task-status { font-size: 10px; padding: 1px 6px; border-radius: 3px; background: var(--bg-card); }
.task-status.running { color: var(--agent-color, var(--accent)); font-weight: 600; }
.task-status.completed { color: var(--color-green); }
.task-status.failed { color: var(--color-red); }
.task-status.pending { color: var(--text-faint); }
.task-tokens { font-size: 10px; color: var(--text-faint); font-family: 'SF Mono', 'Fira Code', monospace; }
.task-empty { font-size: 12px; color: var(--text-faint); padding: 16px; text-align: center; }
</style>
```

---

# 第二部分：已有文件变更

## 6. `server.py` 修改要点

### 6.1 导入变化

```python
# 新增
from src.agent._utils import SSE_HEADERS, is_punctuation_only
from src.agent.orchestrator import Orchestrator   # 替代旧的 CustomSupervisor

# 删除
from src.agent.event_bus import event_bus          # 删除
from src.agent.supervisor import CustomSupervisor  # 删除

# checkpoint 导入新增
update_session_project_path,    # 新增
from src.agent.checkpoint import (
    load_messages, save_message, delete_task_updates_for_sessions,
    update_acp_session_id, get_tool_usage_stats,
    list_agents, get_agent, upsert_agent, delete_agent,
    list_clis, get_cli, upsert_cli, delete_cli,
)
```

### 6.2 全局单例替换

```python
# 旧
supervisor_instance: CustomSupervisor | None = None
def get_supervisor() -> CustomSupervisor:
    ...

# 新
orchestrator_instance: Orchestrator | None = None
def get_supervisor() -> Orchestrator:
    global orchestrator_instance
    if orchestrator_instance is None:
        orchestrator_instance = Orchestrator(config)
    return orchestrator_instance
```

### 6.3 `_passthrough()` 简化 batching（server.py ~Line 172）

旧版维护 `thinking_meta` / `message_meta` 两本 dict；新版只保留 `t_buf` / `m_buf` 简单字符串缓冲。

**SSE headers：** 所有 `StreamingResponse` 使用 `headers=SSE_HEADERS`（来自 `_utils.py`），而非重复内联。

### 6.4 SSE DB 持久化重构（server.py `stream()` ~Line 350-440）

**变化核心：** 从两阶段（`_message_accum` + `_flush_message()`）改为实时持久化：

```python
# 旧方案
_message_accum = ""
def _flush_message():
    if _message_accum:
        save_message(session_id, "ai", _message_accum, thinking=..., name=agent_name)

# 新方案 — 每种事件类型独立持久化
async for event in _passthrough(supervisor.run(request.task, history=history or None, summary=session_summary)):
    etype = event.get("type", "")
    if etype == "message":
        chunk = event.get("data", "")
        _message_accum += chunk
    elif etype == "thinking":
        _thinking_accum += event.get("data", "")
        yield payload; continue
    elif etype == "thinking_done":
        _save_accumulated()   # 攒够才写 DB
    elif etype == "plan":
        save_message(session_id, "ai", event.get("data", ""), name="plan")
    elif etype == "tool_call":
        tcs = event.get("data", [])
        if tcs:
            save_message(session_id, "ai", "", tool_calls=json.dumps(tcs), name=agent_name)
    elif etype == "summary":
        save_message(session_id, "ai", event.get("data", ""), name="summary")
    elif etype == "metrics":
        save_metrics(session_id, json.dumps(event["data"]))
    yield payload
_save_accumulated()
```

### 6.5 `/api/compact` — force + keep

```python
# 旧
summary_text, recent = await compressor.compress(history, llm=get_agent().model)
marked = db_compact_session(request.session_id, summary_text)

# 新
summary_text, recent = await compressor.compress(history, llm=get_agent().model, force=True)
marked = db_compact_session(request.session_id, summary_text, keep=1)
```

### 6.6 `/api/sessions/{id}` 返回新字段

```python
return {
    ...
    "summary": summary,        # 新增
    "task_phases": [],         # 新增
}
```

### 6.7 `/api/orchestrate` — session_summary 注入

```python
session_summary = get_session_summary(session_id)
...
async for event in _passthrough(supervisor.run(
    request.task, history=history or None, summary=session_summary
)):
```

### 6.8 删除 `/api/events/stream/{stream_id}` SSE 端点

旧版有独立 SSE event_bus 端点，整个 `event_bus.py` 逻辑删除。所有 SSE 仅通过 `/chat`, `/orchestrate`, `/acp/run` 端点输出。

### 6.9 新增端点清单

| 端点                                    | 用途                 |
| --------------------------------------- | -------------------- |
| `PATCH /api/sessions/{id}/title`        | 重命名会话           |
| `PATCH /api/sessions/{id}/project-path` | 更新项目路径         |
| `DELETE /api/sessions/{id}`             | 删除会话             |
| `GET /api/files/tree`                   | 文件树浏览           |
| `POST /api/files/pick-directory`        | Windows 文件夹选择器 |
| `POST /api/files/validate-directory`    | 校验目录可访问       |
| `GET /api/files/browse`                 | 目录递归浏览         |
| `GET /api/files/drives`                 | Windows 驱动器列表   |
| `GET /api/files/content`                | 文件内容读取         |
| `POST /api/config/reload`               | 热重载配置           |
| `GET /api/skills`                       | 技能列表             |
| `GET /api/tools`                        | 工具列表             |
| `GET /api/acp/agents`                   | ACP agent 列表       |
| `GET /api/acp/check/{id}`               | ACP 可用性检查       |
| `GET /api/acp/sessions/{id}`            | ACP session 列表     |
| `GET/POST/DELETE /api/agents/{id}`      | Agent CRUD           |
| `GET/POST/DELETE /api/acp/config/{id}`  | ACP 配置 CRUD        |
| `POST /api/memory/store`                | 记忆存储             |
| `POST /api/memory/query`                | 记忆查询             |
| `GET /api/memory/list/{ns}`             | 记忆列表             |
| `DELETE /api/memory/{ns}/{key}`         | 记忆删除             |

---

## 7. `src/agent/checkpoint.py` 修改

### 7.1 核心变化：引入 Message 类

```python
# 旧
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

# 新
from langchain_core.messages import BaseMessage
from src.agent.message import Message
```

### 7.2 删除的函数

```python
_serialize_message(msg: BaseMessage) -> dict      # Message.to_db_params() 替代
_deserialize_message(row) -> BaseMessage           # Message.from_db_row().to_langchain() 替代
create_session(user_id, title, project_path)       # 简化为 create_session(title, project_path)
_seed_default_agents(conn)                         # 删除 DB 种子数据
_seed_default_clis(conn)                           # 删除 DB 种子数据
list_agents(), get_agent(), upsert_agent(), delete_agent()  # 删除 DB CRUD
list_clis(), get_cli(), upsert_cli(), delete_cli()          # 删除 DB CRUD
```

### 7.3 新增函数

```python
def load_messages(session_id) -> list[Message]          # 返回 Message 对象列表
def rename_session(session_id, title)                    # 独立重命名
def update_session_project_path(session_id, path)        # 更新项目路径
def delete_task_updates_for_sessions(session_ids)        # 批量删除
```

### 7.4 修改函数

**`load_history()` / `load_messages()` / `load_history_with_meta()`**
```python
# 旧
rows = conn.execute(...)
return [_deserialize_message(row) for row in rows]

# 新 — 通过 Message 类转换
rows = conn.execute(...)
return [Message.from_db_row(row).to_langchain() for row in rows]
```
`load_history_with_meta()` 使用 `from_db_row_verbose()` + `to_frontend_dict()`.

**`save_turn()` / `save_message()`**
```python
# 旧：手动构造 SQL params
conn.execute("INSERT ... (?, ?, ?, ?, ?, ?)", (session_id, role, content, thinking, tool_calls, name))

# 新：委托 Message.to_db_params()
msg = Message(role=role, content=content, thinking=thinking or None, name=name or None)
if tool_calls:
    msg.tool_calls = json.loads(tool_calls) if isinstance(tool_calls, str) else tool_calls
conn.execute("INSERT ... (?, ?, ?, ?, ?, ?)", (session_id, *msg.to_db_params()))
```

**`load_task_updates()`** — 去重
```sql
-- 旧
SELECT agent, task, status, state, started_at, ended_at, elapsed_ms
FROM task_updates WHERE session_id = ? ORDER BY id

-- 新
SELECT agent, task, status, state, started_at, ended_at, elapsed_ms
FROM task_updates
WHERE session_id = ?
  AND id IN (SELECT MAX(id) FROM task_updates WHERE session_id = ? GROUP BY agent, task)
ORDER BY id
```

**`compact_session()`** — 新增 keep 参数
```python
def compact_session(session_id: str, summary: str, keep: int | None = None) -> int:
    keep = _KEEP_RECENT if keep is None else keep
    if total <= keep:
        ...  # 保存 summary，返回 0
```

**`delete_session()`** — 级联删除
```python
def delete_session(session_id):
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM task_updates WHERE session_id = ?", (session_id,))  # 新增
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
```

### 7.5 DB schema 变化

`sessions` 表新增可迁移列：`user_id TEXT`, `title TEXT`, `summary TEXT`, `compacted_at TIMESTAMP`, `status TEXT DEFAULT 'active'`, `acp_session_id TEXT`, `project_path TEXT`, `metrics TEXT`, `duration_ms INTEGER DEFAULT 0`。

原始备份已通过 auto-migrate 添加了对照列；当前版本使用逐列 `ALTER TABLE` 代替批量 auto-migrate。

---

## 8. `src/agent/context/compression.py` 修改

### 8.1 核心变化：turn-based 压缩

```python
# 旧
self.keep_recent = 5                    # 保留 5 条消息

# 新
self.keep_recent_turns = 3              # 保留 3 轮（human+ai 配对）

@staticmethod
def extract_turns(messages) -> list[list[BaseMessage]]:
    """按 HumanMessage -> AIMessage 配对分轮次"""
```

### 8.2 `compress()` 新增 `force` 参数

```python
async def compress(self, messages, llm=None, force=False) -> tuple[str, list[BaseMessage]]:
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]
    if not non_system:
        return "", system_msgs
    turns = self.extract_turns(non_system)
    if not force and len(turns) <= self.keep_recent_turns:  # force 跳过守卫
        return "", system_msgs + non_system
    old_turns = turns[:-self.keep_recent_turns]
    recent_turns = turns[-self.keep_recent_turns:]
    summary = await self._summarize(...)
    return summary, system_msgs + recent_msgs
```

### 8.3 `should_compress()` 新增阈值判断

```python
def should_compress(self, messages):
    token_count = count_tokens(messages)
    return token_count > int(self.max_tokens * self.threshold)
```

---

## 9. 前端修改

### 9.1 `ui/src/stores/chat.ts`

**重构：** 约 150 行内联消息管理逻辑抽取到 `messageManager.ts`。SSE 事件处理全部委托：

| 旧操作                     | 新调用                               |
| -------------------------- | ------------------------------------ |
| `messages.value.push(...)` | `msg.addUser() / msg.addAssistant()` |
| 内联查找 assistant         | `msg.ensureAssistant()`              |
| `m.content += chunk`       | `msg.appendContent()`                |
| 内联 thinking              | `msg.appendThinking()`               |
| 内联 tool_calls            | `msg.mergeToolCalls()`               |
| restore 逻辑               | `msg.restore()`                      |
| clear                      | `msg.clear()`                        |

**SSE 事件映射：**
```
thinking_start  → msg.resetThinking(agentName)
thinking        → msg.appendThinking(agentName, chunk)
thinking_done   → msg.setThinking(agentName, false)
message         → msg.appendContent(agentName, chunk)
tool_call       → msg.mergeToolCalls(agentName, tcs)
plan            → msg.setPlanContent(agentName, plan)
summary         → msg.addSummary(agentName, summary)
error           → msg.appendError(agentName, error)
done / abort    → msg.setThinking(agentName, false)
```

### 9.2 `ui/src/utils/api.ts`

**新增接口类型：**
```typescript
interface TaskUpdate { agent, task, status, state?, started_at?, ended_at?, elapsed_ms?, elapsedMs? }
interface TaskPhaseUpdate { phase, status, agent?, timestamp, step?, totalSteps?, description? }
interface MetricsData { elapsed_ms, agent_calls, tokens: Record<string, {input, output, ms?}> }
interface CompactResult { session_id, summary, deleted_messages, kept_messages }
```

**新增 API 函数：**
```typescript
compactSession(sessionId): Promise<CompactResult>
restoreSession(sessionId): Promise<{messages, task_updates, metrics, summary}>
```

### 9.3 `ui/src/components/ChatMessage.vue`

- 支持 `thinking` 块显示（可折叠）
- 支持 `toolCalls` 内联显示
- 支持多 agent 名称标签
- 支持 `planContent` 和 `summary` 类型消息

### 9.4 `ui/src/components/MonitorPanel.vue`

- 集成 `AgentTaskPanel` 子组件
- 增加 Token 消耗统计区域
- 任务状态面板（右侧）

### 9.5 `ui/src/components/InputBar.vue`

- 新增 slash command 处理：
  - `/compact` → 调用 `compactSession()`
  - `/clear` → 清空当前会话消息
  - `/new` → 创建新会话

### 9.6 `Sidebar.vue`

- 会话列表增加执行状态标记（processing / completed）
- session_id 显示支持

### 9.7 `DirectoryTreeBrowser.vue` (新增)

完整文件浏览组件：
- 驱动器列表 → 目录树递归加载
- 面包屑导航
- 搜索过滤
- 目录/文件选择回调

---

## 10. `pyproject.toml` 依赖变更

```toml
# 新增
httpx
aiofiles
```

---

# 恢复步骤

```bash
# 1. 从备份复制基础
cp -r diff/langgraph-agent-v2-main/* .

# 2. 删除不再使用的文件
rm src/agent/supervisor.py src/agent/graph.py

# 3. 创建新增文件（源码见第一部分）
# src/agent/message.py           ← 第 1 节
# src/agent/_utils.py             ← 第 2 节
# src/agent/orchestrator.py       ← 第 3 节
# ui/src/utils/messageManager.ts  ← 第 4 节
# ui/src/components/AgentTaskPanel.vue  ← 第 5 节
# ui/src/components/DirectoryTreeBrowser.vue
# config/acp_agents.json          ← 空 []
# config/tools.json               ← 空 []
# config/skills.json              ← 空 []

# 4. 修改已有文件（按第二部分逐节操作）
# server.py                       ← 第 6 节
# src/agent/checkpoint.py         ← 第 7 节
# src/agent/context/compression.py ← 第 8 节
# ui/src/stores/chat.ts           ← 第 9.1 节
# ui/src/utils/api.ts             ← 第 9.2 节
# ui/src/components/*.vue         ← 第 9.3-9.7 节

# 5. 安装依赖
pip install -e ".[dev]"
cd ui && npm install

# 6. 验证
cd ..
pytest --cov=src -v
ruff check .
```