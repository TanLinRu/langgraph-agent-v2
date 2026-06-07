<script setup lang="ts">
import { inject, ref, onMounted, onUnmounted } from 'vue'
import { useSessionsStore } from '../stores/sessions'
import { useThemeStore } from '../stores/theme'
import ConvAvatar from './ConvAvatar.vue'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ toggle: [] }>()

const sessions = useSessionsStore()
const theme = useThemeStore()
import { buildEvalCaseFromSession } from '../utils/api'
const evalRunning = ref<string | null>(null)
const openCreateModal = inject<() => void>('openCreateModal', () => {})

const renamingId = ref<string | null>(null)
const renameValue = ref('')
const renameInput = ref<HTMLInputElement | null>(null)

// Live duration counter for active session
const now = ref(Date.now())
let liveTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  liveTimer = setInterval(() => { now.value = Date.now() }, 1000)
  sessions.fetchSessions()
})
onUnmounted(() => {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null }
})

function startRename(sessionId: string, currentTitle: string) {
  renamingId.value = sessionId
  renameValue.value = currentTitle || '新会话'
  // Wait for DOM update then focus + select
  setTimeout(() => {
    renameInput.value?.focus()
    renameInput.value?.select()
  }, 10)
}

function finishRename(sessionId: string) {
  const title = renameValue.value.trim()
  if (title && title !== '新会话') {
    sessions.renameSession(sessionId, title)
  }
  renamingId.value = null
}

function cancelRename() {
  renamingId.value = null
}

function handleRenameKeydown(e: KeyboardEvent, sessionId: string) {
  if (e.key === 'Enter') {
    finishRename(sessionId)
  } else if (e.key === 'Escape') {
    cancelRename()
  }
}

function robotType(title: string): string {
  if (!title) return 'supervisor'
  const lower = title.toLowerCase()
  if (lower.includes('代码') || lower.includes('code') || lower.includes('重构')) return 'coder'
  if (lower.includes('研究') || lower.includes('research') || lower.includes('搜索')) return 'researcher'
  if (lower.includes('分析') || lower.includes('analys') || lower.includes('数据')) return 'analyst'
  return 'supervisor'
}

function formatTime(dateStr: string): string {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const pad = (n: number) => n.toString().padStart(2, '0')
  const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
  if (sameDay) return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
  if (m > 0) return `${m}:${sec.toString().padStart(2, '0')}`
  return `${sec}s`
}

function formatElapsed(updatedAt: string, nowRef: number): string {
  const start = new Date(updatedAt).getTime()
  const elapsed = Math.max(0, nowRef - start)
  return formatDuration(elapsed)
}

function handleNewSession() {
  openCreateModal()
}

async function handleEvalSession(sessionId: string, e: Event) {
  e.stopPropagation()
  if (evalRunning.value === sessionId) return
  evalRunning.value = sessionId
  try {
    await buildEvalCaseFromSession(sessionId)
  } catch (err: any) {
    console.warn('eval session error', err)
  }
  evalRunning.value = null
}

