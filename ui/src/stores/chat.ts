import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useMessageManager } from '../utils/messageManager'
import { useStreamManager } from '../utils/streamManager'
import { restoreSession as apiRestoreSession } from '../utils/api'
import { useSessionsStore } from './sessions'

/**
 * Chat Store —— 用 Pinia 封装的组合式 store。
 *
 * 内部委托:
 * - 状态管理 → `useMessageManager()` (messages / typewriter / taskItems / metrics)
 * - 流通信 → `useStreamManager()` (SSE send / abort / backpressure)
 *
 * 对外保持与旧版完全兼容的 API surface:
 *   `useChatStore()` 返回 `{ messages, isLoading, send, abort, ... }`
 */
export const useChatStore = defineStore('chat', () => {
  // ── Message 状态 (委托 messageManager) ──────────────────
  const msg = useMessageManager()

  // ── Session 状态 (本地) ─────────────────────────────────
  const sessionId = ref<string | null>(null)

  // ── Stream 状态 (委托 streamManager) ────────────────────
  const stream = useStreamManager(msg, sessionId)

  // ── Sync sessionId from sessions store ─────────────────
  const sessionsStore = useSessionsStore()
  watch(() => sessionsStore.activeSessionId, async (id) => {
    if (id && id !== sessionId.value) {
      stream.abort()
      sessionId.value = id
      await restoreSession()
    } else if (!id) {
      stream.abort()
      sessionId.value = null
      msg.clear()
    }
  })

  // ── 会话恢复 ────────────────────────────────────────────
  async function restoreSession() {
    const id = sessionId.value
    if (!id) return

    msg.clear()

    try {
      const data = await apiRestoreSession(id)
      if (!data.messages || data.messages.length === 0) return

      const restored: import('../utils/api').ChatMessage[] = []
      for (const m of data.messages) {
        if ((m as any).compacted) continue
        if (m.type === 'human') {
          restored.push({ role: 'user', content: m.content })
        } else if (m.type === 'ai') {
          const name = (m as any).name as string | undefined
          const hasContent = m.content && m.content.trim()
          const hasThinking = !!(m as any).thinking
          const hasToolCalls = !!(m as any).tool_calls
          const isPlan = name === 'plan'
          const isSummary = name === 'summary'
          const isThinkingOnly = name === 'thinking'
          if (isThinkingOnly) continue
          if (hasToolCalls && !hasContent && !isPlan && !isSummary) continue
          const chatMsg: import('../utils/api').ChatMessage = {
            role: 'assistant', content: m.content || '',
          }
          if (hasThinking) {
            chatMsg.thinking = (m as any).thinking
            chatMsg.thinkingDone = true
          }
          if (hasToolCalls) chatMsg.toolCalls = (m as any).tool_calls
          if (isPlan) chatMsg.isPlan = true
          else if (isSummary) chatMsg.isSummary = true
          else if (name && !isThinkingOnly) chatMsg.agentName = name
          restored.push(chatMsg)
        }
      }

      if (data.summary) {
        restored.unshift({
          role: 'system', content: `[Compacted context]\n${data.summary}`,
        })
      }

      msg.restore(restored)

      if (data.task_updates && data.task_updates.length > 0) {
        msg.taskItems.value = data.task_updates.map((t: any) => ({
          agent: t.agent || '', task: t.task || '', status: t.status || 'completed',
          state: t.state || undefined, startedAt: t.started_at ?? undefined,
          endedAt: t.ended_at ?? undefined, elapsedMs: t.elapsed_ms ?? undefined,
        }))
      }
      if (data.metrics) {
        msg.setMetrics(data.metrics)
      }
      if (data.audit_summary) {
        msg.setAuditSummary(data.audit_summary)
      }
      if (data.project_path && sessionId.value) {
        const existing = sessionsStore.getSessionById(sessionId.value)
        if (existing && !existing.project_path) {
          existing.project_path = data.project_path
        }
      }
    } catch (e: any) {
      if (e.message?.includes('404') || e.message?.includes('Not Found')) {
        // session gone on server — reset
        sessionId.value = null
        sessionsStore.activeSessionId = null
      } else {
        // transient error (network / 500 / timeout) — keep sessionId,
        // the SSE stream will reconnect or create a new one
        console.warn('[CHAT] restore failed (transient):', e.message)
      }
    }
  }

  // ── 便捷方法:clear / newSession ──────────────────────────
  function clearMessages() {
    stream.abort()
    msg.clear()
    sessionId.value = null
    stream.pendingMessages.value = []
    stream.eventLog.value = []
    stream.currentPhase.value = null
    stream.currentDispatch.value = null
    stream.permissionRequest.value = null
  }

  function newSession() {
    clearMessages()
    sessionsStore.activeSessionId = null
  }

  // ── 对外导出 (保持旧 API 兼容) ─────────────────────────
  return {
    // 状态 (来自 msg)
    messages: msg.messages,
    typewriterState: msg.typewriterState,
    thinkTypeState: msg.thinkTypeState,
    taskItems: msg.taskItems,
    metrics: msg.metrics,
    auditSummary: msg.auditSummary,
    // 状态 (来自 stream)
    isLoading: stream.isLoading,
    streamingActive: stream.streamingActive,
    eventLog: stream.eventLog,
    currentPhase: stream.currentPhase,
    currentDispatch: stream.currentDispatch,
    pendingMessages: stream.pendingMessages,
    permissionRequest: stream.permissionRequest,
    pendingReview: stream.pendingReview,
    submitReview: stream.submitReview,
    // Session
    sessionId,
    // 方法
    sendOrchestrate: stream.sendOrchestrate,
    sendACP: stream.sendACP,
    send: stream.send,
    abort: stream.abort,
    abortAndSend: stream.abortAndSend,
    clearMessages,
    newSession,
    restoreSession,
    formatElapsed: () => '',  // kept for compat, can inline later
    handleCompact: stream.handleCompact,
  }
})
