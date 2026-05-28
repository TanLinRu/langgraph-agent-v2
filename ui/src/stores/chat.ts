import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import {
  streamChatCallbacks,
  streamOrchestrate,
  compactSession,
  restoreSession as apiRestoreSession,
  type ChatMessage,
} from '../utils/api'

const SESSION_KEY = 'chat_session_id'
const SSE_DELAY_MS = 120  // delay before major SSE events (tool_call, message, plan, summary)

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const streamingActive = ref(false)
  const sessionId = ref<string | null>(null)
  const mode = ref<'single' | 'multi'>('single')

  // Typewriter state per message index
  const typewriterState = ref<Record<number, { display: string; full: string; done: boolean }>>({})
  // Thinking typewriter state per message index
  const thinkTypeState = ref<Record<number, { display: string; full: string; done: boolean; pendingDone: boolean }>>({})

  let _typeTimer: ReturnType<typeof setInterval> | null = null

  // SSE backpressure: major events queued with 120ms delay
  let _eventQueue: Array<() => void> = []
  let _eventTimer: ReturnType<typeof setTimeout> | null = null

  // Thinking: backend batches chunks, frontend renders directly
  let _thinkChunkCount = 0

  function _startTypewriter() {
    if (_typeTimer) return
    _typeTimer = setInterval(() => {
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
          // All chars rendered — keep msg.thinking as-is (don't clear it)
          if (state.pendingDone && messages.value[idx]) {
            messages.value[idx].isThinking = false
            // Ensure thinking content persists for visibility
            if (!messages.value[idx].thinking && state.full) {
              messages.value[idx].thinking = state.full
            }
          }
        }
      }
      if (!hasMore && _typeTimer) {
        clearInterval(_typeTimer)
        _typeTimer = null
      }
    }, 15)
  }

  function _enqueueEvent(fn: () => void, label?: string) {
    _eventQueue.push(fn)
    console.log(`[CHAT:QUEUE] enqueued: ${label || 'fn'}, queue=${_eventQueue.length}`)
    if (!_eventTimer) {
      _eventTimer = setTimeout(() => {
        const next = _eventQueue.shift()!
        console.log(`[CHAT:QUEUE] fired: queue remaining=${_eventQueue.length}`)
        next()
        _eventTimer = null
        if (_eventQueue.length > 0) _scheduleNextMajor()
      }, SSE_DELAY_MS)
    }
  }

  function _scheduleNextMajor() {
    if (_eventTimer) return
    _eventTimer = setTimeout(() => {
      const next = _eventQueue.shift()!
      console.log(`[CHAT:QUEUE] fired: queue remaining=${_eventQueue.length}`)
      next()
      _eventTimer = null
      if (_eventQueue.length > 0) _scheduleNextMajor()
    }, SSE_DELAY_MS)
  }

  function _flushEventQueue() {
    console.log(`[CHAT:QUEUE] flush all: ${_eventQueue.length} queued events`)
    for (const fn of _eventQueue) fn()
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
  }

  // Restore sessionId from localStorage on init
  const savedSessionId = localStorage.getItem(SESSION_KEY)
  if (savedSessionId) {
    sessionId.value = savedSessionId
  }

  // Persist sessionId to localStorage when it changes
  watch(sessionId, (id) => {
    if (id) {
      localStorage.setItem(SESSION_KEY, id)
    } else {
      localStorage.removeItem(SESSION_KEY)
    }
  })

  async function restoreSession() {
    const id = sessionId.value
    if (!id) return

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
        if (m.type === 'human') {
          const msg: ChatMessage = { role: 'user', content: m.content }
          if ((m as any).compacted) msg.compacted = true
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
      console.log(`[CHAT] restored ${restored.length} messages (hasSummary=${!!data.summary})`)
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
    messages.value.push({ role: 'user', content })
    isLoading.value = true
    streamingActive.value = false  // will be set true when assistant msg is created

    let thinkingContent = ''
    let assistantMsg: ChatMessage | null = null
    let msgIdx = -1

    function ensureAssistantMsg(agentName?: string): ChatMessage {
      if (!assistantMsg) {
        assistantMsg = { role: 'assistant', content: '', agentName }
        messages.value.push(assistantMsg)
        msgIdx = messages.value.length - 1
        streamingActive.value = true  // hide loading dots, show assistant msg
      }
      if (agentName && !assistantMsg.agentName) {
        assistantMsg.agentName = agentName
      }
      return assistantMsg
    }

    streamChatCallbacks(
      content,
      // onEvent — called immediately for each SSE event
      (event) => {
        if (event.session_id) {
          sessionId.value = event.session_id as string
        }

        const agentName = event.agent_name as string | undefined

        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          const msg = ensureAssistantMsg(agentName)
          msg.isThinking = true
          // Initialize thinking typewriter state
          if (msgIdx >= 0) {
            thinkTypeState.value[msgIdx] = { display: '', full: '', done: false, pendingDone: false }
            msg.thinking = ''
          }
          console.log('[CHAT] thinking_start')
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          const msg = ensureAssistantMsg(agentName)
          if (msgIdx >= 0 && thinkTypeState.value[msgIdx]) {
            // Append to typewriter buffer, let _startTypewriter render char by char
            thinkTypeState.value[msgIdx].full += (event.data as string)
            _startTypewriter()
          } else {
            // Fallback: direct set if typewriter state not initialized
            msg.thinking = (msg.thinking || '') + (event.data as string)
          }
        } else if (event.type === 'thinking_done') {
          console.log(`[CHAT] thinking_done: ${_thinkChunkCount} batches`)
          if (msgIdx >= 0 && thinkTypeState.value[msgIdx]) {
            const ts = thinkTypeState.value[msgIdx]
            if (ts.done) {
              // Typewriter already finished — clear immediately
              if (assistantMsg) assistantMsg.isThinking = false
            } else {
              // Typewriter still running — defer until it finishes
              ts.pendingDone = true
            }
          } else if (assistantMsg) {
            assistantMsg.isThinking = false
          }
        } else if (event.type === 'tool_call') {
          _enqueueEvent(() => {
            const msg = ensureAssistantMsg(agentName)
            msg.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
          }, 'tool_call')
        } else if (event.type === 'message') {
          _enqueueEvent(() => {
            const msg = ensureAssistantMsg(agentName)
            const fullContent = event.data as string
            if (msgIdx >= 0 && fullContent) {
              // Typewriter animation for final message
              typewriterState.value[msgIdx] = { display: '', full: fullContent, done: false }
              msg.content = ''
              _startTypewriter()
            } else {
              msg.content = fullContent
            }
          }, 'message')
        } else if (event.type === 'summary') {
          _enqueueEvent(() => {
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
          _enqueueEvent(() => {
            messages.value.push({ role: 'system', content: `Error: ${event.data}` })
          }, 'error')
        }
      },
      // onDone — called when stream ends or errors
      () => {
        console.log('[CHAT] stream done')
        _flushEventQueue()
        // Clear any lingering isThinking state (e.g., stream ended without thinking_done)
        for (const msg of messages.value) {
          if (msg.isThinking) msg.isThinking = false
        }
        isLoading.value = false
        streamingActive.value = false
      },
      sessionId.value || undefined,
    )
  }

  async function sendOrchestrate(task: string) {
    messages.value.push({ role: 'user', content: task })
    isLoading.value = true

    // Track per-agent state
    let supervisorMsg: ChatMessage | null = null
    let supervisorMsgIdx = -1
    const agentMsgs: Record<string, ChatMessage> = {}

    function getSupervisorMsg(): ChatMessage {
      if (!supervisorMsg) {
        supervisorMsg = { role: 'assistant', content: '', agentName: 'supervisor' }
        messages.value.push(supervisorMsg)
        supervisorMsgIdx = messages.value.length - 1
        streamingActive.value = true
      }
      return supervisorMsg
    }

    function getAgentMsg(agentName: string): ChatMessage {
      if (!agentMsgs[agentName]) {
        const msg: ChatMessage = { role: 'assistant', content: '', agentName }
        agentMsgs[agentName] = msg
        messages.value.push(msg)
        streamingActive.value = true
      }
      return agentMsgs[agentName]
    }

    try {
      for await (const event of streamOrchestrate(task, sessionId.value || undefined)) {
        if (event.session_id) {
          sessionId.value = event.session_id as string
        }

        const agentName = (event.agent_name as string) || 'supervisor'
        const isMajor = event.type === 'tool_call' || event.type === 'message'
          || event.type === 'plan' || event.type === 'summary' || event.type === 'error'

        // Thinking: typewriter animation
        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          const msg = getSupervisorMsg()
          msg.isThinking = true
          // Initialize thinking typewriter state
          if (supervisorMsgIdx >= 0) {
            thinkTypeState.value[supervisorMsgIdx] = { display: '', full: '', done: false, pendingDone: false }
            msg.thinking = ''
          }
          console.log('[CHAT:ORCH] thinking_start')
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          const msg = getSupervisorMsg()
          if (supervisorMsgIdx >= 0 && thinkTypeState.value[supervisorMsgIdx]) {
            // Append to typewriter buffer, let _startTypewriter render char by char
            thinkTypeState.value[supervisorMsgIdx].full += (event.data as string)
            _startTypewriter()
          } else {
            msg.thinking = (msg.thinking || '') + (event.data as string)
          }
          continue
        } else if (event.type === 'thinking_done') {
          console.log(`[CHAT:ORCH] thinking_done: ${_thinkChunkCount} batches`)
          if (supervisorMsgIdx >= 0 && thinkTypeState.value[supervisorMsgIdx]) {
            const ts = thinkTypeState.value[supervisorMsgIdx]
            if (ts.done) {
              if (supervisorMsg) (supervisorMsg as ChatMessage).isThinking = false
            } else {
              ts.pendingDone = true
            }
          } else if (supervisorMsg) {
            (supervisorMsg as ChatMessage).isThinking = false
          }
          continue
        }

        // Major events: delay for stepped visual effect
        if (isMajor) {
          await new Promise(r => setTimeout(r, SSE_DELAY_MS))
        }

        if (event.type === 'plan') {
          console.log('[CHAT:ORCH] plan')
          messages.value.push({
            role: 'assistant',
            content: event.data as string,
            agentName: 'supervisor',
            isPlan: true,
          })
        } else if (event.type === 'tool_call') {
          console.log(`[CHAT:ORCH] tool_call: ${agentName}`)
          const msg = getAgentMsg(agentName)
          msg.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
        } else if (event.type === 'message') {
          console.log(`[CHAT:ORCH] message: ${agentName}`)
          const msg = getAgentMsg(agentName)
          msg.content = event.data as string
        } else if (event.type === 'summary') {
          console.log('[CHAT:ORCH] summary')
          messages.value.push({
            role: 'assistant',
            content: event.data as string,
            agentName: 'supervisor',
            isSummary: true,
          })
        } else if (event.type === 'error') {
          messages.value.push({ role: 'system', content: `Error: ${event.data}` })
        }
      }
      console.log('[CHAT:ORCH] stream done')
    } catch (e: any) {
      messages.value.push({ role: 'system', content: `Connection error: ${e.message}` })
    } finally {
      // Clear any lingering isThinking state
      for (const msg of messages.value) {
        if (msg.isThinking) msg.isThinking = false
      }
      isLoading.value = false
      streamingActive.value = false
    }
  }

  function clearMessages() {
    messages.value = []
    sessionId.value = null
    typewriterState.value = {}
    thinkTypeState.value = {}
    if (_typeTimer) { clearInterval(_typeTimer); _typeTimer = null }
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
  }

  function newSession() {
    clearMessages()
    // sessionId is now null, next send will create a new session
  }

  async function handleCompact(): Promise<string> {
    const id = sessionId.value
    if (!id) return 'No active session to compact.'

    isLoading.value = true
    try {
      const result = await compactSession(id)
      // Reload the compacted session to get the updated state
      await restoreSession()
      return `Session compacted: removed ${result.deleted_messages} old messages, kept ${result.kept_messages} recent.`
    } catch (e: any) {
      return `Compact failed: ${e.message}`
    } finally {
      isLoading.value = false
    }
  }

  async function send(content: string) {
    // Handle slash commands
    if (content.startsWith('/')) {
      const cmd = content.trim().toLowerCase()
      if (cmd === '/compact') {
        const result = await handleCompact()
        messages.value.push({ role: 'system', content: result })
        return
      }
      if (cmd === '/clear') {
        clearMessages()
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

    if (mode.value === 'multi') {
      await sendOrchestrate(content)
    } else {
      sendMessage(content)
    }
  }

  // Auto-restore session on store init
  if (sessionId.value) {
    restoreSession()
  }

  return {
    messages, isLoading, streamingActive, sessionId, mode,
    typewriterState,
    sendMessage, sendOrchestrate, send, clearMessages, newSession, restoreSession,
  }
})
