# Orchestrator v2 执行计划

## 概述

将当前 `supervisor → execute → review` 三段线性 StateGraph 替换为支持**中断、并行、审核门、反模式自优化**的新图。

### 设计原则

1. **新增能力不破坏现有协议** — SSE 事件格式、前端消费、/chat 端点、CLI 模式、ACP 协议、db 层全部不变
2. **可验证** — 每个阶段都有对应的 test case，旧测试只需调整 mock 对象
3. **增量替换** — 一整个 PR，但内部按文件粒度分 commit，每个 commit 可独立测试
4. **向后兼容** — `/api/orchestrate` 端点 URL 不变，响应格式保持兼容

### Harness 能力映射

| Harness 维度 | 实现方式 | 覆盖节点 |
|---|---|---|
| **规则 (Rules)** | Pydantic 模型校验（`Plan`, `Step`, `GraphState`）+ 运行时守卫（`max_steps`, `max_revisions`, 循环依赖检测, step 超时）+ 节点输入/输出类型约束 | perceive → plan → dispatch → synthesize → reflect 全线 |
| **控制 (Control)** | `NodeInterrupt` 运行时中断 + conditional edge 三态路由（approve/revise/reject）+ `_route_from_synthesize` 守卫函数 | plan（中断点）→ synthesize（路由） |
| **上下文 (Context)** | `GraphState.history` 持有原始历史 → perceive_node 压缩为 `history_summary` → plan_node 注入 prompt → dispatch_node 注入 sub-agent | perceive → plan → dispatch |
| **感知 (Perception)** | `load_constraints()` 从 `memory/experiences.md` 读取反模式 → plan_node 注入 prompt → reflect_node 检测新反模式 → `save_anti_pattern()` 持久化 | reflect → (文件) → plan |

---

## 阶段零：预研与设计（当前）

- [x] 评审当前 orchestrator/core.py 的 3 节点图
- [x] 确认 SSE 事件格式兼容性（新图不需要新事件类型）
- [x] 确认 Perceive 节点依赖（ContextCompressor 复用现有逻辑）
- [x] 确认并行分叉机制（dispatch_node 内部用 `asyncio.gather`，不是 LangGraph `Send()` API — 因为 sub-agent 调用是 Python 协程而非子图）
- [x] 确认中断机制（LangGraph `interrupt()` 函数，`from langgraph.types import interrupt`，非已弃用的 `NodeInterrupt` 异常）
- [x] 确认中断节点分离设计：`plan_node` 只生成 plan 不中断；新增 `wait_node` 专用于中断，避免 state 修改丢失
- [x] 确认恢复 API：`Command(resume=...)`，非 `astream(None)`
- [x] Checkpointer 用 `InMemorySaver`（`langgraph.checkpoint.memory`，注意重启后丢失）
- [x] 确认 resume 时的事件泵：`resume()` 需要有独立的事件泵循环，或复用 `run()` 的事件泵

**产出：** 本文档

---

## 阶段一：核心数据结构（1 个 commit）

**目标：** 定义新 Graph 使用的 Pydantic 模型，替换当前基于 dict 和 regex 的 plan 格式。

### 改动文件：`src/agent/orchestrator/planner.py`

