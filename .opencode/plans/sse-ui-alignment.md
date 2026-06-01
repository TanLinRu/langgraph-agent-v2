# SSE 体验对齐 docs/SSE.html + 空消息/状态清理

> 创建于 2026-06-01
> 来源:用户反馈 ① 任务面板未清除 + 消息末尾空 "." ② docs/SSE.html 视觉对齐

## 背景

用户提交了一份 session JSON 反馈两个问题:
1. 任务面板(子任务调度)在前一个任务结束后,新任务未清除旧 task items
2. supervisor 在末尾产出一条 `{"content":".","name":"supervisor"}` 的空消息,被怀疑"未集中展示"

进一步分析后,发现需要:
- 任务列表状态机扩展(7 态)+ 中文状态文本
- 前端事件队列重构(MICRO/STEP/MACRO 三类延迟)
- 对齐 `docs/SSE.html` 的设计语言(topo bar / handoff / 思考块 / 工具块 / 摘要块 / 错误块)

## 用户决策(已确认)

| 决策点 | 选择 |
|--------|------|
| Summary 策略 | 有 sub-agent 执行 → 产 summary;无 → 不产 |
| TopologyBar | 总是显示(任务时高亮,任务后保留) |
| EventLog | 本期跳过 |
| ChatMessage 重构 | 一次性大改(完整分段式) |

## Phase 1 — 后端清理

### 1.1 server.py `_flush_message` 内容有效性
- 位置:`server.py:370-379`
- 跳过纯空白/纯标点(`.,!?;:。,!?;:`)
- 跳过长度 < 3 且无 `thinking` 关联

### 1.2 supervisor.py 移除重复 message yield
- 位置:`src/agent/supervisor.py:240-247`
- 移除 `yield {"type": "message", "data": agent_content, ...}`(ACP agent 已自带)
- 保留 `results.append` 用于 summary 阶段

### 1.3 supervisor.py summary 条件放宽
- 位置:`src/agent/supervisor.py:249-264`
- `if len(results) > 1` → `if results`
- 单步时,直接将 `agent_content` 作为 summary 内容,跳过 LLM 调用

## Phase 2 — 前端状态清理

- `ui/src/stores/chat.ts`:
  - `restoreSession` (L191-256) 开头:`taskItems.value = []; metrics.value = null`
  - `abort` (L59-76):`taskItems.value = []`
  - watch 回调 (L181-189) `else if (!id)` 分支:`taskItems.value = []; metrics.value = null`

## Phase 3 — SSE 事件队列重构

- `ui/src/stores/chat.ts`:
  - `_enqueueEvent` 拆 3 类延迟:
    - `MICRO` (0ms):`thinking` chunk
    - `STEP` (80ms):`tool_call`, `plan`, `summary`
    - `MACRO` (0ms):`thinking_start`, `thinking_done`, `done`, `error`, `task_update`
  - 新增 `agentName` 切换时插入 handoff 消息(对齐 SSE.html)
  - `typewriterState` 改 RAF(不阻塞 micro 事件)

## Phase 4 — 新增 TopologyBar 组件

- 新增 `ui/src/components/TopologyBar.vue`:
  - 节点:Supervisor + 4 workers (researcher / coder / analyst / writer / opencode / claude-agent)
  - 状态色:`idle / thinking / working / done / failed / delegating / aggregating`
  - 动画:flow line (svg) + pulse ring
  - 中文:空闲/派发中/汇总中/决策中/思考中/工作中/接收任务/完成/失败
  - 永远挂载(loading 时高亮)
- 修改 `ui/src/components/ChatTab.vue`:
  - 插入 `<TopologyBar v-if="chat.isLoading || chat.taskItems.length" />`

## Phase 5 — ChatMessage 重构

### 5.1 抽出 6 个新子组件

- `HandoffBadge.vue` — "🔗 从 X 交接 → Y" 灰底
- `ThinkingBlock.vue` — 折叠面板 + ▶ 箭头 + 圆点动画
- `ToolCallBlock.vue` — "🔧 TOOL" + name + args
- `ToolResultBlock.vue` — "✅ " + output 绿框
- `SummaryBlock.vue` — "📌 摘要" 蓝框
- `ErrorBlock.vue` — "❌ ERROR" 红框

### 5.2 ChatMessage.vue 完整重写

分段式结构(对齐 docs/SSE.html):
```vue
<template>
  <div class="msg-agent">
    <HandoffBadge v-if="msg.handoffFrom" .../>
    <div class="agent-header">
      <ConvAvatar :type="msg.agentName" :size="32"/>
      <span class="name">{{ agentLabel }}</span>
      <span class="status">{{ agentStatusText }}</span>
    </div>
    <ThinkingBlock v-if="msg.thinking" .../>
    <ToolCallBlock v-for="tc in msg.toolCalls" .../>
    <ToolResultBlock v-if="msg.toolResult" .../>
    <div v-if="msg.content" class="msg-content" v-html="renderMd(msg.content)"/>
    <SummaryBlock v-if="msg.isSummary" .../>
    <ErrorBlock v-if="msg.isError" .../>
  </div>
</template>
```

### 5.3 中文状态机(10 态)
```
接收任务 | 决策中 | 思考中 | 派发中 | 汇总中 | 等待 | 工作中 | 完成 | 失败 | 空闲
```

`agentStatus` 字段由 store 根据 SSE 事件更新:
- `thinking_start` → 思考中
- `task_update(running)` → 工作中
- `task_update(completed)` → 完成
- `error` → 失败

## Phase 6 — MonitorPanel 中文 7 态

- `ui/src/utils/api.ts` `TaskUpdate` 扩字段:
  ```ts
  export interface TaskUpdate {
    agent: string
    task: string
    status: 'pending' | 'running' | 'completed' | 'failed'  // 新增 failed
    startedAt?: number
    endedAt?: number
    elapsedMs?: number
  }
  ```
- `ui/src/components/MonitorPanel.vue` 改造:
  - 中文状态:`等待 / 思考中 / 工作中 / 已完成 / 失败`
  - 每项加耗时显示
  - 顶部加聚合卡片:本次 supervisor 耗时 / agent 数 / token 总和

## Phase 7 — 验证

- `pytest --cov=src -v` 64 tests 必须通过
- `ruff check . && mypy src` 必须通过
- `cd ui && vue-tsc -b && vite build` 必须通过
- 手动验证:
  - 数据库无 `content="."` 行
  - TopologyBar 节点状态正确切换
  - ChatMessage 中文状态正确
  - taskItems 切换 session 时清空

## 进度跟踪

| Phase | 状态 | 完成时间 |
|-------|------|---------|
| 1.1 | pending | |
| 1.2 | pending | |
| 1.3 | pending | |
| 2 | pending | |
| 3 | pending | |
| 4 | pending | |
| 5.1 | pending | |
| 5.2 | pending | |
| 5.3 | pending | |
| 6 | pending | |
| 7 | pending | |

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| ChatMessage 大改影响 sendACP 路径 | 抽 6 个子组件后,sendACP 复用同一套 |
| 移除 supervisor 重复 message 后 summary 拿不到 agent_content | agent_content 在 for 循环外已捕获,只是不再 yield |
| TopologyBar 总是显示占空间 | idle 半透明(opacity 0.45)+ 最小高度 80px |
| SSE 事件队列重构可能丢事件 | flushEventQueue() onDone 兜底 |
