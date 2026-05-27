import { defineStore } from 'pinia'
import { ref } from 'vue'
import { streamChatCallbacks, streamOrchestrate, type ChatMessage } from '../utils/api'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const streamingActive = ref(false)
  const sessionId = ref<string | null>(null)

  // Typewriter state per message index
  const typewriterState = ref<Record<number, { display: string; full: string; done: boolean }>>({})

  let _typeTimer: ReturnType<typeof setInterval> | null = null

  function _startTypewriter() {
    if (_typeTimer) return
    _typeTimer = setInterval(() => {
      let hasMore = false
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
      if (!hasMore && _typeTimer) {
        clearInterval(_typeTimer)
        _typeTimer = null
      }
    }, 20)
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
          thinkingContent = ''
          // Don't create message yet — wait for first thinking content
        } else if (event.type === 'thinking') {
          thinkingContent += event.data as string
          const msg = ensureAssistantMsg(agentName)
          msg.thinking = thinkingContent
        } else if (event.type === 'thinking_done') {
          // no-op, thinking content already displayed
        } else if (event.type === 'tool_call') {
          const msg = ensureAssistantMsg(agentName)
          msg.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
        } else if (event.type === 'message') {
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
        } else if (event.type === 'summary') {
          messages.value.push({
            role: 'assistant',
            content: event.data as string,
            agentName: 'supervisor',
            isSummary: true,
          })
          assistantMsg = null
          msgIdx = -1
        } else if (event.type === 'error') {
          messages.value.push({ role: 'system', content: `Error: ${event.data}` })
        }
      },
      // onDone — called when stream ends or errors
      () => {
        isLoading.value = false
        streamingActive.value = false
      },
      sessionId.value || undefined,
    )
  }

  async function sendOrchestrate(task: string) {
    messages.value.push({ role: 'user', content: task })
    isLoading.value = true

    const agentThinking: Record<string, string> = {}
    const agentMsgs: Record<string, ChatMessage> = {}

    function ensureAgentMsg(agentName: string): ChatMessage {
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

        if (event.type === 'thinking_start') {
          agentThinking[agentName] = ''
          ensureAgentMsg(agentName)
        } else if (event.type === 'thinking') {
          agentThinking[agentName] = (agentThinking[agentName] || '') + (event.data as string)
          const msg = ensureAgentMsg(agentName)
          msg.thinking = agentThinking[agentName]
        } else if (event.type === 'thinking_done') {
          // no-op
        } else if (event.type === 'tool_call') {
          const msg = ensureAgentMsg(agentName)
          msg.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
        } else if (event.type === 'message') {
          const msg = ensureAgentMsg(agentName)
          msg.content = event.data as string
        } else if (event.type === 'summary') {
          messages.value.push({
            role: 'assistant',
            content: event.data as string,
            agentName: 'supervisor',
            isSummary: true,
          })
          agentMsgs['supervisor'] = undefined as any
        } else if (event.type === 'error') {
          messages.value.push({ role: 'system', content: `Error: ${event.data}` })
        }
      }
    } catch (e: any) {
      messages.value.push({ role: 'system', content: `Connection error: ${e.message}` })
    } finally {
      isLoading.value = false
      streamingActive.value = false
    }
  }

  function clearMessages() {
    messages.value = []
    sessionId.value = null
    typewriterState.value = {}
    if (_typeTimer) { clearInterval(_typeTimer); _typeTimer = null }
  }

  return {
    messages, isLoading, streamingActive, sessionId,
    typewriterState,
    sendMessage, sendOrchestrate, clearMessages,
  }
})