```python
from __future__ import annotations

from pydantic import BaseModel


class Step(BaseModel):
    agent: str                     # agent id (coder/researcher/opencode/...)
    task: str                      # 子任务描述
    depends_on: list[str] = []     # 依赖的其他 step.agent（为空则可并行）
    context: str = ""              # 该 step 的额外上下文（perceive 阶段注入）


class Plan(BaseModel):
    steps: list[Step]
    reasoning: str = ""            # supervisor 的思考过程（可选，透传给前端）
    auto_approve: bool = False     # True = 单步/简单任务，不中断等待审核


class AgentResult(BaseModel):
    agent: str
    task: str
    result: str
    error: str = ""
    elapsed_ms: int = 0


class AntiPattern(BaseModel):
    label: str                     # 反模式标签（plan_drift / context_overload / ...）
    task: str
    agent: str
    what_happened: str
    suggestion: str
    severity: str = "medium"       # high / medium / low


class GraphState(BaseModel):       # 替换当前 TypedDict
    task: str
    history: list[dict] = []       # 原始对话历史（perceive_node 的输入）
    history_summary: str = ""      # perceive 阶段输出的上下文摘要（事实列表）
    plan: Plan | None = None
    results: dict[str, AgentResult] = {}     # agent_name → result
    errors: list[str] = []
    review_decision: str = ""      # "approve" | "revise" | "reject" | ""
    review_feedback: str = ""      # revise 时用户的反馈
    anti_patterns: list[AntiPattern] = []
    constraints: list[str] = []    # 从 anti_patterns 提炼的约束，下次 plan 注入

    # ── 运行时保护 ─────────────────────────────────────────────
    step_count: int = 0            # 当前已执行 step 数，防无限循环
    max_steps: int = 20            # 单次 graph 调用的最大 step 上限
    max_revisions: int = 3         # 最大 revise 次数，超限强制 approve
```

### 删除

- `_PLAN_RE` 全局 regex 变量
- `_parse_plan()` 静态方法（改为 `Plan.model_validate()`）

### 受影响测试

- `test_supervisor.py::TestParsePlan`（5 个 test）→ **删除**，不再需要 regex 解析
- 新加 `test_plan_model.py` 测试 Pydantic model 序列化/反序列化

### 不影响

- `build_agent_descriptions()` 函数签名不变
- `load_experiences()` / `save_experiences()` 函数签名不变（内容格式稍后改）

---

## 阶段二：重写 Graph 结构（1 个 commit，最大改动）

**目标：** 用 6 节点新图替换当前 3 节点图。

### 改动文件：`src/agent/orchestrator/core.py`（重写 ~80%）

```python
class Orchestrator:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.model = _models.resolve_model(config)
        self.sub_agents: dict[str, dict] = {}
        self.acp_agents: dict[str, str] = {}
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self._tokens: dict[str, dict[str, int]] = {}
        self._memory_provider: MemoryManager | None = None  # 延迟初始化
        self._load_agent_configs()

    def _build_graph(self):
        """
        节点:
          perceive  →  plan → wait → dispatch  →  synthesize  →  reflect
                              ↑         │           │
                              └─────────┴──── revise ┘

        conditional: review_decision == "approve" → reflect
                     review_decision == "revise"  → plan (with constraints + feedback)
                     review_decision == "reject"  → end (with error event)

        入口: perceive
        中断节点: wait（与 plan_node 分离，避免 state 修改丢失）
          - plan_node 生成 plan 后，如果 auto_approve=False，路由到 wait_node
          - wait_node 调用 interrupt(value={"plan": plan.json()}) 挂起
          - auto_approve=True → 跳过 wait_node，直连 dispatch
          
        中断恢复：
          - 用户 approve: astream(Command(resume="approved"), config)
          - 用户 revise: 调用 update_state 设置 review_feedback 并清空 plan
                        astream(Command(resume="revised"), config)
          - 用户 reject: 调用 update_state 设置 review_decision="reject"
                        astream(Command(resume="rejected"), config)

        守卫:
          - step_count >= max_steps → 终止
          - revisions >= max_revisions → 强制 approve
          - depends_on 循环依赖检测 → reject
        """
        builder = StateGraph(GraphState)
        builder.add_node("perceive", self._perceive_node)
        builder.add_node("plan", self._plan_node)
        builder.add_node("wait", self._wait_node)
        builder.add_node("dispatch", self._dispatch_node)
        builder.add_node("synthesize", self._synthesize_node)
        builder.add_node("reflect", self._reflect_node)
        builder.set_entry_point("perceive")
        builder.add_edge("perceive", "plan")
        builder.add_conditional_edges(
            "plan",
            self._route_from_plan,
            {"dispatch": "dispatch", "wait": "wait"},
        )
        builder.add_edge("wait", "dispatch")
        builder.add_edge("dispatch", "synthesize")
        builder.add_conditional_edges(
            "synthesize",
            self._route_from_synthesize,
            {
                "approve": "reflect",
                "revise": "plan",    # plan_node 收到 review_feedback，重新生成
                "reject": "__end__",
                "skip": "reflect",
            },
        )
        builder.add_edge("reflect", "__end__")

        from langgraph.checkpoint.memory import InMemorySaver
        checkpointer = InMemorySaver()
        return builder.compile(checkpointer=checkpointer)

    def _route_from_plan(self, state: GraphState) -> str:
        """plan 完成后决定是否中断。"""
        if state.plan and state.plan.auto_approve:
            return "dispatch"
        return "wait"

    def _route_from_synthesize(self, state: GraphState) -> str:
        """根据 synthesize_node 的审核结果路由。"""
        decision = state.review_decision
        state.step_count += 1

        # 守卫: 超过 revise 上限
        if decision == "revise" and state.step_count >= state.max_revisions:
            return "approve"
        # 守卫: 超过最大 step
        if state.step_count >= state.max_steps:
            return "approve"

        return decision or "skip"

    async def _wait_node(self, state: GraphState) -> dict:
        """中断节点：仅负责挂起 graph，不修改 state。"""
        from langgraph.types import interrupt
        plan_json = state.plan.model_dump() if state.plan else {}
        await interrupt({"plan": plan_json})
        return {}
```

