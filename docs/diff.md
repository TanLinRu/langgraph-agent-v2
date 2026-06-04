# 项目差异文档 — backup → current

> 从 `diff/langgraph-agent-v2-main`（备份）到当前项目（修改后）的完整差异。
> 另一 AI agent 可据此将备份逐步修改至当前状态。

---

## 变更总览

| 层          | 新增     | 修改      | 删除 |
| ----------- | -------- | --------- | ---- |
| 后端 Python | 5 个文件 | 18 个文件 | 0    |
| 前端 Vue/TS | 2 个文件 | 12 个文件 | 0    |
| 配置/文档   | 0        | 3 个文件  | 0    |

---

## 第一部分：后端 Python

### 1.1 架构核心重构

备份是 **4 阶段过程式流水线**（Plan → Dispatch → Summarize → Metrics），当前是 **3 节点 LangGraph StateGraph**（Supervisor → Execute → Review）。

| 维度          | 备份版本                                                     | 当前版本                                                     |
| ------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 编排器        | `Orchestrator` 过程式流水线（`planner.py` → `dispatcher.py` → `summarizer.py`） | `Orchestrator` = `StateGraph(GraphState)` 3 节点（`supervisor_node` → `execute_node` → `review_node`） |
| 计划生成      | `Planner.stream()` 调用 `model.astream()`，产出 `thinking_start/thinking/thinking_done/plan` 事件 | `_supervisor_node_impl()` 调用 `model.ainvoke()`，显式 `yield make_thinking_start/make_thinking/make_thinking_done/make_plan` |
| 子 Agent 调用 | `LocalDispatcher` / `ACPDispatcher` 接口，各有 `stream()` 方法 | `SubAgentTool(BaseTool)` / `ACPSubAgentTool(BaseTool)`，作为 LangChain Tool 在 `create_react_agent` 中调用 |
| 审计          | 无（仅 `summarizer.py` 做多步汇总）                          | `_review_node_impl()` 用 `AUDITOR_PROMPT` LLM 审计 + `planner.save_experiences()` 存到 `memory/experiences.md` |
| 重试          | 无                                                           | `execute_node_impl` 每步 retry 1 次                          |
| 事件桥接      | 直接 `yield`                                                 | `asyncio.Queue` → `run()` 消费队列                           |

### 1.2 逐个文件差异

#### 新增文件（备份中没有）

| 文件                              | 行数 | 说明                                                  |
| --------------------------------- | ---- | ----------------------------------------------------- |
| `src/agent/orchestrator/tools.py` | 123  | `SubAgentTool` / `ACPSubAgentTool` 基于 Tool 的包装器 |
| `src/agent/tools/load_skill.py`   | —    | 按需加载 skill 的工具                                 |
| `tests/test_abort.py`             | —    | 中止/取消测试                                         |
| `tests/test_acp_tools.py`         | —    | ACP 工具集成测试                                      |

#### 修改文件

##### `src/agent/orchestrator/core.py` — **完全重写**

**备份** (227 行): 过程式 `stream()` → `Planner.stream()` plan → `make_dispatcher()` dispatch → `summarize_stream()` summary

**当前** (395 行，+168): 3 节点 StateGraph

```python
class GraphState(TypedDict):
    messages: list[BaseMessage]
    plan_text: str
    steps: list[dict]
    results: list[dict]
    errors: list[dict]
    review: str

graph = StateGraph(GraphState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("execute", execute_node)
graph.add_node("review", review_node)
graph.add_edge("supervisor", "execute")
graph.add_edge("execute", "review")
graph.add_conditional_edges("review", lambda s: "end" if s.get("review") else "execute")
```

关键函数：

- `_supervisor_node_impl()` — `model.ainvoke()`，产出 thinking_start/thinking/thinking_done/plan 事件
- `_parse_plan(text)` — 正则 `r"^\s*[-*]\s*(\w+)\s*[:：]\s*(.+)"` 解析 plan
- `_execute_node_impl(state)` — 逐个执行 steps，dispatch SubAgentTool/ACPSubAgentTool，track running tools，push task_update
- `_review_node_impl(state)` — `AUDITOR_PROMPT` + model.ainvoke()，存 experiences，push audit_summary
- `run(task, history, summary)` — 消费 asyncio.Queue，yield 事件

##### `src/agent/orchestrator/planner.py` — **简化**

**备份** (195 行): `_build_prompt()` + `stream()` + `parse_plan()` 全部在 Planner 类中

**当前** (103 行，-92): 仅保留 `load_experiences()` / `save_experiences()` / `build_agent_descriptions()` / `_convert_history()`

计划生成已移至 `core.py` 的 `_supervisor_node_impl()`。

##### `src/agent/orchestrator/_events.py` — +1 行

添加 `make_audit_summary` 和 `EventType` 导入。

##### `src/agent/orchestrator/dispatcher.py` — **增强**

**备份** (205 行): 基础版本

**当前** (238 行，+33):

- `LocalDispatcher.stream()`: 添加 `recursion_limit=200`、`try/except` 错误处理
- `ACPDispatcher.stream()`: 添加连接时间测量、"正在连接..." thinking 事件、agent_id 查找回退、`previous_results → context`

##### `src/agent/events.py` — +审计事件

- 添加 `AUDIT_SUMMARY: Final[str] = "audit_summary"` 事件类型
- 添加 `make_audit_summary(agent_name, data)` 工厂函数
- events 架构表新增 `audit_summary` 行
- `EventType` enum 包含 `AUDIT_SUMMARY`

##### `src/agent/prompts/system_prompt.py` — **提示词重构**

**备份**: `SUPERVISOR_PROMPT`（硬编码 agent 列表）+ `SUPERVISOR_PROMPT_TEMPLATE`

**当前**:

- `SUPERVISOR_PLAN_PROMPT` — 使用 `{agent_descriptions}` + `{experiences}` 占位符，`{{task}}`（转义），语言无关响应
- `EXECUTE_PLAN_PROMPT` (新增) — 执行计划提示词
- `AUDITOR_PROMPT` (新增，中文) — 审计提示词，要求用中文输出结构化审计报告（总结/各 Agent 结果/问题与经验/对未来会话建议）

