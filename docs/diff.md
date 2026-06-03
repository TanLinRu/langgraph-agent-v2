# 项目差异文档 — langgraph-agent-v2

> 完整差异：基于 `diff/langgraph-agent-v2-main` 备份 → 当前项目。
> 另一 AI agent 可据此将备份逐步修改至当前状态。

## 文件变更总览

### 后端

| 文件                                                   | 变化                                    |
| ------------------------------------------------------ | --------------------------------------- |
| `src/agent/supervisor.py`                              | ❌ 删除，重构为 orchestrator 包          |
| `src/agent/graph.py`                                   | ❌ 删除                                  |
| `src/agent/event_bus.py`                               | ❌ 删除                                  |
| `src/agent/state.py`                                   | ❌ 删除（死代码）                         |
| `src/agent/orchestrator/`（NEW 包）                     | ✨ 替代 supervisor + graph               |
| `src/agent/orchestrator/__init__.py`                   | ✨ 重新导出 Orchestrator/Planner/Dispatcher |
| `src/agent/orchestrator/core.py`                       | ✨ Orchestrator 类（plan→dispatch→summarize） |
| `src/agent/orchestrator/planner.py`                    | ✨ Planner 类（prompt 构造 + plan 解析）  |
| `src/agent/orchestrator/dispatcher.py`                 | ✨ LocalDispatcher + ACPDispatcher 工厂  |
| `src/agent/orchestrator/summarizer.py`                 | ✨ 多 agent 结果汇总流                   |
| `src/agent/orchestrator/_events.py`                    | ✨ 便捷重导出 events.py                  |
| `src/agent/events.py`                                  | ✨ 统一事件协议：EventType + make_event 工厂 |
| `src/agent/message.py`                                 | ✨ Message 数据类（dataclass, to_langchain） |
| `src/agent/_utils.py`                                  | ✨ 共享工具函数（extract_file_refs, SSE_HEADERS） |
| `src/agent/checkpoint.py`                              | ❌ 删除，重构为 db/ 包                   |
| `src/agent/db/`（NEW 包）                               | ✨ 替代 checkpoint.py                    |
| `src/agent/db/__init__.py`                             | ✨ 重新导出所有 CRUD 函数                |
| `src/agent/db/connection.py`                           | ✨ 连接管理 + schema 自动迁移（4 表）    |
| `src/agent/db/sessions.py`                             | ✨ 会话 CRUD（create/delete/list/rename）|
| `src/agent/db/messages.py`                             | ✨ 消息 CRUD（save/load/history/compact）|
| `src/agent/db/tasks.py`                                | ✨ 任务更新 CRUD（去重 GROUP BY）        |
| `src/agent/db/tools.py`                                | ✨ 工具使用统计 + 指标持久化             |
| `src/agent/db/compact.py`                              | ✨ compact_session（keep 参数）          |
| `src/agent/agent/`（NEW 包）                            | ✨ 替代单文件 agent.py                   |
| `src/agent/agent/__init__.py`                          | ✨ 重新导出 Agent                       |
| `src/agent/agent/core.py`                              | ✨ Agent ReAct 循环（astream_events 解析）|
| `src/agent/agent/streaming.py`                         | ✨ extract_file_refs 工具               |
| `src/agent/orchestrator.py`（旧）                       | ❌ 已拆分为 orchestrator/ 包             |
| `src/agent/agent.py`（旧）                              | ❌ 已拆分为 agent/ 包                    |
| `server.py`                                            | 🔄 重构 — 导入路径、SSE 转发、端点      |
| `src/agent/acp_agent.py`                               | 🔄 更新导入路径（from src.agent.db ...）|
| `src/agent/main.py`                                    | 🔄 更新导入路径                          |
| `src/agent/context/compression.py`                      | 🔄 修改 — turn-based, force 参数        |
| `tests/test_event_bus.py`                              | ❌ 删除（5 个已删除模块的测试）           |
| `tests/test_supervisor.py`                             | 🔄 完全重写 — 14 个 Orchestrator 测试    |
| `tests/test_server.py`                                 | 🔄 更新 — orchestrator_instance + 2 新测试 |
| `tests/test_mock_flow.py`                              | 🔄 更新 — turn-based 压缩断言            |

