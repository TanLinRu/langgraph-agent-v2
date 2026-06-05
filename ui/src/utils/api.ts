/**
 * API 模块 — 统一导出入口
 *
 * 为保持向后兼容,此文件作为 barrel 重新导出所有子模块:
 * - `types.ts`      → 类型定义 (ChatMessage, MetricsData, TaskUpdate 等)
 * - `endpoints.ts`  → REST 端点函数 (fetchAgents, createSession 等)
 * - `sse.ts`        → SSE 流式通信 (streamChatCallbacks, streamOrchestrate 等)
 *
 * 所有已有 `from './api'` 的导入无需改动。
 */

export * from './api/types'
export { streamChatCallbacks, streamChatFetch, streamOrchestrate, streamOrchestrateReview } from './api/sse'
export {
  listTools,
  fetchAcpAgents,
  fetchAgents,
  updateAgentConfig,
  fetchFileTree,
  fetchFileContent,
  fetchCliList,
  listSessions,
  createSession,
  deleteSessionById,
  updateSessionProjectPath,
  renameSessionById,
  restoreSession,
  browseDirectories,
  listDrives,
  compactSession,
  reviewPlan,
} from './api/endpoints'
