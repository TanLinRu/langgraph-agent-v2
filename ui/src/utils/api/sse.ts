/**
 * SSE 流式通信函数
 *
 * 封装基于 fetch + ReadableStream 的 SSE 请求:
 * - streamChatCallbacks → 回调风格 (/chat 端点)
 * - streamChatFetch → 异步迭代器风格 (/chat 端点)
 * - streamOrchestrate → 异步迭代器风格 (/api/orchestrate 端点)
 */

import type { SSEEvent } from './types'

const API_BASE = import.meta.env.VITE_API_BASE || ''

/**
 * 通过 fetch + ReadableStream 发起 POST /chat 的 SSE 流式请求。
 *
 * 每个事件立即触发 onEvent 回调,让 Vue 实时更新 DOM。
 * 流结束时触发 onDone。
 */
export function streamChatCallbacks(
  message: string,
  onEvent: (event: SSEEvent) => void,
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
 * 异步迭代器风格的 POST /api/orchestrate SSE 流式请求。
 * 用于多智能体编排场景 (Supervisor → Worker)。
 */
export async function* streamOrchestrate(task: string, sessionId?: string, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
  const url = `${API_BASE}/api/orchestrate`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, session_id: sessionId }),
    signal,
  })

  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
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

/**
 * POST /api/agent/send SSE 流式请求。
 * 统一的 @mention 单 agent 调度端点。
 */
export async function* streamAgentSend(
  agentId: string,
  message: string,
  sessionId?: string,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const url = `${API_BASE}/api/agent/send`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: agentId, message, session_id: sessionId }),
    signal,
  })

  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
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

/**
 * 用户提交 approve/revise/reject 后，stream 恢复并继续。
 */
export async function* streamOrchestrateReview(
  sessionId: string,
  threadId: string,
  decision: string,
  feedback?: string,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const url = `${API_BASE}/api/orchestrate/${sessionId}/review`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, thread_id: threadId, decision, feedback: feedback || '' }),
    signal,
  })

  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
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
