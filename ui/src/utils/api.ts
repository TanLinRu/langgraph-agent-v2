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
 * Stream chat via EventSource (GET /chat/stream).
 * EventSource is the browser's native SSE client — no buffering, real-time events.
 */
export function streamChat(message: string, sessionId?: string): AsyncGenerator<Record<string, unknown>> {
  const params = new URLSearchParams({ message })
  if (sessionId) params.set('session_id', sessionId)
  const url = `${API_BASE}/chat/stream?${params.toString()}`

  console.log(`[SSE-TRACE] streamChat: EventSource → ${url}`)
  const t0 = performance.now()

  const es = new EventSource(url)
  const queue: Array<{ value: Record<string, unknown>; done: boolean }> = []
  let resolveWaiter: (() => void) | null = null
  let closed = false

  function enqueue(value: Record<string, unknown>, done = false) {
    if (closed) return
    queue.push({ value, done })
    if (resolveWaiter) {
      resolveWaiter()
      resolveWaiter = null
    }
  }

  const eventTypes = ['thinking_start', 'thinking', 'thinking_done', 'tool_call', 'message', 'summary', 'error']
  for (const type of eventTypes) {
    es.addEventListener(type, (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms streamChat: ${type}`)
      enqueue(data)
    })
  }

  es.addEventListener('done', () => {
    console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms streamChat: done`)
    es.close()
    closed = true
    enqueue({ type: 'done' }, true)
  })

  es.onerror = () => {
    if (!closed) {
      console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms streamChat: error, closing`)
      es.close()
      closed = true
      enqueue({ type: 'done' }, true)
    }
  }

  return {
    [Symbol.asyncIterator]() { return this },
    async next() {
      if (queue.length > 0) {
        const item = queue.shift()!
        return { value: item.value, done: item.done }
      }
      if (closed) return { value: { type: 'done' }, done: true }
      await new Promise<void>((r) => { resolveWaiter = r })
      if (queue.length > 0) {
        const item = queue.shift()!
        return { value: item.value, done: item.done }
      }
      return { value: { type: 'done' }, done: true }
    },
    return() { es.close(); closed = true; return Promise.resolve({ value: undefined, done: true }) },
    throw(e) { es.close(); closed = true; return Promise.reject(e) },
  }
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
          console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms streamChatFetch: #${eventIdx} ${event.type}`)
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