### 各节点逻辑

#### perceive_node

```
功能: 将对话历史压缩为结构化的上下文摘要

输入: GraphState.history + GraphState.task
逻辑:
  1. 从 state.history 读取原始对话历史（由 run() 在调用 graph.ainvoke() 前存入 state）
  2. 如果有 summary（上次 compact 的产物），直接作为上下文的一部分
  3. 用 ContextCompressor._summarize（复用现有，需传入 self.model）压缩历史为事实列表
  4. 如果上轮的结果是 ACP agent 的输出，提取事实而非保留操作描述
  5. 将 history_summary（事实列表字符串）存入 state

事件: thinking_start("supervisor") → thinking("supervisor", progress) → thinking_done("supervisor")

关键质量: 提炼格式必须是"事实"而非"操作"
  ✓ "[Fact] .env 内容: provider=openai, model=gpt-4o"
  ✗ "[Fact] opencode 读取了 .env 文件"
  ✓ "[Fact] 用户当前要求: 基于 .env 推荐其他模型厂商"

注意: 这是新架构的关键节点。压缩质量直接影响后续 plan 的正确性。
注意2: perceive_node 使用 ContextCompressor._summarize (ainvoke 非流式)，
       不会产生 thinking 流式事件。如果前端需要 perceive 阶段的进度指示，
       可以在 perceive_node 前后显式发送 thinking_start / thinking_done 事件。
```

#### plan_node

```
功能: 生成结构化 Plan。不中断 — 中断由单独的 wait_node 负责。

输入: GraphState (含 task + history_summary + constraints)
逻辑:
  1. 如果 state.plan 已存在（来自 revise 重试）且 state.review_feedback 非空:
     → 带着 feedback 重新生成 plan（不是跳过 LLM）
  2. 否则加载 experiences.md 中的反模式约束
  3. 构建 prompt，注入:
     - agent_descriptions（来自 config）
     - context_facts（来自 perceive 阶段的 history_summary）
     - constraints（来自之前会话的反模式）
     - review_feedback（如果是 revise 重试）
     - task
  4. LLM 输出 JSON 格式的 Plan（非文本）
  5. Plan.steps 中自动标注 auto_approve
  6. 返回 {"plan": plan}

注意: plan_node 不负责中断。中断由 _route_from_plan 路由到 wait_node。

事件: thinking_start("supervisor") → thinking → thinking_done → plan("supervisor", plan.json())

prompt 关键变更（与当前 SUPERVISOR_PLAN_PROMPT 的区别）:
  - 新增 "当前已获取的上下文" 段落 → 避免重复操作
  - 输出格式改为 JSON 而非自由文本 → 不再需要 regex 解析
  - 新增 "之前会话中发现的约束" 段落 → 反模式防护
  - 新增 "用户的修订意见" 段落（revise 重试时）→ 针对性修正
```

#### wait_node

