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
  total_tokens?: number
  total_elapsed_ms?: number
  session_start_time?: number
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

interface NodeConfig {
  id: string
  type: 'agent' | 'approval' | 'finish' | 'start'
  label: string
  agent_type?: string
  agent_id?: string
  description?: string
}

interface EdgeConfig {
  source: string
  target: string
  condition?: string
}

/** 工作流信息 */
export interface WorkflowInfo {
  id: string
  name: string
  description?: string
  enabled: boolean
  nodes_count: number
  nodes?: NodeConfig[]
  edges?: EdgeConfig[]
  start_node?: string
}

/** 工作流插入/更新请求 */
export interface WorkflowUpsertRequest {
  name: string
  description?: string
  nodes?: NodeConfig[]
  edges?: EdgeConfig[]
  start_node?: string
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

/** SSE 事件类型枚举 */
export type SSEEventType =
  | 'thinking_start'
  | 'thinking'
  | 'thinking_done'
  | 'tool_call'
  | 'tool_call_update'
  | 'message'
  | 'summary'
  | 'error'
  | 'done'
  | 'plan'
  | 'task_update'
  | 'audit_summary'
  | 'permission_request'
  | 'metrics'
  | 'interrupt'
  | 'workflow_interrupted'
  | 'agent_thought_chunk'
  | 'available_commands_update'

/** SSE 事件结构 */
export interface SSEEvent {
  type: SSEEventType
  data?: unknown
  session_id?: string
  agent_name?: string
  file_refs?: string[]
  steps?: Array<{ agent: string; task: string }>
}

// ── Eval ──────────────────────────────────────────────────────────────

export interface EvalExpectation {
  must_call_tools: string[]
  must_not_call_tools: string[]
  language: string | null
  min_output_length: number
  max_output_length: number
  must_contain: string[]
  must_not_contain: string[]
  plan_steps: number | null
  plan_agents: string[]
  forbid_hallucinated_refs: boolean
  custom: Record<string, unknown>[]
}

export interface EvalCase {
  case_id: string
  task: string
  tags: string[]
  expected: EvalExpectation
  source_type: string
  source_session_id: string | null
  updated_at: string
}

export interface EvalResultItem {
  assertion: string
  passed: boolean
  detail: string
}

export interface EvalRun {
  task_id: string
  case_id: string
  session_id: string | null
  thread_id: string | null
  passed: boolean
  failures: EvalResultItem[]
  metrics_snapshot: Record<string, unknown>
  config_snapshot: Record<string, unknown>
  triggered_by: string
  created_at: string
}

export interface EvalSuggestion {
  id: number
  dimension: string
  target: string
  current_value: string
  suggested_value: string
  reasoning: string
  evidence: Record<string, unknown>[]
  confidence: number
  applied: boolean
  applied_at: string
  dismissed: boolean
  created_at: string
}
