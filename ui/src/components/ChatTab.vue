<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import katex from 'katex'
import { useChatStore } from '../stores/chat'
import type { ChatMessage } from '../utils/api'

const marked = new Marked(
  { breaks: true, gfm: true },
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code: string, lang: string) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      return hljs.highlightAuto(code).value
    },
  }),
)

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, { displayMode, throwOnError: false, trust: true })
  } catch {
    return displayMode ? `<pre class="math-block">${tex}</pre>` : `<code>${tex}</code>`
  }
}

function renderMd(text: string): string {
  const blocks: string[] = []
  let processed = text.replace(/\$\$([\s\S]*?)\$\$/g, (_m, tex) => {
    if (/[一-鿿]/.test(tex)) return _m
    const placeholder = `%%MATH_BLOCK_${blocks.length}%%`
    blocks.push(renderMath(tex.trim(), true))
    return placeholder
  })
  processed = processed.replace(/\$([^$\n]+?)\$/g, (_m, tex) => {
    if (/[一-鿿]/.test(tex)) return _m
    const placeholder = `%%MATH_INLINE_${blocks.length}%%`
    blocks.push(renderMath(tex.trim(), false))
    return placeholder
  })

  let html = marked.parse(processed) as string

  blocks.forEach((block, i) => {
    html = html.replace(`%%MATH_BLOCK_${i}%%`, block)
    html = html.replace(`%%MATH_INLINE_${i}%%`, block)
  })
  return html
}

const AGENT_COLORS: Record<string, string> = {
  supervisor: '#818cf8',
  coder: '#34d399',
  researcher: '#fbbf24',
  analyst: '#fb7185',
}

const AGENT_LABELS: Record<string, string> = {
  supervisor: 'Supervisor',
  coder: 'Coder',
  researcher: 'Researcher',
  analyst: 'Analyst',
}

function agentColor(name?: string): string {
  return AGENT_COLORS[name || ''] || 'rgba(255,255,255,0.5)'
}

function agentLabel(name?: string): string {
  return AGENT_LABELS[name || ''] || name || 'assistant'
}

const chat = useChatStore()
const input = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const thinkingExpanded = ref<Set<number>>(new Set())
const thinkingLive = ref<Set<number>>(new Set())

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args)
  if (entries.length === 0) return ''
  return entries.map(([k, v]) => {
    const val = typeof v === 'string' ? v : JSON.stringify(v)
    const display = val.length > 120 ? val.slice(0, 120) + '...' : val
    return `${k}: ${display}`
  }).join(', ')
}

function toggleThinking(index: number) {
  if (thinkingExpanded.value.has(index)) {
    thinkingExpanded.value.delete(index)
  } else {
    thinkingExpanded.value.add(index)
  }
}

watch(() => chat.messages.map(m => m.thinking), () => {
  const msgs = chat.messages
  for (let i = 0; i < msgs.length; i++) {
    if (msgs[i].thinking && !thinkingExpanded.value.has(i)) {
      thinkingExpanded.value.add(i)
      thinkingLive.value.add(i)
    }
  }
}, { deep: true })

watch(() => chat.isLoading, (loading) => {
  if (!loading) {
    thinkingLive.value.clear()
  }
})

async function send() {
  const msg = input.value.trim()
  if (!msg || chat.isLoading) return
  input.value = ''
  await chat.sendMessage(msg)
}

watch(() => chat.messages.length, async () => {
  await nextTick()
  messagesRef.value?.scrollTo({ top: messagesRef.value.scrollHeight, behavior: 'smooth' })
})
</script>

