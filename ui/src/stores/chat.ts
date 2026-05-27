import { defineStore } from 'pinia'
import { ref } from 'vue'
import { streamChat, streamOrchestrate, type ChatMessage } from '../utils/api'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const streamingActive = ref(false)
  const sessionId = ref<string | null>(null)

  function _agentColor(name?: string): string {
    const colors: Record<string, string> = {
      supervisor: '#818cf8',
      coder: '#34d399',
      researcher: '#fbbf24',
      analyst: '#fb7185',
    }
    return colors[name || ''] || 'rgba(255,255,255,0.5)'
  }

  async function sendMessage(content: string) {
    messages.value.push({ role: 'user', content })
    isLoading.value = true

    let thinkingContent = ''
    let assistantMsg: ChatMessage | null = null

    function ensureAssistantMsg(agentName?: string): ChatMessage {
      if (!assistantMsg) {
        assistantMsg = { role: 'assistant', content: '', agentName }
        messages.value.push(assistantMsg)
        streamingActive.value = true
      }
      if (agentName && !assistantMsg.agentName) {
        assistantMsg.agentName = agentName
      }
      return assistantMsg
    }

    try {
      for await (const event of streamChat(content, sessionId.value || undefined)) {
        if (event.session_id) {
          sessionId.value = event.session_id as string
        }

        const agentName = event.agent_name as string | undefined

        if (event.type === 'thinking_start') {
          thinkingContent = ''
          ensureAssistantMsg(agentName)
        } else if (event.type === 'thinking') {
          thinkingContent += event.data as string
          const msg = ensureAssistantMsg(agentName)
          msg.thinking = thinkingContent
        } else if (event.type === 'thinking_done') {
          // no-op
        } else if (event.type === 'tool_call') {
          const msg = ensureAssistantMsg(agentName)
          msg.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
        } else if (event.type === 'message') {
          const msg = ensureAssistantMsg(agentName)
          msg.content = event.data as string
        } else if (event.type === 'summary') {
          // Supervisor summary — emit as a separate message
          messages.value.push({
            role: 'assistant',
            content: event.data as string,
            agentName: 'supervisor',
            isSummary: true,
          })
          assistantMsg = null
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
  }

  return { messages, isLoading, streamingActive, sessionId, sendMessage, sendOrchestrate, clearMessages }
})