function handleDelete(sessionId: string, e: Event) {
  e.stopPropagation()
  sessions.deleteSessionById(sessionId)
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: !open }">
    <!-- Header -->
    <div class="sidebar-header">
      <div>
        <div class="sidebar-title">Agent Workbench</div>
        <div class="sidebar-sub">{{ sessions.filteredSessions.length }} sessions</div>
      </div>
      <div class="sidebar-header-actions">
        <button class="collapse-btn" @click="emit('toggle')" :title="open ? 'Collapse sidebar' : 'Expand sidebar'">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
               :style="{ transform: open ? 'rotate(0deg)' : 'rotate(180deg)' }">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
        </button>
        <button class="theme-toggle" @click="theme.toggleTheme()" :title="theme.theme === 'dark' ? 'Switch to light' : 'Switch to dark'">
        <svg v-if="theme.theme === 'dark'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
        </svg>
        <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      </button>
    </div>
    </div>

    <!-- Search + New -->
    <div class="search-row">
      <div class="search-wrap">
        <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input class="conv-search" v-model="sessions.search" placeholder="Search conversations..." />
      </div>
      <button class="new-conv-btn" @click="handleNewSession" title="New conversation">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
      </button>
    </div>

    <!-- Filter tabs -->
    <div class="conv-filter">
      <button :class="['conv-filter-btn', { active: sessions.statusFilter === 'all' }]" @click="sessions.statusFilter = 'all'">全部</button>
      <button :class="['conv-filter-btn', { active: sessions.statusFilter === 'active' }]" @click="sessions.statusFilter = 'active'">进行中</button>
      <button :class="['conv-filter-btn', { active: sessions.statusFilter === 'completed' }]" @click="sessions.statusFilter = 'completed'">已完成</button>
    </div>

    <!-- Conversation list -->
    <div class="conv-list">
      <div
        v-for="session in sessions.filteredSessions"
        :key="session.session_id"
        :class="['conv-item-wrap']"
      >
        <div
          :class="['conv-item', { active: sessions.activeSessionId === session.session_id, processing: session.status === 'processing' }]"
          @click="sessions.switchSession(session.session_id)"
        >
          <div class="conv-avatar-wrap">
            <ConvAvatar :type="robotType(session.title)" :size="46" />
            <div :class="['conv-avatar-indicator', session.status]">
              <template v-if="session.status === 'completed'">✓</template>
            </div>
          </div>
          <div class="conv-info">
            <div class="conv-name">
              <template v-if="renamingId === session.session_id">
                <input
                  ref="renameInput"
                  v-model="renameValue"
                  class="conv-rename-input"
                  @blur="finishRename(session.session_id)"
                  @keydown="handleRenameKeydown($event, session.session_id)"
                  @click.stop
                />
              </template>
              <template v-else>
                <span class="conv-name-text" @dblclick="startRename(session.session_id, session.title)">{{ session.title || '新会话' }}</span>
              </template>
              <span v-if="session.status === 'processing'" class="conv-name-badge processing">
                <span class="thinking-dots-inline"><span></span><span></span><span></span></span>
                思考中
              </span>
              <span v-else-if="session.status === 'active'" class="conv-name-badge active">活跃</span>
              <span v-else class="conv-name-badge completed">已完成</span>
            </div>
            <div class="conv-preview">
              <template v-if="session.status === 'processing'">
                <span class="conv-thinking-row">
                  <span class="conv-thinking-agent"><ConvAvatar :type="robotType(session.title)" :size="18" /></span>
                  <span class="thinking-dots-inline"><span></span><span></span><span></span></span>
                  <span class="conv-thinking-label">思考中...</span>
                </span>
              </template>
              <template v-else>{{ session.summary || '暂无预览' }}</template>
            </div>
          </div>
          <div class="conv-time-col">
            <span class="conv-time">{{ formatTime(session.updated_at) }}</span>
            <span v-if="session.status === 'processing'" class="conv-duration live">{{ formatElapsed(session.updated_at, now) }}</span>
            <span v-else-if="session.status === 'completed'" class="conv-duration">{{ formatDuration(session.duration_ms) }}</span>
            <div v-if="session.status === 'completed' && sessions.activeSessionId !== session.session_id" class="conv-unread"></div>
          </div>
          <button class="conv-hover-eval" @click="handleEvalSession(session.session_id, $event)" :disabled="evalRunning === session.session_id" title="Build eval case from this session">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
        </button>
          <button class="conv-hover-delete" @click="handleDelete(session.session_id, $event)" title="删除">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
        </button>
        </div>
        </div>

      <!-- Empty state -->
      <div v-if="sessions.filteredSessions.length === 0 && !sessions.isLoading" class="conv-empty">
        <p v-if="sessions.search">无匹配会话</p>
        <p v-else>暂无会话</p>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 310px;
  min-width: 310px;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: width 0.3s cubic-bezier(0.16,1,0.3,1),
              min-width 0.3s cubic-bezier(0.16,1,0.3,1),
              opacity 0.3s ease;
  animation: slideIn 0.5s cubic-bezier(0.16,1,0.3,1) both;
  box-shadow: 4px 0 20px rgba(0,0,0,0.05);
}
.sidebar.collapsed {
  width: 0 !important; min-width: 0 !important;
  opacity: 0; overflow: hidden; padding: 0;
  border-right: none;
  pointer-events: none;
}
@keyframes slideIn {
  from { opacity: 0; transform: translateX(-24px); }
  to { opacity: 1; transform: translateX(0); }
}

.sidebar-header {
  padding: 24px 22px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: relative;
}
.sidebar-header::after {
  content: '';
  position: absolute;
  bottom: 0; left: 20px; right: 20px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border-accent), transparent);
}
.sidebar-header-actions {
  display: flex; align-items: center; gap: 4px;
}
.collapse-btn {
  background: none; border: none; color: var(--text-muted);
  cursor: pointer; padding: 4px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.2s;
}
.collapse-btn:hover {
  background: var(--bg-hover); color: var(--text-secondary);
}
.collapse-btn svg {
  transition: transform 0.3s cubic-bezier(0.16,1,0.3,1);
}
.sidebar-title {
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.01em;
  background: linear-gradient(135deg, #e0e7ff, #818cf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  position: relative;
}
.sidebar-title::after {
  content: '';
  position: absolute;
  bottom: -2px; left: 0;
  width: 30%;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 1px;
}
[data-theme="light"] .sidebar-title {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sidebar-sub {
  font-size: 14px;
  color: var(--text-tertiary);
  margin-top: 8px;
  letter-spacing: 0.02em;
}

/* Theme toggle in sidebar */
.theme-toggle {
  width: 32px; height: 32px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-hover); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text-tertiary); cursor: pointer; transition: all 0.2s;
  font-size: 15px; margin-right: -4px;
}
.theme-toggle:hover { background: var(--bg-glass-hover); color: var(--text-secondary); }
.theme-toggle:active { transform: scale(0.88); }