<template>
  <div class="chat-tab">
    <div class="messages" ref="messagesRef">
      <div v-if="chat.messages.length === 0" class="empty">
        <div class="empty-icon">✦</div>
        <p>Start a conversation with the agent</p>
      </div>
      <template v-for="(msg, i) in chat.messages" :key="i">
      <div
        v-if="msg.role !== 'assistant' || msg.content || msg.thinking || msg.toolCalls?.length"
        :class="['msg', msg.role, { 'is-summary': msg.isSummary }]"
        :style="msg.role === 'assistant' && msg.agentName ? { '--agent-color': agentColor(msg.agentName) } : {}"
      >
        <!-- Agent label badge -->
        <div v-if="msg.role === 'assistant' && msg.agentName" class="msg-role agent-badge" :style="{ color: agentColor(msg.agentName) }">
          {{ agentLabel(msg.agentName) }}
        </div>
        <div v-else class="msg-role">{{ msg.role }}</div>

        <!-- Thinking block -->
        <div v-if="msg.thinking" class="thinking-block" :class="{ 'is-live': thinkingLive.has(i) }">
          <button class="thinking-toggle" @click="toggleThinking(i)">
            <span class="thinking-icon">{{ thinkingExpanded.has(i) ? '▾' : '▸' }}</span>
            <span v-if="thinkingLive.has(i)" class="thinking-label">
              Thinking<span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
            </span>
            <span v-else>Thinking process</span>
          </button>
          <Transition name="thinking-expand">
            <div v-if="thinkingExpanded.has(i)" class="thinking-content">
              {{ msg.thinking }}<span v-if="thinkingLive.has(i)" class="cursor-blink">|</span>
            </div>
          </Transition>
        </div>

        <!-- Message content -->
        <div class="msg-content md-body" v-if="msg.content" v-html="renderMd(msg.content)"></div>

        <!-- Tool calls -->
        <div v-if="msg.toolCalls?.length" class="tool-calls">
          <div v-for="(tc, j) in msg.toolCalls" :key="j" class="tool-call">
            <div class="tool-header">
              <span class="tool-icon">&#9881;</span>
              <span class="tool-name">{{ tc.name }}</span>
            </div>
            <div v-if="tc.name === 'execute_code' && tc.args.code" class="tool-code-wrap">
              <details>
                <summary>Show code</summary>
                <pre class="tool-code"><code>{{ tc.args.code }}</code></pre>
              </details>
            </div>
            <div v-else class="tool-args">{{ formatArgs(tc.args) }}</div>
          </div>
        </div>
      </div>
      </template>
      <div v-if="chat.isLoading && !chat.streamingActive" class="msg assistant loading">
        <div class="msg-role">assistant</div>
        <div class="msg-content">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
        </div>
      </div>
    </div>
    <form class="input-bar" @submit.prevent="send">
      <input v-model="input" placeholder="Type a message..." :disabled="chat.isLoading" />
      <button type="submit" :disabled="chat.isLoading || !input.trim()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
        </svg>
      </button>
    </form>
  </div>
</template>

<style>
@import 'highlight.js/styles/github-dark.css';
@import 'katex/dist/katex.min.css';
</style>

<style scoped>
.chat-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
}

.empty-icon {
  font-size: 40px;
  opacity: 0.3;
}

.empty p {
  color: rgba(255, 255, 255, 0.3);
  font-size: 15px;
}

/* ── Message bubbles ───────────────────────────────────────────── */
.msg {
  padding: 14px 18px;
  border-radius: 16px;
  max-width: 75%;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  animation: fadeIn 0.25s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg.user {
  background: rgba(99, 102, 241, 0.2);
  border-color: rgba(99, 102, 241, 0.25);
  align-self: flex-end;
  border-bottom-right-radius: 4px;
}

.msg.assistant {
  background: rgba(255, 255, 255, 0.06);
  border-color: var(--agent-color, rgba(255, 255, 255, 0.1));
  align-self: flex-start;
  border-bottom-left-radius: 4px;
  border-left: 3px solid var(--agent-color, transparent);
}

.msg.assistant.is-summary {
  background: rgba(129, 140, 248, 0.1);
  border-color: rgba(129, 140, 248, 0.3);
  border-left: 3px solid #818cf8;
  align-self: stretch;
  max-width: 100%;
}

.msg.system {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.2);
  align-self: center;
  font-size: 13px;
  text-align: center;
}

.msg-role {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.agent-badge {
  font-weight: 600;
  letter-spacing: 1px;
}

.msg-content {
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.88);
  animation: contentFadeIn 0.4s ease-out;
}

@keyframes contentFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Markdown rendered content ───────────────────────────────── */
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 16px 0 8px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
}
.md-body :deep(h1) { font-size: 1.4em; }
.md-body :deep(h2) { font-size: 1.2em; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 4px; }
.md-body :deep(h3) { font-size: 1.05em; }

.md-body :deep(p) { margin: 6px 0; }

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}

.md-body :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 12px;
  border-left: 3px solid rgba(99, 102, 241, 0.5);
  background: rgba(99, 102, 241, 0.06);
  border-radius: 0 6px 6px 0;
  color: rgba(255, 255, 255, 0.7);
}

.md-body :deep(code) {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.9em;
  background: rgba(0, 0, 0, 0.3);
  padding: 1px 5px;
  border-radius: 4px;
  color: #e0b0ff;
}