```
功能: 唯一的职责是中断 graph 等待用户审核。不修改 state。

输入: GraphState (无特殊依赖)
逻辑:
  1. 调用 interrupt(value={"plan": state.plan.json()}) 挂起 graph
  2. 等待外部通过 Command(resume=...) 恢复
  3. 恢复后直接返回（不修改 state）

注意: wait_node 与 plan_node 分离的原因：
  - LangGraph 在 interrupt() 调用时只 checkpoint 之前的 state 修改
  - 如果 plan_node 既设置 state.plan 又调用 interrupt()，plan 会丢失
  - wait_node 不修改任何 state，中断后恢复时只重跑 wait_node 本身

中断流程:
  用户通过 API 提交决策 → 调用 Orchestrator.resume():
    approve: Command(resume="approved")
    revise: Command(update={"plan": None, "review_feedback": feedback}, resume="revised")
           → 清空 plan，plan_node 会用 feedback 重新生成
    reject: Command(update={"review_decision": "reject"}, resume="rejected")
           → synthesize 检测到 reject → 终止
```

#### dispatch_node

```
功能: 并行分发给各个 sub-agent

输入: GraphState.plan.steps
逻辑:
  1. 解析 steps，构建依赖图（DAG）
  2. 按拓扑排序分层：同一层内无依赖，用 asyncio.gather 并行执行
  3. 同层各 step 执行完后，继续下一层
  4. 每个 sub-agent 调用时注入:
     - 原始 task
     - history_summary（perceive 阶段的输出）
     - 该 step 的 task
     - 同层之前已完成的其他步骤结果（如果有）
  5. 收集结果 → results dict
  6. 守卫: 如果某个 step 超时（可配置，默认 600s），标记为 error，不阻塞其他 step

注意: 使用 asyncio.gather 并行执行 Python 协程，而非 LangGraph 的 Send() API
原因: sub-agent 调用是外部协程（ACP 子进程 / LangGraph create_react_agent），
不是子图。Send() 用于图内分叉子图，适合 map-reduce 模式，不适用于本场景。

事件:
  - 每个 step 开始: task_update(agent, task, "running")
  - 每个 step 结束: task_update(agent, task, "completed")
  - 每个 step 失败: task_update(agent, task, "failed") + 记录 error
  - 每个 step 输出: message(agent, result_text)

SubAgentTool._arun 签名变更:
  - 新增参数: context: str = ""
  - 注入到 sub-agent 的 system prompt 中
```

#### synthesize_node

```
功能: 汇总所有 sub-agent 的结果，做出审核决策

输入: GraphState (含 task + plan + results)
逻辑:
  1. 如果没有结果 → review_decision = "reject"（不需要 LLM）
  2. 如果有错误且无成功结果 → review_decision = "reject"（不需要 LLM）
  3. 如果所有结果都成功 → 调用 LLM 审核（使用 AUDITOR_PROMPT 升级版）
  4. LLM 输出 review_decision: "approve" | "revise" | "reject"
  5. 如果是 "revise"，附带反馈（存入 review_feedback，作为下一次 plan 的 constraints）

守卫规则:
  - 重复操作检测: 同文件被多个 agent 操作 → revise
  - 空结果检测: agent 返回空或不相关内容 → revise
  - 错误传播检测: 如果 step A 的结果被 step B 当作输入，且 B 失败了 → revise

事件: audit_summary("supervisor", audit_text)

审核 prompt 升级（与当前 AUDITOR_PROMPT 的区别）:
  - 新增输出要求: "请给出审核决策: approve / revise / reject"
  - 新增 "revise 时需给出具体改进建议"
  - 新增检查项: "是否有 agent 执行了重复操作"
```

#### reflect_node

