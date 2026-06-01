<script setup lang="ts">
import { computed, nextTick, ref, watch, onMounted, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'
import { useSessionsStore } from '../stores/sessions'
import ChatHeader from './ChatHeader.vue'
import ChatMessage from './ChatMessage.vue'
import ThinkingPanel from './ThinkingPanel.vue'
import TaskBoard from './TaskBoard.vue'
import StatusBar from './StatusBar.vue'
import InputBar from './InputBar.vue'
import DirectoryPicker from './DirectoryPicker.vue'
import TopologyBar from './TopologyBar.vue'

const chat = useChatStore()
const sessions = useSessionsStore()
const messagesRef = ref<HTMLElement | null>(null)
const input = ref('')

const projectPathInput = ref('')
const pathSetting = ref(false)
const showPathPicker = ref(false)

const currentSession = computed(() => {
  const id = sessions.activeSessionId
  if (!id) return null
  return sessions.sessions.find(s => s.session_id === id) || null
})

const projectPath = computed(() => currentSession.value?.project_path || '')
const needsProjectPath = computed(() => !!currentSession.value && !currentSession.value.project_path)

async function setProjectPath() {
  const id = sessions.activeSessionId
  const path = projectPathInput.value.trim()
  if (!id) return
  if (!path) {
    chat.messages.push({ role: 'system', content: '⚠ 请先输入项目路径，或在右侧 Files 标签浏览目录后点击 📌' })
    return
  }
  pathSetting.value = true
  await sessions.setProjectPath(id, path)
  pathSetting.value = false
  projectPathInput.value = ''
  chat.messages.push({ role: 'system', content: `✅ 项目路径已设置为: ${path}` })
}

function onPathPicked(path: string) {
  projectPathInput.value = path
  showPathPicker.value = false
  setProjectPath()
}

// Timer for processing elapsed time
const elapsedMs = ref(0)
let timerInterval: ReturnType<typeof setInterval> | null = null

watch(() => chat.isLoading, (loading) => {
  if (loading) {
    elapsedMs.value = 0
    timerInterval = setInterval(() => { elapsedMs.value += 1000 }, 1000)
  } else {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
  }
})
onUnmounted(() => {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null }
})

// Thinking chunks tracking
interface ThinkingChunk { agentName: string; text: string }
const thinkingChunks = ref<ThinkingChunk[]>([])
const thinkingStepCount = ref(0)
const isThinkingActive = ref(false)

// Task items tracking (use store-level taskItems shared with MonitorPanel)
const taskItems = computed(() => chat.taskItems)

// Watch for thinking state changes
watch(() => chat.messages, (msgs) => {
  // Recalculate thinking chunks from messages with thinking content
  const chunks: ThinkingChunk[] = []
  for (const msg of msgs) {
    if (msg.thinking) {
      chunks.push({ agentName: msg.agentName || 'supervisor', text: msg.thinking })
    }
    if (msg.isThinking) {
      isThinkingActive.value = true
    }
  }
  thinkingChunks.value = chunks
  thinkingStepCount.value = chunks.length

  // Check if any message is still thinking
  const anyThinking = msgs.some(m => m.isThinking)
  if (!anyThinking) isThinkingActive.value = false
}, { deep: true })

function isTyping(i: number): boolean {
  const state = chat.typewriterState[i]
  return state ? !state.done : false
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
  if (m > 0) return `${m}:${sec.toString().padStart(2, '0')}`
  return `${sec}s`
}

function robotType(title: string): string {
  const lower = title.toLowerCase()
  if (lower.includes('代码') || lower.includes('code') || lower.includes('重构')) return 'coder'
  if (lower.includes('研究') || lower.includes('research') || lower.includes('搜索')) return 'researcher'
  if (lower.includes('分析') || lower.includes('analys') || lower.includes('数据')) return 'analyst'
  return 'supervisor'
}

function getActiveSessionTitle(): string {
  const id = sessions.activeSessionId
  if (!id) return 'New conversation'
  const s = sessions.sessions.find(s => s.session_id === id)
  return s?.title || 'New conversation'
}

async function send() {
  const msg = input.value.trim()
  if (!msg || chat.isLoading) return
  input.value = ''
  await chat.send(msg)
}

function handleFileClick(path: string) {
  // Will be wired to FileDrawer in Phase 5
  console.log('[ChatTab] file click:', path)
}

// Auto-scroll
watch(() => chat.messages.length, async () => {
  await nextTick()
  messagesRef.value?.scrollTo({ top: messagesRef.value.scrollHeight, behavior: 'smooth' })
})
</script>

