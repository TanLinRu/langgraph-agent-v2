# LangGraph Agent v2

基于 LangGraph 的多智能体 AI 系统，支持 Supervisor 编排、实时 SSE 流式传输、上下文压缩、双重记忆（SQLite + ChromaDB），以及 ACP 协议集成外部编码代理（OpenCode / Claude Code）。

## 项目亮点

### 🧠 多智能体协作编排

Supervisor 模式采用 **think → plan → dispatch → summarize** 四阶段流程：LLM 自主思考并生成执行计划，按能力分派给 coder / researcher / analyst / direct 等专业子代理，每个子代理拥有独立的工具集、模型配置和系统提示词，最终汇总结果。支持单任务直达（跳过 summarize）和多任务并行调度。

### 🔌 ACP 协议集成

通过 Agent Client Protocol（JSON-RPC 2.0 over stdio）将外部编码代理（OpenCode、Claude Code）无缝接入系统。ACP 代理拥有完整的会话生命周期管理（create → prompt → stream → cancel → close），支持原生 ACP 模式和 run-mode fallback。前端可通过 `@agent` 直接调用，Supervisor 也可在计划中调度 ACP 代理。

### 📡 实时 SSE 流式架构

基于 Server-Sent Events 的全链路实时通信：
- 服务端 50 字符批处理 `thinking` 事件，减少网络开销
- 120ms 背压队列防止事件风暴
- 11 种结构化事件类型（thinking / tool_call / message / plan / task_update / metrics 等）
- 双打字机动画系统（消息 3字符/15ms，思考 2字符/15ms）

### 🗜️ 智能上下文压缩

当 token 用量超过阈值（默认 70%）时自动触发：保留最近 5 条消息，通过 LLM 将历史对话压缩为结构化摘要，注入系统提示词的 `[Previous Conversation Summary]` 区域。支持 `/compact` 手动触发。

### 💾 双重记忆系统

- **SQLite**：结构化元数据存储（会话、消息、工具使用记录）
- **ChromaDB**：向量相似度搜索，支持语义检索

通过 REST API 提供命名空间 CRUD，支持 key-value 存储和向量查询。

### ⚡ 动态配置热加载

所有代理、工具、技能、ACP 配置均存储在 JSON 文件中，`ConfigManager` 每 5 秒轮询文件变更并自动重载。支持运行时通过 REST API 增删改查代理配置，无需重启服务。

### 🎨 现代化前端体验

Vue 3 + Pinia + TypeScript 构建的三栏布局：
- **左侧边栏**：会话列表，支持搜索、状态过滤（全部/进行中/已完成）
- **中间聊天区**：消息气泡、思考过程可视化、任务进度面板
- **右侧面板**：监控指标、代理配置、工具库、文件浏览器
- **文件抽屉**：可拖拽调整宽度的代码预览浮层

支持深色/浅色主题切换，~60 个 CSS 变量驱动全局样式。

## 业务架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户交互层 (Vue 3 Frontend)                   │
│                                                                     │
│  ┌──────────┐  ┌──────────────────────┐  ┌───────────────────────┐  │
│  │  会话管理  │  │      聊天交互         │  │     监控与配置         │  │
│  │ Sidebar   │  │  ChatTab             │  │  RightPanel           │  │
│  │ ·新建会话  │  │  ·消息收发            │  │  ·Token 用量监控       │  │
│  │ ·会话搜索  │  │  ·@mention 直调      │  │  ·代理配置管理         │  │
│  │ ·状态过滤  │  │  ·/command 补全      │  │  ·工具库浏览           │  │
│  │ ·会话删除  │  │  ·思考过程可视化      │  │  ·文件浏览器           │  │
│  │           │  │  ·任务进度面板        │  │                       │  │
│  │           │  │  ·中断/取消           │  │                       │  │
│  └──────────┘  └──────────┬───────────┘  └───────────────────────┘  │
└────────────────────────────┼────────────────────────────────────────┘
                             │ HTTP / SSE
