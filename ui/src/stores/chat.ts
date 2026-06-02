import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import {
  streamChatCallbacks,
  streamOrchestrate,
  compactSession,
  restoreSession as apiRestoreSession,
  type ChatMessage,
  type LogEntry,
  type LogEntryType,
  type MetricsData,
  type TaskPhaseUpdate,
  type TaskUpdate,
} from '../utils/api'
import { useSessionsStore } from './sessions'

const SSE_DELAY_MS = 120  // delay before major SSE events (tool_call, message, plan, summary)

export interface ThinkingChunk {
  agentName: string
  text: string
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const streamingActive = ref(false)
  const sessionId = ref<string | null>(null)


  // Typewriter state per message index
  const typewriterState = ref<Record<number, { display: string; full: string; done: boolean }>>({})
  // Thinking typewriter state per message index
  const thinkTypeState = ref<Record<number, { display: string; full: string; done: boolean; pendingDone: boolean }>>({})

  // New state for enhanced features
  const thinkingChunks = ref<ThinkingChunk[]>([])
  const taskItems = ref<TaskUpdate[]>([])
  const metrics = ref<MetricsData | null>(null)
  const eventLog = ref<LogEntry[]>([])
  const currentPhase = ref<TaskPhaseUpdate | null>(null)
  const currentDispatch = ref<{ from: string; to: string; fromLabel?: string; toLabel?: string } | null>(null)

  // Message queue for messages sent during processing
  const pendingMessages = ref<string[]>([])

  // Abort controller for cancelling active requests
  let _abortController: AbortController | null = null
  let _currentAbort: { abort: () => void } | null = null
  let _lastAgent: string | null = null
  let _sessionsStore: ReturnType<typeof useSessionsStore> | null = null

  function _setSessionStatus(status: 'processing' | 'completed') {
    if (!sessionId.value) return
    if (!_sessionsStore) _sessionsStore = useSessionsStore()
    const idx = _sessionsStore.sessions.findIndex(s => s.session_id === sessionId.value)
    if (idx >= 0) {
      _sessionsStore.sessions[idx] = { ..._sessionsStore.sessions[idx], status }
    }
  }

  /**
   * Reconcile taskItems and message agentStatus against actual stream end.
   * If stream ended with some tasks still 'running' (no final task_update arrived),
   * mark them 'failed' and set their elapsed time. This keeps the task list and
   * session status in sync — otherwise the sidebar shows "处理中" forever
   * while the chat shows "完成".
   */
  function _appendLog(type: LogEntryType, content: string, agent?: string) {
    eventLog.value.push({ type, content, timestamp: Date.now(), agent })
  }

  function _reconcileStreamEnd() {
    const now = Date.now()
    for (let i = 0; i < taskItems.value.length; i++) {
      const t = taskItems.value[i]
      if (t.status === 'running' || t.status === 'pending') {
        taskItems.value[i] = {
          ...t,
          status: 'failed',
          endedAt: now,
          elapsedMs: t.startedAt ? now - t.startedAt : 0,
        }
      }
    }
  }

  /**
   * Abort the current streaming request.
   */
  function abort() {
    if (_currentAbort) {
      _currentAbort.abort()
      _currentAbort = null
    } else if (_abortController) {
      _abortController.abort()
      _abortController = null
    }
    isLoading.value = false
    streamingActive.value = false
    pendingMessages.value = []
    taskItems.value = []
    eventLog.value = []
    currentPhase.value = null
    currentDispatch.value = null
    // Clear any queued events
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
    _stopTypewriter()
    if (_thinkingTimeout) { clearTimeout(_thinkingTimeout); _thinkingTimeout = null }
    _setSessionStatus('completed')
    console.log('[CHAT] aborted')
  }

  /**
   * Abort current task and send a new message (override).
   */
  async function abortAndSend(content: string) {
    abort()
    // Small delay to ensure cleanup
    await new Promise(r => setTimeout(r, 100))
    await send(content)
  }

  let _typeRaf: number | null = null
  let _thinkingTimeout: ReturnType<typeof setTimeout> | null = null