```
功能: 提取反模式经验，更新 memory/experiences.md

输入: GraphState (含 task + plan + results + errors + review_decision)
逻辑:
  1. 分析本次执行中的异常模式（使用 REFLECT_PROMPT + LLM 调用）:
     - 是否有 agent 超时或失败 → 标记为 agent_unsuitability
     - 是否有重复操作 → 标记为 context_overload
     - 是否有计划与实际执行偏离 → 标记为 plan_drift
     - 是否有多个 agent 做了类似的事 → 标记为 task_overlap
     - 是否有错误传播 → 标记为 error_cascade
     - 是否有幻觉传播 → 标记为 hallucination_propagation
  2. 每个检测到的反模式 → AntiPattern model
  3. 保存前做去重: 检查 experiences.md 中是否已有相似 label + task 的条目
     - 去重逻辑: 如果已有完全相同的 (label, task)，只更新时间戳，不追加新条目
  4. 如果无重复，用新的 save_anti_pattern() 追加写入 experiences.md
     （不同于旧的 save_experiences()，旧的保留不动给其他组件用）
  5. 更新 GraphState.anti_patterns + constraints

events: summary("supervisor", reflect_text)  # 可选

experiences.md 新格式:
  ## Anti-Pattern: plan_drift
  - Task: "推荐模型厂商"
  - Agent: supervisor
  - What happened: 计划写了 "读 .env"，但 .env 内容已在上下文中
  - Suggestion: 下次检查 context 后再决定是否需要读文件
  - Severity: medium
  - Date: 2026-06-05

新函数:
  - save_anti_pattern(ap: AntiPattern) → 追加或更新时间戳
  - load_constraints() → list[str] — 从 experiences.md 提炼最近 N 条约束
    (与旧 load_experiences() 区分，旧的返回纯文本给其他组件)
```

### 删除

- `_supervisor_node_impl()` — 被 `_plan_node()` 替代
- `_execute_node_impl()` — 被 `_dispatch_node()` 替代
- `_review_node_impl()` — 被 `_synthesize_node()` + `_reflect_node()` 替代

### 保留

- `run()` 方法签名 — `async def run(self, task, history=None, summary=None)` **不变**
- `_load_agent_configs()` — **不变**
- `_estimate_tokens()` — **保留**，但新增 ACP 真实 usage 读取逻辑

### `run()` 方法适配

```python
import uuid

async def run(self, task, history=None, summary=None):
    start_time = time.time()
    self.queue = asyncio.Queue()
    graph_app = self._build_graph()

    # 构建初始 state: history 存入 state，让 perceive_node 能访问
    initial = GraphState(
        task=task,
        history=history or [],
        history_summary=summary or "",
    )

    # 线程 ID：用于中断恢复 + checkpoint
    thread_id = str(uuid.uuid4())
    thread_config = {"configurable": {"thread_id": thread_id}}

    # 启动 graph（带 checkpointer → 支持中断恢复）
    run_task = asyncio.create_task(
        graph_app.ainvoke(initial, config=thread_config)
    )

    # 事件泵（与当前逻辑相同，从 queue 消费）
    final_state = None
    interrupted = False
    while True:
        done_fut = asyncio.ensure_future(run_task)
        get_coro = self.queue.get()
        queue_fut = asyncio.ensure_future(get_coro)
        pending = {done_fut, queue_fut}
        done, _ = await asyncio.wait(pending, return_when=FIRST_COMPLETED)

        if done_fut in done:
            queue_fut.cancel()
            while not self.queue.empty():
                yield await self.queue.get()
            final_state = done_fut.result()
            # 检测中断: ainvoke 返回的 dict 中有 __interrupt__ 键
            if isinstance(final_state, dict) and "__interrupt__" in final_state:
                interrupted = True
                plan_data = final_state.get("plan")
                plan_json = plan_data.model_dump() if plan_data else None
                self._interrupted_threads[thread_id] = graph_app
                yield {"type": "interrupt", "data": {
                    "thread_id": thread_id,
                    "plan": plan_json,
                }}
            break
        if queue_fut in done:
            yield await queue_fut

    if interrupted:
        return  # 等待 review API 恢复，不发送 metrics 和 done

    # 最终 metrics
    elapsed = int((time.time() - start_time) * 1000)
    yield make_metrics("supervisor", {
        "elapsed_ms": elapsed,
        "agent_calls": len(final_state.results) if final_state else 0,
        "tokens": self._tokens,
    })
    yield make_done()
```

### 新增事件类型 `interrupt`

需要在 `src/agent/events.py` 中注册：