### 前端

| 文件                                                         | 变化                                        |
| ------------------------------------------------------------ | ------------------------------------------- |
| `ui/src/utils/api.ts`                                        | 🔄 改为 barrel，重新导出 api/ 子模块        |
| `ui/src/utils/api/types.ts` (NEW)                            | ✨ 类型定义文件（ChatMessage, TaskUpdate 等）|
| `ui/src/utils/api/endpoints.ts` (NEW)                        | ✨ REST 端点函数（fetchAgents, listSessions 等）|
| `ui/src/utils/api/sse.ts` (NEW)                              | ✨ SSE 流式通信（streamChatCallbacks, streamOrchestrate）|
| `ui/src/utils/messageManager.ts`                             | ✨ 消息管理 composable（add/append/merge/restore）|
| `ui/src/utils/streamManager.ts`                              | ✨ 流管理 composable（3 send paths + abort + typewriter）|
| `ui/src/utils/useMarkdown.ts` (NEW)                          | ✨ Markdown + KaTeX 渲染 composable          |
| `ui/src/stores/chat.ts`                                      | 🔄 重构为委托 messageManager + streamManager |
| `ui/src/components/ChatMessage.vue`                          | 🔄 简化为路由组件 → message/ 子组件         |
| `ui/src/components/message/UserMessage.vue` (NEW)            | ✨ 用户消息气泡                              |
| `ui/src/components/message/SystemMessage.vue` (NEW)          | ✨ 系统消息                                  |
| `ui/src/components/message/AgentMessage.vue` (NEW)           | ✨ 智能体消息气泡（avatar + header + blocks）|
| `ui/src/components/AgentTaskPanel.vue`                       | ✨ 任务状态面板                              |
| `ui/src/components/DirectoryTreeBrowser.vue`                 | ✨ 文件树浏览                                |

### 配置

| 文件                          | 变化         |
| ----------------------------- | ------------ |
| `config/acp_agents.json`      | ✨ 新增      |
| `config/tools.json`           | ✨ 新增      |
| `config/skills.json`          | ✨ 新增      |
| `.env.example`                | 🔄 新增注释  |

### 测试

| 文件                            | 变化                         |
| ------------------------------- | ---------------------------- |
| `tests/test_supervisor.py`      | 🔄 重写：14 个 Orchestrator 测试 |
| `tests/test_server.py`          | 🔄 更新 + 2 个新端点测试      |
| `tests/test_mock_flow.py`       | 🔄 turn-based 压缩断言更新    |
| `tests/test_event_bus.py`       | ❌ 删除（5 个测试）            |

---

# 架构概览

```
src/agent/
├── __init__.py
├── _utils.py                        # extract_file_refs, SSE_HEADERS
├── events.py                        # EventType + make_event 工厂
├── message.py                       # Message dataclass
├── config.py                        # AgentConfig (.env → Pydantic)
├── config_manager.py                # ConfigManager (hot-reload JSON)
├── models.py                        # resolve_model()
├── agent/                           # 单 agent ReAct 循环
│   ├── __init__.py
│   ├── core.py                      # Agent.astream_events()
│   └── streaming.py                 # extract_file_refs
├── db/                              # 持久化层
│   ├── __init__.py
│   ├── connection.py                # 连接 + schema 迁移
│   ├── sessions.py                  # 会话 CRUD
│   ├── messages.py                  # 消息 CRUD
│   ├── tasks.py                     # 任务更新 CRUD
│   ├── tools.py                     # 工具使用统计
│   └── compact.py                   # compact_session
├── orchestrator/                    # 多 agent 编排
│   ├── __init__.py
│   ├── core.py                      # Orchestrator pipeline
│   ├── planner.py                   # Planner (plan 生成 + 解析)
│   ├── dispatcher.py                # LocalDispatcher + ACPDispatcher
│   ├── summarizer.py                # 多 agent 结果汇总
│   └── _events.py                   # 便捷重导出
├── context/                         # 上下文管理
│   ├── compression.py               # turn-based 压缩
│   └── memory.py                    # MemoryManager
├── tools/                           # 工具定义
├── prompts/                         # 系统提示词
├── acp_agent.py                     # ACP 智能体支持
├── acp_client.py                    # ACP 客户端
├── acp/                             # ACP 原生客户端
├── file_service.py                  # 文件浏览 API
├── error_handler.py                 # 错误处理 + 熔断
├── skills.py                        # 技能加载
├── audit_logger.py                  # 审计日志
└── backends/                        # 后端抽象
```

