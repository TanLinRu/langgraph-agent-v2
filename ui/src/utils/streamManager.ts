/**
 * 流管理组合式函数 (Stream Manager)
 *
 * 封装 SSE 流式通信的 3 条路径:
 * 1. `sendMessage` — EventSource 回调 (chat/stream 端点)
 * 2. `sendOrchestrate` — async generator (orchestrate 端点)
 * 3. `sendACP` — fetch + reader (acp/send 端点)
 *
 * 职责
 * ----
 * - SSE 事件循环 + JSON 解析
 * - 背压队列 (MICRO/STEP/MACRO 三级) + typewriter 调度
 * - Abort 控制
 * - 事件分派:把每个 SSE event type 对应到 messageManager 的操作
 *
 * 为什么与 messageManager 分离:
 *   消息管理是纯 UI 状态操作,流管理涉及 HTTP 请求 + 取消 + 重连,
 *   两个关注点耦合在一起不利于测试和替换传输层。
 */

import { ref } from 'vue'
import type { ChatMessage, LogEntry, LogEntryType, MetricsData, TaskPhaseUpdate, TaskUpdate } from './api'
import { streamChatCallbacks, streamOrchestrate, compactSession, restoreSession as apiRestoreSession } from './api'
import { useSessionsStore } from '../stores/sessions'