/* Search row */
.search-row {
  display: flex; gap: 8px; margin: 10px 16px; align-items: center;
}
.search-wrap {
  flex: 1; position: relative; display: flex; align-items: center;
}
.search-icon {
  position: absolute; left: 13px; top: 50%; transform: translateY(-50%);
  width: 20px; height: 20px; color: var(--text-tertiary); pointer-events: none;
  flex-shrink: 0;
}
.conv-search {
  width: 100%; padding: 11px 15px 11px 36px;
  background: var(--bg-input);
  border: 1px solid var(--border-input); border-radius: 10px;
  color: var(--text-secondary); font-size: 15px; outline: none;
  transition: border-color 0.2s, background 0.2s;
}
.conv-search::placeholder { color: var(--text-muted); }
.conv-search:focus { border-color: var(--accent-focus); background: var(--bg-glass-hover); }

.new-conv-btn {
  width: 36px; height: 36px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--accent-bg); border: 1px solid var(--border-accent); border-radius: 9px;
  color: var(--accent-text); cursor: pointer; transition: all 0.2s;
}
.new-conv-btn:hover { background: var(--accent-bg-strong); }
.new-conv-btn:active { transform: scale(0.92); }

/* Filter tabs */
.conv-filter {
  display: flex; gap: 4px; margin: 0 16px 8px; padding: 3px;
  background: var(--bg-glass); border-radius: 8px;
}
.conv-filter-btn {
  flex: 1; padding: 7px 0; border: none; border-radius: 6px;
  background: transparent; color: var(--text-tertiary); font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all 0.2s; letter-spacing: 0.3px;
}
.conv-filter-btn:hover { color: var(--text-secondary); }
.conv-filter-btn.active { background: var(--accent-bg); color: var(--accent-text); }

/* Conversation list */
.conv-list { flex: 1; overflow-y: auto; padding: 0 6px; }
.conv-item-wrap {
  position: relative; overflow: hidden; margin: 4px 6px; border-radius: 12px;
}
.conv-item {
  position: relative; z-index: 2;
  display: flex; align-items: center; gap: 14px;
  padding: 14px 16px; cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  border-left: 3px solid transparent;
  border-radius: 12px; 
  background: var(--bg-glass);
  border: 1px solid transparent;
}
.conv-item:hover {
  background: var(--bg-card);
  border-color: var(--border);
  transform: translateX(4px) translateY(-1px);
  padding-left: 20px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.08);
}
.conv-item.active {
  background: var(--bg-active);
  border-left-color: var(--accent);
  border-left-width: 4px;
  border-color: var(--border-accent-soft);
  transform: translateX(2px);
  box-shadow: 0 2px 12px rgba(99,102,241,0.1);
}
.conv-item.processing {
  border-left-color: var(--accent);
  border-color: var(--border-accent);
  animation: processPulse 2s ease-in-out infinite;
}
@keyframes processPulse {
  0%, 100% { border-color: var(--border-accent); box-shadow: 0 2px 12px rgba(99,102,241,0.1); }
  50% { border-color: rgba(129,140,248,0.3); box-shadow: 0 4px 20px rgba(99,102,241,0.15); }
}

.conv-info { flex: 1; min-width: 0; }
.conv-name {
  font-size: 16px; font-weight: 550; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  display: flex; align-items: center; gap: 8px;
}
.conv-name-badge {
  font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; letter-spacing: 0.3px;
  flex-shrink: 0;
}
.conv-name-badge.processing {
  background: rgba(129,140,248,0.12); color: var(--accent-text);
  display: flex; align-items: center; gap: 4px;
}
.conv-name-badge.active { background: rgba(52,211,153,0.1); color: var(--color-green-text); }
.conv-name-badge.completed { background: var(--bg-hover); color: var(--text-secondary); }

.thinking-dots-inline {
  display: inline-flex; gap: 3px; align-items: center;
}
.thinking-dots-inline span {
  width: 5px; height: 5px; border-radius: 50%; background: var(--accent-text);
  animation: dotPulse 1.4s ease-in-out infinite;
}
.thinking-dots-inline span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots-inline span:nth-child(3) { animation-delay: 0.4s; }
@keyframes dotPulse {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.15; }
  40% { transform: scale(1); opacity: 1; }
}