##### `src/agent/agent/core.py` — **惰性加载重构**

**备份**: `__init__` 中急切初始化 `self.tools = TOOLS`, `self.compressor`, `self.agent_graph`

**当前**: 惰性加载

- `self._tools = None` → `_ensure_tools()` 首次调用时 `get_tools()`
- `self._prompt = None` → `_ensure_prompt()` 首次调用时格式化 SYSTEM_PROMPT
- `self._graph = None` → `_ensure_graph()` 首次调用时 `create_agent()`
- 导入从 `from src.agent.tools import TOOLS` 改为 `from src.agent.tools import get_tools`

##### `src/agent/tools/__init__.py` — **热重载**

**备份**: 静态 `TOOLS = _load_tools_from_config()`

**当前**: `get_tools()` 每次通过 ConfigManager 惰性读取（支持热重载）；`TOOLS = get_tools()` 变为函数调用别名

##### `src/agent/models.py` — +日志

添加 `import logging`、`logger = logging.getLogger(__name__)`、`[LLM MODEL]` 日志

##### `src/agent/skills.py` — **输出格式变更**

**备份**: 输出完整 skill 内容 `## {name}\n{content}`

**当前**: 输出 `[Available Skills]` 摘要列表 `- {name}: {description}`，指示 LLM 使用 `load_skill` 工具按需加载；支持按 `agent_id` 过滤

##### `src/agent/acp_agent.py` — +权限 +thinking_start

- 添加 `resolve_permission(self, req_id, option_id)` 方法
- ACP run 开始时先 yield `thinking_start` 事件
- 处理 `permission_request` 事件（添加 agent_id 后 yield）
- +15 行（193 vs 178）

##### `src/agent/acp_client.py` — +permission_request

- `AgentEvent` 的 `type` docstring 添加 `"permission_request"`
- `_map_acp_event()` 添加 `elif event.type == "permission_request":` 映射

##### `src/agent/acp/client.py` — **大幅扩展**

**备份** (385 行): 基础 ACP 客户端

**当前** (648 行，+263):

- `__init__` 添加 `cwd` 参数、`_pending_permissions` dict
- 添加 `_send_response()` / `_log_notification()` / `load_session()` / `create_session()`
- `prompt()` 重写：5s 轮询、last_event_time、permission_request 处理、空闲检测、try/except TimeoutError + CancelledError
- 新增 `_execute_tool()` → `_tool_read()` / `_tool_write()` / `_tool_edit()` / `_tool_bash()` / `_tool_glob()` / `_tool_grep()`
- `_parse_notification()` 扩展：`tool_call` 拆分为 `tool_call` + `tool_call_update`（in_progress/completed/failed）
- 添加 `resolve_permission()`

##### `src/agent/db/__init__.py` — +reconcile_session_tasks

导出 `reconcile_session_tasks`（来自 `db/tasks`）

##### `src/agent/db/tasks.py` — +reconcile_session_tasks

新增 `reconcile_session_tasks(session_id)` 函数，将 session 中 `running`/`pending` 任务标记为 `failed`（用于会话恢复）

##### `server.py` — +权限端点 +finally 协调

**备份** (1123 行) **当前** (1160 行)：

| 差异                                | 说明                                                         |
| ----------------------------------- | ------------------------------------------------------------ |
| 导入                                | 新增 `reconcile_session_tasks` 导入                          |
| `PermissionResponseRequest`         | 新增 Pydantic model                                          |
| `POST /chat` finally                | 新增 `if not _saved` 保存 + `reconcile_session_tasks(session_id)` |
| `GET /chat/stream` finally          | 新增 `if not _saved` 保存 + `reconcile_session_tasks(sid)`   |
| `POST /api/orchestrate` finally     | 新增 `_save_accumulated()` + `reconcile_session_tasks(session_id)` |
| `POST /api/acp/permission-response` | **新增端点** — 解析 ACP 权限请求                             |

##### `tests/test_supervisor.py` — **完全重写**

**备份** (347 行): Mock `model.astream()`，测试 Planner + Dispatcher 路径

**当前** (414 行，+67): Mock `model.ainvoke()` + StateGraph 模拟

- `_make_chunk` 使用 `MagicMock(spec=object)`（仅 content，无 additional_kwargs）
- `_make_model_response()` 同步返回 mock
- 测试: `test_run_produces_plan_audit_metrics_done`、`test_events_in_correct_order`（plan → audit_summary）、`test_execute_node_retries_on_error`、`test_execute_node_skips_unknown_agent`、`test_audit_summary_contains_results`、`test_planner_builds_agent_descriptions`、`test_planner_converts_history`、`test_run_acp_agent_dispatch`

---

## 第二部分：前端 Vue/TS

### 2.1 架构区别

备份使用**索引字典 + 辅助函数**管理消息槽；当前使用**统一的 `ensureAssistant(agentName)`**，按 agentName 从后向前扫描复用消息。

| 维度       | 备份版本                                                     | 当前版本                                           |
| ---------- | ------------------------------------------------------------ | -------------------------------------------------- |
| 消息槽定位 | `ensureAgentMsg(agentName)` + `ensureSupervisorMsg()` + 两套索引 | 统一 `msg.ensureAssistant(agentName)`              |
| 事件流     | `pushPlan()` 创建新 div                                      | `plan` 写入已有 supervisor div                     |
| 审计摘要   | 无                                                           | `audit_summary` 事件 + `setAuditSummary()`         |
| 权限对话框 | 无                                                           | `PermissionDialog.vue` + `permission_request` 事件 |
| 测试框架   | 无 vitest                                                    | `vitest` + 2 个测试文件（11 个测试）               |

### 2.2 逐个文件差异

#### 新增文件（备份中没有）

| 文件                                     | 说明                               |
| ---------------------------------------- | ---------------------------------- |
| `ui/src/components/PermissionDialog.vue` | ACP 权限请求对话框（固定全屏浮层） |
| `ui/src/utils/api/sse.test.ts`           | SSE 流处理单元测试                 |

#### 修改文件

##### `ui/src/utils/streamManager.ts` — **重大重构**

**备份**: 使用 `supervisorMsgIdx` + `agentMsgIndices` 两套索引；`plan` → `pushPlan()` 创建新 div

