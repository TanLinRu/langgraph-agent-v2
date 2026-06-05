import { ref } from 'vue'
import type { ChatMessage, LogEntry, LogEntryType, MetricsData, PermissionRequest, TaskPhaseUpdate, TaskUpdate, SSEEvent } from './api'
import { streamChatCallbacks, streamOrchestrate, streamOrchestrateReview, compactSession, restoreSession as apiRestoreSession } from './api'
import { useSessionsStore } from '../stores/sessions'

export function useStreamManager(
  msg: ReturnType<typeof import('./messageManager').useMessageManager>,
  sessionId: ReturnType<typeof ref<string | null>>,
) {
  const isLoading = ref(false)
  const streamingActive = ref(false)
  const thinkingChunks = ref<Array<{ agentName: string; text: string }>>([])
  const eventLog = ref<LogEntry[]>([])
  const currentPhase = ref<TaskPhaseUpdate | null>(null)
  const currentDispatch = ref<{ from: string; to: string; fromLabel?: string; toLabel?: string } | null>(null)
  const pendingMessages = ref<string[]>([])
  const permissionRequest = ref<PermissionRequest | null>(null)
  const pendingReview = ref<{ threadId: string; plan: Record<string, unknown> | null } | null>(null)

  let _abortController: AbortController | null = null
  let _currentAbort: { abort: () => void } | null = null

  let _typeRaf: number | null = null
  let _thinkingTimeout: ReturnType<typeof setTimeout> | null = null
  let _thinkChunkCount = 0

  let _eventQueue: Array<() => void> = []
  let _eventTimer: ReturnType<typeof setTimeout> | null = null

  const STEP_DELAY_MS = 80
  const SSE_DELAY_MS = 120

  function _setSessionStatus(status: 'processing' | 'completed') {
    const sid = sessionId.value
    if (!sid) return
    const s = useSessionsStore()
    const idx = s.sessions.findIndex(s => s.session_id === sid)
    if (idx >= 0) {
      s.sessions[idx] = { ...s.sessions[idx], status }
    }
    if (status === 'completed') {
      s.fetchSessions()
    }
  }

  function _appendLog(type: LogEntryType, content: string, agent?: string) {
    eventLog.value.push({ type, content, timestamp: Date.now(), agent })
  }

  function _typewriterTick() {
    let hasMore = false
    for (const [key, state] of Object.entries(msg.typewriterState.value)) {
      if (state.done) continue
      const idx = Number(key)
      if (state.display.length < state.full.length) {
        const next = Math.min(state.display.length + 3, state.full.length)
        state.display = state.full.slice(0, next)
        msg.setContent(idx, state.display)
        hasMore = true
      } else {
        state.done = true
      }
    }
    for (const [key, state] of Object.entries(msg.thinkTypeState.value)) {
      if (state.done) continue
      const idx = Number(key)
      if (state.display.length < state.full.length) {
        const next = Math.min(state.display.length + 2, state.full.length)
        state.display = state.full.slice(0, next)
        msg.setContent(idx, state.display)
        hasMore = true
      } else {
        state.done = true
        if (state.pendingDone) {
          msg.setThinkingDone(idx)
          if (!msg.messages.value[idx]?.thinking && state.full) {
            msg.messages.value[idx]!.thinking = state.full
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
    for (const [key, state] of Object.entries(msg.thinkTypeState.value)) {
      if (state.done) continue
      const idx = Number(key)
      state.done = true
      if (state.pendingDone) {
        msg.setThinkingDone(idx)
        if (!msg.messages.value[idx]?.thinking && state.full) {
          msg.messages.value[idx]!.thinking = state.full
        }
      }
    }
    if (_typeRaf !== null) {
      cancelAnimationFrame(_typeRaf)
      _typeRaf = null
    }
  }

  function _enqueueEvent(fn: () => void) {
    _eventQueue.push(fn)
    if (!_eventTimer) {
      _eventTimer = setTimeout(() => {
        const next = _eventQueue.shift()
        if (next) next()
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

  function _enqueueStep(fn: () => void) { _enqueueEvent(fn) }
  function _enqueueImmediate(fn: () => void) { fn() }

  function _flushEventQueue() {
    const batch = _eventQueue.splice(0)
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
    for (const fn of batch) fn()
  }

  function sendMessage(content: string) {
    if (_abortController) _abortController.abort()
    _abortController = new AbortController()
    _setSessionStatus('processing')
    msg.addUser(content)
    msg.resetTaskItems()
    isLoading.value = true
    streamingActive.value = false

    let msgIdx = -1
    function ensureMsgIdx(agentName?: string) {
      if (msgIdx < 0) {
        msgIdx = msg.addAssistant(agentName || 'assistant')
        streamingActive.value = true
      }
      if (agentName && msgIdx >= 0 && !msg.messages.value[msgIdx]?.agentName) {
        msg.messages.value[msgIdx]!.agentName = agentName
      }
    }

    _currentAbort = streamChatCallbacks(
      content,
      (event: SSEEvent) => {
        if (event.session_id) {
          sessionId.value = event.session_id
          useSessionsStore().activeSessionId = event.session_id
        }
        const agentName = event.agent_name
        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          ensureMsgIdx(agentName)
          msg.setThinkingStart(msgIdx)
          msg.initThinkTypewriter(msgIdx)
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          ensureMsgIdx(agentName)
          if (msg.thinkTypeState.value[msgIdx]) {
            msg.thinkTypeState.value[msgIdx].full += (event.data as string)
            _startTypewriter()
          } else {
            msg.appendThinking(msgIdx, event.data as string)
          }
        } else if (event.type === 'thinking_done') {
          if (msgIdx >= 0 && msg.thinkTypeState.value[msgIdx]) {
            const ts = msg.thinkTypeState.value[msgIdx]
            if (ts.done) {
              if (!msg.messages.value[msgIdx]?.thinking && ts.full) {
                msg.messages.value[msgIdx]!.thinking = ts.full
              }
              msg.setThinkingDone(msgIdx)
            } else ts.pendingDone = true
          } else if (msgIdx >= 0) msg.setThinkingDone(msgIdx)
        } else if (event.type === 'tool_call') {
          _enqueueStep(() => {
            ensureMsgIdx(agentName)
            msg.messages.value[msgIdx]!.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
          })
        } else if (event.type === 'message') {
          _enqueueStep(() => {
            ensureMsgIdx(agentName)
            if (msgIdx >= 0) {
              const fullContent = event.data as string
              if (fullContent) {
                msg.initTypewriter(msgIdx, fullContent)
                _startTypewriter()
              }
              if (event.file_refs) msg.messages.value[msgIdx]!.fileRefs = event.file_refs as string[]
            }
          })
        } else if (event.type === 'summary') {
          _enqueueStep(() => {
            msg.pushSummary('supervisor', event.data as string)
          })
        } else if (event.type === 'metrics') {
          msg.setMetrics(event.data as MetricsData)
        } else if (event.type === 'error') {
          _enqueueImmediate(() => msg.addError(String(event.data)))
        }
      },
      () => {
        _flushEventQueue()
        msg.reconcileStreamEnd()
        _setSessionStatus('completed')
        _thinkingTimeout = setTimeout(() => {
          for (const m of msg.messages.value) if (m.isThinking) m.isThinking = false
          _thinkingTimeout = null
        }, 3000)
        isLoading.value = false
        streamingActive.value = false
      },
      sessionId.value || undefined,
    )
  }

  async function sendOrchestrate(task: string) {
    const sid = sessionId.value || useSessionsStore().activeSessionId || undefined
    _setSessionStatus('processing')
    msg.addUser(task)
    msg.resetTaskItems()
    eventLog.value = []
    currentPhase.value = null
    currentDispatch.value = null
    isLoading.value = true
    _appendLog('start', '开始调度任务', 'supervisor')

    try {
      for await (const event of streamOrchestrate(task, sid)) {
        if (event.session_id) {
          sessionId.value = event.session_id
          useSessionsStore().activeSessionId = event.session_id
        }
        const agentName = event.agent_name || 'supervisor'

        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          const idx = msg.ensureAssistant('supervisor')
          msg.setThinkingStart(idx)
          msg.initThinkTypewriter(idx)
          streamingActive.value = true
          continue
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          const idx = msg.ensureAssistant('supervisor')
          if (msg.thinkTypeState.value[idx]) {
            msg.thinkTypeState.value[idx].full += (event.data as string)
            _startTypewriter()
          } else {
            msg.appendThinking(idx, event.data as string)
          }
          continue
        } else if (event.type === 'thinking_done') {
          const idx = msg.ensureAssistant('supervisor')
          if (idx >= 0 && msg.thinkTypeState.value[idx]) {
            const ts = msg.thinkTypeState.value[idx]
            if (ts.done) {
              if (!msg.messages.value[idx]?.thinking && ts.full) {
                msg.messages.value[idx]!.thinking = ts.full
              }
              msg.setThinkingDone(idx)
            } else ts.pendingDone = true
          } else if (idx >= 0) msg.setThinkingDone(idx)
          continue
        }

        if (event.type === 'plan') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          _appendLog('decision', (event.data as string).slice(0, 80), 'supervisor')
          const displayText = event.data as string
          const planSteps = (event.steps || []) as Array<{ agent: string; task: string }>
          for (const step of planSteps) {
            if (!msg.taskItems.value.find(t => t.agent === step.agent && t.task === step.task)) {
              msg.taskItems.value.push({ agent: step.agent, task: step.task, status: 'pending' } as TaskUpdate)
            }
          }
          const p = currentPhase.value as TaskPhaseUpdate | null
          currentPhase.value = {
            step: (p?.step ?? 0) + 1,
            totalSteps: Math.max(p?.totalSteps ?? 0, planSteps.length || 1),
            description: planSteps[0]?.task?.slice(0, 60) || '',
          }
          const idx = msg.ensureAssistant('supervisor')
          msg.messages.value[idx]!.content = displayText
          if (msg.messages.value[idx]!.isThinking) msg.messages.value[idx]!.isThinking = false
          _stopTypewriter()
        } else if (event.type === 'tool_call') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          const idx = msg.ensureAssistant(agentName)
          msg.setHandoff(idx, 'supervisor', agentName)
          const tcs = event.data as Array<{ name: string; args: Record<string, unknown>; status?: string }>
          _appendLog('tool_call', tcs[0]?.name || 'unknown', agentName)
          msg.setAgentStatus(idx, 'working')
          const resultTcs = tcs.filter(tc => tc.status === 'completed' || tc.status === 'result')
          if (resultTcs.length > 0) {
            msg.messages.value[idx]!.toolCalls = resultTcs as any
            msg.clearCompletedToolCalls()
          } else {
            msg.messages.value[idx]!.toolCalls = tcs as any
          }
        } else if (event.type === 'summary') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          _appendLog('summary', (event.data as string).slice(0, 80), 'supervisor')
          msg.pushSummary('supervisor', event.data as string)
        } else if (event.type === 'message') {
          _enqueueImmediate(() => {
            const idx = msg.ensureAssistant(agentName)
            msg.appendContent(idx, event.data as string)
          })
        } else if (event.type === 'task_update') {
          const update = event.data as TaskUpdate
          const now = Date.now()
          const existing = msg.taskItems.value.findIndex(t => t.agent === update.agent && t.task === update.task)
          if (existing >= 0) {
            const prev = msg.taskItems.value[existing]
            const merged: TaskUpdate = { ...prev, ...update }
            if (update.status === 'running' && prev.status !== 'running') {
              merged.startedAt = now
              _appendLog('handoff', `${update.agent} 开始执行: ${update.task.slice(0, 50)}`, update.agent)
              currentDispatch.value = { from: 'supervisor', to: update.agent }
            }
            if ((update.status === 'completed' || update.status === 'failed') && prev.startedAt) {
              merged.endedAt = now; merged.elapsedMs = now - prev.startedAt
              _appendLog('handoff', `${update.agent} 完成`, update.agent)
              currentDispatch.value = { from: update.agent, to: 'supervisor' }
            }
            msg.taskItems.value[existing] = merged
          } else {
            const fresh: TaskUpdate = { ...update }
            if (update.status === 'running') {
              fresh.startedAt = now
              _appendLog('start', `${update.agent} 接收任务: ${update.task.slice(0, 50)}`, update.agent)
              currentDispatch.value = { from: 'supervisor', to: update.agent }
            }
            msg.taskItems.value.push(fresh)
          }
          const agentIdx = msg.ensureAssistant(update.agent)
          if (update.status === 'running') msg.setAgentStatus(agentIdx, 'working')
          else if (update.status === 'completed') msg.setAgentStatus(agentIdx, 'done')
          else if (update.status === 'failed') msg.setAgentStatus(agentIdx, 'failed')
        } else if (event.type === 'audit_summary') {
          msg.setAuditSummary(event.data as string)
        } else if (event.type === 'permission_request') {
          permissionRequest.value = event.data as PermissionRequest
        } else if (event.type === 'metrics') {
          msg.setMetrics(event.data as MetricsData)
        } else if (event.type === 'interrupt') {
          const d = event.data as { thread_id?: string; plan?: Record<string, unknown> | null }
          if (d?.thread_id) {
            pendingReview.value = { threadId: d.thread_id, plan: d.plan || null }
            msg.addSystem('⏸ Plan 已生成，等待您的审核 (approve/revise/reject)')
          }
        } else if (event.type === 'done') {
          // stream complete — let for-await exit naturally
        } else if (event.type === 'error') {
          _appendLog('error', String(event.data), agentName)
          msg.addError(String(event.data))
        }
      }
    } catch (e: any) {
      msg.addError(`Connection error: ${e.message}`)
    } finally {
      _flushEventQueue()
      msg.reconcileStreamEnd()
      _setSessionStatus('completed')
      const failedAgents = new Set(
        msg.taskItems.value.filter(t => t.status === 'failed').map(t => t.agent)
      )
      for (let i = 0; i < msg.messages.value.length; i++) {
        const m = msg.messages.value[i]
        if (m?.role === 'assistant') {
          if (m.agentName && failedAgents.has(m.agentName)) {
            msg.setAgentStatus(i, 'failed')
          } else {
            msg.setAgentStatus(i, 'done')
          }
        }
      }
      isLoading.value = false
      streamingActive.value = false
      _processPendingMessages()
    }
  }

  async function submitReview(decision: 'approve' | 'revise' | 'reject', feedback?: string) {
    const review = pendingReview.value
    if (!review) return
    const sid = sessionId.value
    if (!sid) return
    pendingReview.value = null
    _setSessionStatus('processing')
    _appendLog('decision', `用户审核: ${decision}`, 'user')
    try {
      for await (const event of streamOrchestrateReview(sid, review.threadId, decision, feedback)) {
        const agentName = event.agent_name || 'supervisor'
        if (event.type === 'thinking_start') {
          const idx = msg.ensureAssistant(agentName)
          msg.setThinkingStart(idx)
          msg.initThinkTypewriter(idx)
          streamingActive.value = true
        } else if (event.type === 'thinking') {
          const idx = msg.ensureAssistant(agentName)
          if (msg.thinkTypeState.value[idx]) {
            msg.thinkTypeState.value[idx].full += (event.data as string)
            _startTypewriter()
          } else {
            msg.appendThinking(idx, event.data as string)
          }
        } else if (event.type === 'thinking_done') {
          const idx = msg.ensureAssistant(agentName)
          if (idx >= 0 && msg.thinkTypeState.value[idx]) {
            const ts = msg.thinkTypeState.value[idx]
            if (ts.done) {
              if (!msg.messages.value[idx]?.thinking && ts.full) {
                msg.messages.value[idx]!.thinking = ts.full
              }
              msg.setThinkingDone(idx)
            } else ts.pendingDone = true
          } else if (idx >= 0) msg.setThinkingDone(idx)
        } else if (event.type === 'plan') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          _appendLog('decision', (event.data as string).slice(0, 80), agentName)
          const displayText = event.data as string
          const planSteps = (event.steps || []) as Array<{ agent: string; task: string }>
          for (const step of planSteps) {
            if (!msg.taskItems.value.find(t => t.agent === step.agent && t.task === step.task)) {
              msg.taskItems.value.push({ agent: step.agent, task: step.task, status: 'pending' } as TaskUpdate)
            }
          }
          const idx = msg.ensureAssistant(agentName)
          msg.messages.value[idx]!.content = displayText
          if (msg.messages.value[idx]!.isThinking) msg.messages.value[idx]!.isThinking = false
          _stopTypewriter()
        } else if (event.type === 'message') {
          const idx = msg.ensureAssistant(agentName)
          msg.appendContent(idx, event.data as string)
        } else if (event.type === 'tool_call') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          const idx = msg.ensureAssistant(agentName)
          msg.setHandoff(idx, 'supervisor', agentName)
          const tcs = event.data as Array<{ name: string; args: Record<string, unknown>; status?: string }>
          _appendLog('tool_call', tcs[0]?.name || 'unknown', agentName)
          msg.setAgentStatus(idx, 'working')
          const resultTcs = tcs.filter(tc => tc.status === 'completed' || tc.status === 'result')
          if (resultTcs.length > 0) {
            msg.messages.value[idx]!.toolCalls = resultTcs as any
            msg.clearCompletedToolCalls()
          } else {
            msg.messages.value[idx]!.toolCalls = tcs as any
          }
        } else if (event.type === 'summary') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          _appendLog('summary', (event.data as string).slice(0, 80), agentName)
          msg.pushSummary(agentName, event.data as string)
        } else if (event.type === 'task_update') {
          const update = event.data as TaskUpdate
          const now = Date.now()
          const existing = msg.taskItems.value.findIndex(t => t.agent === update.agent && t.task === update.task)
          if (existing >= 0) {
            msg.taskItems.value[existing] = { ...msg.taskItems.value[existing], ...update }
          } else {
            msg.taskItems.value.push({ ...update })
          }
        } else if (event.type === 'audit_summary') {
          msg.setAuditSummary(event.data as string)
        } else if (event.type === 'metrics') {
          msg.setMetrics(event.data as MetricsData)
        } else if (event.type === 'interrupt') {
          const d = event.data as { thread_id?: string; plan?: Record<string, unknown> | null }
          if (d?.thread_id) {
            pendingReview.value = { threadId: d.thread_id, plan: d.plan || null }
            msg.addSystem('⏸ Plan 已生成，等待您的审核 (approve/revise/reject)')
          }
        } else if (event.type === 'error') {
          msg.addError(String(event.data))
        } else if (event.type === 'permission_request') {
          permissionRequest.value = event.data as PermissionRequest
        } else if (event.type === 'done') {
          // done
        }
      }
    } catch (e: any) {
      msg.addError(`Review submission error: ${e.message}`)
    } finally {
      _flushEventQueue()
      msg.reconcileStreamEnd()
      _setSessionStatus('completed')
      isLoading.value = false
      streamingActive.value = false
      _processPendingMessages()
    }
  }

  async function sendACP(agentId: string, content: string) {
    _setSessionStatus('processing')
    if (_abortController) _abortController.abort()
    _abortController = new AbortController()
    isLoading.value = true
    streamingActive.value = false

    const taskItem: TaskUpdate = {
      agent: agentId, task: content.slice(0, 50),
      status: 'running', startedAt: Date.now(),
    }
    msg.taskItems.value = [taskItem]
    let msgIdx = -1
    _appendLog('start', `ACP agent ${agentId} 开始`, agentId)

    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE || ''}/api/acp/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, message: content, session_id: sessionId.value }),
        signal: _abortController!.signal,
      })
      if (!res.ok || !res.body) {
        msg.addSystem(`⚠ ACP agent ${agentId} 未响应 (${res.status})`)
        taskItem.status = 'failed'
        taskItem.endedAt = Date.now()
        taskItem.elapsedMs = (taskItem.endedAt - (taskItem.startedAt || taskItem.endedAt))
        isLoading.value = false
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let _acpDone = false
      while (!_acpDone) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            _appendLog(event.type as LogEntryType, String(event.data || '').slice(0, 80), agentId)
            if (event.session_id && event.session_id !== sessionId.value) {
              sessionId.value = event.session_id as string
              useSessionsStore().activeSessionId = event.session_id as string
            }
            if (event.type === 'thinking_start') {
              if (msgIdx < 0) { msgIdx = msg.addAssistant(agentId); streamingActive.value = true; msg.setThinkingStart(msgIdx) }
            } else if (event.type === 'thinking') {
              if (msgIdx < 0) { msgIdx = msg.addAssistant(agentId); streamingActive.value = true; msg.setThinkingStart(msgIdx) }
              msg.appendThinking(msgIdx, event.data as string)
            } else if (event.type === 'tool_call') {
              if (msgIdx < 0) { msgIdx = msg.addAssistant(agentId); streamingActive.value = true }
              const tc = Array.isArray(event.data) ? event.data : [event.data]
              const valid = tc.filter((t: any) => t?.name)
              if (valid.length > 0) msg.messages.value[msgIdx]!.toolCalls = valid
            } else if (event.type === 'message') {
              if (msgIdx < 0) { msgIdx = msg.addAssistant(agentId); streamingActive.value = true }
              msg.appendContent(msgIdx, event.data as string)
              msg.setThinkingDone(msgIdx)
            } else if (event.type === 'thinking_done') {
              if (msgIdx >= 0) msg.setThinkingDone(msgIdx)
            } else if (event.type === 'metrics') {
              msg.setMetrics(event.data as MetricsData)
            } else if (event.type === 'done') {
              _acpDone = true
              break
            } else if (event.type === 'permission_request') {
              const data = event.data as PermissionRequest
              if (data) permissionRequest.value = data
            } else if (event.type === 'error') {
              msg.addSystem(`⚠ ${event.data}`)
            }
          } catch { /* skip */ }
        }
      }
      taskItem.status = 'completed'
      taskItem.endedAt = Date.now()
      taskItem.elapsedMs = taskItem.endedAt - (taskItem.startedAt || taskItem.endedAt)
    } catch (e: any) {
      if (e.name !== 'AbortError') msg.addSystem(`⚠ ACP 连接错误: ${e.message}`)
      taskItem.status = 'failed'
      taskItem.endedAt = Date.now()
      taskItem.elapsedMs = taskItem.endedAt - (taskItem.startedAt || taskItem.endedAt)
    } finally {
      _flushEventQueue()
      msg.reconcileStreamEnd()
      _setSessionStatus('completed')
      if (msgIdx >= 0) msg.setThinkingDone(msgIdx)
      const statusIdx = msg.messages.value.findIndex(m =>
        m.role === 'system' && !!m.content &&
        (m.content.startsWith(`@${agentId} 执行中`) || m.content.startsWith(`@${agentId} 继续执行`))
      )
      if (statusIdx >= 0) msg.messages.value.splice(statusIdx, 1)
      permissionRequest.value = null
      isLoading.value = false
      streamingActive.value = false
      _processPendingMessages()
    }
  }

  function abort() {
    if (_currentAbort) { _currentAbort.abort(); _currentAbort = null }
    else if (_abortController) { _abortController.abort(); _abortController = null }
    isLoading.value = false
    streamingActive.value = false
    pendingMessages.value = []
    eventLog.value = []
    currentPhase.value = null
    currentDispatch.value = null
    permissionRequest.value = null
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
    _stopTypewriter()
    if (_thinkingTimeout) { clearTimeout(_thinkingTimeout); _thinkingTimeout = null }
    _setSessionStatus('completed')
  }

  async function abortAndSend(content: string) {
    abort()
    await new Promise(r => setTimeout(r, 100))
    await send(content)
  }

  async function handleCompact(): Promise<string> {
    const sid = sessionId.value ?? useSessionsStore().activeSessionId
    if (!sid) return 'No active session to compact.'
    if (!sessionId.value) sessionId.value = sid
    isLoading.value = true
    try {
      const result = await compactSession(sid)
      if (result.note) return result.note
      return `Session compacted: removed ${result.deleted_messages} old messages, kept ${result.kept_messages} recent.`
    } catch (e: any) {
      return `Compact failed: ${e.message}`
    } finally { isLoading.value = false }
  }

  async function send(content: string) {
    if (isLoading.value) {
      pendingMessages.value.push(content)
      msg.addSystem(`已排队: ${content}`)
      return
    }
    if (content.startsWith('/')) {
      const cmd = content.trim().toLowerCase()
      if (cmd === '/compact') { msg.addSystem(await handleCompact()); return }
      if (cmd === '/clear') { msg.clear(); sessionId.value = null; return }
      if (cmd === '/new') { msg.clear(); sessionId.value = null; return }
      msg.addSystem(`Unknown command: ${cmd}. Available: /compact, /clear, /new`)
      return
    }
    const mentionMatch = content.match(/(?:^|\s)@(\w[\w-]*)(?:\s|$)/)
    if (mentionMatch) {
      const agentName = mentionMatch[1].toLowerCase()
      const cleanContent = content.replace(/@[\w-]+\s?/, '').trim()
      if (cleanContent) {
        const available = await checkAcpAvailable(agentName)
        if (!available) {
          msg.addSystem(`⚠ ACP agent "${agentName}" is not available or not configured. Check config/acp_agents.json`)
          return
        }
        msg.addUser(content)
        msg.addSystem(`@${agentName} 执行中...`)
        await sendACP(agentName, cleanContent)
        return
      }
    }
    await sendOrchestrate(content)
  }

  async function checkAcpAvailable(agentId: string): Promise<boolean> {
    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE || ''}/api/acp/check/${agentId}`)
      if (!res.ok) return false
      const data = await res.json()
      return data.available === true
    } catch { return false }
  }

  function _processPendingMessages() {
    if (pendingMessages.value.length > 0 && !isLoading.value) {
      const next = pendingMessages.value.shift()
      if (next) {
        const idx = msg.messages.value.findIndex(m => m.role === 'system' && m.content?.startsWith('已排队:'))
        if (idx >= 0) msg.messages.value.splice(idx, 1)
        send(next)
      }
    }
  }

  return {
    isLoading, streamingActive, thinkingChunks, eventLog,
    currentPhase, currentDispatch, pendingMessages, permissionRequest,
    pendingReview,
    sendMessage, sendOrchestrate, sendACP, send, handleCompact,
    submitReview,
    abort, abortAndSend, checkAcpAvailable,
  }
}
