# LangGraph Agent v2

基于 LangChain + LangGraph + FastAPI 的多智能体协作系统，支持 6 节点 StateGraph 编排、实时 SSE 流式传输、上下文压缩、双重记忆（SQLite + ChromaDB）、ACP 协议集成外部编码代理（OpenCode / Claude Code）。

## 项目亮点

### 🧠 6 节点 StateGraph 编排

Supervisor 采用 LangGraph **StateGraph** 六阶段流程：

```
perceive → plan → wait → dispatch → synthesize → reflect
```

- **perceive**: 收集对话历史与上轮结果，构建上下文摘要
- **plan**: LLM 自主生成结构化 JSON 计划（含步骤、依赖关系、推理说明）
- **wait**: 支持 HITL（Human-in-the-Loop）中断审核
- **dispatch**: 按 DAG 依赖图并行/串行执行子代理，上游结果自动注入下游 Context
- **synthesize**: Review 节点审计，输出审计报告（含所有 agent 原始产物）
- **reflect**: 反模式检测，记录经验到 `memory/experiences.md`

子代理包括 coder、researcher、analyst、verifier、direct，以及 ACP 外部代理（OpenCode / Claude Code）。

### 🔌 ACP 协议集成

通过 Agent Client Protocol（JSON-RPC 2.0 over stdio）将外部编码代理无缝接入。支持会话生命周期管理，前端通过 `@agent` 直接调用，Supervisor 也可在计划中调度。

### 📡 实时 SSE 流式架构

基于 Server-Sent Events 的全链路实时通信：

- 服务端 `_passthrough` batching 减少网络开销
- 前端背压队列（MICRO/STEP/MACRO 三级）+ typewriter RAF 调度
- 12 种结构化事件类型
- 双打字机动画系统（消息 + 思考过程独立）
- 审计摘要附带所有 agent 原始输出（`agent_outputs` 字段）

### 🗜️ 智能上下文压缩

当 token 用量超过阈值（默认 70%）时自动触发：保留最近 `keep` 轮对话，通过 LLM 将历史压缩为结构化摘要。支持 `/compact` 手动触发。

### 💾 双重记忆系统

- **SQLite**: 结构化元数据存储（会话、消息、工具使用记录、审计摘要）
- **ChromaDB**: 向量相似度搜索

### ⚡ 动态配置热加载

所有代理、工具、技能、ACP 配置均存储在 `config/*.json` 中，`ConfigManager` 每 5 秒轮询变更并自动重载（`agents.json`、`tools.json`、`skills.json`、`acp_agents.json`）。

### 🚦 错误弹性

- 子代理输出截断自动重试（`tools.py:_is_truncated`）
- 熔断器（circuit breaker）防止连续失败雪崩
- 结构化错误信封统一错误处理

## 快速开始

### 后端

```bash
cp .env.example .env
# 编辑 .env 填入 API Key

pip install -e ".[dev]"
python server.py
# → http://localhost:8000
```

### 前端

```bash
cd ui
npm install
npm run dev
# → http://localhost:3000 (代理 API 到 :8000)
```

### CLI

```bash
# 单条消息
python -m src.agent.main --input "What is 2+2?"

# 交互模式
python -m src.agent.main --interactive
```

## 配置

### 环境变量 (`.env`)

```bash
# 模型配置
AGENT_MODEL_PROVIDER=openai       # openai | anthropic
AGENT_MODEL_NAME=gpt-4o

# API Key
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=sk-ant-xxx

# 上下文
AGENT_MAX_TOKENS=128000
AGENT_COMPRESSION_THRESHOLD=0.7
AGENT_ENABLE_THINKING=true        # DashScope/GLM/DeepSeek 设为 false

# 存储
AGENT_MEMORY_DB_PATH=memory/agent.db
AGENT_CHROMA_PATH=memory/chroma

# 服务端
AGENT_SERVER_HOST=0.0.0.0
AGENT_SERVER_PORT=8000
```

支持任何 OpenAI 兼容 API（DeepSeek、DashScope、GLM 等），通过 `OPENAI_BASE_URL` 配置。

### JSON 配置文件（5 秒热加载）