  // SSE backpressure — 3-tier queueing for smooth streaming
  //   MICRO (0ms): thinking chunks — fire immediately, never delay
  //   STEP (80ms): tool_call / plan / summary — small stagger for visual rhythm
  //   MACRO (0ms): state transitions (start/done/error/task_update) — fire immediately
  let _eventQueue: Array<() => void> = []
  let _eventTimer: ReturnType<typeof setTimeout> | null = null

  function formatElapsed(ms?: number): string {
    if (!ms || ms < 0) return ''
    const s = Math.floor(ms / 1000)
    if (s < 60) return `${s}s`
    const m = Math.floor(s / 60)
    const sec = s % 60
    if (m < 60) return `${m}m${sec.toString().padStart(2, '0')}s`
    const h = Math.floor(m / 60)
    const min = m % 60
    return `${h}h${min.toString().padStart(2, '0')}m${sec.toString().padStart(2, '0')}s`
  }

  // Thinking: backend batches chunks, frontend renders directly
  let _thinkChunkCount = 0

  function _typewriterTick() {
    let hasMore = false
    // Message typewriter
    for (const [key, state] of Object.entries(typewriterState.value)) {
      if (state.done) continue
      const idx = Number(key)
      if (state.display.length < state.full.length) {
        const next = Math.min(state.display.length + 3, state.full.length)
        state.display = state.full.slice(0, next)
        if (messages.value[idx]) {
          messages.value[idx].content = state.display
        }
        hasMore = true
      } else {
        state.done = true
      }
    }
    // Thinking typewriter
    for (const [key, state] of Object.entries(thinkTypeState.value)) {
      if (state.done) continue
      const idx = Number(key)
      if (state.display.length < state.full.length) {
        const next = Math.min(state.display.length + 2, state.full.length)
        state.display = state.full.slice(0, next)
        if (messages.value[idx]) {
          messages.value[idx].thinking = state.display
        }
        hasMore = true
      } else {
        state.done = true
        if (state.pendingDone && messages.value[idx]) {
          messages.value[idx].isThinking = false
          if (!messages.value[idx].thinking && state.full) {
            messages.value[idx].thinking = state.full
          }
        }
      }
    }
    if (hasMore) {
      _typeRaf = requestAnimationFrame(_typewriterTick)
    } else {
      _typeRaf = null
    }
  }

  function _startTypewriter() {
    if (_typeRaf !== null) return
    _typeRaf = requestAnimationFrame(_typewriterTick)
  }

  function _stopTypewriter() {
    if (_typeRaf !== null) {
      cancelAnimationFrame(_typeRaf)
      _typeRaf = null
    }
  }

  // Tier classification — aligned with docs/SSE.html
  const MICRO_EVENTS = new Set(['thinking'])
  const STEP_EVENTS = new Set(['tool_call', 'plan', 'summary'])
  const STEP_DELAY_MS = 80

  function _enqueueEvent(fn: () => void, label?: string) {
    _eventQueue.push(fn)
    if (!_eventTimer) {
      _eventTimer = setTimeout(() => {
        const next = _eventQueue.shift()
        if (next) {
          console.log(`[CHAT:QUEUE] fired: ${label || 'fn'}, remaining=${_eventQueue.length}`)
          next()
        }
        _eventTimer = null
        if (_eventQueue.length > 0) _scheduleNext(STEP_DELAY_MS)
      }, STEP_DELAY_MS)
    }
  }

  function _scheduleNext(delay: number) {
    if (_eventTimer) return
    _eventTimer = setTimeout(() => {
      const next = _eventQueue.shift()
      if (next) next()
      _eventTimer = null
      if (_eventQueue.length > 0) _scheduleNext(STEP_DELAY_MS)
    }, delay)
  }

  function _enqueueImmediate(fn: () => void, label?: string) {
    fn()
  }

  function _enqueueStep(fn: () => void, label?: string) {
    _enqueueEvent(fn, label)
  }

  function _flushEventQueue() {
    console.log(`[CHAT:QUEUE] flush all: ${_eventQueue.length} queued events`)
    for (const fn of _eventQueue) fn()
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
  }

