<script setup lang="ts">
import { computed, nextTick, ref, watch, onMounted, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'
import { useSessionsStore } from '../stores/sessions'
import ChatHeader from './ChatHeader.vue'
import ChatMessage from './ChatMessage.vue'
import TaskBoard from './TaskBoard.vue'
import PlanCard from './PlanCard.vue'
import StatusBar from './StatusBar.vue'
import InputBar from './InputBar.vue'
import DirectoryPicker from './DirectoryPicker.vue'
import TopologyBar from './TopologyBar.vue'
import PermissionDialog from './PermissionDialog.vue'
import PlanReviewDialog from './PlanReviewDialog.vue'

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

// Task items tracking (use store-level taskItems shared with MonitorPanel)
const taskItems = computed(() => chat.taskItems)
const permissionRequest = computed(() => chat.permissionRequest)
const pendingReview = computed(() => chat.pendingReview)

// Derive isThinkingActive from messages
const isThinkingActive = computed(() => chat.messages.some(m => m.isThinking))

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

function quickStart(prompt: string) {
  input.value = prompt
  send()
}

async function send() {
  const msg = input.value.trim()
  if (!msg || chat.isLoading) return
  input.value = ''
  await chat.send(msg)
}

function handleReviewResolve(decision: 'approve' | 'revise' | 'reject', feedback?: string) {
  chat.submitReview(decision, feedback)
}

function parsePlanSteps(content: string): Array<{ agent: string; task: string }> {
  const steps: Array<{ agent: string; task: string }> = []
  try {
    const parsed = JSON.parse(content)
    if (parsed.steps && Array.isArray(parsed.steps)) {
      for (const s of parsed.steps) {
        if (s.agent && s.task) steps.push({ agent: s.agent, task: s.task })
      }
    }
  } catch {
    const stepRegex = /(\d+)[.、]\s*(?:\*\*)?(\w[\w-]*)?\*{0,2}[:：]?\s*(.+?)(?=\n\d+[.、]|\n*$)/g
    let match
    while ((match = stepRegex.exec(content)) !== null) {
      const agent = match[2] || 'direct'
      const task = match[3]?.trim() || ''
      if (task) steps.push({ agent, task })
    }
  }
  return steps.length > 0 ? steps : [{ agent: 'direct', task: content.slice(0, 100) }]
}

function handleFileClick(path: string) {
  console.log('[ChatTab] file click:', path)
}

// Auto-scroll
const isNearBottom = ref(true)
const _scrollThreshold = 100

function checkNearBottom() {
  const el = messagesRef.value
  if (!el) return
  isNearBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < _scrollThreshold
}

function scrollToBottom() {
  const el = messagesRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  isNearBottom.value = true
}

function autoScroll() {
  if (!isNearBottom.value) return
  const el = messagesRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
}

watch(() => chat.messages.length, async () => {
  await nextTick()
  autoScroll()
})

// Also scroll when content of the last message changes (streaming)
watch(() => {
  const last = chat.messages[chat.messages.length - 1]
  return last ? last.content + (last.thinking || '') : ''
}, async () => {
  await nextTick()
  autoScroll()
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
    <div class="chat-messages" ref="messagesRef" @scroll="checkNearBottom">
      <button v-if="!isNearBottom" class="scroll-bottom-btn" @click="scrollToBottom" title="滚动到底部">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <!-- Empty state with quick actions -->
      <div v-if="chat.messages.length === 0" class="welcome">
        <div class="welcome-icon">✦</div>
        <div class="welcome-title">Agent Workbench</div>
        <div class="welcome-desc">选择任务快速开始，或直接输入需求</div>
        <div class="quick-actions">
          <button class="qa-card" @click="quickStart('请分析当前项目的代码结构，给出整体架构说明')">
            <span class="qa-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            </span>
            <span class="qa-title">分析项目</span>
            <span class="qa-desc">了解代码架构与模块关系</span>
          </button>
          <button class="qa-card" @click="quickStart('请编写测试用例覆盖核心功能')">
            <span class="qa-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            </span>
            <span class="qa-title">编写测试</span>
            <span class="qa-desc">自动生成并运行单元测试</span>
          </button>
          <button class="qa-card" @click="quickStart('请查找并修复项目中的 Bug')">
            <span class="qa-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            </span>
            <span class="qa-title">调试修复</span>
            <span class="qa-desc">扫描代码并修复问题</span>
          </button>
          <button class="qa-card" @click="quickStart('请实现一个新功能：')">
            <span class="qa-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            </span>
            <span class="qa-title">新功能</span>
            <span class="qa-desc">快速启动功能开发流程</span>
          </button>
        </div>
      </div>

      <!-- Messages -->
      <template v-for="(msg, i) in chat.messages" :key="i">
        <!-- Task board (shows before summary) -->
        <TaskBoard
          v-if="msg.isSummary && taskItems.length"
          :tasks="taskItems"
        />
        <!-- Inline plan card -->
        <PlanCard
          v-else-if="msg.isPlan && msg.content"
          :steps="parsePlanSteps(msg.content)"
          :reasoning="msg.content"
        />
        <!-- Regular message -->
        <ChatMessage
          v-else-if="msg.role !== 'assistant' || msg.content || msg.toolCalls?.length || msg.thinking || msg.isThinking"
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

    <PermissionDialog v-if="permissionRequest" :request="permissionRequest" />
    <PlanReviewDialog v-if="pendingReview" :review="pendingReview" @resolve="handleReviewResolve" />
    <div class="input-zone">
      <InputBar v-model="input" :isProcessing="chat.isLoading" :streamingActive="chat.streamingActive" :pendingCount="chat.pendingMessages.length" :permissionPending="!!permissionRequest" @send="send" @abort="chat.abort()" />
    </div>
    <DirectoryPicker v-if="showPathPicker" @select="onPathPicked" @close="showPathPicker = false" />
  </div>
</template>

<style scoped>
.chat-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-app);
  position: relative;
}

.chat-messages {
  flex: 1; overflow-y: auto; padding: 24px 28px;
  display: flex; flex-direction: column; gap: 18px;
  scroll-behavior: smooth;
  position: relative;
  background: linear-gradient(180deg, rgba(99,102,241,0.02) 0%, transparent 30%);
}

.scroll-bottom-btn {
  position: sticky; bottom: 20px; left: 50%; transform: translateX(-50%);
  z-index: 100;
  width: 40px; height: 40px; border-radius: 50%;
  background: var(--bg-elevated); border: 1px solid var(--border);
  color: var(--text-secondary); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--shadow-lg);
  transition: all 0.3s cubic-bezier(0.34,1.56,0.64,1);
  animation: fadeIn 0.3s ease;
  margin-top: -50px;
  flex-shrink: 0;
}
.scroll-bottom-btn:hover { 
  background: var(--bg-hover); 
  color: var(--text-primary); 
  transform: translateX(-50%) scale(1.1);
  box-shadow: 0 8px 24px rgba(99,102,241,0.2);
}
.scroll-bottom-btn:active { 
  transform: translateX(-50%) scale(0.92); 
}

