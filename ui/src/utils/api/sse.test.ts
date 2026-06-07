import { describe, it, expect, vi, beforeEach } from 'vitest'

describe('SSE stream parsing', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  function mockFetch(bodyChunks: string[]) {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      async start(controller) {
        for (const chunk of bodyChunks) {
          controller.enqueue(encoder.encode(chunk))
        }
        controller.close()
      },
    })
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: stream,
    } as Response)
  }

  function mockFetchFail(status: number) {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status,
      body: null,
    } as unknown as Response)
  }

  describe('streamChatCallbacks', () => {
    it('calls onEvent for each SSE event and onDone at end', async () => {
      mockFetch(['data: {"type":"thinking","data":"x"}\n\n', 'data: {"type":"done"}\n\n'])
      const { streamChatCallbacks } = await import('./sse')

      const events: Record<string, unknown>[] = []
      let done = false

      await new Promise<void>((resolve) => {
        streamChatCallbacks('test', (e) => { events.push(e) }, () => { done = true; resolve() })
      })

      await vi.waitFor(() => {
        expect(events).toHaveLength(2)
        expect(done).toBe(true)
      }, { timeout: 2000 })
    })

    it('handles partial chunks across multiple reads', async () => {
      mockFetch(['data: {"type":"thin', 'king","data":"测试"}\n\n', 'data: {"type":"done"}\n\n'])
      const { streamChatCallbacks } = await import('./sse')

      const events: Record<string, unknown>[] = []
      let done = false

      await new Promise<void>((resolve) => {
        streamChatCallbacks('test', (e) => { events.push(e) }, () => { done = true; resolve() })
      })

      await vi.waitFor(() => {
        expect(events).toHaveLength(2)
        expect(events[0].type).toBe('thinking')
        expect((events[0].data)).toBe('测试')
        expect(done).toBe(true)
      }, { timeout: 2000 })
    })

    it('skips non-data lines', async () => {
      mockFetch(['event: message\n', 'data: {"type":"thinking","data":"x"}\n\n', ':comment\n', 'data: {"type":"done"}\n\n'])
      const { streamChatCallbacks } = await import('./sse')

      const events: Record<string, unknown>[] = []
      let done = false

      await new Promise<void>((resolve) => {
        streamChatCallbacks('test', (e) => { events.push(e) }, () => { done = true; resolve() })
      })

      await vi.waitFor(() => {
        expect(events).toHaveLength(2)
        expect(done).toBe(true)
      }, { timeout: 2000 })
    })

    it('throws on non-ok response (done still called)', async () => {
      mockFetchFail(500)
      const { streamChatCallbacks } = await import('./sse')

      const events: Record<string, unknown>[] = []
      let done = false

      await new Promise<void>((resolve) => {
        streamChatCallbacks('test', (e) => { events.push(e) }, () => { done = true; resolve() })
      })

      await vi.waitFor(() => {
        expect(done).toBe(true)
        expect(events).toHaveLength(0)
      }, { timeout: 2000 })
    })

    it('silently ignores malformed JSON lines', async () => {
      mockFetch(['data: not-json\n\n', 'data: {"type":"done"}\n\n'])
      const { streamChatCallbacks } = await import('./sse')

      const events: Record<string, unknown>[] = []
      let done = false

      await new Promise<void>((resolve) => {
        streamChatCallbacks('test', (e) => { events.push(e) }, () => { done = true; resolve() })
      })

      await vi.waitFor(() => {
        expect(events).toHaveLength(1)
        expect(events[0].type).toBe('done')
        expect(done).toBe(true)
      }, { timeout: 2000 })
    })
  })
})