.conv-preview {
  font-size: 14px; font-weight: 450; color: var(--text-tertiary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 3px;
}
.conv-thinking-row { display: inline-flex; align-items: center; gap: 4px; }
.conv-thinking-agent { display: inline-flex; width: 18px; height: 18px; animation: agentThinkIn 0.4s ease both; }
.conv-thinking-agent :deep(svg) { width: 100%; height: 100%; display: block; }
.conv-thinking-label { font-size: 13px; color: var(--accent-text); margin-left: 4px; font-weight: 500; }
@keyframes agentThinkIn { from{opacity:0;transform:translateY(4px) scale(0.5)} to{opacity:1;transform:translateY(0) scale(1)} }

.conv-avatar-wrap { flex-shrink: 0; position: relative; }
.conv-avatar-wrap :deep(.conv-avatar) { width: 100%; height: 100%; display: block; }
.conv-avatar-indicator {
  position: absolute; right: -3px; bottom: -1px; width: 14px; height: 14px;
  border-radius: 50%; border: 2px solid var(--avatar-border);
  display: flex; align-items: center; justify-content: center;
}
.conv-avatar-indicator.completed { background: var(--accent); font-size: 11px; color: var(--bg-app); font-weight: 700; }
.conv-avatar-indicator.processing { background: var(--accent); animation: badgePulse 1.2s ease-in-out infinite; }
@keyframes badgePulse { 0%,100%{opacity:1} 50%{opacity:0.5} }

.conv-time-col {
  display: flex; flex-direction: column; align-items: flex-end; gap: 3px;
  flex-shrink: 0; align-self: flex-start; margin-top: 4px;
}
.conv-time {
  font-size: 13px; color: var(--text-muted);
}
.conv-duration {
  font-size: 11px; color: var(--text-faint);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.conv-unread {
  width: 8px; height: 8px; border-radius: 50%;
  background: #818cf8; box-shadow: 0 0 8px rgba(129,140,248,0.6);
  margin-top: 2px;
}

/* Eval button — hidden, shows on conv-item hover, slides in left of delete */
.conv-hover-eval {
  position: absolute; right: 52px; top: 0; bottom: 0;
  width: 0; overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  background: rgba(52,211,153,0.85); border: none;
  color: #fff; font-size: 13px; cursor: pointer;
  z-index: 3;
  transition: width 0.3s cubic-bezier(0.34,1.56,0.64,1), background 0.2s ease;
}
.conv-item:hover .conv-hover-eval {
  width: 40px;
  animation: evalSlideIn 0.3s cubic-bezier(0.34,1.56,0.64,1) both;
}
.conv-hover-eval:hover {
  background: rgba(16,185,129,1);
  box-shadow: -4px 0 12px rgba(52,211,153,0.3);
}
.conv-hover-eval:active {
  transform: scale(0.95);
}
.conv-hover-eval:disabled {
  opacity: 0.5; cursor: not-allowed;
}
.conv-hover-eval svg { width: 16px; height: 16px; flex-shrink: 0; }
@keyframes evalSlideIn {
  from { width: 0; opacity: 0; }
  to { width: 40px; opacity: 1; }
}
@media (max-width: 768px) {
  .conv-hover-eval { opacity: 0.7; }
}

/* Delete button — hidden, shows on conv-item hover as a slide-in overlay */
.conv-hover-delete {
  position: absolute; right: 0; top: 0; bottom: 0;
  width: 0; overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  background: rgba(220,38,38,0.9); border: none;
  color: #fff; font-size: 13px; cursor: pointer;
  z-index: 3;
  transition: width 0.3s cubic-bezier(0.34,1.56,0.64,1), background 0.2s ease;
}
.conv-item:hover .conv-hover-delete {
  width: 52px;
  animation: deleteSlideIn 0.3s cubic-bezier(0.34,1.56,0.64,1) both;
}
.conv-hover-delete:hover {
  background: rgba(185,28,28,1);
  box-shadow: -4px 0 12px rgba(220,38,38,0.4);
}
.conv-hover-delete:active {
  transform: scale(0.95);
}
.conv-hover-delete svg { width: 16px; height: 16px; flex-shrink: 0; }
@keyframes deleteSlideIn {
  from { width: 0; opacity: 0; }
  to { width: 52px; opacity: 1; }
}
/* Mobile: always visible */
@media (max-width: 768px) {
  .conv-hover-delete { opacity: 0.7; }
}

/* Rename input */
.conv-rename-input {
  all: unset;
  font-size: 16px; font-weight: 550; color: var(--text-primary);
  background: var(--bg-input);
  border: 1px solid var(--accent-focus); border-radius: 4px;
  padding: 2px 6px; width: 100%; box-sizing: border-box;
  outline: none; min-width: 0;
}
.conv-name-text {
  cursor: text;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* Empty state */
.conv-empty {
  text-align: center; padding: 40px 20px;
  color: var(--text-muted); font-size: 14px;
}
</style>