┌────────────────────────────▼────────────────────────────────────────┐
│                       服务端 (FastAPI)                               │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    路由分发层                                 │    │
│  │  /chat → 单代理    /api/orchestrate → Supervisor             │    │
│  │  /api/acp/send → ACP 代理    /api/sessions → 会话管理        │    │
│  └────────────────────────┬────────────────────────────────────┘    │
│                           │                                         │
│  ┌────────────────────────▼────────────────────────────────────┐    │
│  │                    智能体执行层                               │    │
│  │                                                             │    │
│  │  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │    │
│  │  │ Single Agent │  │  Supervisor  │  │   ACP Agent       │  │    │
│  │  │ ReAct Loop   │  │  编排调度     │  │  外部代理集成      │  │    │
│  │  │ LLM ↔ Tools  │  │  think→plan  │  │  JSON-RPC 2.0     │  │    │
│  │  │              │  │  →dispatch   │  │  OpenCode/Claude   │  │    │
│  │  │              │  │  →summarize  │  │                   │  │    │
│  │  └──────────────┘  └──────┬───────┘  └───────────────────┘  │    │
│  │                           │                                  │    │
│  │  ┌────────────────────────▼──────────────────────────────┐  │    │
│  │  │              子代理池 (config/agents.json)              │  │    │
│  │  │  coder · researcher · analyst · direct · opencode      │  │    │
│  │  │  每个子代理: 独立模型 + 工具集 + 系统提示词              │  │    │
│  │  └───────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    上下文管理层                               │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │    │
│  │  │  压缩引擎     │  │  双重记忆     │  │  会话持久化       │  │    │
│  │  │  Token 阈值   │  │  SQLite +    │  │  SQLite          │  │    │
│  │  │  LLM 摘要     │  │  ChromaDB    │  │  auto-migration  │  │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    工具与配置层                               │    │
│  │  ·5 个动态工具 (execute_code, read/write/list/search)       │    │
│  │  ·JSON 配置热加载 (5s 轮询)                                  │    │
│  │  ·技能注入 (markdown → system prompt)                        │    │
│  │  ·事件总线 (pub/sub SSE 分发)                                │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

## 功能使用指南

### 1. 单代理对话

直接在聊天框输入消息，系统自动选择当前活跃代理处理：

```
用户: 帮我写一个快速排序算法
Agent: [思考中...] [调用 execute_code] [输出结果]
```

### 2. 多代理编排（Supervisor）

发送复杂任务时，Supervisor 自动分析并分派给多个子代理：

```
用户: 分析当前项目的代码质量，找出潜在问题并生成报告
Supervisor: [思考] → [计划]
  - researcher: 搜索项目文件结构
  - analyst: 分析代码质量指标
  - coder: 修复发现的问题
→ [汇总结果]
```

### 3. @mention 直调外部代理

使用 `@agent` 语法直接调用 ACP 代理，绕过 Supervisor：

```
用户: @opencode 帮我重构 server.py 中的路由模块
OpenCode: [直接执行，流式返回结果]
```

### 4. /command 命令补全

输入 `/` 触发命令补全，支持自定义技能命令。

### 5. 中断与取消

处理过程中点击红色 ■ 按钮可中断当前任务。支持：
- 中断后发送新消息（自动覆盖）
- 消息队列（处理中的消息排队等待）

### 6. 会话管理

- **新建会话**：点击侧边栏 + 按钮
- **切换会话**：点击侧边栏会话项
- **搜索会话**：侧边栏顶部搜索框
- **状态过滤**：全部 / 进行中 / 已完成
- **删除会话**：鼠标悬停会话项，右侧滑出删除按钮

### 7. 文件浏览

右侧面板 Files 标签页浏览工作区文件树，点击文件在 FileDrawer 中预览代码（支持语法高亮）。

### 8. 代理配置管理

右侧面板 Agents 标签页查看和编辑代理配置：
- 修改模型、温度、最大 token
- 启用/禁用代理
- 编辑系统提示词
- 配置工具集

### 9. /compact 上下文压缩

当对话过长时，发送 `/compact` 手动触发上下文压缩：
- LLM 将历史消息压缩为结构化摘要
- 摘要注入系统提示词
- 原消息标记为已压缩，不在 UI 显示

## 技术架构

```
┌──────────────────────────────────────────────────────────┐
│  Vue 3 + Pinia Frontend (port 3000)                      │
│  Chat · Agents · Files · Memory · SSE EventSource        │
└─────────────────────┬────────────────────────────────────┘
                      │ HTTP / SSE
┌─────────────────────▼────────────────────────────────────┐
│  FastAPI Server (port 8000)                               │
│  /chat  /chat/stream  /api/orchestrate  /api/*            │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Single Agent              Supervisor (multi-agent)      │
│  create_agent +            think → plan → dispatch       │
│  astream_events            → collect → summarize         │
│  ReAct loop                coder/researcher/analyst/direct│
│                                                          │
│  StateGraph (alt)          ACP Agents (external CLIs)    │
│  ToolNode-based            opencode acp / claude-agent   │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  Context: Compression (70% threshold) · Memory (dual)    │
│  Checkpoint (SQLite) · Skills (markdown injection)       │
├──────────────────────────────────────────────────────────┤
│  SQLite (sessions/messages/metadata)                     │
│  ChromaDB (vector similarity search)                     │
└──────────────────────────────────────────────────────────┘
```