**当前**: 统一 `msg.ensureAssistant(agentName)`

具体差异：

- **导入**: 新增 `PermissionRequest` 类型引入
- **状态**: 新增 `permissionRequest` ref；移除 `_lastAgent`
- **`_setSessionStatus`**: 新增 session 不在本地列表时 `unshift` 创建
- **`sendOrchestrate`**:
  - 移除 `supervisorMsgIdx` / `agentMsgIndices` / `ensureSupervisorMsg` / `ensureAgentMsg`
  - 所有事件用 `msg.ensureAssistant(agentName)` 获取消息索引
  - `plan` 事件：`msg.ensureAssistant('supervisor')` → 直接设 `content=planText` + 清 thinking + 停 typewriter（不再调用 `pushPlan`）
  - `tool_call` 事件：新增 result/completed 分支（标记 pending/running → done + `clearCompletedToolCalls()`）
  - `message` 事件：用 `_enqueueStep` + `appendContent`（备份为直接 `setContent`）
  - `task_update` 事件：用 `msg.ensureAssistant(update.agent)` 替代 `agentMsgIndices`
  - 新增 `audit_summary` 事件处理
  - 新增 `permission_request` 事件处理
  - finally 块：迭代所有 assistant 消息标记 done（备份用 `agentMsgIndices` 字典）
- **`sendACP`**: 添加 `_appendLog` 调试日志、`permission_request` 处理、finally 块清理 `permissionRequest`
- **`abort`**: 保留 `msg.reconcileStreamEnd()` 调用
- **`send`**: 移除 `_lastAgent` 逻辑
- 返回对象新增 `permissionRequest`

##### `ui/src/utils/messageManager.ts`

- 新增 `auditSummary` ref + `setAuditSummary(text)` + `clearCompletedToolCalls()`
- `setMetrics()` 改为增量合并 tokens（`{ ...prev.tokens, ...data.tokens }`）
- `clear()` / `resetTaskItems()` 新增 `auditSummary.value = null`
- `reconcileStreamEnd()` 新增 toolCalls 清理逻辑（pending/running → done + `clearCompletedToolCalls()`）

##### `ui/src/stores/chat.ts`

- Pinia store 暴露新增 `auditSummary: msg.auditSummary`、`permissionRequest: stream.permissionRequest`

##### `ui/src/components/ChatTab.vue`

- **导入**: 新增 `PermissionDialog` 导入
- **消息过滤条件**: `msg.content || msg.toolCalls?.length || msg.thinking || msg.isThinking`
- **模板**: 新增 `<PermissionDialog>` 区块（`.input-zone` 之上）
- **`.input-zone`**: `InputBar` 传递 `permissionPending` prop
- **样式**: 保留 `.input-zone` CSS

##### `ui/src/components/InputBar.vue`

- **Props**: 新增 `permissionPending?: boolean`
- **模板**: input 添加 `:disabled="permissionPending"`；占位符根据 `permissionPending` 切换

##### `ui/src/components/TopologyBar.vue`

- `agentLabel` computed 恢复（从 `chat.taskItems` 取第一个非 supervisor 的 agent 名称）
- `watch(supState)` 恢复完整逻辑

##### `ui/src/components/ThinkingPanel.vue`

- `activeAgent` computed 恢复（取最后一条 thinking 数据块的 agent）
- 模板标题用 `activeAgent` 而非硬编码

##### `ui/src/components/MonitorPanel.vue`

- 导入恢复 `useSessionsStore`
- 计时器用 `watch(sessionsStore.activeSessionId)` 而非固定时间
- 模板恢复审计摘要区块（`chat.auditSummary`）

##### `ui/src/components/ToolCallBlock.vue`

- `toolIcon` 图标映射不同
- CSS 差异：`.tool-call-block` 从 `margin: 3px 0 3px 38px` → `width: 100%` / `margin-left: 0`；紫色主题 → 默认主题

##### `ui/src/components/message/AgentMessage.vue`

- 工具调用状态: `tc.status || (isTyping && j === msg.toolCalls!.length - 1 ? 'running' : 'done')`（备份为 `!isTyping ? 'done' : ...`）
- `.tool-calls` CSS 恢复 `width: 100%` + `align-items: flex-start`

##### `ui/src/utils/api/types.ts`

- 新增 `PermissionRequest` 接口定义（`req_id`, `session_id`, `toolCall`, `options`）

##### `ui/package.json`

- **scripts**: 新增 `"test": "vitest run"`、`"test:watch": "vitest"`
- **devDependencies**: 新增 `"vitest": "^4.1.8"`

##### `ui/vite.config.ts`

- 新增 `/// <reference types="vitest" />` 指令
- 新增 `test` 配置块（`environment: 'node'`, `include: ['src/**/*.test.ts']`）

---

## 第三部分：配置/文档

| 文件                 | 差异                                                         |
| -------------------- | ------------------------------------------------------------ |
| `config/agents.json` | 3 处 desc 中文润色（direct/opencode/claude）；`load_skill` 工具条目存在于当前、不在备份 |
| `config/tools.json`  | 当前版本包含 `load_skill` 工具配置；备份中无                 |
| `AGENTS.md`          | 备份已精简：去掉副标题、删命令行、更新测试计数 55→69、删 StateGraph gotchas 6 条、删 ACP anti-pattern 整节 |

---

## 第四部分：恢复步骤（备份 → 当前）

### 4.1 后端 Python