export function useStreamManager(
  // 接收 messageManager 的方法引用,避免循环依赖
  msg: ReturnType<typeof import('./messageManager').useMessageManager>,
  sessionId: ReturnType<typeof ref<string | null>>,
) {
  // ── 状态 ──────────────────────────────────────────────────
  const isLoading = ref(false)
  const streamingActive = ref(false)
  const thinkingChunks = ref<Array<{ agentName: string; text: string }>>([])
  const eventLog = ref<LogEntry[]>([])
  const currentPhase = ref<TaskPhaseUpdate | null>(null)
  const currentDispatch = ref<{ from: string; to: string; fromLabel?: string; toLabel?: string } | null>(null)
  const pendingMessages = ref<string[]>([])

  // Abort 控制
  let _abortController: AbortController | null = null
  let _currentAbort: { abort: () => void } | null = null
  let _lastAgent: string | null = null

  // Typewriter RAF
  let _typeRaf: number | null = null
  let _thinkingTimeout: ReturnType<typeof setTimeout> | null = null
  let _thinkChunkCount = 0

  // 背压队列
  let _eventQueue: Array<() => void> = []
  let _eventTimer: ReturnType<typeof setTimeout> | null = null

  const STEP_DELAY_MS = 80
  const SSE_DELAY_MS = 120

  // ── Helpers ───────────────────────────────────────────────

  function _setSessionStatus(status: 'processing' | 'completed') {
    const sid = sessionId.value
    if (!sid) return
    const s = useSessionsStore()
    const idx = s.sessions.findIndex(s => s.session_id === sid)
    if (idx >= 0) {
      s.sessions[idx] = { ...s.sessions[idx], status }
    }
  }

  function _appendLog(type: LogEntryType, content: string, agent?: string) {
    eventLog.value.push({ type, content, timestamp: Date.now(), agent })
  }

  // ── Typewriter ────────────────────────────────────────────

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
        msg.setContent(idx, state.display)  // TODO: should use appendThinking for thinking typewriter
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
    if (_typeRaf !== null) {
      cancelAnimationFrame(_typeRaf)
      _typeRaf = null
    }
  }

  // ── 背压队列 ─────────────────────────────────────────────

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
    for (const fn of _eventQueue) fn()
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
  }

  // ── 3 条发送路径 ─────────────────────────────────────────

  /**
   * 1. sendMessage — 通过 EventSource 回调发送
   */
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
      (event: Record<string, unknown>) => {
        if (event.session_id) {
          sessionId.value = event.session_id as string
          useSessionsStore().activeSessionId = event.session_id as string
        }
        const agentName = event.agent_name as string | undefined

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
              msg.setThinkingDone(msgIdx)
            } else {
              ts.pendingDone = true
            }
          } else if (msgIdx >= 0) {
            msg.setThinkingDone(msgIdx)
          }
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
              if (event.file_refs) {
                msg.messages.value[msgIdx]!.fileRefs = event.file_refs as string[]
              }
            }
          })
        } else if (event.type === 'summary') {
          _enqueueStep(() => {
            msg.pushSummary('supervisor', event.data as string)
            msgIdx = -1
          })
        } else if (event.type === 'error') {
          _enqueueImmediate(() => msg.addError(String(event.data)))
        }
      },
      () => {
        msg.reconcileStreamEnd()
        _setSessionStatus('completed')
        if (_eventQueue.length > 10) _flushEventQueue()
        _thinkingTimeout = setTimeout(() => {
          for (const m of msg.messages.value) {
            if (m.isThinking) m.isThinking = false
          }
          _thinkingTimeout = null
        }, 3000)
        isLoading.value = false
        streamingActive.value = false
      },
      sessionId.value || undefined,
    )
  }

  /**
   * 2. sendOrchestrate — 通过 async generator 发送多 agent 编排
   */
  async function sendOrchestrate(task: string) {
    _setSessionStatus('processing')
    msg.addUser(task)
    msg.resetTaskItems()
    eventLog.value = []
    currentPhase.value = null
    currentDispatch.value = null
    isLoading.value = true
    _appendLog('start', '开始调度任务', 'supervisor')

    let supervisorMsgIdx = -1
    const agentMsgIndices: Record<string, number> = {}

    function ensureSupervisorMsg() {
      if (supervisorMsgIdx < 0) {
        supervisorMsgIdx = msg.addAssistant('supervisor')
        streamingActive.value = true
      }
    }

    function ensureAgentMsg(agentName: string): number {
      if (!(agentName in agentMsgIndices)) {
        const idx = msg.addAssistant(agentName)
        agentMsgIndices[agentName] = idx
        streamingActive.value = true
      }
      return agentMsgIndices[agentName]
    }

    try {
      for await (const event of streamOrchestrate(task, sessionId.value || undefined)) {
        if (event.session_id) {
          sessionId.value = event.session_id as string
          useSessionsStore().activeSessionId = event.session_id as string
        }
        const agentName = (event.agent_name as string) || 'supervisor'

        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          ensureSupervisorMsg()
          msg.setThinkingStart(supervisorMsgIdx)
          msg.initThinkTypewriter(supervisorMsgIdx)
          continue
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          ensureSupervisorMsg()
          if (msg.thinkTypeState.value[supervisorMsgIdx]) {
            msg.thinkTypeState.value[supervisorMsgIdx].full += (event.data as string)
            _startTypewriter()
          } else {
            msg.appendThinking(supervisorMsgIdx, event.data as string)
          }
          continue
        } else if (event.type === 'thinking_done') {
          if (supervisorMsgIdx >= 0 && msg.thinkTypeState.value[supervisorMsgIdx]) {
            const ts = msg.thinkTypeState.value[supervisorMsgIdx]
            if (ts.done) {
              msg.setThinkingDone(supervisorMsgIdx)
            } else {
              ts.pendingDone = true
            }
          } else if (supervisorMsgIdx >= 0) {
            msg.setThinkingDone(supervisorMsgIdx)
          }
          continue
        }

        if (event.type === 'plan') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          _appendLog('decision', (event.data as string).slice(0, 80), 'supervisor')
          const planText = event.data as string
          const stepLines = planText.split('\n').filter(l => /^\s*[-*]\s*\w+:/.test(l))
          const stepCount = stepLines.length
          for (const line of stepLines) {
            const match = line.match(/^\s*[-*]\s*(\w+)\s*:\s*(.+)/)
            if (match) {
              const agent = match[1]
              const task = match[2].trim()
              const dup = msg.taskItems.value.find(t => t.agent === agent && t.task === task)
              if (!dup) {
                msg.taskItems.value.push({ agent, task, status: 'pending' } as TaskUpdate)
              }
            }
          }
          const oldStep: number = currentPhase.value?.step ?? 0
          const oldTotal: number = currentPhase.value?.totalSteps ?? 0
          currentPhase.value = {
            step: oldStep + 1,
            totalSteps: Math.max(oldTotal, stepCount || 1),
            description: stepLines[0]?.replace(/^\s*[-*]\s*\w+:\s*/, '').slice(0, 60) || '',
          }
          msg.pushPlan(planText)
        } else if (event.type === 'tool_call') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          const idx = ensureAgentMsg(agentName)
          if (!(agentName in agentMsgIndices)) {
            msg.setHandoff(idx, 'supervisor', agentName)
          }
          const tcs = event.data as Array<{ name: string; args: Record<string, unknown> }>
          _appendLog('tool_call', tcs[0]?.name || 'unknown', agentName)
          msg.setAgentStatus(idx, 'working')
          msg.messages.value[idx]!.toolCalls = tcs
        } else if (event.type === 'summary') {
          await new Promise(r => setTimeout(r, STEP_DELAY_MS))
          _appendLog('summary', (event.data as string).slice(0, 80), 'supervisor')
          ensureSupervisorMsg()
          msg.setAgentStatus(supervisorMsgIdx, 'aggregating')
          msg.messages.value[supervisorMsgIdx]!.summary = event.data as string
          msg.messages.value[supervisorMsgIdx]!.isSummary = true
        } else if (event.type === 'message') {
          const idx = ensureAgentMsg(agentName)
          msg.setContent(idx, event.data as string)
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
              merged.endedAt = now
              merged.elapsedMs = now - prev.startedAt
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
          const agentIdx = agentMsgIndices[update.agent]
          if (agentIdx !== undefined) {
            if (update.status === 'running') msg.setAgentStatus(agentIdx, 'working')
            else if (update.status === 'completed') msg.setAgentStatus(agentIdx, 'done')
            else if (update.status === 'failed') msg.setAgentStatus(agentIdx, 'failed')
          }
        } else if (event.type === 'metrics') {
          msg.setMetrics(event.data as MetricsData)
        } else if (event.type === 'error') {
          _appendLog('error', String(event.data), agentName)
          msg.addError(String(event.data))
        }
      }
    } catch (e: any) {
      msg.addError(`Connection error: ${e.message}`)
    } finally {
      msg.reconcileStreamEnd()
      _setSessionStatus('completed')
      for (const [name, idx] of Object.entries(agentMsgIndices)) {
        if (msg.messages.value[idx]) msg.setAgentStatus(idx, 'done')
      }
      if (supervisorMsgIdx >= 0 && msg.messages.value[supervisorMsgIdx]) {
        msg.setAgentStatus(supervisorMsgIdx, 'done')
        msg.setThinkingDone(supervisorMsgIdx)
      }
      isLoading.value = false
      streamingActive.value = false
      _processPendingMessages()
    }
  }

  /**
   * 3. sendACP — 直接发送给 ACP agent
   */
  async function sendACP(agentId: string, content: string) {
    _lastAgent = agentId
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
            if (event.session_id && event.session_id !== sessionId.value) {
              sessionId.value = event.session_id as string
              useSessionsStore().activeSessionId = event.session_id as string
            }
            if (event.type === 'thinking') {
              if (msgIdx < 0) {
                msgIdx = msg.addAssistant(agentId)
                streamingActive.value = true
              }
              msg.appendThinking(msgIdx, event.data as string)
              msg.setThinkingStart(msgIdx)
            } else if (event.type === 'tool_call') {
              if (msgIdx < 0) {
                msgIdx = msg.addAssistant(agentId)
                streamingActive.value = true
              }
              const tc = Array.isArray(event.data) ? event.data : [event.data]
              const valid = tc.filter((t: any) => t?.name)
              if (valid.length > 0) msg.messages.value[msgIdx]!.toolCalls = valid
            } else if (event.type === 'message') {
              if (msgIdx < 0) {
                msgIdx = msg.addAssistant(agentId)
                streamingActive.value = true
              }
              msg.appendContent(msgIdx, event.data as string)
              msg.setThinkingDone(msgIdx)
            } else if (event.type === 'thinking_done') {
              if (msgIdx >= 0) msg.setThinkingDone(msgIdx)
            } else if (event.type === 'metrics') {
              msg.setMetrics(event.data as MetricsData)
            } else if (event.type === 'error') {
              msg.addSystem(`⚠ ${event.data}`)
            }
          } catch { /* 跳过无法解析的行 */ }
        }
      }
      taskItem.status = 'completed'
      taskItem.endedAt = Date.now()
      taskItem.elapsedMs = taskItem.endedAt - (taskItem.startedAt || taskItem.endedAt)
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        msg.addSystem(`⚠ ACP 连接错误: ${e.message}`)
      }
      taskItem.status = 'failed'
      taskItem.endedAt = Date.now()
      taskItem.elapsedMs = taskItem.endedAt - (taskItem.startedAt || taskItem.endedAt)
    } finally {
      msg.reconcileStreamEnd()
      _setSessionStatus('completed')
      if (msgIdx >= 0) msg.setThinkingDone(msgIdx)
      const statusIdx = msg.messages.value.findIndex(m =>
        m.role === 'system' && !!m.content &&
        (m.content.startsWith(`@${agentId} 执行中`) || m.content.startsWith(`@${agentId} 继续执行`))
      )
      if (statusIdx >= 0) msg.messages.value.splice(statusIdx, 1)
      isLoading.value = false
      streamingActive.value = false
      _processPendingMessages()
    }
  }

  // ── Abort ────────────────────────────────────────────────

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
    eventLog.value = []
    currentPhase.value = null
    currentDispatch.value = null
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

  // ── Compact ─────────────────────────────────────────────

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
    } finally {
      isLoading.value = false
    }
  }

  // ── 发送入口 (含 command / @mention / ACP 路由) ─────────

  async function send(content: string) {
    if (isLoading.value) {
      pendingMessages.value.push(content)
      msg.addSystem(`已排队: ${content}`)
      return
    }

    if (content.startsWith('/')) {
      const cmd = content.trim().toLowerCase()
      if (cmd === '/compact') { msg.addSystem(await handleCompact()); return }
      if (cmd === '/clear') { msg.clear(); sessionId.value = null; _lastAgent = null; return }
      if (cmd === '/new') { msg.clear(); sessionId.value = null; _lastAgent = null; return }
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

    if (_lastAgent) {
      const available = await checkAcpAvailable(_lastAgent)
      if (available) {
        msg.addUser(content)
        msg.addSystem(`@${_lastAgent} 继续执行...`)
        await sendACP(_lastAgent, content)
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
    } catch {
      return false
    }
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
    currentPhase, currentDispatch, pendingMessages,
    sendMessage, sendOrchestrate, sendACP, send, handleCompact,
    abort, abortAndSend, checkAcpAvailable,
  }
}