## SSE 事件类型

| 事件 | 来源 | 说明 |
|------|------|------|
| `thinking_start` | Agent | LLM 推理开始 |
| `thinking` | Agent | 推理内容块（服务端 50 字符批处理） |
| `thinking_done` | Agent | 推理完成 |
| `tool_call` | Agent/Supervisor | 工具调用（名称 + 参数） |
| `message` | Agent/Supervisor | 最终响应 |
| `plan` | Supervisor | 执行计划 |
| `task_update` | Supervisor | 子代理任务状态更新 |
| `summary` | Supervisor | 多代理结果汇总 |
| `metrics` | Agent/Supervisor | Token 用量和耗时指标 |
| `error` | Any | 错误事件 |
| `done` | Any | 流完成 |

事件包含 `agent_name` 和 `session_id` 字段用于多代理路由。

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

## API 接口

### 聊天与流式

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/chat` | SSE 流，单代理（JSON body） |
| `GET` | `/chat/stream` | GET 方式 SSE，用于浏览器 `EventSource` |
| `POST` | `/api/orchestrate` | SSE 流，多代理 Supervisor |

### 会话

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/sessions` | 列出会话 |
| `POST` | `/api/sessions` | 新建会话 |
| `GET` | `/api/sessions/{id}` | 获取会话及消息 |
| `PATCH` | `/api/sessions/{id}/title` | 重命名会话 |
| `DELETE` | `/api/sessions/{id}` | 删除会话 |
| `POST` | `/api/compact` | 压缩/整理会话上下文 |

### 代理（运行时 CRUD）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/agents` | 列出所有配置的代理 |
| `GET` | `/api/agents/{id}` | 获取单个代理配置 |
| `POST` | `/api/agents/{id}` | 创建或更新代理 |
| `DELETE` | `/api/agents/{id}` | 删除代理配置 |

### ACP 代理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/acp/agents` | 列出 ACP 代理及可用状态 |
| `POST` | `/api/acp/send` | 发送消息到 ACP 代理（SSE 流） |
| `GET` | `/api/acp/check/{agent_id}` | 检查 CLI 可用性 |
| `GET` | `/api/acp/sessions/{agent_id}` | 列出 ACP 会话 |
| `GET` | `/api/acp/config` | 列出 ACP 代理配置 |
| `POST` | `/api/acp/config/{id}` | 创建或更新 ACP 配置 |
| `DELETE` | `/api/acp/config/{id}` | 删除 ACP 配置 |

### 记忆

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/memory/store` | 存储 key-content 条目 |
| `POST` | `/api/memory/query` | 向量相似度查询 |
| `GET` | `/api/memory/list/{namespace}` | 列出命名空间条目 |
| `DELETE` | `/api/memory/{namespace}/{key}` | 删除条目 |

### 工具、技能与文件

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/tools` | 列出可用工具及元数据 |
| `GET` | `/api/skills` | 列出已加载技能 |
| `GET` | `/api/files/tree` | 工作区文件树 |
| `GET` | `/api/files/content` | 文件内容（带行号） |
| `POST` | `/api/config/reload` | 强制重载所有 JSON 配置 |

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查及当前模型信息 |

## 项目结构