# 第一部分：新增 / 变更文件说明

## 1. `src/agent/events.py` — 统一事件协议

```python
from enum import Enum

class EventType(str, Enum):
    THINKING_START = "thinking_start"
    THINKING = "thinking"
    THINKING_DONE = "thinking_done"
    TOOL_CALL = "tool_call"
    MESSAGE = "message"
    PLAN = "plan"
    TASK_UPDATE = "task_update"
    METRICS = "metrics"
    SUMMARY = "summary"
    ERROR = "error"
    DONE = "done"

def make_event(event_type: EventType | str, data: Any = "", **extra) -> dict:
    ...

# 便捷工厂
def make_thinking(data, agent_name="") -> dict: ...
def make_plan(data, agent_name="") -> dict: ...
def make_message(data, agent_name="", file_refs=None) -> dict: ...
def make_tool_call(name, args, status="running", agent_name="") -> dict: ...
def make_task_update(agent, task, status, state=None) -> dict: ...
def make_metrics(elapsed_ms, agent_calls, tokens, agent_name="") -> dict: ...
def make_summary(data, agent_name="") -> dict: ...
def make_error(data, agent_name="") -> dict: ...
def make_done(agent_name="") -> dict: ...
```

## 2. `src/agent/orchestrator/` 包

### 2.1 `core.py` — Orchestrator 类

构造：`Orchestrator(config)` → 解析 AgentConfig，构建 sub_agents + acp_agents map。

主流程 `stream(task, history, summary)`：

```
yield thinking_start → [thinking chunks] → thinking_done → plan
→ 解析出 steps
→ 若全是 direct → cleanup 后直接 yield message
→ 否则逐个 dispatch：
    yield task_update(running) → [thinking / tool_call / message] → task_update(completed)
→ 若 results > 1 → yield summary
→ yield metrics → yield done
```

### 2.2 `planner.py` — Planner 类

- `_build_prompt(history, summary)` — 从 config/agents.json + 模板构造 system prompt
- `_convert_history(history)` — 将 Python dict 列表转为 LLM 消息格式
- `stream(task, history, summary)` — 调用 model.astream()，产出 thinking_start / thinking / thinking_done / plan

`_PLAN_RE = r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE`

### 2.3 `dispatcher.py` — Dispatcher 类

`make_dispatcher(agent_id, sub_agents, acp_agents, config)` → 返回 `LocalDispatcher` 或 `ACPDispatcher`。

- **LocalDispatcher.stream(task)** — 调用 `sub_agents[agent_id].astream_events()`
- **ACPDispatcher.stream(task, context)** — 调用 `get_acp_agent().run()`

两种 dispatcher 都会过滤 punctuation-only 内容，fallback 为 `"by {agent} done"`。

### 2.4 `summarizer.py` — summarize_stream()

```python
async def summarize_stream(model, task, results, start_time) -> AsyncIterator[dict]:
    yield summary event
    yield metrics event
    yield done
```

仅当 `len(results) > 1` 时才调用 LLM 总结，否则直接 yield metrics + done。

## 3. `src/agent/db/` 包

### 3.1 `connection.py`

```python
_conn: sqlite3.Connection | None = None

def _get_conn() -> sqlite3.Connection:
    # 延迟连接 + schema 迁移
    # 4 张表：sessions, messages, tool_usage, task_updates
    # 逐列 ALTER TABLE 进行 schema 迁移
```

### 3.2 `sessions.py`

