# LangGraph Agent v2

基于 LangChain + FastAPI 的多智能体 AI 系统，支持 Supervisor 编排、实时 SSE 流式传输、上下文压缩、双重记忆（SQLite + ChromaDB），以及 ACP 协议集成外部编码代理（OpenCode / Claude Code）。

## 项目亮点

### 🧠 多智能体协作编排

Supervisor 模式采用 **think → plan → dispatch → summarize** 四阶段流程：LLM 自主思考并生成执行计划，按能力分派给 coder / researcher / analyst / direct 等专业子代理，每个子代理拥有独立的工具集、模型配置和系统提示词，最终汇总结果。支持单任务直达（跳过 summarize）和多步骤并行调度。

### 🔌 ACP 协议集成

通过 Agent Client Protocol（JSON-RPC 2.0 over stdio）将外部编码代理（OpenCode、Claude Code）无缝接入。ACP 代理拥有完整的会话生命周期管理，支持原生 ACP 模式和 run-mode fallback。前端可通过 `@agent` 直接调用，Supervisor 也可在计划中调度。

### 📡 实时 SSE 流式架构

基于 Server-Sent Events 的全链路实时通信：
- 服务端 `_passthrough` batching 减少网络开销
- 前段背压队列（MICRO/STEP/MACRO 三级）+ typewriter RAF 调度
- 11 种结构化事件类型（thinking / tool_call / message / plan / task_update / metrics 等）
- 双打字机动画系统（消息 + 思考过程独立）

### 🗜️ 智能上下文压缩

当 token 用量超过阈值（默认 70%）时自动触发：保留最近 3 轮对话（human+ai 配对），通过 LLM 将历史压缩为结构化摘要，注入系统提示词的 `[Previous Conversation Summary]` 区域。支持 `/compact` 手动触发。

### 💾 双重记忆系统

- **SQLite**：结构化元数据存储（会话、消息、工具使用记录）
- **ChromaDB**：向量相似度搜索，支持语义检索

### ⚡ 动态配置热加载

所有代理、工具、技能、ACP 配置均存储在 JSON 文件中，`ConfigManager` 每 5 秒轮询文件变更并自动重载。

### 🎨 现代化前端体验

Vue 3 + Pinia + TypeScript，组合式函数拆分：
- `useMessageManager` — 全部消息状态变更
- `useStreamManager` — 3 条发送路径 + 取消 + typewriter + 背压
- `useChatStore` — Pinia 封装，委托给两个 composable

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
| `config/agents.json` | 代理定义（模型、工具、系统提示词、温度） |
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
│  Agent (单代理)     Orchestrator (多代理编排)              │
│  ReAct 循环          plan → dispatch → summarize          │
│  astream_events      coder/researcher/analyst/direct      │
│                                                          │
│  ACP Agent (外部 CLI)    _passthrough SSE batching        │
│  JSON-RPC 2.0 over stdio  实时事件转发 + 持久化           │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  Context: Compression · Memory (SQLite + ChromaDB)       │
│  ConfigManager (5s hot-reload) · Skills injection         │
├──────────────────────────────────────────────────────────┤
│  SQLite (sessions/messages/task_updates/tool_usage)      │
│  ChromaDB (vector similarity search)                     │
└──────────────────────────────────────────────────────────┘
```

### 后端包结构

```
src/agent/
├── events.py                    # EventType + make_event 工厂
├── message.py                   # Message dataclass
├── config.py                    # AgentConfig (.env)
├── config_manager.py            # 热加载 JSON 配置
├── models.py                    # resolve_model()
├── agent/                       # 单代理 ReAct 循环
│   ├── core.py                  # astream_events 解析
│   └── streaming.py             # 文件引用提取
├── db/                          # 持久化层
│   ├── connection.py            # SQLite 连接 + schema 迁移
│   ├── sessions.py              # 会话 CRUD
│   ├── messages.py              # 消息 CRUD
│   ├── tasks.py                 # 任务更新（去重）
│   ├── tools.py                 # 工具使用统计
│   └── compact.py               # 会话压缩
├── orchestrator/                # 多代理编排
│   ├── core.py                  # Orchestrator 管道
│   ├── planner.py               # Plan 生成 + 解析
│   ├── dispatcher.py            # Local + ACP dispatcher
│   └── summarizer.py            # 多代理结果汇总
└── acp_agent.py                 # ACP 代理包装
```

### SSE 事件类型

| 事件 | 来源 | 说明 |
|------|------|------|
| `thinking_start` | Agent | LLM 推理开始 |
| `thinking` | Agent | 推理内容增量 |
| `thinking_done` | Agent | 推理完成 |
| `tool_call` | Agent/Orchestrator | 工具调用 |
| `message` | Agent/Orchestrator | 最终响应 |
| `plan` | Orchestrator | 执行计划 |
| `task_update` | Orchestrator | 子代理任务状态更新 |
| `summary` | Orchestrator | 多代理结果汇总 |
| `metrics` | Any | Token 用量和耗时 |
| `error` | Any | 错误事件 |
| `done` | Any | 流完成 |

## 开发

```bash
# 后端
pip install -e ".[dev]"
pytest --cov=src -v              # 69 测试 + 覆盖率
pytest -k "test_name"            # 单个测试
ruff check .                     # Lint
ruff check --fix .               # 自动修复

# 前端
cd ui
npm run dev                      # Vite 开发服务器 (port 3000)
vue-tsc -b && vite build         # 生产构建
```

### 测试说明
- `tests/conftest.py` 自动隔离环境变量（mock key、临时 DB 路径）— 无需真实 API Key
- Orchestrator 测试 mock `resolve_model` 通过 `unittest.mock.patch("src.agent.models.resolve_model")`
- 标记：`unit`、`integration`、`slow`（定义在 `pyproject.toml`）

## API 接口

### 聊天与流式

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/chat` | SSE 流，单代理 |
| `POST` | `/api/orchestrate` | SSE 流，多代理编排 |

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
| 代理引擎 | `create_agent` (ReAct) |
| 编排器 | 自定义 Orchestrator (plan→dispatch→summarize) |
| ACP 协议 | JSON-RPC 2.0 over stdio |
| 服务端 | FastAPI + sse-starlette + uvicorn |
| 前端 | Vue 3 + Pinia + Vite + TypeScript |
| Markdown | marked + highlight.js + KaTeX |
| 存储 | SQLite + ChromaDB |
| 配置 | Pydantic Settings (.env) + JSON 热加载 |

## 注意事项

- `python server.py --reload` 在 Windows 上可能失败（uvicorn 热重载兼容问题）
- `tests/conftest.py` 自动隔离环境变量 — 测试无需真实 API Key
- 前端的 message `toolCalls` 类型定义在 `api/types.ts`；所有消息操作走 `messageManager`，禁止本地引用
- 导入 `resolve_model` 必须用 `from src.agent import models as _models; _models.resolve_model()`（否则 mock 失效）