```python
class EventType:
    INTERRUPT: Final[str] = "interrupt"

def make_interrupt(thread_id: str, plan: dict | None = None) -> dict:
    return make_event(EventType.INTERRUPT, data={"thread_id": thread_id, "plan": plan})
```

并在 `src/agent/orchestrator/_events.py` 中 re-export。

---

## 阶段三：server.py 新增中断 API（1 个 commit）

**目标：** 前端/用户可以通过 API 对 plan 做出 approve/revise/reject。

### 改动文件：`server.py`

中断恢复的核心要点：**不要创建新的 `run()` 调用**，而是通过 `Orchestrator` 持有的 checkpointer 恢复原有的 graph 线程。

```python
from langgraph.types import Command
from langgraph.checkpoint.memory import InMemorySaver


class ReviewPlanRequest(BaseModel):
    session_id: str
    thread_id: str              # 由 run() 的 interrupt event 返回
    decision: str               # "approve" | "revise" | "reject"
    feedback: str = ""


# Orchestrator 需要暴露恢复方法:
class Orchestrator:
    _interrupted_threads: dict[str, CompiledStateGraph] = {}

    async def resume(self, thread_id: str, decision: str, feedback: str = ""):
        """恢复被中断的 graph 执行（带独立事件泵）。"""
        graph_app = self._interrupted_threads.get(thread_id)
        if not graph_app:
            raise ValueError(f"No interrupted thread: {thread_id}")

        thread_config = {"configurable": {"thread_id": thread_id}}
        self.queue = asyncio.Queue()  # 新队列，resume 期间的事件走这个泵

        if decision == "approve":
            cmd = Command(resume="approved")
        elif decision == "revise":
            # 清空 plan → plan_node 检测到 plan=None 且 review_feedback 非空
            # 会带着 feedback 重新生成 plan
            graph_app.update_state(thread_config, {
                "plan": None,
                "review_feedback": feedback,
            })
            cmd = Command(resume="revised")
        elif decision == "reject":
            graph_app.update_state(thread_config, {
                "review_decision": "reject",
            })
            cmd = Command(resume="rejected")
        else:
            raise ValueError(f"Unknown decision: {decision}")

        # 恢复 graph（带事件泵，与 run() 模式相同）
        run_task = asyncio.create_task(
            graph_app.ainvoke(cmd, config=thread_config)
        )
        while True:
            done_fut = asyncio.ensure_future(run_task)
            get_coro = self.queue.get()
            queue_fut = asyncio.ensure_future(get_coro)
            pending = {done_fut, queue_fut}
            done, _ = await asyncio.wait(pending, return_when=FIRST_COMPLETED)

            if done_fut in done:
                queue_fut.cancel()
                while not self.queue.empty():
                    yield await self.queue.get()
                break
            if queue_fut in done:
                yield await queue_fut

        # 最终 metrics
        final_state = run_task.result()
        elapsed = time.time() - self._resume_start_time
        yield make_metrics("supervisor", {
            "elapsed_ms": int(elapsed * 1000),
            "agent_calls": len(final_state.results) if final_state else 0,
            "tokens": self._tokens,
        })
        yield make_done()


@app.post("/api/orchestrate/{session_id}/review")
async def review_plan(session_id: str, request: ReviewPlanRequest):
    """
    用户对 plan 的审核决策。

    - approve: 继续执行 dispatch（wait_node 的 interrupt 返回 "approved"）
    - revise: 清空 plan + 设置 review_feedback → plan_node 重新生成
    - reject: 设置 review_decision=reject → synthesize 检测到 → 终止
    """
    orchestrator = get_supervisor()
    return StreamingResponse(
        orchestrator.resume(request.thread_id, request.decision, request.feedback),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
```

