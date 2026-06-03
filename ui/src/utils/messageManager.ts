import { ref, type Ref } from 'vue'
import type { ChatMessage, TaskUpdate, MetricsData } from '../utils/api'

type ToolCallShape = { name: string; args: Record<string, unknown>; status?: 'pending' | 'running' | 'done' | 'failed' }

/**
 * 消息管理组合式函数 (Message Manager)
 *
 * 封装 `messages.value` 数组的所有写操作,确保 Vue Proxy 响应性正常。
 * 核心原则:永远不要持有 msg 对象的本地引用再修改;每次通过数组索引访问。
 */
export function useMessageManager() {
  const messages: Ref<ChatMessage[]> = ref([])
  const typewriterState = ref<Record<number, { display: string; full: string; done: boolean }>>({})
  const thinkTypeState = ref<Record<number, { display: string; full: string; done: boolean; pendingDone: boolean }>>({})
  const taskItems = ref<TaskUpdate[]>([])
  const metrics = ref<MetricsData | null>(null)

  // ── 基础消息操作 ──────────────────────────────────────────

  function addUser(content: string): number {
    messages.value.push({ role: 'user', content })
    return messages.value.length - 1
  }

  function addSystem(content: string): number {
    messages.value.push({ role: 'system', content })
    return messages.value.length - 1
  }

  function addAssistant(agentName: string, opts?: {
    content?: string; thinking?: string; isThinking?: boolean;
    toolCalls?: ToolCallShape[];
    isPlan?: boolean; isSummary?: boolean;
  }): number {
    const msg: ChatMessage = { role: 'assistant', content: opts?.content || '', agentName }
    if (opts?.thinking) msg.thinking = opts.thinking
    if (opts?.isThinking) msg.isThinking = true
    if (opts?.toolCalls) msg.toolCalls = opts.toolCalls
    if (opts?.isPlan) msg.isPlan = true
    if (opts?.isSummary) msg.isSummary = true
    messages.value.push(msg)
    return messages.value.length - 1
  }

  function ensureAssistant(agentName: string): number {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m.role === 'assistant' && m.agentName === agentName) return i
    }
    return addAssistant(agentName)
  }

  function appendContent(index: number, text: string): void {
    if (messages.value[index]) {
      messages.value[index].content = (messages.value[index].content || '') + text
    }
  }

  function setContent(index: number, text: string): void {
    if (messages.value[index]) messages.value[index].content = text
  }

  function setThinkingStart(index: number): void {
    if (messages.value[index]) {
      messages.value[index].isThinking = true
      messages.value[index].thinking = ''
    }
  }

  function appendThinking(index: number, text: string): void {
    if (messages.value[index]) {
      messages.value[index].thinking = (messages.value[index].thinking || '') + text
    }
  }

  function setThinkingDone(index: number): void {
    if (messages.value[index]) messages.value[index].isThinking = false
  }

  function mergeToolCalls(agentName: string, toolCalls: ToolCallShape[]): void {
    const prev = messages.value[messages.value.length - 1]
    if (prev && prev.role === 'assistant' && prev.agentName === agentName) {
      prev.toolCalls = [...(prev.toolCalls || []), ...toolCalls]
    } else {
      messages.value.push({ role: 'assistant', content: '', toolCalls, agentName } as ChatMessage)
    }
  }

  function addError(content: string): void {
    messages.value.push({ role: 'system', content: `Error: ${content}` })
  }

  function setAgentStatus(index: number, status: string): void {
    if (messages.value[index]) messages.value[index].agentStatus = status
  }

  function setHandoff(index: number, from: string, to: string): void {
    if (messages.value[index]) {
      messages.value[index].handoffFrom = from
      messages.value[index].handoffTo = to
    }
  }

  function pushSummary(agentName: string, content: string): void {
    messages.value.push({
      role: 'assistant', content, agentName, isSummary: true,
    })
  }

  function pushPlan(planText: string): void {
    messages.value.push({
      role: 'assistant', content: planText, agentName: 'supervisor', isPlan: true,
    })
  }

  // ── Typewriter ─────────────────────────────────────────────

  function initTypewriter(index: number, full: string): void {
    typewriterState.value[index] = { display: '', full, done: false }
    if (messages.value[index]) messages.value[index].content = ''
  }

  function initThinkTypewriter(index: number): void {
    thinkTypeState.value[index] = { display: '', full: '', done: false, pendingDone: false }
  }

  // ── 任务 / 度量 ────────────────────────────────────────────

  function updateTaskItem(agent: string, task: string, updates: Partial<TaskUpdate>): void {
    const idx = taskItems.value.findIndex(t => t.agent === agent && t.task === task)
    if (idx >= 0) {
      taskItems.value[idx] = { ...taskItems.value[idx], ...updates }
    } else {
      taskItems.value.push({ agent, task, ...updates } as TaskUpdate)
    }
  }

  function setMetrics(data: MetricsData): void {
    metrics.value = data
  }

  // ── 批量操作 ──────────────────────────────────────────────

  function restore(raw: ChatMessage[]): void {
    messages.value = raw
  }

  function clear(): void {
    messages.value = []
    typewriterState.value = {}
    thinkTypeState.value = {}
    taskItems.value = []
    metrics.value = null
  }

  function resetTaskItems(): void {
    taskItems.value = []
    metrics.value = null
  }

  /** 流结束时,把所有 running/pending 任务标记为 failed */
  function reconcileStreamEnd(): void {
    const now = Date.now()
    for (let i = 0; i < taskItems.value.length; i++) {
      const t = taskItems.value[i]
      if (t.status === 'running' || t.status === 'pending') {
        taskItems.value[i] = {
          ...t, status: 'failed',
          endedAt: now, elapsedMs: t.startedAt ? now - t.startedAt : 0,
        }
      }
    }
  }

  return {
    // 状态
    messages, typewriterState, thinkTypeState, taskItems, metrics,
    // 基础操作
    addUser, addSystem, addAssistant, ensureAssistant,
    appendContent, setContent,
    // Thinking
    setThinkingStart, appendThinking, setThinkingDone,
    // 类型打字机
    initTypewriter, initThinkTypewriter,
    // 工具/摘要/错误
    mergeToolCalls, addError,
    // Agent 状态
    setAgentStatus, setHandoff,
    // 特殊消息
    pushSummary, pushPlan,
    // 任务/度量
    updateTaskItem, setMetrics,
    // 批量操作
    restore, clear, resetTaskItems, reconcileStreamEnd,
  }
}