| 文件 | 用途 |
|------|------|
| `config/agents.json` | 代理定义（模型、工具、系统提示词、温度、ACP 模式） |
| `config/tools.json` | 工具模块路径和元数据 |
| `config/skills.json` | 技能到代理的映射 |
| `config/acp_agents.json` | 外部 CLI 代理配置（命令、参数、超时、工作目录） |

## 技术架构

```
┌──────────────────────────────────────────────────────────┐
│  Vue 3 + Pinia Frontend (port 3000)                      │
│  messageManager + streamManager composables              │
│  Chat · Agents · Files · Memory · SSE EventSource        │
└─────────────────────┬────────────────────────────────────┘
                      │ HTTP / SSE
┌─────────────────────▼────────────────────────────────────┐
│  FastAPI Server (port 8000)                               │
│  /chat  /api/orchestrate  /api/acp/send  /api/*           │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Agent (单代理)     Orchestrator (多代理 StateGraph)       │
│  ReAct 循环          6 节点: perceive→plan→wait→          │
│  astream_events     dispatch→synthesize→reflect           │
│                                                          │
│  ACP Agent (外部 CLI)    _passthrough SSE batching        │
│  JSON-RPC 2.0 over stdio  实时事件转发 + 持久化           │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  Context: Compression · Memory (SQLite + ChromaDB)       │
│  ConfigManager (5s hot-reload) · Skills injection         │
│  Error handler (circuit breaker + retry)                 │
├──────────────────────────────────────────────────────────┤
│  SQLite (sessions/messages/task_updates/metrics)         │
│  ChromaDB (vector similarity search)                     │
└──────────────────────────────────────────────────────────┘
```

### 后端包结构

```
src/agent/
├── events.py                    # EventType + make_event 工厂
├── message.py                   # Message dataclass
├── config.py                    # AgentConfig (.env)
├── config_manager.py            # 热加载 JSON 配置（5s 轮询）
├── models.py                    # resolve_model()
├── agent/                       # 单代理 ReAct 循环
│   └── core.py
├── db/                          # 持久化层
│   ├── connection.py            # SQLite + auto-migration
│   ├── sessions.py              # 会话 CRUD + audit_summary
│   ├── messages.py              # 消息 CRUD
│   ├── tasks.py                 # 任务更新（去重）
│   ├── tools.py                 # save_metrics / load_metrics
│   └── compact.py               # 会话压缩
├── orchestrator/                # 多代理编排（StateGraph）
│   ├── core.py                  # 6 节点 StateGraph
│   ├── planner.py               # Pydantic 模型 + 计划辅助
│   ├── tools.py                 # SubAgentTool + ACPSubAgentTool
│   └── _events.py               # 事件重导出
├── acp_agent.py                 # ACP 代理包装
├── acp/                         # ACP 原生客户端
│   └── client.py                # ACPNativeClient（JSON-RPC 2.0）
├── context/                     # 上下文管理
│   ├── compression.py           # ContextCompressor
│   ├── memory.py                # SQLite + ChromaDB 双写
│   ├── _helpers.py
│   └── tool_result_manager.py
├── tools/                       # 5 个内置工具
│   ├── execute_code.py          # Python 沙箱执行
│   ├── file_ops.py              # 读写文件 + 列表目录
│   ├── search.py                # glob 搜索
│   └── load_skill.py            # 技能加载
├── error_handler.py             # 错误重试 + 熔断
├── file_service.py              # 文件浏览服务
├── skills.py                    # 技能管理器
├── audit_logger.py              # 审计日志
└── prompts/                     # 系统提示词
    └── system_prompt.py         # SUPERVISOR_PLAN_PROMPT_V2 etc
```

### SSE 事件类型

| 事件 | 来源 | 说明 |
|------|------|------|
| `thinking_start` | Agent/Orchestrator | LLM 推理开始 |
| `thinking` | Agent/Orchestrator | 推理内容增量 |
| `thinking_done` | Agent/Orchestrator | 推理完成 |
| `tool_call` | Agent/Orchestrator | 工具调用 |
| `message` | Agent/Orchestrator | 最终响应 |
| `plan` | Orchestrator | 执行计划（含 steps 数组） |
| `task_update` | Orchestrator | 子代理任务状态（pending/running/completed/failed）|
| `summary` | Orchestrator | 多代理结果汇总 |
| `audit_summary` | Orchestrator | 审计报告 + `agent_outputs`（所有 agent 原始输出）|
| `metrics` | Any | Token 消耗和耗时 |
| `interrupt` | Orchestrator | HITL 中断（含 thread_id + plan） |
| `permission_request` | Orchestrator | 工具调用权限请求 |
| `error` | Any | 错误事件 |
| `done` | Any | 流完成 |