| 函数 | 功能 |
|------|------|
| `create_session(title, project_path)` | 创建会话 |
| `delete_session(session_id)` | 级联删除 messages + task_updates |
| `list_sessions()` | 列表 |
| `rename_session(session_id, title)` | 重命名 |
| `update_session_status(session_id, status)` | 更新状态 |
| `update_session_duration(session_id, ms)` | 更新耗时 |
| `update_session_project_path(session_id, path)` | 更新项目路径 |
| `get_session_summary(session_id)` | 获取摘要 |

### 3.3 `messages.py`

| 函数 | 功能 |
|------|------|
| `save_message(session_id, role, content, ...)` | 保存单条消息 |
| `save_turn(session_id, user_msg, ai_msg, ...)` | 保存一轮对话 |
| `load_messages(session_id)` | 返回 Message 对象列表 |
| `load_history(session_id)` | 返回 LangChain BaseMessage 列表 |
| `load_history_with_meta(session_id)` | 返回前端格式 dicts |

### 3.4 `tasks.py`

| 函数 | 功能 |
|------|------|
| `save_task_update(session_id, agent, task, status)` | 保存任务更新 |
| `load_task_updates(session_id)` | 加载（去重：MAX(id) GROUP BY agent,task） |
| `delete_task_updates(session_ids)` | 批量删除 |

### 3.5 `tools.py`

| 函数 | 功能 |
|------|------|
| `record_tool_usage(session_id, tool, duration_ms, success)` | 记录工具使用 |
| `get_tool_usage_stats()` | 统计 |
| `save_metrics(session_id, data)` | 保存指标 |
| `load_metrics(session_id)` | 加载指标 |

### 3.6 `compact.py`

```python
def compact_session(session_id, summary, keep=5) -> int:
    # 标记早期的 keep 条之外的消息为 compacted=1
    # 更新 sessions.summary + compacted_at
    # 返回标记行数
```

## 4. 前端拆分详情

### 4.1 `api/types.ts` — 所有类型定义

```typescript
export type AgentStatus = 'idle' | 'receiving' | 'deciding' | 'thinking' | ...
export interface ChatMessage { role, content, toolCalls?, agentName?, thinking?, ... }
export interface TaskUpdate { agent, task, status, state?, startedAt?, ... }
export interface MetricsData { elapsed_ms, agent_calls, tokens }
export interface SessionInfo { session_id, title, status, ... }
export interface BrowseNode { path, name, type, children?, ... }
// + LogEntry, ACPAgentInfo, CliInfo, FileInfo, etc.
```

### 4.2 `api/endpoints.ts` — REST 函数

```typescript
listTools(), fetchAgents(), fetchAcpAgents(), updateAgentConfig()
fetchFileTree(), fetchFileContent(), fetchCliList()
listSessions(), createSession(), deleteSessionById(), renameSessionById()
restoreSession(), browseDirectories(), listDrives(), compactSession()
```

### 4.3 `api/sse.ts` — 流式通信

```typescript
streamChatCallbacks(message, onEvent, onDone, sessionId?)  // 回调风格
streamChatFetch(message, sessionId?)                       // async iterator
streamOrchestrate(task, sessionId?)                        // async iterator
```

### 4.4 `messageManager.ts` — 消息状态管理

```typescript
export function useMessageManager() {
  // state
  messages: Ref<ChatMessage[]>
  typewriterState, thinkTypeState
  taskItems: Ref<TaskUpdate[]>
  metrics: Ref<MetricsData | null>

  // mutations — 所有操作通过数组索引修改，禁止本地引用
  addUser(content), addSystem(content)
  addAssistant(agentName, opts?), ensureAssistant(agentName)
  appendContent(index, text), setContent(index, text)
  setThinkingStart(index), appendThinking(index, text), setThinkingDone(index)
  mergeToolCalls(agentName, toolCalls)
  pushPlan(content), addSummary(content), addError(content)
  updateTask(t), setMetrics(m)
  restore(raw: any[]), clear()
}
```

### 4.5 `streamManager.ts` — 流通信管理