<template>
  <div class="chat-tab">
    <ChatHeader
      :sessionTitle="getActiveSessionTitle()"
      :agentType="robotType(getActiveSessionTitle())"
      :isProcessing="chat.isLoading"
      :isThinking="isThinkingActive"
      :elapsedTime="formatElapsed(elapsedMs)"
      :projectPath="projectPath"
    />
    <TopologyBar />
    <!-- Project path prompt -->
    <div v-if="needsProjectPath" class="project-path-prompt">
      <div class="ppp-icon">📁</div>
      <div class="ppp-text">请设置项目路径 (project path) 才能开始会话</div>
      <div class="ppp-row">
        <input v-model="projectPathInput" class="ppp-input" placeholder="输入项目路径，如 D:\project\my-app" @keydown.enter="setProjectPath" />
        <button class="ppp-btn-outline" @click="showPathPicker = true" title="浏览文件夹">📂</button>
        <button class="ppp-btn" :class="{ loading: pathSetting }" :disabled="pathSetting" @click="setProjectPath" title="设置">
          <svg v-if="pathSetting" class="ppp-spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" stroke-linecap="round"><animateTransform attributeName="transform" type="rotate" dur="1s" repeatCount="indefinite" from="0 12 12" to="360 12 12"/></circle></svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
      </div>
    </div>
    <StatusBar :isProcessing="chat.isLoading" />
    <div class="chat-messages" ref="messagesRef">
      <!-- Empty state -->
      <div v-if="chat.messages.length === 0" class="welcome">
        <div class="welcome-icon">✦</div>
        <div class="welcome-title">Agent Workbench</div>
        <div class="welcome-desc">Start a conversation or choose a task from the sidebar</div>
      </div>

      <!-- Messages -->
      <template v-for="(msg, i) in chat.messages" :key="i">
        <!-- Thinking panel — position at the last message with thinking -->
        <ThinkingPanel
          v-if="thinkingChunks.length > 0 && i === chat.messages.reduce((last, m, idx) => (m.isThinking || m.thinking ? idx : last), -1)"
          :chunks="thinkingChunks"
          :isThinking="isThinkingActive"
          :stepCount="thinkingStepCount"
          :elapsedMs="elapsedMs"
        />
        <!-- Task board (shows before summary) -->
        <TaskBoard
          v-if="msg.isSummary && taskItems.length"
          :tasks="taskItems"
        />
        <!-- Regular message -->
        <ChatMessage
          v-if="msg.role !== 'assistant' || msg.content || msg.toolCalls?.length"
          :msg="msg"
          :index="i"
          :isTyping="isTyping(i)"
          @file-click="handleFileClick"
        />
      </template>

      <!-- Loading dots -->
      <div v-if="chat.isLoading && !chat.streamingActive" class="msg-agent-wrap">
        <div class="msg-avatar-col">
          <div class="loading-avatar">🤖</div>
        </div>
        <div class="msg-agent-bubble loading-bubble">
          <div class="loading-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <InputBar v-model="input" :isProcessing="chat.isLoading" :pendingCount="chat.pendingMessages.length" @send="send" @abort="chat.abort()" />
    <DirectoryPicker v-if="showPathPicker" @select="onPathPicked" @close="showPathPicker = false" />
  </div>
</template>

<style scoped>
.chat-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chat-messages {
  flex: 1; overflow-y: auto; padding: 24px 28px;
  display: flex; flex-direction: column; gap: 16px;
  scroll-behavior: smooth;
}

/* Welcome */
.welcome {
  text-align: center; padding: 80px 20px;
}
.welcome-icon {
  font-size: 52px; opacity: 0.08; margin-bottom: 20px;
}
.welcome-title {
  font-size: 22px; font-weight: 600; color: var(--text-muted); margin-bottom: 10px; letter-spacing: -0.01em;
}
.welcome-desc {
  font-size: 15px; color: var(--text-faint); line-height: 1.6;
}

/* Loading state */
.loading-avatar {
  width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
  font-size: 18px;
}
.loading-bubble {
  padding: 16px 20px; border-radius: 14px;
  background: var(--bg-glass); border: 1px solid var(--border);
  border-left: 4px solid var(--accent);
}
.loading-dots {
  display: flex; gap: 5px;
}
.loading-dots span {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--text-muted);
  animation: dotPulse 1.4s ease-in-out infinite;
}
.loading-dots span:nth-child(2) { animation-delay: 0.2s; }
.loading-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes dotPulse {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.15; }
  40% { transform: scale(1); opacity: 1; }
}

/* ── Project path prompt ── */
.project-path-prompt {
  padding: 16px 28px;
  background: var(--bg-glass);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.ppp-icon { font-size: 20px; }
.ppp-text { font-size: 14px; color: var(--text-secondary); flex-shrink: 0; }
.ppp-row { display: flex; gap: 8px; flex: 1; min-width: 240px; }
.ppp-input {
  flex: 1; padding: 8px 12px;
  background: var(--bg-input); border: 1px solid var(--border-input); border-radius: 8px;
  color: var(--text-secondary); font-size: 14px; outline: none;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.ppp-input:focus { border-color: var(--accent-focus); }
.ppp-btn {
  width: 38px; border: none; border-radius: 8px;
  background: var(--accent-bg-strong); color: var(--accent-text);
  font-size: 14px; font-weight: 600; cursor: pointer; padding: 0;
  transition: background 0.2s; display: flex; align-items: center; justify-content: center;
}
.ppp-btn:hover { background: var(--bg-accent-hover); }
.ppp-btn:active { transform: scale(0.96); }
.ppp-spinner { display: block; }
.ppp-btn-outline {
  width: 38px; border: 1px solid var(--border); border-radius: 8px;
  background: transparent; color: var(--accent-text);
  font-size: 16px; cursor: pointer; line-height: 1; padding: 0;
  transition: all 0.2s; display: flex; align-items: center; justify-content: center;
}
.ppp-btn-outline:hover { background: var(--bg-hover); border-color: var(--border-accent); }
.ppp-btn-outline:active { transform: scale(0.96); }
.ppp-hint { font-size: 12px; color: var(--text-muted); align-self: center; white-space: nowrap; }
.ppp-hint strong { color: var(--accent-text); }

</style>