```bash
# 1. 新增文件
# src/agent/orchestrator/tools.py
#   → SubAgentTool(BaseTool), ACPSubAgentTool(BaseTool)
#   → 使用 create_react_agent 构建 sub-agent，dispatch ACP 时用 get_acp_agent()
#
# src/agent/tools/load_skill.py
#   → load_skill tool，通过 ConfigManager 读取 skill 内容

# 2. 替换文件
# src/agent/orchestrator/core.py
#   → 备份的流水线替换为 3 节点 StateGraph
#   → 添加 _supervisor_node_impl / _execute_node_impl / _review_node_impl
#   → 添加 _parse_plan() 正则解析
#   → run() 改为 asyncio.Queue + graph.ainvoke()
#
# src/agent/orchestrator/planner.py
#   → 删除 _build_prompt(), stream(), parse_plan()
#   → 保留 load_experiences(), save_experiences(), build_agent_descriptions(), _convert_history()
#
# src/agent/orchestrator/_events.py
#   → 添加 make_audit_summary 导入
#
# src/agent/orchestrator/dispatcher.py
#   → LocalDispatcher: 添加 recursion_limit=200 + try/except
#   → ACPDispatcher: 添加连接时间 + "正在连接..." event + agent_id 回退
#
# src/agent/events.py
#   → 添加 AUDIT_SUMMARY 事件类型 + make_audit_summary()
#   → EventType 包含 AUDIT_SUMMARY
#
# src/agent/prompts/system_prompt.py
#   → 备份的 SUPERVISOR_PROMPT + SUPERVISOR_PROMPT_TEMPLATE
#   → 替换为 SUPERVISOR_PLAN_PROMPT + EXECUTE_PLAN_PROMPT + AUDITOR_PROMPT(中文)
#
# src/agent/agent/core.py
#   → 急切初始化 → 惰性加载（_ensure_tools/_ensure_prompt/_ensure_graph）
#   → TOOLS → get_tools()
#
# src/agent/tools/__init__.py
#   → 静态 TOOLS → 函数 get_tools()（ConfigManager 惰性读取）
#
# src/agent/skills.py
#   → get_skills_prompt() 输出格式改为 [Available Skills] 摘要
#
# src/agent/acp_agent.py
#   → 添加 resolve_permission()
#   → 添加 thinking_start 事件
#   → 处理 permisson_request
#
# src/agent/acp_client.py
#   → AgentEvent type 添加 "permission_request"
#   → _map_acp_event() 添加映射
#
# src/agent/acp/client.py
#   → 大幅扩展：_send_response, _log_notification, load_session
#   → prompt() 重写：5s 轮询, permission_request 处理
#   → 新增 _execute_tool + 6 个工具方法
#   → _parse_notification 扩展
#   → resolve_permission()
#
# src/agent/db/__init__.py
#   → 导出 reconcile_session_tasks
#
# src/agent/db/tasks.py
#   → 添加 reconcile_session_tasks()
#
# server.py
#   → 导入 reconcile_session_tasks
#   → 添加 PermissionResponseRequest
#   → 3 个 SSE 端点 finally 块添加 reconcile_session_tasks()
#   → 添加 POST /api/acp/permission-response 端点
#
# tests/test_supervisor.py
#   → 完全替换：mock model.ainvoke() + StateGraph 测试
```

### 4.2 前端 Vue/TS

```bash
# 1. 新增文件
# ui/src/components/PermissionDialog.vue
# ui/src/utils/api/sse.test.ts

# 2. 替换文件
# ui/src/utils/streamManager.ts
#   → 删除: supervisorMsgIdx, agentMsgIndices, ensureSupervisorMsg(), ensureAgentMsg()
#   → 修改: 所有事件 handler 用 msg.ensureAssistant(agentName)
#   → plan handler: 删 pushPlan() → msg.ensureAssistant('supervisor') + 设 content + 停 typewriter
#   → tool_call handler: 添加 result/completed 分支 + clearCompletedToolCalls()
#   → message handler: _enqueueStep + appendContent
#   → task_update handler: msg.ensureAssistant(update.agent)
#   → 新增: audit_summary / permission_request 事件处理
#   → finally: 迭代所有 assistant 消息
#   → sendACP: 添加 _appendLog / permission_request / finally 清理
#   → abort: 保留 reconcileStreamEnd()
#   → 返回: 添加 permissionRequest
#
# ui/src/utils/messageManager.ts
#   → 添加 auditSummary ref + setAuditSummary() + clearCompletedToolCalls()
#   → setMetrics() 增量合并 tokens
#   → reconcileStreamEnd() 添加 toolCalls 清理
#
# ui/src/stores/chat.ts
#   → 添加 auditSummary / permissionRequest 暴露
#
# ui/src/components/ChatTab.vue
#   → 消息过滤: 恢复 thinking/isThinking 条件
#   → 模板: 添加 PermissionDialog
#   → input-zone: 恢复 .input-zone div + permissionPending prop
#
# ui/src/components/InputBar.vue
#   → 添加 permissionPending prop + 禁用/占位符逻辑
#
# ui/src/components/MonitorPanel.vue
#   → 恢复 sessionsStore 导入 + watch 计时器
#   → 恢复 auditSummary 区块
#
# ui/src/components/ToolCallBlock.vue
#   → 回退 margin 到 0 / width 100%
#   → 默认主题（非紫色）
#
# ui/src/components/message/AgentMessage.vue
#   → tool_call status 逻辑回退
#   → .tool-calls CSS 恢复 width 100%
#
# ui/src/utils/api/types.ts
#   → 添加 PermissionRequest 接口
#
# ui/package.json
#   → 添加 vitest devDependency + test scripts
#
# ui/vite.config.ts
#   → 添加 vitest reference + test 配置

# 3. 配置
# config/agents.json: 添加 load_skill 工具引用（可选）
# config/tools.json: 添加 load_skill 工具配置
```

### 4.3 验证

```bash
# 后端
cd <project_root>
pytest tests/test_supervisor.py -v            # 20 tests
ruff check .                                  # 仅预存 E501

# 前端
cd ui
npm install                                    # 安装 vitest
npx vitest run                                 # 11 tests
npx vue-tsc --noEmit                           # type-check clean
```

---

## 附录：关键差异速查表