  // Sync sessionId from sessions store
  const sessionsStore = useSessionsStore()
  watch(() => sessionsStore.activeSessionId, (id) => {
    if (id && id !== sessionId.value) {
      sessionId.value = id
      restoreSession()
    } else if (!id) {
      sessionId.value = null
      messages.value = []
      taskItems.value = []
      metrics.value = null
    }
  })

  async function restoreSession() {
    const id = sessionId.value
    if (!id) return

    taskItems.value = []
    metrics.value = null
    thinkingChunks.value = []
    typewriterState.value = {}
    thinkTypeState.value = {}

    try {
      console.log(`[CHAT] restoring session: ${id}`)
      const data = await apiRestoreSession(id)
      if (!data.messages || data.messages.length === 0) {
        console.log('[CHAT] restore: no messages')
        return
      }

      // Convert backend messages to ChatMessage format
      const restored: ChatMessage[] = []
      for (const m of data.messages) {
        // Skip compacted messages (they are represented by the summary)
        if ((m as any).compacted) continue

        if (m.type === 'human') {
          const msg: ChatMessage = { role: 'user', content: m.content }
          restored.push(msg)
        } else if (m.type === 'ai') {
          const name = (m as any).name as string | undefined
          const hasContent = m.content && m.content.trim()
          const hasThinking = !!(m as any).thinking
          const hasToolCalls = !!(m as any).tool_calls
          const isPlan = name === 'plan'
          const isSummary = name === 'summary'
          const isThinkingOnly = name === 'thinking'

          // Skip thinking-only messages (thinking content is embedded in the final message)
          if (isThinkingOnly) continue
          // Skip tool_call messages with no content (intermediate events)
          if (hasToolCalls && !hasContent && !isPlan && !isSummary) continue

          const msg: ChatMessage = { role: 'assistant', content: m.content || '' }
          if (hasThinking) msg.thinking = (m as any).thinking
          if (hasToolCalls) msg.toolCalls = (m as any).tool_calls
          if ((m as any).compacted) msg.compacted = true
          if (isPlan) msg.isPlan = true
          else if (isSummary) msg.isSummary = true
          else if (name && !isThinkingOnly) msg.agentName = name
          restored.push(msg)
        }
      }

      // If there's a summary, prepend it as a system message
      if (data.summary) {
        restored.unshift({
          role: 'system',
          content: `[Compacted context]\n${data.summary}`,
        })
      }

      messages.value = restored
      // Restore task_updates and metrics for session history replay
      if (data.task_updates && data.task_updates.length > 0) {
        const raw: any[] = data.task_updates
        taskItems.value = raw.map(t => ({
          agent: t.agent || '',
          task: t.task || '',
          status: t.status || 'completed',
          state: t.state || undefined,
          startedAt: t.started_at ?? undefined,
          endedAt: t.ended_at ?? undefined,
          elapsedMs: t.elapsed_ms ?? undefined,
        })) as TaskUpdate[]
      }
      if (data.metrics) {
        metrics.value = data.metrics
      }
      console.log(`[CHAT] restored ${restored.length} messages (hasSummary=${!!data.summary}, tasks=${taskItems.value.length})`)
    } catch (e: any) {
      // 404 is expected after DB clear — just reset silently
      if (e.message?.includes('404') || e.message?.includes('Not Found')) {
        console.log(`[CHAT] session ${id} not found, clearing sessionId`)
      } else {
        console.warn('[CHAT] restore failed:', e.message)
      }
      sessionId.value = null
    }
  }

