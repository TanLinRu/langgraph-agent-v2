/**
 * API 类型定义
 *
 * 集中管理所有与后端通信的数据类型、枚举和接口定义,
 * 避免类型在多个文件间重复定义。
 */

/** 智能体状态枚举 */
export type AgentStatus =
  | 'idle'
  | 'receiving'
  | 'deciding'
  | 'thinking'
  | 'delegating'
  | 'aggregating'
  | 'waiting'
  | 'working'
  | 'done'
  | 'failed'

/** 任务阶段状态枚举 */
export type TaskState = 'idle' | 'thinking' | 'working' | 'delegating' | 'aggregating' | 'done' | 'failed'

/** 事件日志类型枚举 */
export type LogEntryType = 'start' | 'thinking' | 'tool_call' | 'result' | 'summary' | 'handoff' | 'decision' | 'error' | 'phase'

/** 事件日志条目 */
export interface LogEntry {
  type: LogEntryType
  content: string
  timestamp: number
  agent?: string
}

/** 任务阶段进度更新 */
export interface TaskPhaseUpdate {
  step: number
  totalSteps: number
  description: string
}

/** 任务派发事件 (from→to) */
export interface TaskDispatchEvent {
  from: string
  to: string
  fromLabel?: string
  toLabel?: string
}

/** 聊天消息结构 (前后端统一格式) */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  toolCalls?: Array<{ name: string; args: Record<string, unknown>; status?: 'pending' | 'running' | 'done' | 'failed' }>
  toolResults?: Array<{ content: string; success?: boolean }>
  agentName?: string
  thinking?: string
  thinkingDone?: boolean
  isThinking?: boolean
  isSummary?: boolean
  summary?: string
  isPlan?: boolean
  compacted?: boolean
  fileRefs?: string[]
  isStreaming?: boolean
  agentStatus?: AgentStatus | string
  handoffFrom?: string
  handoffTo?: string
  isError?: boolean
}

/** 智能体信息 (来自 /api/agents) */
export interface AgentInfo {
  id: string
  name: string
  type: string
  status: string
  desc: string
  tools?: string[]
  system_prompt?: string
  model?: string | null
  temperature?: number | null
  max_tokens?: number | null
  enabled?: boolean
}

/** 文件信息 (代码查看器) */
export interface FileInfo {
  path: string
  language: string
  lines: Array<{ num: number; text: string; hl: string }>
}

/** 指标数据 (每次 AI 调用) */
export interface MetricsData {
  elapsed_ms: number
  agent_calls: number
  tokens: Record<string, { input: number; output: number; ms: number }>
}

/** 任务更新 (用于侧边栏任务列表) */
export interface TaskUpdate {
  agent: string
  task: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  state?: TaskState
  startedAt?: number
  endedAt?: number
  elapsedMs?: number
}

/** CLI/ACP 工具信息 */
export interface CliInfo {
  id: string
  name: string
  command: string
  args: string[]
  timeout: number
  desc: string
  enabled: boolean
  mode?: string  // "cli" | "acp"
}

/** ACP 智能体信息 */
export interface ACPAgentInfo {
  id: string
  name: string
  desc: string
  acp_cli_id: string
  command: string
  cwd: string
  enabled: boolean
  available: boolean
}

/** 会话信息 */
export interface SessionInfo {
  session_id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
  summary: string
  compacted_at: string | null
  status: string
  duration_ms: number
  project_path: string
}

/** 权限请求 (来自 ACP agent) */
export interface PermissionRequest {
  req_id: string
  session_id?: string
  toolCall: { name: string; args: Record<string, unknown> }
  options: Array<{ id: string; label: string; description?: string }>
  agent_id?: string
}

/** 文件浏览器节点 */
export interface BrowseNode {
  path: string
  name: string
  type: 'dir' | 'file'
  size?: number
  children?: BrowseNode[]
}
