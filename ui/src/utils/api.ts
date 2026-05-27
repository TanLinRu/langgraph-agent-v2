export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  toolCalls?: Array<{ name: string; args: Record<string, unknown> }>
  agentName?: string
  thinking?: string
  isSummary?: boolean
}

const API_BASE = import.meta.env.VITE_API_BASE || ''

/**
 * Stream chat via EventSource with callbacks — no async generator bottleneck.
 * Each event fires the callback immediately, letting Vue update the DOM in real-time.
 */
export function streamChatCallbacks(
  message: string,
  onEvent: (event: Record<string, unknown>) => void,
  onDone: () => void,
  sessionId?: string,
): EventSource {
  const params = new URLSearchParams({ message })
  if (sessionId) params.set('session_id', sessionId)
  const url = `${API_BASE}/chat/stream?${params.toString()}`

  console.log(`[SSE-TRACE] streamChatCallbacks: EventSource → ${url}`)
  const t0 = performance.now()

  const es = new EventSource(url)

  const eventTypes = ['thinking_start', 'thinking', 'thinking_done', 'tool_call', 'message', 'summary', 'error']
  for (const type of eventTypes) {
    es.addEventListener(type, (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms SSE: ${type}`)
      onEvent(data)
    })
  }

  es.addEventListener('done', () => {
    console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms SSE: done`)
    es.close()
    onDone()
  })

  es.onerror = () => {
    console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms SSE: error`)
    es.close()
    onDone()
  }

  return es
}

/**
 * Stream chat via fetch + ReadableStream (POST /chat).
 */
export async function* streamChatFetch(message: string, sessionId?: string): AsyncGenerator<Record<string, unknown>> {
  const url = `${API_BASE}/chat`
  const t0 = performance.now()

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })

  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventIdx = 0

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6))
          eventIdx++
          console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms fetch: #${eventIdx} ${event.type}`)
          yield event
        } catch {}
      }
    }
  }
}

export async function* streamOrchestrate(task: string, sessionId?: string): AsyncGenerator<Record<string, unknown>> {
  const url = `${API_BASE}/api/orchestrate`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, session_id: sessionId }),
  })

  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

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
      if (line.startsWith('data: ')) {
        try { yield JSON.parse(line.slice(6)) } catch {}
      }
    }
  }
}

export async function listTools(): Promise<Array<{ name: string; description: string }>> {
  const res = await fetch(`${API_BASE}/api/tools`)
  const data = await res.json()
  return data.tools
}

export async function listSessions(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/sessions`)
  const data = await res.json()
  return data.sessions
}
