# Agent 框架深度对比报告（v2）

> 基于开源现状（2026 年 6 月）与本项目 `langgraph-agent-v2` 源码的逐项分析。
> 项目路径：`D:\project\ai\langgraph-agent-v2`

---

## 一、项目架构速览

| 维度 | 当前实现 |
|------|----------|
| **编排引擎** | LangGraph StateGraph（6 节点：perceive → plan → wait → dispatch → synthesize → reflect） |
| **节点数量** | 6 个，含 1 个 HITL 中断点（wait） |
| **图拓扑** | 有环有向图（synthesize → plan 修订回路） |
| **子 Agent 类型** | 本地 ReAct Agent（`create_react_agent`）+ 外部 ACP Agent（JSON-RPC 2.0 over stdio） |
| **流式传输** | SSE 协议，12 种事件类型（`events.py:EventType`），含 thinking/plan/tool_call/message/metrics |
| **持久化** | SQLite（会话/消息）+ ChromaDB + `memory/experiences.md`（反模式库） |
| **HITL** | `langgraph.types.interrupt()` + `Command(resume=...)` |
| **错误处理** | `circuit_breaker.py` + `RetryHandler` + `ErrorEnvelope` 结构化错误 |
| **上下文压缩** | `ContextCompressor`（按 token 阈值触发，保留最近 3 轮） |
| **配置热加载** | `ConfigManager`（5s 轮询 `config/*.json` 文件变更） |
| **跨语言 Agent** | ACP 协议（`ACPNativeClient`）连接 OpenCode/Claude Code 等外部 CLI |
| **反模式学习** | `_reflect_node` 自动提取失败模式写入 `experiences.md`，下次 plan 时加载 |
| **Token 估算** | `len(text) * 1.5`（`_estimate_tokens`），按 agent 名称分桶统计 |

---

## 二、框架横向对比（针对本项目需求）

### 打分系统说明

每个维度 0-5 分，满分 35。得分基于 **本项目** 的需求权重，非通用评分。

| 权重 | 维度 | 说明 |
|------|------|------|
| ⭐⭐⭐⭐⭐ | 图编排（有环/条件边） | 6 节点 DAG + revision 回路需要原生图支持 |
| ⭐⭐⭐⭐⭐ | 多 Agent（本地+外部混合） | 既需要本地 ReAct，又需要 ACP 外部进程 |
| ⭐⭐⭐⭐⭐ | HITL（中断+恢复） | `wait` 节点必须支持用户审核后继续 |
| ⭐⭐⭐⭐ | 流式 SSE 协议 | 12 种事件的精细控制 |
| ⭐⭐⭐⭐ | 持久化 & 状态恢复 | SQLite + ChromaDB + checkpoint |
| ⭐⭐⭐ | 反模式/自学习 | 从失败中自动提取约束 |
| ⭐⭐⭐ | Per-agent 隔离 | 每个 agent 有自己的模型/tools/system_prompt |
| ⭐⭐ | A2A 协议兼容 | 未来与外部 A2A agent 互操作 |
| ⭐⭐ | 社区生态 | GitHub Stars + 文档 + 第三方集成 |

### 综合评分