/* Welcome */
.welcome {
  text-align: center; padding: 100px 30px;
  animation: welcomeFadeIn 0.8s cubic-bezier(0.34,1.56,0.64,1) both;
}
@keyframes welcomeFadeIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}
.welcome-icon {
  font-size: 64px; 
  opacity: 0.06; 
  margin-bottom: 24px;
  animation: iconFloat 6s ease-in-out infinite;
}
@keyframes iconFloat {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  50% { transform: translateY(-10px) rotate(5deg); }
}
.welcome-title {
  font-size: 24px; 
  font-weight: 650; 
  color: var(--text-muted); 
  margin-bottom: 12px; 
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--text-secondary), var(--text-muted));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.welcome-desc {
  font-size: 15px; 
  color: var(--text-faint); 
  line-height: 1.7;
  max-width: 400px;
  margin: 0 auto 28px;
}

.quick-actions {
  display: flex; flex-wrap: wrap; gap: 12px;
  justify-content: center;
  max-width: 520px; margin: 0 auto;
  animation: quickActionsIn 0.6s cubic-bezier(0.34,1.56,0.64,1) both;
  animation-delay: 0.3s;
}
@keyframes quickActionsIn {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}
.qa-card {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: 16px 18px;
  min-width: 110px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34,1.56,0.64,1);
  font-family: inherit;
}
.qa-card:hover {
  transform: translateY(-4px);
  border-color: var(--border-accent);
  box-shadow: 0 8px 24px rgba(99,102,241,0.15),
              0 0 40px rgba(99,102,241,0.05);
  background: var(--bg-glass-hover);
}
.qa-card:active {
  transform: translateY(-1px) scale(0.97);
}
.qa-icon {
  display: flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; border-radius: 10px;
  color: var(--accent-text);
  background: var(--accent-bg);
  margin-bottom: 6px;
  transition: all 0.3s ease;
}
.qa-card:hover .qa-icon {
  background: var(--accent-bg-hover);
  transform: scale(1.1);
}
.qa-title {
  font-size: 13px; font-weight: 600;
  color: var(--text-primary);
}
.qa-desc {
  font-size: 11px; color: var(--text-tertiary);
  line-height: 1.3;
}