| 备份中的写法                        | 当前写法                                                   |
| ----------------------------------- | ---------------------------------------------------------- |
| `ensureAgentMsg(name)`              | `msg.ensureAssistant(name)`                                |
| `ensureSupervisorMsg()`             | `msg.ensureAssistant('supervisor')`                        |
| `msg.pushPlan(planText)`            | `msg.ensureAssistant('supervisor')` + `content = planText` |
| `agentMsgIndices[name]`             | `msg.ensureAssistant(name)`                                |
| `supervisorMsgIdx`                  | 删除，统一用 `msg.ensureAssistant('supervisor')`           |
| `audit_summary` 不处理              | `msg.setAuditSummary(data)`                                |
| `permission_request` 不处理         | `permissionRequest.value = data`                           |
| `from src.agent.tools import TOOLS` | `from src.agent.tools import get_tools`                    |
| 静态 `TOOLS`                        | 函数 `get_tools()` 热重载                                  |
| `model.astream()` plan              | `model.ainvoke()` plan                                     |
| `LocalDispatcher.stream()`          | `SubAgentTool._arun()`                                     |
| 无 reconcile                        | `reconcile_session_tasks(session_id)`                      |
| `make_summary` 汇总                 | `AUDITOR_PROMPT` + `make_audit_summary`                    |xxxxxxxxxx # 项目差异文档 — backup → current> 从 `diff/langgraph-agent-v2-main`（备份）到当前项目（修改后）的完整差异。> 另一 AI agent 可据此将备份逐步修改至当前状态。---## 变更总览| 层          | 新增     | 修改      | 删除 || ----------- | -------- | --------- | ---- || 后端 Python | 5 个文件 | 18 个文件 | 0    || 前端 Vue/TS | 2 个文件 | 12 个文件 | 0    || 配置/文档   | 0        | 3 个文件  | 0    |---## 第一部分：后端 Python### 1.1 架构核心重构备份是 **4 阶段过程式流水线**（Plan → Dispatch → Summarize → Metrics），当前是 **3 节点 LangGraph StateGraph**（Supervisor → Execute → Review）。| 维度          | 备份版本                                                     | 当前版本                                                     || ------------- | ------------------------------------------------------------ | ------------------------------------------------------------ || 编排器        | `Orchestrator` 过程式流水线（`planner.py` → `dispatcher.py` → `summarizer.py`） | `Orchestrator` = `StateGraph(GraphState)` 3 节点（`supervisor_node` → `execute_node` → `review_node`） || 计划生成      | `Planner.stream()` 调用 `model.astream()`，产出 `thinking_start/thinking/thinking_done/plan` 事件 | `_supervisor_node_impl()` 调用 `model.ainvoke()`，显式 `yield make_thinking_start/make_thinking/make_thinking_done/make_plan` || 子 Agent 调用 | `LocalDispatcher` / `ACPDispatcher` 接口，各有 `stream()` 方法 | `SubAgentTool(BaseTool)` / `ACPSubAgentTool(BaseTool)`，作为 LangChain Tool 在 `create_react_agent` 中调用 || 审计          | 无（仅 `summarizer.py` 做多步汇总）                          | `_review_node_impl()` 用 `AUDITOR_PROMPT` LLM 审计 + `planner.save_experiences()` 存到 `memory/experiences.md` || 重试          | 无                                                           | `execute_node_impl` 每步 retry 1 次                          || 事件桥接      | 直接 `yield`                                                 | `asyncio.Queue` → `run()` 消费队列                           |### 1.2 逐个文件差异#### 新增文件（备份中没有）| 文件                              | 行数 | 说明                                                  || --------------------------------- | ---- | ----------------------------------------------------- || `src/agent/orchestrator/tools.py` | 123  | `SubAgentTool` / `ACPSubAgentTool` 基于 Tool 的包装器 || `src/agent/tools/load_skill.py`   | —    | 按需加载 skill 的工具                                 || `tests/test_abort.py`             | —    | 中止/取消测试                                         || `tests/test_acp_tools.py`         | —    | ACP 工具集成测试                                      |#### 修改文件##### `src/agent/orchestrator/core.py` — **完全重写****备份** (227 行): 过程式 `stream()` → `Planner.stream()` plan → `make_dispatcher()` dispatch → `summarize_stream()` summary**当前** (395 行，+168): 3 节点 StateGraph```pythonclass GraphState(TypedDict):    messages: list[BaseMessage]    plan_text: str    steps: list[dict]    results: list[dict]    errors: list[dict]    review: strgraph = StateGraph(GraphState)graph.add_node("supervisor", supervisor_node)graph.add_node("execute", execute_node)graph.add_node("review", review_node)graph.add_edge("supervisor", "execute")graph.add_edge("execute", "review")graph.add_conditional_edges("review", lambda s: "end" if s.get("review") else "execute")```关键函数：- `_supervisor_node_impl()` — `model.ainvoke()`，产出 thinking_start/thinking/thinking_done/plan 事件- `_parse_plan(text)` — 正则 `r"^\s*[-*]\s*(\w+)\s*[:：]\s*(.+)"` 解析 plan- `_execute_node_impl(state)` — 逐个执行 steps，dispatch SubAgentTool/ACPSubAgentTool，track running tools，push task_update- `_review_node_impl(state)` — `AUDITOR_PROMPT` + model.ainvoke()，存 experiences，push audit_summary- `run(task, history, summary)` — 消费 asyncio.Queue，yield 事件##### `src/agent/orchestrator/planner.py` — **简化****备份** (195 行): `_build_prompt()` + `stream()` + `parse_plan()` 全部在 Planner 类中**当前** (103 行，-92): 仅保留 `load_experiences()` / `save_experiences()` / `build_agent_descriptions()` / `_convert_history()`计划生成已移至 `core.py` 的 `_supervisor_node_impl()`。##### `src/agent/orchestrator/_events.py` — +1 行添加 `make_audit_summary` 和 `EventType` 导入。##### `src/agent/orchestrator/dispatcher.py` — **增强****备份** (205 行): 基础版本**当前** (238 行，+33):- `LocalDispatcher.stream()`: 添加 `recursion_limit=200`、`try/except` 错误处理- `ACPDispatcher.stream()`: 添加连接时间测量、"正在连接..." thinking 事件、agent_id 查找回退、`previous_results → context`##### `src/agent/events.py` — +审计事件- 添加 `AUDIT_SUMMARY: Final[str] = "audit_summary"` 事件类型- 添加 `make_audit_summary(agent_name, data)` 工厂函数- events 架构表新增 `audit_summary` 行- `EventType` enum 包含 `AUDIT_SUMMARY`##### `src/agent/prompts/system_prompt.py` — **提示词重构****备份**: `SUPERVISOR_PROMPT`（硬编码 agent 列表）+ `SUPERVISOR_PROMPT_TEMPLATE`**当前**:- `SUPERVISOR_PLAN_PROMPT` — 使用 `{agent_descriptions}` + `{experiences}` 占位符，`{{task}}`（转义），语言无关响应- `EXECUTE_PLAN_PROMPT` (新增) — 执行计划提示词- `AUDITOR_PROMPT` (新增，中文) — 审计提示词，要求用中文输出结构化审计报告（总结/各 Agent 结果/问题与经验/对未来会话建议）##### `src/agent/agent/core.py` — **惰性加载重构****备份**: `__init__` 中急切初始化 `self.tools = TOOLS`, `self.compressor`, `self.agent_graph`**当前**: 惰性加载- `self._tools = None` → `_ensure_tools()` 首次调用时 `get_tools()`- `self._prompt = None` → `_ensure_prompt()` 首次调用时格式化 SYSTEM_PROMPT- `self._graph = None` → `_ensure_graph()` 首次调用时 `create_agent()`- 导入从 `from src.agent.tools import TOOLS` 改为 `from src.agent.tools import get_tools`##### `src/agent/tools/__init__.py` — **热重载****备份**: 静态 `TOOLS = _load_tools_from_config()`**当前**: `get_tools()` 每次通过 ConfigManager 惰性读取（支持热重载）；`TOOLS = get_tools()` 变为函数调用别名##### `src/agent/models.py` — +日志添加 `import logging`、`logger = logging.getLogger(__name__)`、`[LLM MODEL]` 日志##### `src/agent/skills.py` — **输出格式变更****备份**: 输出完整 skill 内容 `## {name}\n{content}`**当前**: 输出 `[Available Skills]` 摘要列表 `- {name}: {description}`，指示 LLM 使用 `load_skill` 工具按需加载；支持按 `agent_id` 过滤##### `src/agent/acp_agent.py` — +权限 +thinking_start- 添加 `resolve_permission(self, req_id, option_id)` 方法- ACP run 开始时先 yield `thinking_start` 事件- 处理 `permission_request` 事件（添加 agent_id 后 yield）- +15 行（193 vs 178）##### `src/agent/acp_client.py` — +permission_request- `AgentEvent` 的 `type` docstring 添加 `"permission_request"`- `_map_acp_event()` 添加 `elif event.type == "permission_request":` 映射##### `src/agent/acp/client.py` — **大幅扩展****备份** (385 行): 基础 ACP 客户端**当前** (648 行，+263):- `__init__` 添加 `cwd` 参数、`_pending_permissions` dict- 添加 `_send_response()` / `_log_notification()` / `load_session()` / `create_session()`- `prompt()` 重写：5s 轮询、last_event_time、permission_request 处理、空闲检测、try/except TimeoutError + CancelledError- 新增 `_execute_tool()` → `_tool_read()` / `_tool_write()` / `_tool_edit()` / `_tool_bash()` / `_tool_glob()` / `_tool_grep()`- `_parse_notification()` 扩展：`tool_call` 拆分为 `tool_call` + `tool_call_update`（in_progress/completed/failed）- 添加 `resolve_permission()`##### `src/agent/db/__init__.py` — +reconcile_session_tasks导出 `reconcile_session_tasks`（来自 `db/tasks`）##### `src/agent/db/tasks.py` — +reconcile_session_tasks新增 `reconcile_session_tasks(session_id)` 函数，将 session 中 `running`/`pending` 任务标记为 `failed`（用于会话恢复）##### `server.py` — +权限端点 +finally 协调**备份** (1123 行) **当前** (1160 行)：| 差异                                | 说明                                                         || ----------------------------------- | ------------------------------------------------------------ || 导入                                | 新增 `reconcile_session_tasks` 导入                          || `PermissionResponseRequest`         | 新增 Pydantic model                                          || `POST /chat` finally                | 新增 `if not _saved` 保存 + `reconcile_session_tasks(session_id)` || `GET /chat/stream` finally          | 新增 `if not _saved` 保存 + `reconcile_session_tasks(sid)`   || `POST /api/orchestrate` finally     | 新增 `_save_accumulated()` + `reconcile_session_tasks(session_id)` || `POST /api/acp/permission-response` | **新增端点** — 解析 ACP 权限请求                             |##### `tests/test_supervisor.py` — **完全重写****备份** (347 行): Mock `model.astream()`，测试 Planner + Dispatcher 路径**当前** (414 行，+67): Mock `model.ainvoke()` + StateGraph 模拟- `_make_chunk` 使用 `MagicMock(spec=object)`（仅 content，无 additional_kwargs）- `_make_model_response()` 同步返回 mock- 测试: `test_run_produces_plan_audit_metrics_done`、`test_events_in_correct_order`（plan → audit_summary）、`test_execute_node_retries_on_error`、`test_execute_node_skips_unknown_agent`、`test_audit_summary_contains_results`、`test_planner_builds_agent_descriptions`、`test_planner_converts_history`、`test_run_acp_agent_dispatch`---## 第二部分：前端 Vue/TS### 2.1 架构区别备份使用**索引字典 + 辅助函数**管理消息槽；当前使用**统一的 `ensureAssistant(agentName)`**，按 agentName 从后向前扫描复用消息。| 维度       | 备份版本                                                     | 当前版本                                           || ---------- | ------------------------------------------------------------ | -------------------------------------------------- || 消息槽定位 | `ensureAgentMsg(agentName)` + `ensureSupervisorMsg()` + 两套索引 | 统一 `msg.ensureAssistant(agentName)`              || 事件流     | `pushPlan()` 创建新 div                                      | `plan` 写入已有 supervisor div                     || 审计摘要   | 无                                                           | `audit_summary` 事件 + `setAuditSummary()`         || 权限对话框 | 无                                                           | `PermissionDialog.vue` + `permission_request` 事件 || 测试框架   | 无 vitest                                                    | `vitest` + 2 个测试文件（11 个测试）               |### 2.2 逐个文件差异#### 新增文件（备份中没有）| 文件                                     | 说明                               || ---------------------------------------- | ---------------------------------- || `ui/src/components/PermissionDialog.vue` | ACP 权限请求对话框（固定全屏浮层） || `ui/src/utils/api/sse.test.ts`           | SSE 流处理单元测试                 |#### 修改文件##### `ui/src/utils/streamManager.ts` — **重大重构****备份**: 使用 `supervisorMsgIdx` + `agentMsgIndices` 两套索引；`plan` → `pushPlan()` 创建新 div**当前**: 统一 `msg.ensureAssistant(agentName)`具体差异：- **导入**: 新增 `PermissionRequest` 类型引入- **状态**: 新增 `permissionRequest` ref；移除 `_lastAgent`- **`_setSessionStatus`**: 新增 session 不在本地列表时 `unshift` 创建- **`sendOrchestrate`**:  - 移除 `supervisorMsgIdx` / `agentMsgIndices` / `ensureSupervisorMsg` / `ensureAgentMsg`  - 所有事件用 `msg.ensureAssistant(agentName)` 获取消息索引  - `plan` 事件：`msg.ensureAssistant('supervisor')` → 直接设 `content=planText` + 清 thinking + 停 typewriter（不再调用 `pushPlan`）  - `tool_call` 事件：新增 result/completed 分支（标记 pending/running → done + `clearCompletedToolCalls()`）  - `message` 事件：用 `_enqueueStep` + `appendContent`（备份为直接 `setContent`）  - `task_update` 事件：用 `msg.ensureAssistant(update.agent)` 替代 `agentMsgIndices`  - 新增 `audit_summary` 事件处理  - 新增 `permission_request` 事件处理  - finally 块：迭代所有 assistant 消息标记 done（备份用 `agentMsgIndices` 字典）- **`sendACP`**: 添加 `_appendLog` 调试日志、`permission_request` 处理、finally 块清理 `permissionRequest`- **`abort`**: 保留 `msg.reconcileStreamEnd()` 调用- **`send`**: 移除 `_lastAgent` 逻辑- 返回对象新增 `permissionRequest`##### `ui/src/utils/messageManager.ts`- 新增 `auditSummary` ref + `setAuditSummary(text)` + `clearCompletedToolCalls()`- `setMetrics()` 改为增量合并 tokens（`{ ...prev.tokens, ...data.tokens }`）- `clear()` / `resetTaskItems()` 新增 `auditSummary.value = null`- `reconcileStreamEnd()` 新增 toolCalls 清理逻辑（pending/running → done + `clearCompletedToolCalls()`）##### `ui/src/stores/chat.ts`- Pinia store 暴露新增 `auditSummary: msg.auditSummary`、`permissionRequest: stream.permissionRequest`##### `ui/src/components/ChatTab.vue`- **导入**: 新增 `PermissionDialog` 导入- **消息过滤条件**: `msg.content || msg.toolCalls?.length || msg.thinking || msg.isThinking`- **模板**: 新增 `<PermissionDialog>` 区块（`.input-zone` 之上）- **`.input-zone`**: `InputBar` 传递 `permissionPending` prop- **样式**: 保留 `.input-zone` CSS##### `ui/src/components/InputBar.vue`- **Props**: 新增 `permissionPending?: boolean`- **模板**: input 添加 `:disabled="permissionPending"`；占位符根据 `permissionPending` 切换##### `ui/src/components/TopologyBar.vue`- `agentLabel` computed 恢复（从 `chat.taskItems` 取第一个非 supervisor 的 agent 名称）- `watch(supState)` 恢复完整逻辑##### `ui/src/components/ThinkingPanel.vue`- `activeAgent` computed 恢复（取最后一条 thinking 数据块的 agent）- 模板标题用 `activeAgent` 而非硬编码##### `ui/src/components/MonitorPanel.vue`- 导入恢复 `useSessionsStore`- 计时器用 `watch(sessionsStore.activeSessionId)` 而非固定时间- 模板恢复审计摘要区块（`chat.auditSummary`）##### `ui/src/components/ToolCallBlock.vue`- `toolIcon` 图标映射不同- CSS 差异：`.tool-call-block` 从 `margin: 3px 0 3px 38px` → `width: 100%` / `margin-left: 0`；紫色主题 → 默认主题##### `ui/src/components/message/AgentMessage.vue`- 工具调用状态: `tc.status || (isTyping && j === msg.toolCalls!.length - 1 ? 'running' : 'done')`（备份为 `!isTyping ? 'done' : ...`）- `.tool-calls` CSS 恢复 `width: 100%` + `align-items: flex-start`##### `ui/src/utils/api/types.ts`- 新增 `PermissionRequest` 接口定义（`req_id`, `session_id`, `toolCall`, `options`）##### `ui/package.json`- **scripts**: 新增 `"test": "vitest run"`、`"test:watch": "vitest"`- **devDependencies**: 新增 `"vitest": "^4.1.8"`##### `ui/vite.config.ts`- 新增 `/// <reference types="vitest" />` 指令- 新增 `test` 配置块（`environment: 'node'`, `include: ['src/**/*.test.ts']`）---## 第三部分：配置/文档| 文件                 | 差异                                                         || -------------------- | ------------------------------------------------------------ || `config/agents.json` | 3 处 desc 中文润色（direct/opencode/claude）；`load_skill` 工具条目存在于当前、不在备份 || `config/tools.json`  | 当前版本包含 `load_skill` 工具配置；备份中无                 || `AGENTS.md`          | 备份已精简：去掉副标题、删命令行、更新测试计数 55→69、删 StateGraph gotchas 6 条、删 ACP anti-pattern 整节 |---## 第四部分：恢复步骤（备份 → 当前）### 4.1 后端 Python```bash# 1. 新增文件# src/agent/orchestrator/tools.py#   → SubAgentTool(BaseTool), ACPSubAgentTool(BaseTool)#   → 使用 create_react_agent 构建 sub-agent，dispatch ACP 时用 get_acp_agent()## src/agent/tools/load_skill.py#   → load_skill tool，通过 ConfigManager 读取 skill 内容# 2. 替换文件# src/agent/orchestrator/core.py#   → 备份的流水线替换为 3 节点 StateGraph#   → 添加 _supervisor_node_impl / _execute_node_impl / _review_node_impl#   → 添加 _parse_plan() 正则解析#   → run() 改为 asyncio.Queue + graph.ainvoke()## src/agent/orchestrator/planner.py#   → 删除 _build_prompt(), stream(), parse_plan()#   → 保留 load_experiences(), save_experiences(), build_agent_descriptions(), _convert_history()## src/agent/orchestrator/_events.py#   → 添加 make_audit_summary 导入## src/agent/orchestrator/dispatcher.py#   → LocalDispatcher: 添加 recursion_limit=200 + try/except#   → ACPDispatcher: 添加连接时间 + "正在连接..." event + agent_id 回退## src/agent/events.py#   → 添加 AUDIT_SUMMARY 事件类型 + make_audit_summary()#   → EventType 包含 AUDIT_SUMMARY## src/agent/prompts/system_prompt.py#   → 备份的 SUPERVISOR_PROMPT + SUPERVISOR_PROMPT_TEMPLATE#   → 替换为 SUPERVISOR_PLAN_PROMPT + EXECUTE_PLAN_PROMPT + AUDITOR_PROMPT(中文)## src/agent/agent/core.py#   → 急切初始化 → 惰性加载（_ensure_tools/_ensure_prompt/_ensure_graph）#   → TOOLS → get_tools()## src/agent/tools/__init__.py#   → 静态 TOOLS → 函数 get_tools()（ConfigManager 惰性读取）## src/agent/skills.py#   → get_skills_prompt() 输出格式改为 [Available Skills] 摘要## src/agent/acp_agent.py#   → 添加 resolve_permission()#   → 添加 thinking_start 事件#   → 处理 permisson_request## src/agent/acp_client.py#   → AgentEvent type 添加 "permission_request"#   → _map_acp_event() 添加映射## src/agent/acp/client.py#   → 大幅扩展：_send_response, _log_notification, load_session#   → prompt() 重写：5s 轮询, permission_request 处理#   → 新增 _execute_tool + 6 个工具方法#   → _parse_notification 扩展#   → resolve_permission()## src/agent/db/__init__.py#   → 导出 reconcile_session_tasks## src/agent/db/tasks.py#   → 添加 reconcile_session_tasks()## server.py#   → 导入 reconcile_session_tasks#   → 添加 PermissionResponseRequest#   → 3 个 SSE 端点 finally 块添加 reconcile_session_tasks()#   → 添加 POST /api/acp/permission-response 端点## tests/test_supervisor.py#   → 完全替换：mock model.ainvoke() + StateGraph 测试```### 4.2 前端 Vue/TS```bash# 1. 新增文件# ui/src/components/PermissionDialog.vue# ui/src/utils/api/sse.test.ts# 2. 替换文件# ui/src/utils/streamManager.ts#   → 删除: supervisorMsgIdx, agentMsgIndices, ensureSupervisorMsg(), ensureAgentMsg()#   → 修改: 所有事件 handler 用 msg.ensureAssistant(agentName)#   → plan handler: 删 pushPlan() → msg.ensureAssistant('supervisor') + 设 content + 停 typewriter#   → tool_call handler: 添加 result/completed 分支 + clearCompletedToolCalls()#   → message handler: _enqueueStep + appendContent#   → task_update handler: msg.ensureAssistant(update.agent)#   → 新增: audit_summary / permission_request 事件处理#   → finally: 迭代所有 assistant 消息#   → sendACP: 添加 _appendLog / permission_request / finally 清理#   → abort: 保留 reconcileStreamEnd()#   → 返回: 添加 permissionRequest## ui/src/utils/messageManager.ts#   → 添加 auditSummary ref + setAuditSummary() + clearCompletedToolCalls()#   → setMetrics() 增量合并 tokens#   → reconcileStreamEnd() 添加 toolCalls 清理## ui/src/stores/chat.ts#   → 添加 auditSummary / permissionRequest 暴露## ui/src/components/ChatTab.vue#   → 消息过滤: 恢复 thinking/isThinking 条件#   → 模板: 添加 PermissionDialog#   → input-zone: 恢复 .input-zone div + permissionPending prop## ui/src/components/InputBar.vue#   → 添加 permissionPending prop + 禁用/占位符逻辑## ui/src/components/MonitorPanel.vue#   → 恢复 sessionsStore 导入 + watch 计时器#   → 恢复 auditSummary 区块## ui/src/components/ToolCallBlock.vue#   → 回退 margin 到 0 / width 100%#   → 默认主题（非紫色）## ui/src/components/message/AgentMessage.vue#   → tool_call status 逻辑回退#   → .tool-calls CSS 恢复 width 100%## ui/src/utils/api/types.ts#   → 添加 PermissionRequest 接口## ui/package.json#   → 添加 vitest devDependency + test scripts## ui/vite.config.ts#   → 添加 vitest reference + test 配置# 3. 配置# config/agents.json: 添加 load_skill 工具引用（可选）# config/tools.json: 添加 load_skill 工具配置```### 4.3 验证```bash# 后端cd <project_root>pytest tests/test_supervisor.py -v            # 20 testsruff check .                                  # 仅预存 E501# 前端cd uinpm install                                    # 安装 vitestnpx vitest run                                 # 11 testsnpx vue-tsc --noEmit                           # type-check clean```---## 附录：关键差异速查表| 备份中的写法                        | 当前写法                                                   || ----------------------------------- | ---------------------------------------------------------- || `ensureAgentMsg(name)`              | `msg.ensureAssistant(name)`                                || `ensureSupervisorMsg()`             | `msg.ensureAssistant('supervisor')`                        || `msg.pushPlan(planText)`            | `msg.ensureAssistant('supervisor')` + `content = planText` || `agentMsgIndices[name]`             | `msg.ensureAssistant(name)`                                || `supervisorMsgIdx`                  | 删除，统一用 `msg.ensureAssistant('supervisor')`           || `audit_summary` 不处理              | `msg.setAuditSummary(data)`                                || `permission_request` 不处理         | `permissionRequest.value = data`                           || `from src.agent.tools import TOOLS` | `from src.agent.tools import get_tools`                    || 静态 `TOOLS`                        | 函数 `get_tools()` 热重载                                  || `model.astream()` plan              | `model.ainvoke()` plan                                     || `LocalDispatcher.stream()`          | `SubAgentTool._arun()`                                     || 无 reconcile                        | `reconcile_session_tasks(session_id)`                      || `make_summary` 汇总                 | `AUDITOR_PROMPT` + `make_audit_summary`                    |bash