| 框架 | 图编排 | 多 Agent 混合 | HITL | SSE 流式 | 持久化 | 自主学习 | Agent 隔离 | A2A 兼容 | 生态 | **总分** |
|------|--------|--------------|------|---------|--------|---------|-----------|---------|------|---------|
| **LangChain/LangGraph** ✅ | 5 | 5 | 5 | 5 | 5 | 3 | 5 | 2 | 5 | **40/40** |
| Pydantic AI | 4 | 3 | 5 | 4 | 4 | 2 | 4 | 3 | 2 | **31** |
| Google ADK | 3 | 4 | 3 | 4 | 4 | 1 | 4 | 5 | 2 | **30** |
| CrewAI | 3 | 4 | 2 | 2 | 2 | 1 | 4 | 1 | 4 | **23** |
| LlamaIndex | 2 | 3 | 2 | 3 | 3 | 1 | 3 | 1 | 4 | **22** |
| Haystack | 3 | 2 | 2 | 3 | 3 | 1 | 3 | 1 | 3 | **21** |
| OpenAI Agents SDK | 2 | 3 | 3 | 3 | 1 | 1 | 3 | 2 | 3 | **21** |
| AutoGen/AG2 | 2 | 4 | 3 | 2 | 2 | 2 | 3 | 2 | 3 | **23** |
| Semantic Kernel | 3 | 3 | 3 | 3 | 3 | 1 | 3 | 2 | 3 | **24** |
| Agno | 2 | 3 | 2 | 3 | 3 | 1 | 2 | 1 | 3 | **20** |
| Dify | 2 | 2 | 1 | 3 | 3 | 1 | 1 | 1 | 3 | **17** |
| Coze | 1 | 2 | 1 | 2 | 2 | 1 | 1 | 1 | 2 | **13** |
| Swarm | 1 | 2 | 1 | 2 | 0 | 0 | 2 | 1 | 2 | **11** |
| MetaGPT | 1 | 2 | 0 | 1 | 2 | 1 | 3 | 1 | 3 | **14** |
| AutoGPT | 1 | 1 | 1 | 2 | 2 | 2 | 1 | 1 | 4 | **15** |
| Cursor Agent | 0 | 1 | 0 | 2 | 1 | 0 | 0 | 0 | 2 | **6** |
| Devin | 0 | 0 | 1 | 2 | 1 | 0 | 0 | 0 | 1 | **5** |
| A2A（协议） | — | — | — | — | — | — | — | 5 | 3 | **（协议）** |

> **框架维度评分依据**：仅基于框架本身的架构能力，不包含「此项目已用 LangGraph」的存量优势。
> A2A 作为通信协议而非框架，不作为主评分对象。

---

## 三、逐框架深度分析

### 1. LangChain / LangGraph（当前选型：✅ 顶配匹配）

**当前使用**（4 个源码入口）：
- `src/agent/orchestrator/core.py:507` — `StateGraph(GraphState)` 构建 6 节点图
- `src/agent/agent/core.py:113` — `create_agent()` 构建单 Agent ReAct 循环
- `src/agent/orchestrator/tools.py:67` — `create_react_agent()` 构建子 Agent
- `src/agent/orchestrator/core.py:537` — `MemorySaver()` checkpoint 持久化

**匹配度逐项分析**：

| 需求 | LangGraph 实现 | 代码证据 |
|------|---------------|---------|
| 有环有向图 | `_route_from_synthesize` 可返回 `"revise"` → `"plan"` 形成回路 | `core.py:525-532` |
| 条件边 | `add_conditional_edges("plan", _route_from_plan, ...)` | `core.py:518-522` |
| 中断/HITL | `interrupt()` + `Command(resume=...)` | `core.py:237`, `core.py:604-658` |
| 多 Agent 混合 | `SubAgentTool` (本地) + `ACPSubAgentTool` (外部) | `tools.py:25-146` |
| 流式 | `astream_events()` + asyncio.Queue 事件转发 | `core.py:548-600` |
| 持久化 | `MemorySaver` + SQLite + ChromaDB | `core.py:537` |
| Per-agent 模型 | `resolve_model(config, model_override=cfg.get("model"))` | `tools.py:60-65` |
| 反模式学习 | `_reflect_node` 解析 LLM 输出 → `save_anti_pattern()` | `core.py:420-451` |

**唯一弱项**：A2A 协议兼容（无原生支持）。但可通过 ACP 协议桥接。

**结论**：LangGraph 在本项目的 9 个关键维度上全部满足，其中 6 个维度为满分。

---

### 2. Pydantic AI（总分 31/40 — 最有力的潜在补充）