/* Loading state */
.loading-avatar {
  width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
  font-size: 18px;
  animation: avatarBounce 1s ease-in-out infinite;
}
@keyframes avatarBounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}
.loading-bubble {
  padding: 16px 20px; border-radius: 16px;
  background: var(--bg-card); 
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent);
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  position: relative;
  overflow: hidden;
}
.loading-bubble::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 16px;
  padding: 1px;
  background: linear-gradient(135deg, rgba(99,102,241,0.15), transparent);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
}
.loading-dots {
  display: flex; gap: 6px;
}
.loading-dots span {
  width: 8px; height: 8px; border-radius: 50%;
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
  padding: 18px 28px;
  background: linear-gradient(90deg, rgba(99,102,241,0.08), transparent);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  box-shadow: 0 2px 10px rgba(99,102,241,0.05);
}
.ppp-icon { 
  font-size: 22px; 
  animation: iconWiggle 2s ease-in-out infinite;
}
@keyframes iconWiggle {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(-5deg); }
  75% { transform: rotate(5deg); }
}
.ppp-text { font-size: 14px; color: var(--text-secondary); flex-shrink: 0; font-weight: 500; }
.ppp-row { display: flex; gap: 10px; flex: 1; min-width: 240px; }
.ppp-input {
  flex: 1; padding: 10px 14px;
  background: var(--bg-input); border: 1px solid var(--border-input); border-radius: 10px;
  color: var(--text-secondary); font-size: 14px; outline: none;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.ppp-input:focus { 
  border-color: var(--accent-focus); 
  background: var(--bg-glass-hover);
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
}
.ppp-btn {
  width: 42px; height: 42px;
  border: none; border-radius: 10px;
  background: var(--accent-bg-strong); color: var(--accent-text);
  font-size: 14px; font-weight: 600; cursor: pointer; padding: 0;
  transition: all 0.3s cubic-bezier(0.34,1.56,0.64,1); 
  display: flex; align-items: center; justify-content: center;
  position: relative;
  overflow: hidden;
}
.ppp-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at center, rgba(255,255,255,0.3) 0%, transparent 70%);
  opacity: 0;
  transition: opacity 0.3s ease;
}
.ppp-btn:active::before {
  opacity: 1;
  animation: ripple 0.5s ease-out;
}
.ppp-btn:hover { 
  background: var(--bg-accent-hover); 
  transform: scale(1.05);
  box-shadow: 0 4px 16px rgba(99,102,241,0.3);
}
.ppp-btn:active { transform: scale(0.96); }
.ppp-spinner { display: block; }
.ppp-btn-outline {
  width: 42px; height: 42px;
  border: 1px solid var(--border); border-radius: 10px;
  background: transparent; color: var(--accent-text);
  font-size: 18px; cursor: pointer; line-height: 1; padding: 0;
  transition: all 0.3s cubic-bezier(0.34,1.56,0.64,1); 
  display: flex; align-items: center; justify-content: center;
}
.ppp-btn-outline:hover { 
  background: var(--bg-hover); 
  border-color: var(--border-accent); 
  transform: scale(1.05);
}
.ppp-btn-outline:active { transform: scale(0.96); }
.ppp-hint { font-size: 12px; color: var(--text-muted); align-self: center; white-space: nowrap; }
.ppp-hint strong { color: var(--accent-text); }

.input-zone {
  position: relative;
  background: var(--bg-surface);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-top: 1px solid var(--border);
  box-shadow: 0 -4px 20px rgba(0,0,0,0.08);
}

@keyframes ripple {
  from { transform: scale(0); }
  to { transform: scale(2); }
}
</style>
