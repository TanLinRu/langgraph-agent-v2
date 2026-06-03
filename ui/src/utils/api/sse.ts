/**
 * SSE 流式通信函数
 *
 * 封装基于 fetch + ReadableStream 的 SSE 请求:
 * - streamChatCallbacks → 回调风格 (/chat 端点)
 * - streamChatFetch → 异步迭代器风格 (/chat 端点)
 * - streamOrchestrate → 异步迭代器风格 (/api/orchestrate 端点)
 */

const API_BASE = import.meta.env.VITE_API_BASE || ''

/**
 * 通过 fetch + ReadableStream 发起 POST /chat 的 SSE 流式请求。
 *
 * 每个事件立即触发 onEvent 回调,让 Vue 实时更新 DOM。
 * 流结束时触发 onDone。
 */
export function streamChatCallbacks(
  message: string,
  onEvent: (event: Record<string, unknown>) => void,
  onDone: () => void,
  sessionId?: string,
): { abort: () => void } {
  const controller = new AbortController()
  const t0 = performance.now()

  console.log(`[SSE-TRACE] streamChatCallbacks: POST → /chat`)

  fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal: controller.signal,
  }).then(async (res) => {
    if (!res.ok || !res.body) {
      console.warn(`[SSE-TRACE] HTTP ${res.status}`)
      onDone()
      return
    }

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
            console.log(`[SSE-TRACE] ${(performance.now() - t0).toFixed(0)}ms POST: #${eventIdx} ${event.type}`)
            onEvent(event)
            if (event.type === 'done') {
              onDone()
              return
            }
          } catch {}
        }
      }
    }
    onDone()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      console.warn('[SSE-TRACE] fetch error:', err)
    }
    onDone()
  })

  return { abort: () => controller.abort() }
}

/**
 * 异步迭代器风格的 POST /chat SSE 流式请求。
 * 每次 `for await (const event of streamChatFetch(...))` 消费一个事件。
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

/**
 * 异步迭代器风格的 POST /api/orchestrate SSE 流式请求。
 * 用于多智能体编排场景 (Supervisor → Worker)。
 */
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
