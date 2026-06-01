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

export interface FileInfo {
  path: string
  language: string
  lines: Array<{ num: number; text: string; hl: string }>
}

export interface MetricsData {
  elapsed_ms: number
  agent_calls: number
  tokens: Record<string, { input: number; output: number; ms: number }>
}

export interface TaskUpdate {
  agent: string
  task: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  state?: 'idle' | 'thinking' | 'working' | 'done' | 'failed'
  startedAt?: number
  endedAt?: number
  elapsedMs?: number
}

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

const API_BASE = import.meta.env.VITE_API_BASE || ''

/**
 * Stream chat via fetch + ReadableStream (POST) — supports longer messages and better SSE control.
 * Each event fires the callback immediately, letting Vue update the DOM in real-time.
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

export async function listTools(): Promise<Array<{ name: string; description: string; type: string; icon: string; usage: number; lastUsed: string | null }>> {
  const res = await fetch(`${API_BASE}/api/tools`)
  const data = await res.json()
  return data.tools
}

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

export async function fetchAcpAgents(): Promise<ACPAgentInfo[]> {
  const res = await fetch(`${API_BASE}/api/acp/agents`)
  const data = await res.json()
  return data.agents
}

export async function fetchAgents(): Promise<AgentInfo[]> {
  const res = await fetch(`${API_BASE}/api/agents`)
  const data = await res.json()
  return data.agents
}

export async function updateAgentConfig(agentId: string, config: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${API_BASE}/api/agents/${agentId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error(`Update agent config failed: ${res.status}`)
}

export async function fetchFileTree(root?: string): Promise<Record<string, string[]>> {
  const params = root ? `?root=${encodeURIComponent(root)}` : ''
  const res = await fetch(`${API_BASE}/api/files/tree${params}`)
  const data = await res.json()
  return data.tree
}

export async function fetchFileContent(path: string): Promise<FileInfo> {
  const res = await fetch(`${API_BASE}/api/files/content?path=${encodeURIComponent(path)}`)
  if (!res.ok) throw new Error(`Fetch file content failed: ${res.status}`)
  return res.json()
}

export async function fetchCliList(): Promise<CliInfo[]> {
  const res = await fetch(`${API_BASE}/api/clis`)
  const data = await res.json()
  return data.clis
}

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

export async function listSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${API_BASE}/api/sessions`)
  const data = await res.json()
  return data.sessions
}

export async function createSession(title?: string, projectPath?: string): Promise<{ session_id: string; title: string; project_path: string }> {
  const res = await fetch(`${API_BASE}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title || null, project_path: projectPath || null }),
  })
  if (!res.ok) throw new Error(`Create session failed: ${res.status}`)
  return res.json()
}

export async function deleteSessionById(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete session failed: ${res.status}`)
}

export async function updateSessionProjectPath(sessionId: string, projectPath: string): Promise<{ session_id: string; project_path: string }> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/project-path`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_path: projectPath }),
  })
  if (!res.ok) throw new Error(`Update project path failed: ${res.status}`)
  return res.json()
}

export async function renameSessionById(sessionId: string, title: string): Promise<{ session_id: string; title: string }> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/title`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) throw new Error(`Rename session failed: ${res.status}`)
  return res.json()
}

export async function restoreSession(sessionId: string): Promise<{
  session_id: string
  messages: Array<{ type: string; content: string; thinking?: string; tool_calls?: Array<{ name: string; args: Record<string, unknown> }>; name?: string; compacted?: boolean }>
  summary: string
}> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`)
  if (!res.ok) throw new Error(`Session not found: ${sessionId}`)
  return res.json()
}

export interface BrowseNode {
  path: string
  name: string
  type: 'dir' | 'file'
  size?: number
  children?: BrowseNode[]
}

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

export async function listDrives(): Promise<Array<{ path: string; label: string }>> {
  const res = await fetch(`${API_BASE}/api/files/drives`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  return data.drives
}

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