### 可用的子代理

| 代理 | 类型 | 工具 | 用途 |
|------|------|------|------|
| coder | 本地 | execute_code, read_file, write_file, search_files, load_skill | 代码生成、调试、重构 |
| researcher | 本地 | search_files, list_directory, read_file | 信息检索与文件搜索 |
| analyst | 本地 | execute_code, read_file, search_files | 数据分析与报告 |
| verifier | 本地 | read_file, search_files, list_directory, execute_code | 事实核查与引用验证 |
| direct | 本地 | 全部 5 个工具 | 直接助手，处理简单任务 |
| opencode | ACP | — | 外部 AI 编码代理 (OpenCode ACP) |
| claude | ACP | — | 外部 AI 编码代理 (Claude Code ACP) |

## 开发

```bash
# 后端
pip install -e ".[dev]"
pytest --cov=src -v              # 94 测试 + 覆盖率
pytest -k "test_name"            # 单个测试
ruff check .                     # Lint
ruff check --fix .               # 自动修复

# 前端
cd ui
npm run dev                      # Vite 开发服务器 (port 3000)
npx vue-tsc -b && npx vite build # 生产构建
```

### 测试说明
- `tests/conftest.py` 自动隔离环境变量（mock key、临时 DB 路径）— 无需真实 API Key
- Orchestrator 测试 mock `resolve_model` 通过 `from src.agent import models as _models` 模式
- Mock 模型返回预定义 JSON 计划，不调用真实 LLM

## API 接口

### 聊天与流式

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/chat` | SSE 流，单代理 |
| `GET` | `/chat/stream` | SSE 流，单代理（GET 方式，适用 EventSource） |
| `POST` | `/api/orchestrate` | SSE 流，多代理编排 |
| `POST` | `/api/orchestrate/{session_id}/review` | 提交 HITL 审核决策 |

### 会话

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/sessions` | 列出会话 |
| `POST` | `/api/sessions` | 新建会话 |
| `GET` | `/api/sessions/{id}` | 获取会话及消息 |
| `PATCH` | `/api/sessions/{id}/title` | 重命名 |
| `DELETE` | `/api/sessions/{id}` | 删除 |
| `POST` | `/api/compact` | 压缩上下文 |

### ACP 代理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/acp/agents` | 列出 ACP 代理 |
| `POST` | `/api/acp/send` | 发送消息（SSE 流） |
| `GET` | `/api/acp/check/{id}` | 可用性检查 |

### 记忆与文件

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/memory/store` | 记忆存储 |
| `POST` | `/api/memory/query` | 向量查询 |
| `GET` | `/api/files/tree` | 文件树 |
| `GET` | `/api/files/content` | 文件内容 |

## 技术栈

| 层级 | 技术 |
|------|------|
| LLM 框架 | LangChain + LangGraph |
| 代理引擎 | `create_react_agent` (ReAct) |
| 编排器 | LangGraph StateGraph (6 节点) |
| ACP 协议 | JSON-RPC 2.0 over stdio |
| 服务端 | FastAPI + sse-starlette + uvicorn |
| 前端 | Vue 3 + Pinia + Vite + TypeScript |
| Markdown | marked + highlight.js + KaTeX |
| 存储 | SQLite + ChromaDB |
| 配置 | Pydantic Settings (.env) + JSON 热加载 |

## 注意事项

- `python server.py --reload` 在 Windows 上可能失败（uvicorn 热重载兼容问题）
- `tests/conftest.py` 自动隔离环境变量 — 测试无需真实 API Key
- 导入 `resolve_model` 必须用 `from src.agent import models as _models; _models.resolve_model()`（否则 mock 失效）
- 前端 message `toolCalls` 类型定义在 `api/types.ts`；所有消息操作走 `messageManager`，禁止本地引用 alias
- 更多开发细节见 `AGENTS.md`