.md-body :deep(pre) {
  margin: 8px 0;
  padding: 12px;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 8px;
  overflow-x: auto;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.md-body :deep(pre code) {
  background: none;
  padding: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
}

.md-body :deep(table) {
  margin: 8px 0;
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}

.md-body :deep(th),
.md-body :deep(td) {
  padding: 6px 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  text-align: left;
}

.md-body :deep(th) {
  background: rgba(255, 255, 255, 0.06);
  font-weight: 600;
}

.md-body :deep(hr) {
  margin: 12px 0;
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.md-body :deep(a) {
  color: #818cf8;
  text-decoration: none;
}
.md-body :deep(a:hover) {
  text-decoration: underline;
}

.md-body :deep(strong) {
  color: rgba(255, 255, 255, 0.95);
  font-weight: 600;
}

.md-body :deep(.katex-display) {
  margin: 8px 0;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  overflow-x: auto;
}

.md-body :deep(.katex) {
  font-size: 1.05em;
  color: rgba(255, 255, 255, 0.9);
}

/* ── Tool calls ────────────────────────────────────────────────── */
.tool-calls {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-call {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  overflow: hidden;
  font-size: 12px;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(99, 102, 241, 0.06);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.tool-icon {
  color: rgba(129, 140, 248, 0.6);
  font-size: 11px;
}

.tool-name {
  color: #818cf8;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-weight: 500;
}

.tool-args {
  padding: 8px 12px;
  color: rgba(255, 255, 255, 0.4);
  font-family: 'SF Mono', 'Fira Code', monospace;
  line-height: 1.5;
  word-break: break-all;
}

.tool-code-wrap details {
  cursor: pointer;
}

.tool-code-wrap summary {
  padding: 6px 12px;
  color: rgba(255, 255, 255, 0.4);
  font-size: 11px;
  user-select: none;
}

.tool-code-wrap summary:hover {
  color: rgba(255, 255, 255, 0.6);
}

.tool-code {
  margin: 0;
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.3);
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.7);
  overflow-x: auto;
  max-height: 200px;
}

/* ── Thinking block ──────────────────────────────────────────── */
.thinking-block {
  margin-bottom: 10px;
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-radius: 8px;
  overflow: hidden;
  transition: border-color 0.3s;
}

.thinking-block.is-live {
  border-color: rgba(139, 92, 246, 0.45);
  box-shadow: 0 0 12px rgba(139, 92, 246, 0.1);
}

.thinking-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 12px;
  background: rgba(139, 92, 246, 0.08);
  border: none;
  color: rgba(139, 92, 246, 0.8);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s;
}

.thinking-toggle:hover {
  background: rgba(139, 92, 246, 0.15);
}

.thinking-icon {
  font-size: 10px;
  width: 14px;
  text-align: center;
}

.thinking-label {
  display: inline-flex;
  align-items: center;
}

.thinking-dots span {
  animation: dotPulse 1.4s ease-in-out infinite;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotPulse {
  0%, 60%, 100% { opacity: 0.2; }
  30% { opacity: 1; }
}

.thinking-content {
  padding: 12px;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.5);
  white-space: pre-wrap;
  max-height: 400px;
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.15);
}

.cursor-blink {
  animation: blink 0.8s step-end infinite;
  color: rgba(139, 92, 246, 0.8);
  font-weight: bold;
}

@keyframes blink {
  50% { opacity: 0; }
}

.thinking-expand-enter-active,
.thinking-expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.thinking-expand-enter-from,
.thinking-expand-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.thinking-expand-enter-to,
.thinking-expand-leave-from {
  opacity: 1;
  max-height: 400px;
}

/* ── Loading dots ──────────────────────────────────────────────── */
.loading .msg-content {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
  animation: bounce 1.4s ease-in-out infinite;
}

.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ── Input bar ─────────────────────────────────────────────────── */
.input-bar {
  padding: 16px 24px;
  display: flex;
  gap: 10px;
  background: rgba(255, 255, 255, 0.03);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.input-bar input {
  flex: 1;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  outline: none;
  transition: all 0.2s;
}

.input-bar input::placeholder {
  color: rgba(255, 255, 255, 0.25);
}

.input-bar input:focus {
  border-color: rgba(99, 102, 241, 0.5);
  background: rgba(255, 255, 255, 0.08);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.input-bar button {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(99, 102, 241, 0.25);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 12px;
  color: #c7d2fe;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.input-bar button:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.4);
  border-color: rgba(99, 102, 241, 0.5);
  transform: scale(1.05);
}

.input-bar button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
</style>