  /**
   * Send message using EventSource callbacks — no async generator.
   * Each SSE event directly mutates the Vue store, triggering immediate DOM updates.
   */
  function sendMessage(content: string) {
    // Abort any previous request
    if (_abortController) _abortController.abort()
    _abortController = new AbortController()

    _setSessionStatus('processing')
    messages.value.push({ role: 'user', content })
    taskItems.value = []
    isLoading.value = true
    streamingActive.value = false

    let assistantMsg: ChatMessage | null = null
    let msgIdx = -1

    function ensureMsgIdx(agentName?: string) {
      if (msgIdx < 0) {
        assistantMsg = { role: 'assistant', content: '', agentName }
        messages.value.push(assistantMsg)
        msgIdx = messages.value.length - 1
        streamingActive.value = true
      }
      if (agentName && msgIdx >= 0 && !messages.value[msgIdx].agentName) {
        messages.value[msgIdx].agentName = agentName
      }
    }

    _currentAbort = streamChatCallbacks(
      content,
      // onEvent — called immediately for each SSE event
      (event) => {
        if (event.session_id) {
          sessionId.value = event.session_id as string
          // Sync to sessions store
          sessionsStore.activeSessionId = event.session_id as string
        }

        const agentName = event.agent_name as string | undefined

        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          ensureMsgIdx(agentName)
          messages.value[msgIdx].isThinking = true
          messages.value[msgIdx].agentStatus = 'thinking'
          // Initialize thinking typewriter state
          thinkTypeState.value[msgIdx] = { display: '', full: '', done: false, pendingDone: false }
          messages.value[msgIdx].thinking = ''
          console.log('[CHAT] thinking_start')
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          ensureMsgIdx(agentName)
          if (thinkTypeState.value[msgIdx]) {
            // Append to typewriter buffer, let _startTypewriter render char by char
            thinkTypeState.value[msgIdx].full += (event.data as string)
            _startTypewriter()
          } else {
            // Fallback: direct set if typewriter state not initialized
            messages.value[msgIdx].thinking = (messages.value[msgIdx].thinking || '') + (event.data as string)
          }
        } else if (event.type === 'thinking_done') {
          console.log(`[CHAT] thinking_done: ${_thinkChunkCount} batches`)
          if (msgIdx >= 0 && thinkTypeState.value[msgIdx]) {
            const ts = thinkTypeState.value[msgIdx]
            if (ts.done) {
              messages.value[msgIdx].isThinking = false
            } else {
              ts.pendingDone = true
            }
          } else if (msgIdx >= 0) {
            messages.value[msgIdx].isThinking = false
          }
        } else if (event.type === 'tool_call') {
          _enqueueStep(() => {
            ensureMsgIdx(agentName)
            messages.value[msgIdx].toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
          }, 'tool_call')
        } else if (event.type === 'message') {
          _enqueueStep(() => {
            ensureMsgIdx(agentName)
            if (msgIdx >= 0) {
              const fullContent = event.data as string
              if (fullContent) {
                typewriterState.value[msgIdx] = { display: '', full: fullContent, done: false }
                messages.value[msgIdx].content = ''
                _startTypewriter()
              }
              if (event.file_refs) {
                messages.value[msgIdx].fileRefs = event.file_refs as string[]
              }
            }
          }, 'message')
        } else if (event.type === 'summary') {
          _enqueueStep(() => {
            messages.value.push({
              role: 'assistant',
              content: event.data as string,
              agentName: 'supervisor',
              isSummary: true,
            })
            assistantMsg = null
            msgIdx = -1
          }, 'summary')
        } else if (event.type === 'error') {
          _enqueueImmediate(() => {
            messages.value.push({ role: 'system', content: `Error: ${event.data}` })
          }, 'error')
        }
      },
      // onDone — called when stream ends or errors
      () => {
        console.log('[CHAT] stream done')
        _reconcileStreamEnd()
        _setSessionStatus('completed')
        // Don't flush queue immediately — let the timer drain naturally for smooth animation
        if (_eventQueue.length > 10) {
          _flushEventQueue()
        }
        // Don't clear isThinking immediately — let typewriter finish naturally
        _thinkingTimeout = setTimeout(() => {
          for (const msg of messages.value) {
            if (msg.isThinking) msg.isThinking = false
          }
          _thinkingTimeout = null
        }, 3000)
        // If no assistant message was created, show error
        if (!assistantMsg) {
          messages.value.push({ role: 'system', content: '⚠ 未收到响应，请重试。' })
        }
        isLoading.value = false
        streamingActive.value = false
        // Process pending messages
        _processPendingMessages()
      },
      sessionId.value || undefined,
    )
  }

  async function sendOrchestrate(task: string) {
    _setSessionStatus('processing')
    messages.value.push({ role: 'user', content: task })
    taskItems.value = []
    eventLog.value = []
    currentPhase.value = null
    currentDispatch.value = null
    isLoading.value = true
    _appendLog('start', '开始调度任务', 'supervisor')

    // Track per-agent state
    let supervisorMsgIdx = -1
    const agentMsgIndices: Record<string, number> = {}
    let lastDispatchedAgent: string | null = null

    function ensureSupervisorMsg() {
      if (supervisorMsgIdx < 0) {
        const msg: ChatMessage = { role: 'assistant', content: '', agentName: 'supervisor' }
        messages.value.push(msg)
        supervisorMsgIdx = messages.value.length - 1
        streamingActive.value = true
      }
    }

    function ensureAgentMsg(agentName: string): number {
      if (!(agentName in agentMsgIndices)) {
        const msg: ChatMessage = { role: 'assistant', content: '', agentName }
        messages.value.push(msg)
        agentMsgIndices[agentName] = messages.value.length - 1
        streamingActive.value = true
      }
      return agentMsgIndices[agentName]
    }

    try {
      for await (const event of streamOrchestrate(task, sessionId.value || undefined)) {
        if (event.session_id) {
          sessionId.value = event.session_id as string
          sessionsStore.activeSessionId = event.session_id as string
        }

        const agentName = (event.agent_name as string) || 'supervisor'

        // Thinking: typewriter animation (MICRO — fire immediately)
        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          ensureSupervisorMsg()
          messages.value[supervisorMsgIdx].isThinking = true
          messages.value[supervisorMsgIdx].agentStatus = 'thinking'
          thinkTypeState.value[supervisorMsgIdx] = { display: '', full: '', done: false, pendingDone: false }
          messages.value[supervisorMsgIdx].thinking = ''
          console.log('[CHAT:ORCH] thinking_start')
          continue
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          ensureSupervisorMsg()
          if (thinkTypeState.value[supervisorMsgIdx]) {
            thinkTypeState.value[supervisorMsgIdx].full += (event.data as string)
            _startTypewriter()
          } else {
            messages.value[supervisorMsgIdx].thinking = (messages.value[supervisorMsgIdx].thinking || '') + (event.data as string)
          }
          continue
        } else if (event.type === 'thinking_done') {
          console.log(`[CHAT:ORCH] thinking_done: ${_thinkChunkCount} batches`)
          if (supervisorMsgIdx >= 0 && thinkTypeState.value[supervisorMsgIdx]) {
            const ts = thinkTypeState.value[supervisorMsgIdx]
            if (ts.done) {
              messages.value[supervisorMsgIdx].isThinking = false
            } else {
              ts.pendingDone = true
            }
          } else if (supervisorMsgIdx >= 0) {
            messages.value[supervisorMsgIdx].isThinking = false
          }
          continue
        }

        // STEP events: tool_call / plan / summary (80ms stagger for visual rhythm)
        if (event.type === 'plan') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          console.log('[CHAT:ORCH] plan')
          _appendLog('decision', (event.data as string).slice(0, 80), 'supervisor')
          const planText = event.data as string
          // Parse plan steps → pre-populate pending task items in MonitorPanel
          const stepLines = planText.split('\n').filter(l => /^\s*[-*]\s*\w+:/.test(l))
          const stepCount = stepLines.length
          for (const line of stepLines) {
            const match = line.match(/^\s*[-*]\s*(\w+)\s*:\s*(.+)/)
            if (match) {
              const agent = match[1]
              const task = match[2].trim()
              // Avoid duplicates if the same step was already added
              const dup = taskItems.value.find(t => t.agent === agent && t.task === task)
              if (!dup) {
                taskItems.value.push({ agent, task, status: 'pending' })
              }
            }
          }
          const oldStep = (currentPhase as any).value?.step ?? 0
          const oldTotal = (currentPhase as any).value?.totalSteps ?? 0
          currentPhase.value = {
            step: oldStep + 1,
            totalSteps: Math.max(oldTotal, stepCount || 1),
            description: stepLines[0]?.replace(/^\s*[-*]\s*\w+:\s*/, '').slice(0, 60) || '',
          }
          messages.value.push({
            role: 'assistant',
            content: planText,
            agentName: 'supervisor',
            isPlan: true,
          })
        } else if (event.type === 'tool_call') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          console.log(`[CHAT:ORCH] tool_call: ${agentName}`)
          const idx = ensureAgentMsg(agentName)
          if (!(agentName in agentMsgIndices)) {
            // First time seeing this agent — record handoff badge from supervisor
            messages.value[idx].handoffFrom = 'supervisor'
            messages.value[idx].handoffTo = agentName
            lastDispatchedAgent = agentName
          }
          const tcs = event.data as Array<{ name: string; args: Record<string, unknown> }>
          _appendLog('tool_call', tcs[0]?.name || 'unknown', agentName)
          messages.value[idx].agentStatus = 'working'
          messages.value[idx].toolCalls = tcs
        } else if (event.type === 'summary') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          console.log('[CHAT:ORCH] summary')
          _appendLog('summary', (event.data as string).slice(0, 80), 'supervisor')
          ensureSupervisorMsg()
          messages.value[supervisorMsgIdx].agentStatus = 'aggregating'
          messages.value[supervisorMsgIdx].summary = event.data as string
          messages.value[supervisorMsgIdx].isSummary = true
        } else if (event.type === 'message') {
          console.log(`[CHAT:ORCH] message: ${agentName}`)
          const idx = ensureAgentMsg(agentName)
          messages.value[idx].content = event.data as string
        } else if (event.type === 'task_update') {
          const update = event.data as TaskUpdate
          const now = Date.now()
          const existing = taskItems.value.findIndex(t => t.agent === update.agent && t.task === update.task)
          if (existing >= 0) {
            const prev = taskItems.value[existing]
            const merged: TaskUpdate = { ...prev, ...update }
            if (update.status === 'running' && prev.status !== 'running') {
              merged.startedAt = now
              _appendLog('handoff', `${update.agent} 开始执行: ${update.task.slice(0, 50)}`, update.agent)
              currentDispatch.value = { from: 'supervisor', to: update.agent }
            }
            if ((update.status === 'completed' || update.status === 'failed') && prev.startedAt) {
              merged.endedAt = now
              merged.elapsedMs = now - prev.startedAt
              _appendLog('handoff', `${update.agent} 完成: ${formatElapsed(merged.elapsedMs)}`, update.agent)
              currentDispatch.value = { from: update.agent, to: 'supervisor' }
            }
            taskItems.value[existing] = merged
          } else {
            const fresh: TaskUpdate = { ...update }
            if (update.status === 'running') {
              fresh.startedAt = now
              _appendLog('start', `${update.agent} 接收任务: ${update.task.slice(0, 50)}`, update.agent)
              currentDispatch.value = { from: 'supervisor', to: update.agent }
            }
            taskItems.value.push(fresh)
          }
          // Sync agentStatus on the agent's message bubble
          const agentIdx = agentMsgIndices[update.agent]
          if (agentIdx !== undefined) {
            if (update.status === 'running') messages.value[agentIdx].agentStatus = 'working'
            else if (update.status === 'completed') messages.value[agentIdx].agentStatus = 'done'
            else if (update.status === 'failed') messages.value[agentIdx].agentStatus = 'failed'
          }
        } else if (event.type === 'metrics') {
          metrics.value = event.data as MetricsData
        } else if (event.type === 'error') {
          _appendLog('error', String(event.data), agentName)
          messages.value.push({ role: 'system', content: `Error: ${event.data}` })
        }
      }
      console.log('[CHAT:ORCH] stream done')
    } catch (e: any) {
      messages.value.push({ role: 'system', content: `Connection error: ${e.message}` })
    } finally {
      _reconcileStreamEnd()
      _setSessionStatus('completed')
      // Mark all agents done/failed
      for (const [name, idx] of Object.entries(agentMsgIndices)) {
        if (messages.value[idx]) messages.value[idx].agentStatus = 'done'
      }
      if (supervisorMsgIdx >= 0 && messages.value[supervisorMsgIdx]) {
        messages.value[supervisorMsgIdx].agentStatus = 'done'
        messages.value[supervisorMsgIdx].isThinking = false
      }
      isLoading.value = false
      streamingActive.value = false
    }
  }

  /**
   * Send message directly to ACP agent (bypass supervisor).
   * Streams events via POST /api/acp/send.
   */
  async function sendACP(agentId: string, content: string) {
    _lastAgent = agentId
    _setSessionStatus('processing')
    // Abort any previous request
    if (_abortController) _abortController.abort()
    _abortController = new AbortController()

    isLoading.value = true
    streamingActive.value = false

    // Add task update for ACP agent
    const taskItem: TaskUpdate = { agent: agentId, task: content.slice(0, 50), status: 'running', startedAt: Date.now() }
    taskItems.value = [taskItem]

    const assistantMsg: ChatMessage = { role: 'assistant', content: '', agentName: agentId }
    let msgIdx = -1

    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE || ''}/api/acp/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, message: content, session_id: sessionId.value }),
        signal: _abortController.signal,
      })

      if (!res.ok || !res.body) {
        messages.value.push({ role: 'system', content: `⚠ ACP agent ${agentId} 未响应 (${res.status})` })
        taskItem.status = 'failed'
        taskItem.endedAt = Date.now()
        taskItem.elapsedMs = (taskItem.endedAt - (taskItem.startedAt || taskItem.endedAt))
        isLoading.value = false
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))

            // Sync session_id from backend
            if (event.session_id && event.session_id !== sessionId.value) {
              sessionId.value = event.session_id as string
              sessionsStore.activeSessionId = event.session_id as string
            }

            if (event.type === 'thinking') {
              if (msgIdx < 0) {
                messages.value.push(assistantMsg)
                msgIdx = messages.value.length - 1
                streamingActive.value = true
              }
              const m = messages.value[msgIdx]
              m.thinking = (m.thinking || '') + event.data
              m.isThinking = true
            } else if (event.type === 'tool_call') {
              if (msgIdx < 0) {
                messages.value.push(assistantMsg)
                msgIdx = messages.value.length - 1
                streamingActive.value = true
              }
              const tc = Array.isArray(event.data) ? event.data : [event.data]
              const valid = tc.filter((t: any) => t?.name)
              if (valid.length > 0) messages.value[msgIdx].toolCalls = valid
            } else if (event.type === 'message') {
              if (msgIdx < 0) {
                messages.value.push(assistantMsg)
                msgIdx = messages.value.length - 1
                streamingActive.value = true
              }
              const m = messages.value[msgIdx]
              m.content = (m.content || '') + (event.data || '')
              m.isThinking = false
            } else if (event.type === 'thinking_done') {
              if (msgIdx >= 0) messages.value[msgIdx].isThinking = false
            } else if (event.type === 'metrics') {
              metrics.value = event.data
            } else if (event.type === 'error') {
              messages.value.push({ role: 'system', content: `⚠ ${event.data}` })
            }
          } catch {}
        }
      }
      taskItem.status = 'completed'
      taskItem.endedAt = Date.now()
      taskItem.elapsedMs = taskItem.endedAt - (taskItem.startedAt || taskItem.endedAt)
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        messages.value.push({ role: 'system', content: `⚠ ACP 连接错误: ${e.message}` })
      }
      taskItem.status = 'failed'
      taskItem.endedAt = Date.now()
      taskItem.elapsedMs = taskItem.endedAt - (taskItem.startedAt || taskItem.endedAt)
    } finally {
      _reconcileStreamEnd()
      _setSessionStatus('completed')
      if (msgIdx >= 0) messages.value[msgIdx].isThinking = false
      // Remove the "执行中..." / "继续执行..." status message
      const statusIdx = messages.value.findIndex(m =>
        m.role === 'system' && !!m.content && (m.content.startsWith(`@${agentId} 执行中`) || m.content.startsWith(`@${agentId} 继续执行`))
      )
      if (statusIdx >= 0) messages.value.splice(statusIdx, 1)
      isLoading.value = false
      streamingActive.value = false
      _processPendingMessages()
    }
  }

  function clearMessages() {
    messages.value = []
    sessionId.value = null
    _lastAgent = null
    typewriterState.value = {}
    thinkTypeState.value = {}
    thinkingChunks.value = []
    taskItems.value = []
    metrics.value = null
    eventLog.value = []
    currentPhase.value = null
    currentDispatch.value = null
    pendingMessages.value = []
    _stopTypewriter()
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
  }

  function _processPendingMessages() {
    if (pendingMessages.value.length > 0 && !isLoading.value) {
      const next = pendingMessages.value.shift()
      if (next) {
        // Remove the "已排队" system message
        const idx = messages.value.findIndex(m => m.role === 'system' && m.content?.startsWith('已排队:'))
        if (idx >= 0) messages.value.splice(idx, 1)
        send(next)
      }
    }
  }

  function newSession() {
    clearMessages()
    sessionsStore.activeSessionId = null
    // sessionId is now null, next send will create a new session
  }

  async function handleCompact(): Promise<string> {
    const id = sessionId.value
    if (!id) return 'No active session to compact.'

    isLoading.value = true
    try {
      const result = await compactSession(id)
      if (result.note) {
        return result.note
      }
      // Reload the compacted session — wrap in try-catch to not lose sessionId
      try {
        await restoreSession()
      } catch (restoreErr: any) {
        console.warn('[CHAT] restore after compact failed:', restoreErr.message)
        // Don't null out sessionId — keep the current session
      }
      return `Session compacted: removed ${result.deleted_messages} old messages, kept ${result.kept_messages} recent.`
    } catch (e: any) {
      return `Compact failed: ${e.message}`
    } finally {
      isLoading.value = false
    }
  }

  async function checkAcpAvailable(agentId: string): Promise<boolean> {
    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE || ''}/api/acp/check/${agentId}`)
      if (!res.ok) return false
      const data = await res.json()
      return data.available === true
    } catch {
      return false
    }
  }

  async function send(content: string) {
    // Queue message if currently processing
    if (isLoading.value) {
      pendingMessages.value.push(content)
      messages.value.push({ role: 'system', content: `已排队: ${content}` })
      return
    }

    // Guard: require project path before sending
    if (sessionId.value) {
      const s = useSessionsStore()
      const session = s.sessions.find(s => s.session_id === sessionId.value)
      if (session && !session.project_path) {
        messages.value.push({ role: 'system', content: '⚠ 请先设置项目路径 (project path) 才能开始会话' })
        return
      }
    }

    // Handle slash commands
    if (content.startsWith('/')) {
      const cmd = content.trim().toLowerCase()
      if (cmd === '/compact') {
        const result = await handleCompact()
        messages.value.push({ role: 'system', content: result })
        return
      }
      if (cmd === '/clear') {
        newSession()
        return
      }
      if (cmd === '/new') {
        newSession()
        return
      }
      // Unknown command
      messages.value.push({ role: 'system', content: `Unknown command: ${cmd}. Available: /compact, /clear, /new` })
      return
    }

    // Parse @ mention: @agent_name at the start or after space
    const mentionMatch = content.match(/(?:^|\s)@(\w[\w-]*)(?:\s|$)/)
    if (mentionMatch) {
      const agentName = mentionMatch[1].toLowerCase()
      const cleanContent = content.replace(/@[\w-]+\s?/, '').trim()
      if (cleanContent) {
        // Check ACP agent availability before dispatching
        const available = await checkAcpAvailable(agentName)
        if (!available) {
          messages.value.push({ role: 'system', content: `⚠ ACP agent "${agentName}" is not available or not configured. Check config/acp_agents.json` })
          return
        }
        messages.value.push({ role: 'user', content })
        messages.value.push({ role: 'system', content: `@${agentName} 执行中...` })
        // Direct ACP call — bypass supervisor
        await sendACP(agentName, cleanContent)
        return
      }
    }

    // Route to the same ACP agent as the last command in this session
    if (_lastAgent) {
      const available = await checkAcpAvailable(_lastAgent)
      if (available) {
        messages.value.push({ role: 'user', content })
        messages.value.push({ role: 'system', content: `@${_lastAgent} 继续执行...` })
        await sendACP(_lastAgent, content)
        return
      }
    }

    await sendOrchestrate(content)
  }

  return {
    messages, isLoading, streamingActive, sessionId,
    typewriterState, thinkingChunks, taskItems, metrics, pendingMessages,
    eventLog, currentPhase, currentDispatch,
    sendOrchestrate, sendACP, send, abort, abortAndSend,
    clearMessages, newSession, restoreSession,
    formatElapsed,
  }
})