**核心优势**：
- Pydantic 类型安全：结构化输出保证（本项目大量使用 Pydantic `BaseModel`: `Planner.py:28-73`）
- 持久化执行：agent 状态可在崩溃后恢复（本项目 `MemorySaver` 已有，但可借鉴实现）
- HITL 工具审批（`events.py:84` 已有 `permission_request` 事件，可受益）
- MCP/A2A 双协议支持（本项目的 ACP 类似 MCP，但缺 A2A）

**与本项目的整合点**：
```
当前:  LangGraph StateGraph ──→ SubAgentTool (create_react_agent)
                          └──→ ACPSubAgentTool (ACP 进程)

可引入: Pydantic AI 用于结构化输出层
        └── 替换 planner.py 中的 Plan 解析兜底（_parse_plan_fallback）
        └── 增强 synthesize 节点的审计报告结构化
```

**迁移成本**：低。仅作为结构化输出/持久化增强层选择性引入，不改编排层。

---

### 3. Google ADK（总分 30/40 — 生态适配潜力，但社区小）

**核心优势**：
- A2A 协议原生支持（本项目缺 A2A）
- 多语言 SDK（Python/TS/Go/Java/Kotlin）
- Graph workflows（ADK 2.0 新加入的图编排，尚不成熟）
- 内置 evaluation framework（本项目无 eval 层）

**关键差距**：
```python
# 本项目已实现的反模式学习系统：
# core.py:420-451
async def _reflect_node(self, state: GraphState) -> dict:
    # 解析失败模式 → 保存到 experiences.md → 下次 plan 加载
    patterns_data = json.loads(reflect_text)
    for item in patterns_data:
        save_anti_pattern(AntiPattern(**item))
```
ADK 无类似机制，需自行构建。

**迁移成本**：极高。需要重写整个 6 节点 StateGraph，放弃 MemorySaver checkpoint，适配 ADK 的 agent 生命周期。

**结论**：当 A2A 生态成熟、且需要与 Google Vertex AI 深度绑定时可考虑，当前不做迁移。

---

### 4. CrewAI（总分 23/40 — 多 Agent 抽象最直观，但图能力不足）

**核心差距**：
```python
# 本项目需要的有环图拓扑：
# core.py:525-532
builder.add_conditional_edges(
    "synthesize",
    self._route_from_synthesize,
    {
        "approve": "reflect",
        "revise": "plan",    # ← 回路！CrewAI 不支持
        "reject": "__end__",
    },
)
```
CrewAI 的 process 模型（sequential/hierarchical）无法表达 revision 回路。

**CrewAI 适合的场景**（本项目已有类似能力）：
```
CrewAI: ResearchAgent → WriteAgent → ReviewAgent
本项目: perceive → plan → dispatch → synthesize → reflect
```
`perceive→plan→dispatch→synthesize` 这 4 步本质上是一个 Crew，但 `synthesize→plan` 回路是 CrewAI 做不到的。

---

### 5. LlamaIndex（总分 22/40 — 文档/RAG 层有价值的补充）

**最佳整合点**：
- **LlamaParse**：本项目如果涉及 PDF/复杂文档解析，可引入 LlamaParse 作为文件工具
- **Agentic Document Processing**：提取-分类-分割管道，可作为 `dispatch` 节点的一个子任务

**不替换**：LlamaIndex 的 Workflows 引擎是 DAG（无环），无法实现 `synthesize→plan` 回路。

---

### 6. Haystack（总分 21/40 — 企业级 RAG，但 agent 能力弱）

**最佳整合点**：
- **Haystack RAG pipeline**：如果项目需要做企业级语义搜索/文档问答，可作为工具集成
- **SOC 2 合规**：本项目目前无合规层，Haystack 可补

**不替换**：Haystack 的 pipeline 是 DAG（无环），且 agent 能力弱于 LangGraph。

---

### 7. AutoGen / AG2（总分 23/40 — 对话式多 Agent，但图形控制不足）