```typescript
export function useStreamManager(msg, sessionId) {
  // state
  isLoading, streamingActive, eventLog
  currentPhase, currentDispatch
  pendingMessages

  // 3 send paths
  sendMessage(text)         // EventSource → /chat 端点
  sendOrchestrate(text)     // async generator → /api/orchestrate
  sendACP(agentId, text)    // fetch+reader → /acp/send

  // control
  abort(), abortAndSend(text)
  handleCompact()
  checkAcpAvailable(agentId)
}
```

事件调度规则：

| SSE Event | MessageManager 操作 |
|-----------|-------------------|
| `thinking_start` | `setThinkingStart(idx)` |
| `thinking` | `appendThinking(idx, chunk)` |
| `thinking_done` | `setThinkingDone(idx)` |
| `plan` | `pushPlan(planText)` + 更新 `currentPhase` |
| `message` | `appendContent(idx, chunk)` |
| `tool_call` | `mergeToolCalls(agentName, tcs)` |
| `task_update` | `updateTask(taskData)` |
| `summary` | `addSummary(summary)` |
| `metrics` | `setMetrics(metrics)` |
| `error` | `addError(error)` |
| `done` | 清理 + 设置 `isLoading = false` |

### 4.6 `stores/chat.ts` — Pinia 封装

```typescript
export const useChatStore = defineStore('chat', () => {
  const msg = useMessageManager()
  const sessionId = ref<string | null>(null)
  const stream = useStreamManager(msg, sessionId)

  // sync sessionId → restoreSession
  watch(() => sessionsStore.activeSessionId, ...)

  // 暴露与旧版兼容的 API
  return { messages, isLoading, streamingActive, sessionId,
           send, sendOrchestrate, sendACP, abort,
           clearMessages, newSession, restoreSession, ... }
})
```

### 4.7 `useMarkdown.ts` — Markdown 渲染

```typescript
export function renderMd(text: string): string
```

基于 marked + highlight.js + KaTeX，支持 `$$` 块级公式和 `$` 行内公式，含中文跳过。

### 4.8 ChatMessage 子组件

```
ChatMessage.vue          # 路由：role === 'user' → UserMessage
                                    'system' → SystemMessage
                                    'assistant' → AgentMessage

message/UserMessage.vue   # 用户气泡（右对齐，淡入）
message/SystemMessage.vue # 系统消息（居中，含 ErrorBlock）
message/AgentMessage.vue  # 智能体气泡（avatar + header + handoff + thinking
                          #   + tool_calls + results + summary + content + file_refs）
```

---

# 第二部分：关键修改（server.py, checkpoint.py 等）

## 5. `server.py` 修改要点

### 5.1 导入路径变化

```python
# 新
from src.agent._utils import SSE_HEADERS, is_punctuation_only
from src.agent.orchestrator import Orchestrator    # 替换 CustomSupervisor
from src.agent.db import (                         # 替换 checkpoint 模块
    create_session, delete_session, save_message, save_turn,
    load_history, load_history_with_meta,
    save_task_update, load_task_updates,
    compact_session as db_compact_session,
    get_session_summary, get_tool_usage_stats,
    save_metrics, load_metrics,
    ...
)

# 删除
from src.agent.event_bus import event_bus           # 删除
from src.agent.supervisor import CustomSupervisor   # 删除
from src.agent.checkpoint import ...                # 替换
```

### 5.2 全局单例

```python
orchestrator_instance: Orchestrator | None = None
def get_supervisor() -> Orchestrator: ...
def get_agent() -> Agent: ...
```

### 5.3 SSE 事件处理（`stream()` 端点）

```
flowchart:
  _passthrough → event loop:
    thinking_start → record flag
    thinking → append to _thinking_accum
    thinking_done → _save_accumulated()
    message → append to _message_accum + forward
    tool_call → save_message(..., tool_calls=json.dumps(tcs))
    plan → save_message(..., name="plan")
    task_update → save_task_update(...)
    summary → save_message(..., name="summary")
    metrics → save_metrics(...)
    error → save fallback
    done → _save_accumulated()
```

### 5.4 `/api/compact` — force + keep

