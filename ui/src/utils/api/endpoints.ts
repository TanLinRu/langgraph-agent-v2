/**
 * REST API 端点函数
 *
 * 所有对后端的 HTTP 请求封装为纯函数,返回 Promise。
 * 不涉及 SSE 流式通信 (归属 sse.ts)。
 */

import type { AgentInfo, ACPAgentInfo, CliInfo, MetricsData, BrowseNode, SessionInfo, TaskUpdate } from './types'

const API_BASE = import.meta.env.VITE_API_BASE || ''

/** 获取工具列表 /api/tools */
export async function listTools(): Promise<Array<{ name: string; description: string; type: string; icon: string; usage: number; lastUsed: string | null }>> {
  const res = await fetch(`${API_BASE}/api/tools`)
  const data = await res.json()
  return data.tools
}

/** 获取 ACP 智能体列表 /api/acp/agents */
export async function fetchAcpAgents(): Promise<ACPAgentInfo[]> {
  const res = await fetch(`${API_BASE}/api/acp/agents`)
  const data = await res.json()
  return data.agents
}

/** 获取智能体列表 /api/agents */
export async function fetchAgents(): Promise<AgentInfo[]> {
  const res = await fetch(`${API_BASE}/api/agents`)
  const data = await res.json()
  return data.agents
}

/** 更新智能体配置 /api/agents/:id */
export async function updateAgentConfig(agentId: string, config: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${API_BASE}/api/agents/${agentId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error(`Update agent config failed: ${res.status}`)
}

/** 获取文件树 /api/files/tree */
export async function fetchFileTree(root?: string): Promise<Record<string, string[]>> {
  const params = root ? `?root=${encodeURIComponent(root)}` : ''
  const res = await fetch(`${API_BASE}/api/files/tree${params}`)
  const data = await res.json()
  return data.tree
}

/** 获取文件内容 /api/files/content */
export async function fetchFileContent(path: string): Promise<{ path: string; language: string; lines: Array<{ num: number; text: string; hl: string }> }> {
  const res = await fetch(`${API_BASE}/api/files/content?path=${encodeURIComponent(path)}`)
  if (!res.ok) throw new Error(`Fetch file content failed: ${res.status}`)
  return res.json()
}

/** 获取 CLI 工具列表 /api/clis */
export async function fetchCliList(): Promise<CliInfo[]> {
  const res = await fetch(`${API_BASE}/api/clis`)
  const data = await res.json()
  return data.clis
}

/** 获取会话列表 /api/sessions */
export async function listSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${API_BASE}/api/sessions`)
  const data = await res.json()
  return data.sessions
}

/** 创建会话 /api/sessions (POST) */
export async function createSession(title?: string, projectPath?: string): Promise<{ session_id: string; title: string; project_path: string }> {
  const res = await fetch(`${API_BASE}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title || null, project_path: projectPath || null }),
  })
  if (!res.ok) throw new Error(`Create session failed: ${res.status}`)
  return res.json()
}

/** 删除会话 /api/sessions/:id (DELETE) */
export async function deleteSessionById(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete session failed: ${res.status}`)
}

/** 更新会话项目路径 /api/sessions/:id/project-path (PATCH) */
export async function updateSessionProjectPath(sessionId: string, projectPath: string): Promise<{ session_id: string; project_path: string }> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/project-path`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_path: projectPath }),
  })
  if (!res.ok) throw new Error(`Update project path failed: ${res.status}`)
  return res.json()
}

/** 重命名会话 /api/sessions/:id/title (PATCH) */
export async function renameSessionById(sessionId: string, title: string): Promise<{ session_id: string; title: string }> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/title`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) throw new Error(`Rename session failed: ${res.status}`)
  return res.json()
}

/** 恢复会话 /api/sessions/:id (GET) */
export async function restoreSession(sessionId: string): Promise<{
  session_id: string
  messages: Array<{ type: string; content: string; thinking?: string; tool_calls?: Array<{ name: string; args: Record<string, unknown> }>; name?: string; compacted?: boolean }>
  summary: string
  task_updates: TaskUpdate[]
  metrics: MetricsData | null
  audit_summary: string
  project_path: string
}> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`)
  if (!res.ok) throw new Error(`Session not found: ${sessionId}`)
  return res.json()
}

/** 浏览目录 /api/files/browse */
export async function browseDirectories(
  path: string,
  depth = 2,
  includeFiles = false,
): Promise<BrowseNode> {
  const params = new URLSearchParams({ path, depth: String(depth), include_files: String(includeFiles) })
  const res = await fetch(`${API_BASE}/api/files/browse?${params}`)
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json())?.detail || '' } catch { detail = await res.text().catch(() => '') }
    throw new Error(detail || `HTTP ${res.status}`)
  }
  const data = await res.json()
  return data.tree
}

/** 获取驱动器列表 /api/files/drives */
export async function listDrives(): Promise<Array<{ path: string; label: string }>> {
  const res = await fetch(`${API_BASE}/api/files/drives`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  return data.drives
}

/** 提交 plan 审核决策 /api/orchestrate/:session_id/review (POST) */
export async function reviewPlan(
  sessionId: string,
  threadId: string,
  decision: 'approve' | 'revise' | 'reject',
  feedback?: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/orchestrate/${sessionId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, thread_id: threadId, decision, feedback: feedback || '' }),
  })
  if (!res.ok) throw new Error(`Review plan failed: ${res.status}`)
}

/** 压缩会话 /api/compact (POST) */
export async function compactSession(sessionId: string): Promise<{
  session_id: string
  summary: string
  deleted_messages: number
  kept_messages: number
  note?: string
}> {
  const res = await fetch(`${API_BASE}/api/compact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`Compact failed: ${res.status}`)
  return res.json()
}
