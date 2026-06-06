# AI Agent Frameworks Comparison — LangGraph Agent v2 项目视角

> 生成日期: 2026-06-06
> 背景: 本项目已基于 **LangGraph + LangChain** 构建了一套多智能体编排系统。本文件从现有架构出发，评估各框架的替代/集成价值。

---

## 目录

1. [项目现状快照](#1-项目现状快照)
2. [各框架横向对比](#2-各框架横向对比)
3. [与本项目的深度匹配分析](#3-与本项目的深度匹配分析)
4. [集成可行性评估](#4-集成可行性评估)
5. [推荐策略](#5-推荐策略)

---

## 1. 项目现状快照

| 维度 | 当前实现 |
|------|----------|
| **编排引擎** | LangGraph `StateGraph`，6 节点 DAG（perceive → plan → wait → dispatch → synthesize → reflect） |
| **子智能体** | `create_react_agent` 按需创建，每个子智能体有独立 model/tools/prompt 覆盖 |
| **外部智能体** | ACP 协议（JSON-RPC 2.0 over stdio），对接 OpenCode / Claude Code |
| **流式** | SSE 统一事件协议，14 种 EventType，`_passthrough()` 微事件批处理 |
| **持久化** | SQLite（sessions/messages/tool_usage/task_updates）+ ChromaDB 向量记忆 |
| **人机交互** | LangGraph `interrupt()` / `Command()` 实现计划审批回路 |
| **上下文压缩** | `ContextCompressor`，基于 token 阈值触发 LLM 摘要 |
| **跨会话学习** | `memory/experiences.md`，reflect 节点自动提取反模式 |
| **可观测性** | 结构化 JSONL Audit Logger + 指标收集 |
| **前端** | Vue 3 + Pinia，三层背压队列（MICRO/STEP/MACRO） |
| **模型** | 多 Provider（OpenAI / Anthropic / 兼容 API），按 agent 粒度覆盖 |

---

## 2. 各框架横向对比

### 2.1 核心维度矩阵

| 框架 | 架构范式 | 图编排 | 多智能体 | 流式 | 持久化/检查点 | Python | GitHub Stars | 许可 |
|------|----------|--------|----------|------|---------------|--------|-------------|------|
| **LangGraph** ← 当前 | 有状态有环图 | ✅ 原生 | Supervisor/Hierarchy/Swarm | ✅ Full | Checkpointers (SQLite/Postgres) | ✅ | ~29K | MIT |
| Microsoft Agent Framework | 状态机图 | ✅ | GroupChat/Handoff/Magentic | ✅ | Session + Checkpointing | ✅ | ~11K | MIT |
| CrewAI | 角色协作 | ❌ 无图 | Sequential/Hierarchical/Parallel | ⚠️ 有限 | Short/Long/Entity/Summary 记忆 | ✅ | ~48K | MIT |
| AutoGen (legacy) | 对话中心 | ❌ | GroupChat/Handoff | ✅ | ⚠️ 外部 | ✅ | ~57K | CC-BY-4.0 |
| LlamaIndex Workflows | 事件驱动流水线 | ✅ DAG | Choreography/Orchestrator | ✅ Event-driven | Index-based 检索 | ✅ | ~47K | MIT |
| Haystack | Pipeline DAG | ✅ DAG | Coordinator/Specialist | ✅ callback | Pipeline state | ✅ | ~18K | Apache 2.0 |
| Smolagents | Code-as-Action | ❌ | ManagedAgent 层级 | ⚠️ Step | In-memory 消息列表 | ✅ | ~27.7K | Apache 2.0 |
| OpenAI Agents SDK | 轻量 Handoff | ❌ | Handoff chains | ✅ SSE | ❌ 无内置 | ✅ | ~15K+ | MIT |
| Mastra | 图 + 工作流 | ✅ | Agent-as-Tool | ✅ Real-time | Thread-based 持久化 | ❌ TS only | ~22K | Apache 2.0 |
| Agno (Phidata) | Runtime-first | ✅ 工作流 | Teams/Delegation | ✅ SSE | Session + Vector 记忆 | ✅ | ~40K | Apache 2.0 |
| Dify | 可视化低代码 | ✅ 工作流 | Agent 节点 | ✅ SSE | PostgreSQL + Vector DB | ✅ | ~138K | Apache 2.0 |
| Vercel AI SDK | 统一工具包 | ❌ | ❌ 原生不支持 | ✅ 一流 | ❌ 无内置 | ❌ TS only | ~24.6K | MIT |
| PocketFlow | 极简图 | ✅ 核心 (~100行) | 设计模式实现 | ❌ | ❌ 无 | ✅ | ~2K+ | MIT |
| Atomic Agents | 原子组件管线 | ❌ | Pipeline 组合 | ⚠️ Async | ❌ 无内置 | ✅ | ~1.5K+ | MIT |
| Pydantic AI | 类型安全结构化 | ❌ | ❌ 原生不支持 | ✅ | ❌ 无内置 | ✅ | ~10K+ | MIT |
| Semantic Kernel | 依赖注入中间件 | ❌ | 通过 Agent Framework | ✅ | 通过 Agent Framework | ✅ | ~27K | MIT |
| Google ADK | 层级多智能体 | ✅ 层级 | Hierarchical + A2A | ✅ | 会话状态 | ✅ | ~5K+ | Apache 2.0 |
| PraisonAI | 低代码 YAML | ⚠️ 有限 | Sequential/Parallel/Hierarchical | ⚠️ Callback | 多数据库持久会话 | ✅ | ~7K | 开源 |

### 2.2 关键特性对比

| 特性 | LangGraph | MS Agent Framework | CrewAI | LlamaIndex WF | Mastra | Agno |
|------|-----------|-------------------|--------|---------------|--------|------|
| **Human-in-the-loop** | ✅ interrupt/Command | ✅ Checkpointing | ⚠️ 有限 | ❌ | ✅ | ❌ |
| **DAG 依赖执行** | ✅ 自定义 | ✅ Sequential/Parallel | ❌ 线性 | ✅ | ✅ | ⚠️ |
| **动态工具加载** | ✅ config-driven | ✅ Plugin system | ✅ role-based | ❌ | ✅ | ✅ |
| **外部智能体协议** | 自定义 ACP | A2A native | ⚠️ 实验性 | ❌ | MCP | MCP |
| **反模式学习** | ✅ 自定义 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **跨会话记忆** | ✅ Checkpointer | ✅ Session state | ✅ Entity memory | ✅ LlamaCloud | ✅ Thread | ✅ Vector |
| **SSE 流式** | ✅ astream_events | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| **测试隔离** | ✅ mock resolve_model | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ |

---

## 3. 与本项目的深度匹配分析

### 3.1 本项目独特需求

1. **多节点 DAG 编排** — 6 节点图，含条件路由和 revise 回路
2. **外部智能体桥接 (ACP)** — JSON-RPC over stdio，非 HTTP/A2A
3. **计划审批回路** — interrupt/resume 实现的人机协作
4. **子智能体 per-call 隔离** — 每次 dispatch 创建独立 `create_react_agent`
5. **反模式自学习** — reflect 节点 + `experiences.md`
6. **微事件批处理** — `_passthrough()` 的 200 字符 thinking 和 150 字符 message 积累
7. **统一 SSE 事件协议** — 14 种 EventType，三种执行路径共享
8. **上下文感知压缩** — token 阈值触发的 LLM 摘要
9. **每个 agent 粒度模型/tool/prompt 覆盖** — `agents.json` 配置驱动

### 3.2 各框架匹配度打分（1-5）

| 框架 | 图编排 | 多智能体 | 外部智能体 | HITL | 流式 | 持久化 | 易集成 | 总分 |
|------|--------|----------|------------|------|------|--------|--------|------|
| **LangGraph (当前)** | 5 | 5 | 5 (ACP) | 5 | 5 | 5 | 5 (已用) | **35** |
| MS Agent Framework | 4 | 5 (A2A) | 3 (A2A≠ACP) | 4 | 4 | 4 | 2 (重写) | **26** |
| CrewAI | 2 | 4 | 2 | 2 | 3 | 3 | 3 | **19** |
| LlamaIndex WF | 4 | 3 | 1 | 2 | 4 | 3 | 2 | **19** |
| Haystack | 4 | 3 | 2 | 3 | 4 | 3 | 3 | **22** |
| Smolagents | 1 | 2 | 1 | 1 | 2 | 1 | 4 | **12** |
| OpenAI Agents SDK | 1 | 3 | 1 | 2 | 4 | 1 | 3 | **15** |
| Mastra | 4 | 3 | 2 | 3 | 4 | 4 | 1 (TS) | **21** |
| Agno | 3 | 4 | 2 | 2 | 4 | 4 | 3 | **22** |
| Dify | 3 | 3 | 1 | 2 | 4 | 4 | 2 | **19** |

### 3.3 详细分析

#### LangGraph (当前方案) ⭐ 总分 35

**优势：**
- 已深度集成，6 节点 StateGraph 稳定运行
- `interrupt()`/`Command()` 完美支撑计划审批回路
- `MemorySaver` checkpointer + `JsonPlusSerializer` 处理线程持久化
- `astream_events` 提供细粒度事件钩子（`on_chat_model_stream`, `on_tool_start` 等）
- 子智能体通过 `create_react_agent` 独立创建，隔离性好
- LangSmith 可选用于生产 tracing

**短板：**
- `GraphRecursionError` 硬限制需要手动捕获
- token 估算粗糙（`len(text)*1.5`），缺少真实 `usage_metadata`
- 学习曲线仍然存在，新人上手慢

#### Microsoft Agent Framework ⚠️ 总分 26

**优势：**
- A2A 协议原生支持，可能替代自定义 ACP
- GroupChat/Magentic 模式丰富
- 企业级 telemetry 和 RBAC

**劣势：**
- **2026 年 3 月才 GA**，生产案例极少
- A2A ≠ ACP，需要重写外部智能体通信层
- 所有 6 个图节点 + 路由逻辑需移植
- 当前不支持 per-agent model 覆盖（需要验证）

**结论：暂不迁移，保持观察。** 若 ACP 生态转向 A2A，可考虑桥接层而非全量迁移。

#### CrewAI 总分 19

**优势：**
- 角色（Role/Goal/Backstory）定义简洁，适合快速原型
- 活跃社区（48K stars），文档质量高

**劣势：**
- **无图编排**，不支持 6 节点 DAG + 条件路由
- 不支持 HITL interrupt/resume
- 层级模式已知 bug 多
- 无法实现 per-call `create_react_agent` 隔离
- 企业功能需付费 AMP

**结论：不适合。** 项目需求（图编排、HITL、DAG 执行）超出 CrewAI 能力边界。

#### LlamaIndex Workflows 总分 19

**优势：**
- 最佳数据连接器（160+ LlamaHub）
- LlamaParse 文档解析一流
- Event-driven Workflows API 干净

**劣势：**
- **多智能体编排非核心能力**，agent 能力是二等公民
- 无 HITL 支持
- 无外部智能体协议
- 需保留 LCEL 子智能体（`create_react_agent`），增加运行时复杂度

**结论：不适合作为编排引擎。** 可作为 RAG/文档处理模块集成，而非替代 LangGraph。

#### Haystack 总分 22

**优势：**
- Pipeline DAG 成熟，组件模型清晰
- 2.x 的 Agent 组件支持 tool-calling 和流式
- `ComponentTool` 可将任意 pipeline 组件封装为 agent tool

**劣势：**
- Agent 能力是 2.x 新增，不如 LangGraph 成熟
- 外部智能体协议缺失
- 需要保留 LangChain 生态用于 `create_react_agent` 和 ACP

**结论：部分集成可行。** 可将 Haystack 用于搜索/RAG 管线，保留 LangGraph 做编排。

#### Smolagents 总分 12

**优势：**
- ~1K 行核心，极简可读
- Code-as-action 模式比 JSON tool-calling 少 30% LLM 步骤

**劣势：**
- **无状态管理、无持久化、无图编排** — 与项目需求严重不匹配
- ManagedAgent 层级远不如 StateGraph 灵活
- 本地 Python 执行器不是安全边界

**结论：不适合。** 理念有参考价值（Code-as-action），但框架过于轻量。

#### OpenAI Agents SDK 总分 15

**优势：**
- 最简接口，OpenAI 模型最快投产
- Guardrails 输入/输出校验干净

**劣势：**
- **无内置记忆、无图编排、无外部智能体协议**
- OpenAI 供应商锁定
- Handoff 模式简单，难支撑 supervisor → dispatch → synthesize 流程

**结论：不适合。** 供应商锁定的轻量级框架，无法满足项目复杂度。

#### Mastra 总分 21

**优势：**
- TypeScript 原生，全套件（agents/workflows/RAG/evals/memory）
- Workflows 图支持分支/循环/重试/HITL
- Mastra Studio 可视化调试

**劣势：**
- **TypeScript only** — 本项目 Python 栈，无法直接使用
- 年轻，API 仍在快速演进

**结论：不适于替换。** 若未来有 TypeScript 子项目可参考其设计。

#### Agno (Phidata) 总分 22

**优势：**
- 快速 agent 实例化（宣称比 LangGraph 快 5000x）
- 内置 session 管理、向量记忆、knowledge 和 guardrails
- Teams 模式支持多智能体协作

**劣势：**
- rebrand 造成社区分裂
- 工作流图能力不如 LangGraph 成熟
- 外部智能体协议缺失

**结论：观察。** 性能声称值得关注，但缺少 HITL 和 ACP 关键能力。

#### Dify 总分 19

**优势：**
- 138K stars，最大社区
- 拖拽式工作流，非技术人员友好
- 内置 RAG、模型管理、可观测性

**劣势：**
- **低代码平台而非框架** — 不适合作为代码项目核心编排引擎
- 灵活度远低于 LangGraph
- 自托管需 Docker Compose，增加运维负担

**结论：不适于替换。** 可作为管理后台观察，不适合嵌入现有代码。

---

## 4. 集成可行性评估

### 4.1 可集成的框架组件

以下框架的部分能力可选择性引入，无需全量替换：

| 框架 | 可复用组件 | 集成方式 | 工作量 |
|------|-----------|----------|--------|
| **LlamaIndex** | `LlamaParse` 文档解析 + LlamaHub 数据连接器 | 添加为 tool 或 context 处理器 | 小 (1-2d) |
| **Haystack** | Pipeline 组件（检索/过滤/重排） | 封装为 `BaseTool` 供子智能体调用 | 中 (3-5d) |
| **Smolagents** | Code-as-action 执行器（参考） | 新增 `CodeActionTool` 可选执行模式 | 中 (3-5d) |
| **OpenAI Agents SDK** | Guardrails 校验模式 | 独立引入，封装为 input/output 校验层 | 小 (2-3d) |
| **Pydantic AI** | 结构化输出校验 | 已部分使用 Pydantic，可加强 tool output schema | 小 (1-2d) |

### 4.2 需重写的框架替代

| 框架 | 替代代价 | 关键障碍 |
|------|---------|---------|
| MS Agent Framework | **高** (2-4 周) | ACP≠A2A，6 节点图重写，per-agent 模型覆盖验证 |
| CrewAI | **高** (3-4 周) | 无图编排，无 HITL，无 DAG 执行，需大量定制 |
| Mastra | **极高** (1-2 月) | 语言栈不兼容 (Python vs TS) |

---

## 5. 推荐策略

### 短期：深化 LangGraph 能力（0-3 月）

```
┌─ 当前状态 ─────────────────────────────────────────────┐
│ LangGraph StateGraph (6节点) + ACP + SQLite + ChromaDB │
└────────────────────────────────────────────────────────┘
         │
         ▼
┌─ 优化方向 ──────────────────────────────────────────────┐
│ 1. 升级 LangGraph checkpointer 到 PostgresSaver        │
│ 2. 接入 LangSmith 生产 tracing + eval                   │
│ 3. 用真实 usage_metadata 替换 len(text)*1.5 token 估算   │
│ 4. 强化 GraphRecursionError 恢复策略                     │
│ 5. ACP 协议添加心跳/重连机制                             │
└────────────────────────────────────────────────────────┘
```

### 中期：选择性集成（3-6 月）

```
┌─ 集成 LlamaParse ──────┐
│ 处理复杂文档输入         │
└────────────────────────┘
         +
┌─ 集成 Haystack Pipeline ─┐
│ 搜索/RAG 管线替代自制     │
└──────────────────────────┘
         +
┌─ 集成 Guardrails ────────┐
│ 输入/输出安全过滤         │
└──────────────────────────┘
```

### 长期：跟踪候选（6-12 月）

```
┌─ MS Agent Framework ───┐
│ 观察 A2A 生态成熟度     │
│ ACP ↔ A2A 桥接层研究   │
└────────────────────────┘
         +
┌─ Agno ─────────────────┐
│ 性能 benchmark 验证     │
│ 是否可替换子智能体层    │
└────────────────────────┘
```

### 结论

| 结论 | 说明 |
|------|------|
| **保持 LangGraph 为核心** | 当前框架选择正确，已构建的能力（6 节点图、HITL、ACP、反模式学习）在其他框架中要么缺失要么不成熟 |
| **不迁移到任何替代框架** | 所有评估框架在关键维度（图编排+HITL+外部智能体+per-agent 隔离）均不如当前方案 |
| **选择性引入特定组件** | LlamaIndex 文档解析、Haystack 检索管线、Guardrails 校验层值得作为模块集成 |
| **关注 A2A 协议演进** | 若 ACP 生态向 A2A 迁移，MS Agent Framework 或 Google ADK 可能在长期成为外部智能体桥接的替代方案 |

---

*本文件基于 2026 年 6 月各框架公开信息及 LangGraph Agent v2 项目 v2.x 源码架构分析。*