```
├── server.py                          # FastAPI 服务端（全部接口）
├── config/
│   ├── agents.json                    # 代理定义
│   ├── tools.json                     # 工具注册表
│   ├── skills.json                    # 技能到代理映射
│   └── acp_agents.json               # 外部 CLI 代理配置
├── src/agent/
│   ├── agent.py                       # 单代理 (create_agent + astream_events)
│   ├── supervisor.py                  # 多代理 CustomSupervisor
│   ├── graph.py                       # StateGraph 变体 (ToolNode)
│   ├── config.py                      # Pydantic 设置 (.env)
│   ├── config_manager.py             # 热加载 JSON 配置管理器
│   ├── models.py                      # resolve_model() 支持代理级覆盖
│   ├── checkpoint.py                  # SQLite 会话持久化
│   ├── acp_agent.py                   # ACP 代理包装器
│   ├── acp_client.py                  # ACP 客户端（原生 + run fallback）
│   ├── acp/                           # ACP 协议实现
│   │   └── client.py                  # JSON-RPC 2.0 over stdio
│   ├── context/
│   │   ├── compression.py             # Token 感知上下文压缩
│   │   └── memory.py                  # SQLite + ChromaDB 记忆管理
│   ├── tools/                         # 动态工具实现
│   │   ├── execute_code.py            # Python 沙箱执行
│   │   ├── file_ops.py                # 文件读写操作
│   │   └── search.py                  # 文件搜索
│   ├── prompts/                       # 系统提示词模板
│   ├── skills.py                      # 技能加载与注入
│   ├── state.py                       # AgentState 定义
│   ├── event_bus.py                   # 发布/订阅事件总线
│   ├── file_service.py                # 文件树和内容服务
│   └── error_handler.py              # 错误处理工具
├── tests/                             # Pytest 测试套件 (66 tests)
├── skills/                            # Markdown 技能文件
├── memory/                            # SQLite + ChromaDB 数据文件
└── ui/                                # Vue 3 + Vite + TypeScript 前端
    ├── src/
    │   ├── components/                # Vue 组件
    │   │   ├── Sidebar.vue            # 会话列表侧边栏
    │   │   ├── ChatTab.vue            # 聊天主区域
    │   │   ├── ChatMessage.vue        # 消息气泡组件
    │   │   ├── ThinkingPanel.vue      # 思考过程面板
    │   │   ├── TaskBoard.vue          # 任务进度面板
    │   │   ├── InputBar.vue           # 输入栏（@mention, /command）
    │   │   ├── RightPanel.vue         # 右侧面板（4 标签页）
    │   │   ├── FileDrawer.vue         # 文件预览浮层
    │   │   └── ...
    │   ├── stores/                    # Pinia 状态管理
    │   │   ├── chat.ts                # 消息、流式传输、打字机动画
    │   │   ├── sessions.ts            # 多会话管理
    │   │   ├── agents.ts              # 代理配置管理
    │   │   └── theme.ts               # 主题切换
    │   └── utils/                     # 工具函数
    └── ...
```

## 代理执行路径

| 路径 | 文件 | 说明 |
|------|------|------|
| `Agent`（单代理） | `src/agent/agent.py` | ReAct 循环：`create_agent` + `astream_events` |
| `CustomSupervisor`（多代理） | `src/agent/supervisor.py` | think→plan→dispatch→summarize，子代理来自 `config/agents.json` |
| `StateGraph`（变体） | `src/agent/graph.py` | LangGraph `StateGraph` + `ToolNode` |
| `ACPAgent`（外部代理） | `src/agent/acp_agent.py` | ACP 协议集成 OpenCode / Claude Code |

### 单代理流程

`POST /chat` → 用户消息 → 上下文压缩检查 → `create_agent` ReAct 循环（LLM ↔ 工具）→ SSE 流（thinking + tool_call + message + metrics）

### 多代理流程

`POST /api/orchestrate` → 用户任务 → Supervisor 思考 + 计划 → 分派到子代理（`astream_events`）→ 收集结果 → 汇总

### ACP 代理流程

`POST /api/acp/send` → 消息路由到外部 CLI → JSON-RPC 会话管理 → 流式事件回传为 SSE

## 开发

```bash
# 后端
pip install -e ".[dev]"
pytest --cov=src -v              # 全部测试 + 覆盖率
pytest -k "test_name"            # 单个测试
ruff check .                     # Lint
mypy src                         # 类型检查

# 前端
cd ui
npm run dev                      # Vite 开发服务器 (port 3000)
vue-tsc -b && vite build         # 生产构建
```

## 技术栈

| 层级 | 技术 |
|------|------|
| LLM 框架 | LangChain + LangGraph |
| 代理引擎 | `create_agent` (ReAct) / `StateGraph` (ToolNode) |
| 编排器 | 自定义 Supervisor (think→plan→dispatch→summarize) |
| ACP 协议 | JSON-RPC 2.0 over stdio（原生）+ run fallback |
| 服务端 | FastAPI + sse-starlette + uvicorn |
| 前端 | Vue 3 + Pinia + Vite + TypeScript |
| Markdown | marked + highlight.js + KaTeX |
| 存储 | SQLite（会话/记忆）+ ChromaDB（向量） |
| 配置 | Pydantic Settings (.env) + JSON 配置（热加载） |

## 注意事项

- `python server.py --reload` 在 Windows 上可能失败（uvicorn 热重载问题，建议使用 WSL 或不加 `--reload`）
- DashScope / GLM / DeepSeek 需设置 `AGENT_ENABLE_THINKING=false`（不支持 `reasoning_content`）
- `tests/conftest.py` 自动隔离环境变量（mock key、临时 DB 路径）— 单元测试无需真实 API Key
- `opencode.json` 必须位于项目根目录，`.opencode/commands/` 存放自定义斜杠命令