### 新建端点

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/orchestrate/{session_id}/review` | POST | 提交审核决策，恢复被中断的 graph |
| `/api/orchestrate/{session_id}/plan` | GET | 获取当前 plan 详情（前端展示） |
| `/api/orchestrate/{session_id}/state` | GET | 获取当前 graph 执行状态（含 pending 中断） |

### 不影响

- `/chat` 端点（单 agent ReAct 循环，不走新图）
- `/api/acp/send` 端点（直接 ACP bypass，不走新图）

---

## 阶段四：SubAgentTool 上下文注入（1 个 commit）

**目标：** dispatch 时 sub-agent 能拿到完整的上下文而非只有 subtask。

### 改动文件：`src/agent/orchestrator/tools.py`

```python
class SubAgentTool(BaseTool):
    # 新增字段
    context: str = ""               # perceive 阶段的上下文摘要
    prior_results: str = ""         # 之前完成的 step 结果（可选）

    async def _arun(self, task: str) -> str:
        # 构建 prompt 时注入 context
        system_prompt = cfg.get("system_prompt", "") + "\n\n"
        if self.context:
            system_prompt += f"[上下文信息]\n{self.context}\n\n"
        if self.prior_results:
            system_prompt += f"[已完成的步骤结果]\n{self.prior_results}\n\n"
        system_prompt += f"你的子任务：{task}"
        ...
```

同理 `ACPSubAgentTool`：调用 `acp.run(task, context=self.context)`。

### ACP agent 也需要支持 context

改动 `acp_agent.py` 中的 `ACPAgent.run()`：

```python
async def run(self, message: str, context: str = "", session_id: str = "") -> AsyncIterator[dict]:
    if context:
        # 将 context 注入到 prompt 中（不是独立 message 事件，避免前端显示"上下文"文本）
        full_prompt = f"Context:\n{context}\n\n---\n\nTask: {message}"
    else:
        full_prompt = message
    # ... 后续用 full_prompt 调用 ACP client，不变