```python
marked = db_compact_session(request.session_id, summary_text, keep=1)
```

### 5.5 新增端点

| 端点 | 用途 |
|------|------|
| `PATCH /api/sessions/{id}/title` | 重命名会话 |
| `PATCH /api/sessions/{id}/project-path` | 更新项目路径 |
| `DELETE /api/sessions/{id}` | 删除会话 |
| `GET /api/files/tree` | 文件树 |
| `POST /api/files/pick-directory` | Windows 文件夹选择 |
| `POST /api/files/validate-directory` | 目录校验 |
| `GET /api/files/browse` | 目录递归浏览 |
| `GET /api/files/drives` | 驱动器列表 |
| `GET /api/files/content` | 文件内容 |
| `GET /api/acp/agents` | ACP agent 列表 |
| `GET /api/acp/check/{id}` | ACP 可用性检查 |
| `GET /api/acp/sessions/{id}` | ACP session 列表 |

### 5.6 删除端点

- `/api/events/stream/{stream_id}` — event_bus 删除后不再需要

## 6. `tests/test_supervisor.py` 重写

14 个测试，覆盖：
- **TestParsePlan**: basic_plan, bold_agent_name, chinese_colon, single_agent, empty_plan, extra_text_ignored
- **TestExtractCode**: fenced_block, inline_backticks, plain_text
- **TestOrchestratorInit**: init_with_mock_model
- **TestOrchestratorRun**: run_single_agent, run_direct_agent, run_no_plan_fallback, run_acp_agent_dispatch

Mock 方式：`unittest.mock.patch("src.agent.models.resolve_model")`。

## 7. 关键导入技巧

`planner.py` 和 `core.py` 使用 `from src.agent import models as _models` + `_models.resolve_model()` 而非 `from src.agent.models import resolve_model`，确保 `unittest.mock.patch()` 在所有消费者中生效（避免 Python import 绑定泄露）。

---

# 恢复步骤

```bash
# 1. 从备份复制基础
cp -r diff/langgraph-agent-v2-main/* .

# 2. 删除不再使用的文件
rm src/agent/supervisor.py src/agent/graph.py src/agent/event_bus.py
rm src/agent/state.py
rm src/agent/orchestrator.py  # 旧单体
rm src/agent/agent.py         # 旧单体
rm src/agent/checkpoint.py    # 已拆分为 db/ 包
rm tests/test_event_bus.py

# 3. 创建新增文件
# --- 后端 ---
# src/agent/events.py
# src/agent/message.py
# src/agent/_utils.py
# src/agent/orchestrator/__init__.py, core.py, planner.py, dispatcher.py, summarizer.py, _events.py
# src/agent/db/__init__.py, connection.py, sessions.py, messages.py, tasks.py, tools.py, compact.py
# src/agent/agent/__init__.py, core.py, streaming.py
# --- 前端 ---
# ui/src/utils/api/types.ts, endpoints.ts, sse.ts
# ui/src/utils/messageManager.ts
# ui/src/utils/streamManager.ts
# ui/src/utils/useMarkdown.ts
# ui/src/components/message/UserMessage.vue, SystemMessage.vue, AgentMessage.vue
# ui/src/components/AgentTaskPanel.vue
# ui/src/components/DirectoryTreeBrowser.vue
# --- 配置 ---
# config/acp_agents.json (空 [])
# config/tools.json (空 [])
# config/skills.json (空 [])

# 4. 替换已有文件
# server.py (导入路径 + SSE 处理 + 端点)
# ui/src/stores/chat.ts (委托 messageManager + streamManager)
# ui/src/utils/api.ts (barrel 重导出)
# ui/src/components/ChatMessage.vue (路由到 message/ 子组件)

# 5. 删除测试备份
# tests/test_supervisor.py → 用重写版本替换
# tests/test_server.py → 更新
# tests/test_mock_flow.py → 更新 (turn-based)

# 6. 安装依赖
pip install -e ".[dev]"
cd ui && npm install

# 7. 验证
cd ..
pytest --cov=src -v
ruff check .
cd ui && npx vue-tsc -b && npx vite build
```