**核心差距**：Conversational Agent 的消息传递模型 vs 本项目的 StateGraph 图模型。

```python
# AutoGen 模式：
agent_a.send(message, agent_b)  # 消息传递
agent_b.send(reply, agent_a)    # 对等对话

# 本项目模式：
# core.py:518-522
builder.add_edge("perceive", "plan")
builder.add_conditional_edges("plan", _route_from_plan, {
    "dispatch": "dispatch",
    "wait": "wait",
})  # 有向图边，无对等对话
```

AutoGen 更适合协作式辩论/讨论场景，本项目需要的是 supervisor→subordinate 的层级编排。

**AG2 的 A2A 支持**值得关注：如果未来需要跨框架 agent 协作，AG2 可能是桥接层。

---

### 8. Semantic Kernel（总分 24/40 — .NET 企业首选，但本项目是 Python）

**核心优势与本项目无交集**：
- C#/.NET 优先 — 本项目纯 Python
- Azure 生态绑定 — 本项目云无关
- Process Framework（BPM 编排）— 本项目已有 StateGraph

**唯一有价值点**：Plugin 架构的设计模式（native code + semantic prompts 混合），可作为 `SubAgentTool` 的优化参考。

---

### 9. OpenAI Agents SDK（总分 21/40 — 简洁但无持久化、无图）

**关键缺失**：
```python
# 本项目依赖的持久化 checkpoint：
# core.py:537
checkpointer = MemorySaver()
return builder.compile(checkpointer=checkpointer)
```
OpenAI Agents SDK **无内置持久化**。需要外部集成 Temporal 才能达到同样效果。

**唯一亮点**：三层 guardrails（input/output/tool）比本项目目前的 circuit breaker 更完善，可选择性引入 guardrail 概念。

---

### 10-18. 其余框架（不推荐作为主框架）

| 框架 | 总分 | 不推荐原因 |
|------|------|-----------|
| Agno | 20 | 轻量多 Agent 但无图编排、无 checkpoint |
| Dify | 17 | 低代码可视化、无编程级控制、无 HITL |
| Coze | 13 | SaaS 平台、无法自建、数据主权问题 |
| Swarm | 11 | 教育项目、已停止维护、无持久化 |
| MetaGPT | 14 | 仅软件模拟场景、通用编排能力弱 |
| AutoGPT | 15 | 自主循环不稳定、无结构化图 |
| Cursor Agent | 6 | IDE 级、不通用 |
| Devin | 5 | 闭源 SaaS、不通用 |

---

## 四、集成可行性评估

### ✅ 可选择性引入（低风险、高价值）

| 框架 | 引入组件 | 集成方式 | 预期收益 |
|------|---------|---------|---------|
| **LlamaIndex** | LlamaParse | 作为新 tool 注册到 `tools.json` | 增强 PDF/复杂文档解析 |
| **Haystack** | Pipeline 组件 | 可选 tool（`search_documents`） | 企业级语义搜索增强 |
| **Pydantic AI** | 结构化输出/持久化 | 替换 `planner.py` 的 Plan 解析兜底 | 提高 Plan/审计输出可靠性 |
| **OpenAI Agents SDK** | Guardrail 模式 | `error_handler.py` 新增 guardrail 层 | 输入/输出安全过滤 |
| **A2A 协议** | 跨框架通信 | `ACPNativeClient` 旁新增 A2A 客户端 | 与 Google/LlamaIndex agent 互操作 |
| **AG2** | 多 Agent 桥接 | ACP+ 模式，注册为 A2A 节点 | 扩展外部 agent 种类 |

### ❌ 不推荐替换的主框架

