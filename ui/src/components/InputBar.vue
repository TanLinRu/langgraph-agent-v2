<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { fetchAgents, fetchAcpAgents, type AgentInfo, type ACPAgentInfo } from '../utils/api'

const input = defineModel<string>({ default: '' })
defineProps<{
  isProcessing: boolean
  pendingCount?: number
}>()
const emit = defineEmits<{
  send: []
  abort: []
}>()

// Command history (↑/↓ arrows)
const _history: string[] = []
let _historyIdx = -1
let _savedInput = ''

function onHistoryUp() {
  if (_history.length === 0) return
  if (_historyIdx === -1) _savedInput = input.value
  _historyIdx = Math.min(_historyIdx + 1, _history.length - 1)
  input.value = _history[_history.length - 1 - _historyIdx]
}

function onHistoryDown() {
  if (_historyIdx <= 0) {
    _historyIdx = -1
    input.value = _savedInput
    _savedInput = ''
    return
  }
  _historyIdx--
  input.value = _history[_history.length - 1 - _historyIdx]
}

function pushHistory(text: string) {
  if (!text.trim()) return
  if (_history.length > 0 && _history[_history.length - 1] === text) return
  _history.push(text)
  _historyIdx = -1
  _savedInput = ''
}

// Commands
const COMMANDS = [
  { cmd: '/compact', desc: 'Compress session context' },
  { cmd: '/clear', desc: 'Clear all messages' },
  { cmd: '/new', desc: 'Start a new session' },
]

// Agents for @ mention
const agents = ref<AgentInfo[]>([])
const acpAgents = ref<ACPAgentInfo[]>([])
const showDropdown = ref(false)
const dropdownFilter = ref('')
const filteredItems = ref<Array<{ label: string; desc: string; type: 'command' | 'agent'; badge?: string }>>([])

onMounted(async () => {
  try {
    agents.value = await fetchAgents()
  } catch (e) {
    console.warn('[InputBar] fetchAgents failed:', e)
  }
  try {
    acpAgents.value = await fetchAcpAgents()
  } catch (e) {
    console.warn('[InputBar] fetchAcpAgents failed:', e)
  }
})

function onInput(e: Event) {
  const val = (e.target as HTMLInputElement).value
  const cursorPos = (e.target as HTMLInputElement).selectionStart || val.length

  // Check for @ mention
  const atIndex = val.lastIndexOf('@', cursorPos - 1)
  if (atIndex >= 0 && (atIndex === 0 || val[atIndex - 1] === ' ')) {
    const filter = val.slice(atIndex + 1, cursorPos).toLowerCase()
    dropdownFilter.value = filter
    const matchedAgents = agents.value
      .filter(a => (a.name.toLowerCase().includes(filter) || a.id.toLowerCase().includes(filter)) && a.enabled !== false)
      .map(a => ({ label: `@${a.id}`, desc: a.desc, type: 'agent' as const, badge: undefined }))
    const matchedAcp = acpAgents.value
      .filter(a => (a.name.toLowerCase().includes(filter) || a.id.toLowerCase().includes(filter)) && a.enabled !== false)
      .map(a => ({ label: `@${a.id}`, desc: a.desc, type: 'agent' as const, badge: a.available ? 'ACP' : 'ACP (offline)' }))
    const seen = new Set<string>()
    filteredItems.value = [...matchedAgents, ...matchedAcp].filter(item => {
      if (seen.has(item.label)) return false
      seen.add(item.label)
      return true
    })
    showDropdown.value = filteredItems.value.length > 0
    return
  }

  // Check for / command
  if (val.startsWith('/') && !val.includes(' ')) {
    dropdownFilter.value = val.toLowerCase()
    filteredItems.value = COMMANDS
      .filter(c => c.cmd.startsWith(dropdownFilter.value))
      .map(c => ({ label: c.cmd, desc: c.desc, type: 'command' as const }))
    showDropdown.value = filteredItems.value.length > 0
  } else {
    showDropdown.value = false
  }
}

function selectItem(item: { label: string; type: 'command' | 'agent' }) {
  if (item.type === 'command') {
    input.value = item.label + ' '
  } else {
    // Replace the @mention in the input
    const val = input.value
    const atIndex = val.lastIndexOf('@')
    if (atIndex >= 0) {
      input.value = val.slice(0, atIndex) + item.label + ' '
    } else {
      input.value = item.label + ' '
    }
  }
  showDropdown.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    showDropdown.value = false
    return
  }
  if (e.key === 'Tab' && showDropdown.value && filteredItems.value.length) {
    e.preventDefault()
    selectItem(filteredItems.value[0])
    return
  }
  if (e.key === 'ArrowUp' && !showDropdown.value) {
    e.preventDefault()
    onHistoryUp()
    return
  }
  if (e.key === 'ArrowDown' && !showDropdown.value) {
    e.preventDefault()
    onHistoryDown()
    return
  }
}