```

注意：**已与当前实际实现一致** — `acp_agent.py:75` 已使用此模式。

### 不影响

- `acp_client.py` 协议层（JSON-RPC 消息格式不变）

---

## 阶段五：反模式系统 + reflect_node（1 个 commit）

**目标：** 实现 reflect_node，完成反模式的提取、存储、注入循环。

### 改动文件

- `src/agent/orchestrator/planner.py` — 新增 `AntiPattern` model 的序列化/反序列化
- `src/agent/orchestrator/core.py` — `_reflect_node()` 实现
- `src/agent/prompts/system_prompt.py` — 新增 `REFLECT_PROMPT`

```python
REFLECT_PROMPT = """分析本次 agent 协作执行过程，识别反模式。

原始任务: {task}
计划: {plan}
执行结果: {results}
错误: {errors}
审核决策: {review_decision}

请识别是否存在以下反模式（如无则输出空列表）:
1. plan_drift: 计划包含不必要或重复的步骤
2. context_overload: sub-agent 收到的上下文过多或过少
3. agent_confusion: agent 执行了超出其职责的任务
4. error_cascade: 一个 agent 的失败导致其他 agent 做无用功
5. task_overlap: 多个 agent 做了相似或重复的工作
6. hallucination_propagation: 一个 agent 的错误输出被其他 agent 当作事实

输出 JSON 格式:
[
  {{
    "label": "plan_drift",
    "task": "...",
    "agent": "supervisor",
    "what_happened": "...",
    "suggestion": "...",
    "severity": "medium"
  }}
]
"""
```

### experiences.md 读写

- `load_experiences()` → 同时返回反模式列表（结构化解析）
- `save_experiences()` → 追加反模式条目
- 新增 `get_constraints()` → 从 experiences.md 提炼 `constraints: list[str]`

---

## 阶段六：测试（贯穿各阶段）

### 新测试文件：`tests/test_orchestrator_v2.py`

| 测试 | 内容 |
|---|---|
| `test_perceive_node_compresses_history` | 多轮对话 → perceive 输出不包含操作细节 |
| `test_perceive_node_preserves_facts` | ACP agent 读取的文件内容在摘要中被保留 |
| `test_plan_node_structured_output` | LLM 输出 JSON → Plan model 正确解析 |
| `test_plan_node_auto_approve_single_step` | 单步任务 → auto_approve=True |
| `test_dispatch_node_parallel` | 两个无依赖 step → 并行执行 |
| `test_dispatch_node_context_injection` | sub-agent 收到上下文 |
| `test_synthesize_node_approve` | 审核通过 → review_decision=approve |
| `test_synthesize_node_revise` | 审核不通过 → review_decision=revise |
| `test_reflect_node_anti_patterns` | 重复操作 → 标记 plan_drift |
| `test_reflect_node_experiences_persist` | 反模式写入 experiences.md |
| `test_scenario_env_recommendation` | 完整场景：读 env → 推荐厂商（不需重读文件）|
| `test_graph_state_serde` | GraphState Pydantic 序列化/反序列化 |
| `test_orchestrator_init_v2` | Orchestrator v2 初始化 |

### 已有测试适配

- `test_supervisor.py::TestParsePlan`（5 个） → **删除**（Plan 不再用 regex 解析）
- `test_supervisor.py::TestPlannerHelpers`（2 个） → **保留**，`build_agent_descriptions` 不变
- `test_supervisor.py::TestOrchestratorInit`（1 个） → **保留**
- `test_supervisor.py::TestOrchestratorRun`（6 个） → **重写**，mock 新节点

### 测试策略

- 所有 mock 测试，不需要真实 API key（复用 conftest.py 的 `_isolated_env`）
- 场景测试（`test_scenario_env_recommendation`）通过 Mock 模拟 ACP 输出和 LLM 响应
- Mock 方式：**单元级 mock `model.astream`**（与当前测试一致）。
  新图有三个节点调用 LLM（plan、synthesize、reflect），需要在 `model.astream.side_effect` 中按顺序提供多个 stream
- 测试 `perceive_node` 的**关键质量**：历史中包含 `.env` 内容时，提炼后的事实列表不应丢失该信息
- 中断恢复测试：
  - `test_interrupt_raises_on_plan` — mock graph_app.ainvoke 返回 `{"__interrupt__": ...}`，验证 run() 正确检测并 yield interrupt 事件
  - `test_resume_approve` — mock graph_app.ainvoke(cmd=Command(resume="approved")), 验证恢复后 dispatch 执行
  - `test_resume_revise_clears_plan` — 验证 resume 时 state.plan 被清除，review_feedback 被设置
  - `test_resume_invalid_thread_id` — 验证不存在的 thread_id 返回错误

---

## 阶段七：清理（1 个 commit）

### 删除

- `orchestrator/dispatcher.py` — 已死（旧版 process 式调度）
- `orchestrator/summarizer.py` — 已死（旧版汇总器）
- `_PLAN_RE` — 不再需要
- `_parse_plan()` — 不再需要

### 重命名（可选）

- `planner.py` → 保留原名，内容已缩减为纯工具函数 + model 定义

---

## 时间线

| 阶段 | 估计文件数 | 估计工时 |
|---|---|---|
| 一：Pydantic 数据结构 | 2 文件（planner.py + 测试） | 1-2h |
| 二：重写 Graph 核心 | 1 文件（core.py） | **8-12h**（新增 wait_node + Command resume + __interrupt__ 检测 + 事件泵） |
| 三：server.py + events.py 中断 API | 2 文件（server.py + events.py） | **3-5h**（Command 模式 + INTERRUPT 事件类型 + error handling） |
| 四：SubAgentTool 上下文注入 | 2 文件（tools.py + acp_agent.py） | 1-2h |
| 五：反模式系统 | 3 文件（planner, core, prompts） | 2-3h |
| 六：测试 | 2 文件（新 + 旧适配） | **4-6h**（中断/恢复测试 + resume 场景） |
| 七：清理 | 2 文件删除 | 0.5h |

## 不变清单（不 touch）

- `server.py` 中 `/chat`、`/api/acp/send`、所有 session/tool/skill/memory 端点
- `acp/client.py`（ACPNativeClient 协议层）
- `acp_agent.py` 对外接口（仅加 context 参数）
- `events.py` 现有事件类型不变；**但新增 `INTERRUPT` 事件类型**（不破坏兼容）
- `config/*.json` 结构
- `db/` 层全部
- `agent/core.py`（单 agent ReAct 循环）
- `context/` 全部
- `ui/` 前端全部（SSE 事件格式兼容）
- `.env` / `config_manager.py` / `error_handler.py`
