# LangGraph Agent v2 使用教程

## 目录

1. [项目概述](#1-项目概述)
2. [环境准备与安装](#2-环境准备与安装)
3. [配置文件详解](#3-配置文件详解)
4. [CLI 命令行使用](#4-cli-命令行使用)
5. [API 接口使用](#5-api-接口使用)
6. [前端 UI 使用](#6-前端-ui-使用)
7. [三大 Agent 执行模式](#7-三大-agent-执行模式)
8. [ACP 外部代理集成](#8-acp-外部代理集成)
9. [技能系统](#9-技能系统)
10. [记忆系统](#10-记忆系统)
11. [会话管理](#11-会话管理)
12. [错误处理与重试机制](#12-错误处理与重试机制)
13. [常见问题与故障排查](#13-常见问题与故障排查)

---

## 1. 项目概述

LangGraph Agent v2 是一个基于 LangGraph 的多智能体 AI 系统，提供：

- **三种 Agent 执行路径**：单 Agent（ReAct）、多 Agent Supervisor 编排、StateGraph
- **实时 SSE 流式传输**：支持思考过程、工具调用、消息等事件流
- **上下文压缩**：Token 感知的自动压缩，默认 70% 阈值
- **双存储记忆系统**：SQLite（结构化）+ ChromaDB（向量检索）
- **ACP 协议**：集成外部 CLI 工具（OpenCode、Claude Code）作为 Agent
- **技能系统**：Markdown 技能文件注入 Agent 系统提示词
- **热重载配置**：JSON 配置文件 5 秒轮询热加载

### 技术栈

| 层 | 技术 |
|---|---|
| LLM 框架 | LangChain >=0.3.0 + LangGraph >=0.2.0 |
| Agent | `create_agent` (ReAct) / `StateGraph` (ToolNode) / 自定义 Supervisor |
| ACP | JSON-RPC 2.0 over stdio |
| 后端 | FastAPI + sse-starlette + uvicorn |
| 前端 | Vue 3.4 + Pinia 2.1 + Vite 5 + TypeScript |
| 存储 | SQLite + ChromaDB |
| 配置 | Pydantic Settings (.env) + JSON 配置（热重载） |

---

## 2. 环境准备与安装

### 系统要求

- Python >= 3.11
- Node.js >= 18（前端）
- 操作系统：Windows / macOS / Linux

### 后端安装

```bash
# 1. 克隆项目
git clone <repo-url>
cd langgraph-agent-v2

# 2. 配置环境变量
cp .env.example .env

# 3. 安装依赖（含开发依赖）
pip install -e ".[dev]"

# 4. 启动服务
python server.py
# → http://localhost:8000
```

### 前端安装

```bash
cd ui
npm install
npm run dev
# → http://localhost:3000（自动代理 API 到 :8000）
```

### 验证安装

```bash
# 健康检查
curl http://localhost:8000/health
# 返回示例：{"status":"ok","model":"gpt-4o","provider":"openai","agents":7,"sessions":0}

# 查看可用 Agent
curl http://localhost:8000/api/agents
```

---

## 3. 配置文件详解

### `.env` 环境变量

```ini
# ── 模型提供商 ──
AGENT_MODEL_PROVIDER=openai      # openai | anthropic
AGENT_MODEL_NAME=gpt-4o          # 模型名称

# ── API 密钥 ──
OPENAI_API_KEY=sk-xxx            # OpenAI 兼容 API Key
OPENAI_BASE_URL=https://api.openai.com/v1  # 可换 DeepSeek/DashScope 等
ANTHROPIC_API_KEY=sk-ant-xxx     # Anthropic API Key

# ── 上下文窗口 ──
AGENT_MAX_TOKENS=128000          # 最大 Token 数
AGENT_COMPRESSION_THRESHOLD=0.7  # 压缩阈值（70%）
AGENT_ENABLE_THINKING=true       # 开启思考过程（DashScope/GLM/DeepSeek 需关闭）

# ── 存储路径 ──
AGENT_MEMORY_DB_PATH=memory/agent.db
AGENT_CHROMA_PATH=memory/chroma

# ── 服务器 ──
AGENT_SERVER_HOST=0.0.0.0
AGENT_SERVER_PORT=8000
```

**提示**: 支持任意 OpenAI 兼容 API（如 DeepSeek、DashScope、GLM 等），只需修改 `OPENAI_BASE_URL`。

### JSON 配置文件

所有 JSON 配置文件支持热重载（5 秒轮询检测），修改后自动生效。

| 文件 | 用途 |
|---|---|
| `config/agents.json` | Agent 定义（模型、工具、系统提示词、温度） |
| `config/tools.json` | 工具注册表（模块路径、元数据） |
| `config/skills.json` | 技能到 Agent 的映射 |
| `config/acp_agents.json` | 外部 CLI Agent 配置（命令、参数、超时） |

#### `config/agents.json` 结构

```json
{
  "agents": {
    "supervisor": {
      "name": "Supervisor",
      "type": "supervisor",
      "desc": "会话编排与任务调度",
      "enabled": true,
      "model": null,           // null 表示使用默认模型
      "temperature": null,     // null 表示使用默认温度
      "max_tokens": null,      // null 表示使用默认最大值
      "tools": [],             // 使用的工具列表
      "system_prompt": "You are a supervisor..."
    },
    "coder": {
      "name": "Coder",
      "type": "coder",
      "desc": "代码生成、调试与重构",
      "enabled": true,
      "temperature": 0.3,      // 代码任务用较低温度
      "tools": ["execute_code", "read_file", "write_file", "search_files"],
      "system_prompt": "You are a coding expert..."
    }
  }
}
```

#### `config/tools.json` 结构

5 个内置工具：

| 工具 ID | 功能 | 所属模块 |
|---|---|---|
| `execute_code` | 沙箱执行 Python 代码 | `src.agent.tools.execute_code` |
| `read_file` | 读取文件内容（支持偏移/限制） | `src.agent.tools.file_ops` |
| `write_file` | 写入文件 | `src.agent.tools.file_ops` |
| `list_directory` | 列出目录内容 | `src.agent.tools.file_ops` |
| `search_files` | 按 glob 模式搜索文件 | `src.agent.tools.search` |

---

## 4. CLI 命令行使用

### 单次查询

```bash
# 直接提问
python -m src.agent.main --input "什么是 Python 的装饰器？"

# 指定模型
python -m src.agent.main --input "写一个快速排序" --provider openai --model gpt-4o
```

### 交互模式

```bash
python -m src.agent.main --interactive
```

交互模式下：
- 输入消息后回车发送
- 工具调用会显示 `[Tool: tool_name(args)]`
- 输入 `quit` 或 `Ctrl+C` 退出

### 恢复会话

```bash
# 恢复最近一次会话
python -m src.agent.main --interactive --resume

# 恢复指定会话
python -m src.agent.main --interactive --resume <session-id>
```

---

## 5. API 接口使用

### 5.1 单 Agent 对话（SSE 流式）

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "用 Python 写一个斐波那契数列",
    "session_id": null,
    "agent_id": "direct",
    "user_id": "user1"
  }'
```

SSE 事件类型：

| 事件 | 说明 |
|---|---|
| `thinking_start` | LLM 开始推理 |
| `thinking` | 推理内容块（服务端批量合并） |
| `thinking_done` | 推理完成 |
| `tool_call` | 工具调用（名称 + 参数） |
| `message` | 最终助手回复 |
| `metrics` | Token 用量和耗时 |
| `error` | 错误信息 |
| `done` | 流结束 |

### 5.2 浏览器 EventSource

```javascript
// 浏览器端使用 GET SSE
const source = new EventSource(
  "/chat/stream?message=你好&session_id=xxx&agent_id=direct"
);

source.addEventListener("message", (e) => {
  const data = JSON.parse(e.data);
  console.log(data);
});
source.addEventListener("done", () => source.close());
```

### 5.3 多 Agent Supervisor 编排

```bash
curl -N -X POST http://localhost:8000/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{
    "message": "分析项目代码结构并生成报告",
    "session_id": null,
    "user_id": "user1"
  }'
```

额外 SSE 事件：

| 事件 | 说明 |
|---|---|
| `plan` | Supervisor 生成的执行计划 |
| `task_update` | 子任务状态更新 |
| `summary` | 多 Agent 结果汇总 |

### 5.4 会话管理

```bash
# 创建新会话
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user1"}'

# 列出会话
curl http://localhost:8000/api/sessions?user_id=user1

# 获取会话详情（含消息历史）
curl http://localhost:8000/api/sessions/<session-id>

# 修改会话标题
curl -X PATCH http://localhost:8000/api/sessions/<session-id>/title \
  -H "Content-Type: application/json" \
  -d '{"title": "我的会话"}'

# 设置项目路径
curl -X PATCH http://localhost:8000/api/sessions/<session-id>/project-path \
  -H "Content-Type: application/json" \
  -d '{"project_path": "D:/project/myapp"}'

# 删除会话
curl -X DELETE http://localhost:8000/api/sessions/<session-id>
```

### 5.5 Agent 运行时管理（CRUD）

```bash
# 列出所有 Agent
curl http://localhost:8000/api/agents

# 获取单个 Agent
curl http://localhost:8000/api/agents/coder

# 创建/更新 Agent
curl -X POST http://localhost:8000/api/agents/coder \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Coder",
    "type": "coder",
    "tools": ["execute_code", "read_file", "write_file"],
    "temperature": 0.2,
    "system_prompt": "You are a coding expert..."
  }'

# 删除 Agent
curl -X DELETE http://localhost:8000/api/agents/coder
```

### 5.6 记忆系统操作

```bash
# 存储记忆
curl -X POST http://localhost:8000/api/memory/store \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "user_prefs",
    "key": "lang",
    "content": "用户偏好 Python 语言"
  }'

# 向量相似度查询
curl -X POST http://localhost:8000/api/memory/query \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "user_prefs",
    "query": "编程语言偏好",
    "top_k": 5
  }'

# 列出命名空间所有条目
curl http://localhost:8000/api/memory/list/user_prefs

# 删除条目
curl -X DELETE http://localhost:8000/api/memory/user_prefs/lang
```

### 5.7 文件浏览

```bash
# 获取工作区文件树
curl http://localhost:8000/api/files/tree

# 读取文件内容
curl "http://localhost:8000/api/files/content?path=server.py&offset=1&limit=50"

# 打开系统文件夹选择器（仅 Windows）
curl -X POST http://localhost:8000/api/files/pick-directory
```

### 5.8 工具与技能查询

```bash
# 列出所有可用工具
curl http://localhost:8000/api/tools

# 列出已加载技能
curl http://localhost:8000/api/skills

# 强制重载配置
curl -X POST http://localhost:8000/api/config/reload
```

### 5.9 健康检查

```bash
curl http://localhost:8000/health
# {"status":"ok","model":"gpt-4o","provider":"openai","agents":7,"sessions":0}
```

---

## 6. 前端 UI 使用

启动前端后访问 `http://localhost:3000`。

### 主要界面

| 区域 | 说明 |
|---|---|
| **左侧栏** | 会话列表、文件浏览器、Agent 面板 |
| **中间** | 聊天主区域，显示消息和思考过程 |
| **右侧面板** | 工具面板、监控面板、任务看板 |
| **底部输入栏** | 消息输入、Agent 选择、发送按钮 |

### 功能说明

- **Agent 选择**：下拉选择使用哪个 Agent（Direct / Coder / Researcher 等）
- **思考过程**：LLM 推理过程以可展开的 typewriter 块显示
- **Markdown 渲染**：支持代码高亮、数学公式（KaTeX）
- **文件浏览器**：浏览工作区文件，点击查看内容
- **会话管理**：创建、切换、重命名、删除会话
- **主题切换**：明暗主题切换

---

## 7. 三大 Agent 执行模式

### 7.1 单 Agent 模式（`agent.py`）

**适用场景**：简单对话、单一任务、工具调用

```
POST /chat
  → User message
  → context compression check（检查是否需压缩）
  → create_agent ReAct loop（LLM ↔ 工具循环）
  → SSE stream（thinking → tool_call → message → metrics → done）
```

**特点**：
- 使用 LangChain `create_agent` 构建 ReAct 循环
- 通过 `astream_events` 流式输出（v2 格式）
- 支持 `reasoning_content` 思维链透明

### 7.2 多 Agent Supervisor 模式（`supervisor.py`）

**适用场景**：复杂任务拆解、多专业协作

```
POST /api/orchestrate
  → User task
  → Supervisor 思考 + 生成执行计划（plan）
  → 分发到子 Agent（coder / researcher / analyst / direct）
  → 每个子 Agent 通过 astream_events 执行
  → 收集结果并汇总摘要（summary）
```

**可用的子 Agent**：

| Agent | 擅长 | 工具 |
|---|---|---|
| **Coder** | 代码生成、调试、重构 | 代码执行、文件读写、搜索 |
| **Researcher** | 信息检索、文件分析 | 搜索、目录列表、文件读取 |
| **Analyst** | 数据分析、报告 | 代码执行、文件读取、搜索 |
| **Direct** | 简单任务直接处理 | 全部工具 |

**子 Agent 可通过 `config/agents.json` 自定义**，每个 Agent 可独立设置：
- 使用的模型（`model` 字段，null 则用默认模型）
- 温度参数（`temperature`）
- 最大 Token（`max_tokens`）
- 可用的工具集（`tools` 数组）
- 自定义系统提示词（`system_prompt`）

### 7.3 StateGraph 模式（`graph.py`）

**适用场景**：需要精确控制状态流转的复杂工作流

```
Think Node（LLM + 工具绑定）
  → 有工具调用？→ ToolNode（执行工具）→ Think Node
  → 无工具调用？→ END
```

**特点**：
- 使用 LangGraph `StateGraph` + `ToolNode`
- 条件边路由（`should_continue`）
- 比 `create_agent` 更底层的控制

---

## 8. ACP 外部代理集成

ACP（Agent Communication Protocol）允许将外部 CLI 工具作为 LangGraph Agent 使用。

### 支持的 CLI

| CLI | 配置 ID | 命令 |
|---|---|---|
| OpenCode | `opencode` | `opencode acp` |
| Claude Code | `claude` | `claude-agent-acp` |

### ACP 配置（`config/acp_agents.json`）

```json
{
  "acp_agents": {
    "opencode": {
      "name": "OpenCode",
      "command": "opencode",
      "args": [],
      "timeout": 600,
      "cwd": ".",
      "desc": "OpenCode — 终端 AI 编码代理",
      "enabled": true
    }
  }
}
```

### 通信模式

采用双模式策略：
1. **原生模式**（首选）：持久化 JSON-RPC 2.0 over stdio，支持完整会话管理
2. **回退模式**：`run --format json` 一次性执行

### API 使用

```bash
# 检查 CLI 是否可用
curl http://localhost:8000/api/acp/check/opencode

# 发送消息到 ACP Agent（SSE 流式）
curl -N -X POST http://localhost:8000/api/acp/send \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "opencode",
    "message": "分析当前项目代码质量",
    "session_id": null
  }'

# 列出 ACP 会话
curl http://localhost:8000/api/acp/sessions/opencode

# 管理 ACP 配置
curl http://localhost:8000/api/acp/config                    # 列出所有
curl http://localhost:8000/api/acp/config/opencode           # 获取单个
curl -X POST http://localhost:8000/api/acp/config/opencode \ # 创建/更新
  -H "Content-Type: application/json" \
  -d '{"name":"OpenCode","command":"opencode","args":[],"timeout":600,"cwd":"."}'
curl -X DELETE http://localhost:8000/api/acp/config/opencode  # 删除
```

### 在 Supervisor 中使用 ACP Agent

ACP Agent（opencode、claude）已在 `config/agents.json` 中注册，Supervisor 会自动将它们作为可用子 Agent 纳入编排计划。例如：

```json
{
  "opencode": {
    "type": "opencode",
    "acp_mode": true,
    "acp_cli_id": "opencode"
  }
}
```

当 Supervisor 接到编码任务时，会自动将代码相关子任务分配给 OpenCode 或 Claude Code 执行。

---

## 9. 技能系统

技能系统允许将 Markdown 文件注入特定 Agent 的系统提示词，提供专业领域指导。

### 创建技能文件

在 `skills/` 目录下创建 Markdown 文件：

```markdown
# skills/code-review.md

## Code Review Checklist

- 检查是否有硬编码敏感信息
- 验证输入参数合法性
- 确保异常处理完善
- 检查资源释放
```

### 配置技能映射

编辑 `config/skills.json`：

```json
{
  "skills": {
    "code-review": {
      "file": "skills/code-review.md",
      "enabled": true,
      "agents": ["coder", "opencode"],
      "desc": "Code review checklist and best practices"
    }
  }
}
```

### 技能注入流程

```
skills/*.md  →  config/skills.json（代理映射）
  →  Agent 启动时读取
  →  注入到该系统提示词
  →  Agent 在对话中遵循技能指导
```

### 查看已加载技能

```bash
curl http://localhost:8000/api/skills
```

---

## 10. 记忆系统

双存储架构：SQLite 用于结构化元数据，ChromaDB 用于向量相似度搜索。

### 架构

```
写操作 → 同时写入 SQLite + ChromaDB
查询操作 → ChromaDB 向量搜索 → 返回相关条目
注入 → 查询到的记忆注入 LLM 上下文
```

### 命名空间

记忆按 `namespace` 组织，推荐命名方式：

| 命名空间 | 用途 |
|---|---|
| `user_prefs` | 用户偏好 |
| `project_context` | 项目上下文 |
| `conversation_history` | 对话历史摘要 |

### API 使用

```bash
# 存储
curl -X POST http://localhost:8000/api/memory/store \
  -H "Content-Type: application/json" \
  -d '{"namespace": "project_context", "key": "arch", "content": "微服务架构，含 3 个服务"}'

# 向量查询（语义搜索）
curl -X POST http://localhost:8000/api/memory/query \
  -H "Content-Type: application/json" \
  -d '{"namespace": "project_context", "query": "系统架构", "top_k": 5}'

# 列表
curl http://localhost:8000/api/memory/list/project_context

# 删除
curl -X DELETE http://localhost:8000/api/memory/project_context/arch
```

---

## 11. 会话管理

### 自动功能

- **自动编号**：新会话自动生成标题（如"会话 3"）
- **自动标题**：根据首条用户消息自动生成语义标题
- **持续时间追踪**：记录会话开始到最新活动的时间
- **自动压缩**：Token 达到阈值时自动压缩历史消息

### 会话压缩

当对话历史 Token 数超过 `AGENT_COMPRESSION_THRESHOLD`（默认 70%）时，自动触发压缩：

- 使用 LLM 生成历史摘要
- 保留最近 5 条消息完整
- 旧消息标记 `compacted=1`
- 保留系统提示词，与现有摘要合并

```bash
# 手动触发压缩
curl -X POST http://localhost:8000/api/compact \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<session-id>"}'
```

### 持久化

会话数据存储在 `memory/sessions.db` 中，包括：
- 消息历史（role、content、timestamp）
- 会话元数据（user_id、title、summary、status）
- ACP 会话 ID 关联
- 项目路径绑定

---

## 12. 错误处理与重试机制

### 结构化错误

所有错误通过 `ErrorEnvelope` 统一封装：

```json
{
  "error": {
    "type": "tool_error",
    "message": "执行代码时出错",
    "details": "NameError: name 'x' is not defined",
    "recoverable": true
  }
}
```

### 重试策略

| 组件 | 最大重试 | 策略 |
|---|---|---|
| LLM 调用 | 3 次 | 指数退避 |
| 工具调用 | 3 次 | 指数退避 |
| Supervisor 调度 | 2 次 | 指数退避 |

### 熔断器（Circuit Breaker）

- **触发条件**：连续 5 次失败
- **熔断状态**：60 秒内拒绝请求
- **恢复**：60 秒后尝试半开，成功则关闭

### SSE 错误事件

流式过程中错误通过 `error` 事件类型推送：

```json
{"event": "error", "data": {"type": "llm_error", "message": "API 调用超时"}}
```

---

## 13. 常见问题与故障排查

### 启动问题

**Q**: `python server.py --reload` 在 Windows 失败？

**A**: uvicorn 的 `--reload` 在 Windows 上不稳定，建议去掉 `--reload` 或使用 WSL。

**Q**: 前端请求后端 404？

**A**: 确保后端先启动（端口 8000），前端开发服务器（端口 3000）会自动代理 API 请求到 8000。

### 模型配置

**Q**: 如何使用 DeepSeek / DashScope？

**A**: 修改 `.env`：
```ini
AGENT_MODEL_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-xxx
```
并设置 `AGENT_ENABLE_THINKING=false`（这些模型不支持 `reasoning_content`）。

**Q**: 如何使用 Anthropic Claude？

**A**: 修改 `.env`：
```ini
AGENT_MODEL_PROVIDER=anthropic
AGENT_MODEL_NAME=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-xxx
```

### 运行时问题

**Q**: 上下文过多被截断？

**A**: 调整阈值 `AGENT_COMPRESSION_THRESHOLD=0.5`（更早触发压缩）或增加 `AGENT_MAX_TOKENS`。

**Q**: Agent 工具调用卡住？

**A**: 检查熔断器状态，等待 60 秒自动恢复。或重启服务。

**Q**: 配置文件修改未生效？

**A**: JSON 配置文件每 5 秒热重载一次，最多等待 5 秒。也可调用 `POST /api/config/reload` 强制重载。

**Q**: ACP Agent 连接失败？

**A**: 检查对应 CLI 是否已安装（`opencode --version` 或 `claude --version`），以及 `config/acp_agents.json` 中的 `command` 路径是否正确。

### 测试

```bash
# 运行全部测试
pytest --cov=src -v

# 运行单个测试
pytest -k "test_compression"

# Lint + 类型检查
ruff check . && mypy src
```

测试文件在 `tests/conftest.py` 中自动隔离环境变量（mock API Key、临时 DB 路径），无需真实 API Key。

---

## 附录：完整 API 端点速查

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 健康检查 |
| `POST` | `/chat` | 单 Agent SSE 对话 |
| `GET` | `/chat/stream` | GET SSE 流 |
| `POST` | `/api/orchestrate` | 多 Agent 编排 |
| `GET/POST` | `/api/sessions` | 会话列表/创建 |
| `GET/PATCH/DELETE` | `/api/sessions/{id}` | 会话操作 |
| `POST` | `/api/compact` | 手动压缩会话 |
| `GET/POST/DELETE` | `/api/agents[/{id}]` | Agent CRUD |
| `GET` | `/api/acp/agents` | ACP Agent 状态 |
| `POST` | `/api/acp/send` | ACP 消息发送 |
| `GET` | `/api/acp/config[/{id}]` | ACP 配置管理 |
| `POST` | `/api/memory/store` | 存储记忆 |
| `POST` | `/api/memory/query` | 向量查询 |
| `GET/DELETE` | `/api/memory/{namespace}[/{key}]` | 记忆操作 |
| `GET` | `/api/tools` | 工具列表 |
| `GET` | `/api/skills` | 技能列表 |
| `GET/POST` | `/api/files/tree` / `/api/files/pick-directory` | 文件浏览 |
| `GET` | `/api/files/content` | 文件内容 |
| `POST` | `/api/config/reload` | 重载配置 |
| `GET` | `/api/events/stream/{stream_id}` | SSE 事件总线 |