function handleSubmit() {
  if (input.value.trim()) {
    pushHistory(input.value)
    emit('send')
  }
}
</script>

<template>
  <div class="input-area">
    <div class="command-dropdown" v-if="showDropdown">
      <div v-for="item in filteredItems" :key="item.label" class="command-item" @mousedown.prevent="selectItem(item)">
        <span :class="['command-cmd', item.type]">{{ item.label }}</span>
        <span class="command-desc">{{ item.desc }}</span>
        <span v-if="item.badge" :class="['acp-badge', { offline: item.badge.includes('offline') }]">{{ item.badge }}</span>
      </div>
    </div>
    <form :class="['input-bar', { queued: isProcessing }]" @submit.prevent="handleSubmit">
      <input
        v-model="input"
        :placeholder="isProcessing ? (pendingCount ? `已排队 ${pendingCount} 条消息...` : 'Agent 处理中...') : '输入消息... @ 提及 Agent'"
        @input="onInput"
        @keydown="onKeydown"
        @blur="showDropdown = false"
      />
      <!-- Queue indicator + Abort button during processing -->
      <span v-if="isProcessing" class="queue-indicator" :title="pendingCount ? `已排队 ${pendingCount} 条消息` : 'Agent 处理中...'">
        <svg class="queue-spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" stroke-linecap="round"/>
        </svg>
        <span v-if="pendingCount" class="queue-count">{{ pendingCount }}</span>
      </span>
      <button v-if="isProcessing" type="button" class="abort-btn" @click="emit('abort')" title="中断任务">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
      </button>
      <!-- Send button when idle -->
      <button v-else type="submit" :disabled="!input.trim()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
        </svg>
      </button>
    </form>
  </div>
</template>

<style scoped>
.input-area {
  flex-shrink: 0;
  position: relative;
}
.command-dropdown {
  margin: 0 24px;
  background: var(--bg-surface);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}
.acp-badge {
  font-size: 9px; font-weight: 600; padding: 1px 5px; border-radius: 4px;
  background: var(--accent-bg); color: var(--accent-text);
  margin-left: auto; flex-shrink: 0; letter-spacing: 0.5px;
  text-transform: uppercase;
}
.acp-badge.offline { background: var(--bg-hover); color: var(--text-muted); }
.command-item {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px; cursor: pointer; transition: background 0.15s;
}
.command-item:hover { background: var(--accent-bg); }
.command-cmd {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 13px; color: var(--accent); font-weight: 500;
}
.command-cmd.agent { color: var(--color-green); }
.command-desc { font-size: 12px; color: var(--text-muted); }

.input-bar {
  padding: 16px 24px; display: flex; gap: 12px;
  background: var(--bg-surface); backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--border);
  position: relative; align-items: center;
}
.input-bar.queued input { opacity: 0.7; }

.input-bar input {
  flex: 1; padding: 13px 18px;
  background: var(--bg-hover); border: 1px solid var(--border-input); border-radius: 12px;
  color: var(--text-primary); font-size: 16px; outline: none;
  transition: border-color 0.2s, background 0.2s;
}
.input-bar input::placeholder { color: var(--text-muted); }
.input-bar input:focus { border-color: var(--accent-focus); background: var(--bg-glass-hover); }

.input-bar button {
  width: 50px; height: 50px;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-accent-strong); border: 1px solid var(--border-accent); border-radius: 12px;
  color: var(--accent-text); cursor: pointer; transition: all 0.2s; flex-shrink: 0;
}
.input-bar button:hover:not(:disabled) { background: var(--bg-accent-hover); }
.input-bar button:active:not(:disabled) { transform: scale(0.95); }
.input-bar button:disabled { opacity: 0.3; cursor: not-allowed; }
.abort-btn {
  width: 50px; height: 50px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3); border-radius: 12px;
  color: var(--color-red); cursor: pointer; transition: all 0.2s; flex-shrink: 0;
}
.abort-btn:hover { background: rgba(239,68,68,0.25); }

/* Queue spinner indicator */
.queue-indicator {
  display: flex; align-items: center; gap: 4px;
  color: var(--accent-text); flex-shrink: 0;
}
.queue-spinner {
  animation: spin 1s linear infinite;
  opacity: 0.8;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.queue-count {
  font-size: 12px; font-weight: 600; min-width: 14px; text-align: center;
}
</style>