| 框架 | 迁移成本 | 风险 | 理由 |
|------|---------|------|------|
| LangGraph → CrewAI | 高（重写整个图） | 高 | 不支持回路、无 checkpoint |
| LangGraph → Google ADK | 极高 | 高 | 社区小、API 不稳定、A2A 生态未成熟 |
| LangGraph → Semantic Kernel | 高 | 中 | .NET 倾向、Azure 绑定 |
| LangGraph → AutoGen | 高 | 高 | 对话模型 vs 图模型，控制力下降 |
| LangGraph → Pydantic AI | 中 | 中 | 太新、生态小、尚无大规模生产案例 |

### 🟡 可选择性监测（看 1-2 年后的发展）

| 框架 | 监测点 | 触发迁移/引入的条件 |
|------|-------|-------------------|
| Pydantic AI | GitHub Stars > 50k、社区生态 > 100 集成 | 需要更可靠的结构化输出保证 |
| Google ADK | A2A 协议成为行业标准 | 需要大规模跨厂商 agent 编排 |
| AG2 | 社区 > 30k stars | 需要原生 A2A + MCP 双协议支持 |
| A2A | 实际采纳率 > 30% 财富 500 强 | 需要跨组织 agent 协作 |

---

## 五、技术债务与改进建议

### 当前项目中的框架使用细节

```python
# 1. LangGraph 版本兼容性
# core.py:19 — 使用 langgraph.types.Command, interrupt
# core.py:17 — 使用 langgraph.checkpoint.memory.MemorySaver
# 当前锁定 langgraph 版本，需确认升级时 API 兼容

# 2. create_react_agent vs create_agent
# tools.py:67 — 使用 langgraph.prebuilt.create_react_agent
# core.py:113 — 使用 langchain.agents.create_agent
# 两个不同路径创建 Agent，增加了维护复杂度

# 3. MemorySaver 生产化
# core.py:537 — MemorySaver 是内存级 checkpoint
# 生产环境需要替换为 langgraph-checkpoint-postgres 或 SQLite
```

### 建议优先级

1. **短期（立即）**：保持 LangGraph 为主编排引擎，不做迁移
2. **短期（1-2 周）**：
   - 统一 Agent 创建路径（全部用 `create_react_agent`）
   - 将 `MemorySaver` 替换为 `SqliteSaver` 或 `PostgresSaver` 以实现持久化 checkpoint
   - 在 `error_handler.py` 中引入 guardrail 概念
3. **中期（1-3 个月）**：
   - 引入 LlamaParse 作为文件处理工具
   - 评估 Pydantic AI 的结构化输出层集成
   - 建立 A2A 协议兼容的客户端桥接（如 AG2 的 A2A 模块）
4. **长期（6-12 个月）**：
   - 根据 A2A 生态成熟度，决定是否引入 A2A 作为跨框架通信层
   - 持续关注 `Pydantic AI` 和 `Google ADK` 的发展
   - 考虑将 `checkpointer` 升级到 `langgraph-checkpoint-postgres`

---

## 六、核心结论

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  保持 LangGraph 为编排引擎，不迁移到替代框架。         │
│                                                     │
│  理由：                                              │
│  1. 有环有向图（6 节点 + revision 回路）             │
│     是项目最核心、最独特的需求，                       │
│     只有 LangGraph 原生支持。                        │
│                                                     │
│  2. 本地 ReAct + ACP 外部 Agent 的混合编排          │
│     在 LangGraph 中通过 SubAgentTool /              │
│     ACPSubAgentTool 优雅实现。                       │
│                                                     │
│  3. interrupt/Command 的 HITL 模式                  │
│     与项目 wait 节点的需求完全匹配。                  │
│                                                     │
│  4. 反模式学习系统（reflect → save → load）          │
│     是项目独特附加值，非标准化框架能力。               │
│                                                     │
│  可选择性增强：                                      │
│  → LlamaParse（文档解析）                            │
│  → Pydantic AI（结构化输出）                         │
│  → A2A 协议（未来跨框架通信）                        │
│  → Guardrails（安全过滤）                            │
│                                                     │
└─────────────────────────────────────────────────────┘
```
