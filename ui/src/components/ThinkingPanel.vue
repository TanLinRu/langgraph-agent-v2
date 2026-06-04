<script setup lang="ts">
import { ref, computed } from 'vue'
import ConvAvatar from './ConvAvatar.vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import katex from 'katex'

const _marked = new Marked(
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

function renderMd(text: string): string {
  const blocks: string[] = []
  let processed = text.replace(/\$\$([\s\S]*?)\$\$/g, (_m, tex) => {
    if (/[一-鿿]/.test(tex)) return _m
    const placeholder = `%%MATH_BLOCK_${blocks.length}%%`
    blocks.push(katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }))
    return placeholder
  })
  processed = processed.replace(/\$([^$\n]+?)\$/g, (_m, tex) => {
    if (/[一-鿿]/.test(tex)) return _m
    const placeholder = `%%MATH_INLINE_${blocks.length}%%`
    blocks.push(katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }))
    return placeholder
  })
  let html = _marked.parse(processed) as string
  blocks.forEach((block, i) => {
    html = html.replace(`%%MATH_BLOCK_${i}%%`, block)
    html = html.replace(`%%MATH_INLINE_${i}%%`, block)
  })
  return html
}

const props = defineProps<{
  chunks: Array<{ agentName: string; text: string }>
  isThinking: boolean
  stepCount: number
  elapsedMs: number
}>()

const expanded = ref(true)

const activeAgent = computed(() => {
  const cs = props.chunks
  if (!cs.length) return 'supervisor'
  const last = cs[cs.length - 1]
  return last.agentName || 'supervisor'
})

const groupedChunks = computed(() => {
  const groups: Array<{ agent: string; chunks: string[] }> = []
  for (const chunk of props.chunks) {
    const last = groups[groups.length - 1]
    if (last && last.agent === chunk.agentName) {
      last.chunks.push(chunk.text)
    } else {
      groups.push({ agent: chunk.agentName, chunks: [chunk.text] })
    }
  }
  return groups
})

function elapsedStr(): string {
  const s = Math.floor(props.elapsedMs / 1000)
  const m = Math.floor(s / 60)
  const sec = s % 60
  return m > 0 ? `${m}:${sec.toString().padStart(2, '0')}` : `${sec}s`
}
</script>

<template>
  <div v-if="chunks.length || isThinking" class="thinking-panel">
    <!-- Collapsed summary -->
    <div v-if="!expanded && !isThinking" class="thinking-panel-summary" @click="expanded = true">
      <svg class="thinking-panel-summary-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span class="thinking-panel-summary-text">已推理 {{ stepCount }} 步 · 耗时 {{ elapsedStr() }}</span>
      <span class="thinking-panel-summary-expand">展开</span>
    </div>
    <!-- Expanded panel -->
    <template v-else>
      <div class="thinking-panel-header" @click="expanded = !expanded">
        <ConvAvatar :type="activeAgent" :size="24" />
        <span class="thinking-panel-header-label">
          {{ activeAgent === 'supervisor' ? 'Supervisor' : activeAgent }} · <template v-if="isThinking">思考中<span class="thinking-dots"><span></span><span></span><span></span></span></template><template v-else>已推理</template>
        </span>
        <span class="thinking-panel-header-meta">{{ stepCount }} 步 · {{ elapsedStr() }}</span>
        <span :class="['thinking-panel-header-arrow', { open: expanded }]">▾</span>
      </div>
      <div v-if="expanded" class="thinking-panel-body">
        <div v-for="(group, i) in groupedChunks" :key="i" class="thinking-panel-agent-group">
          <div class="thinking-panel-agent-header">
            <ConvAvatar :type="group.agent || 'helper'" :size="18" />
            <span class="thinking-panel-agent-name">{{ group.agent || 'assistant' }}</span>
          </div>
          <div class="thinking-panel-chunk-text" v-html="renderMd(group.chunks.join(''))"></div>
          <span v-if="isThinking" class="stream-cursor"></span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.thinking-panel {
  align-self: flex-start; max-width: 85%; width: 100%;
  animation: msgIn 0.35s cubic-bezier(0.16,1,0.3,1) both;
}
@keyframes msgIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.thinking-panel-header {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; cursor: pointer; user-select: none;
  border-radius: 12px 12px 0 0;
  background: rgba(129,140,248,0.08);
  border: 1px solid rgba(129,140,248,0.15);
  border-bottom: none;
  transition: background 0.15s;
}
.thinking-panel-header:hover { background: rgba(129,140,248,0.13); }
.thinking-panel-header-label {
  font-size: 13px; font-weight: 560; color: var(--accent); letter-spacing: 0.3px;
}
.thinking-panel-header-meta {
  margin-left: auto; font-size: 12px; color: var(--text-muted);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.thinking-panel-header-arrow {
  font-size: 12px; color: var(--accent-text); transition: transform 0.2s; margin-left: 8px;
}
.thinking-panel-header-arrow.open { transform: rotate(180deg); }

.thinking-dots {
  display: inline-flex; gap: 3px; margin-left: 4px;
}
.thinking-dots span {
  width: 5px; height: 5px; border-radius: 50%; background: var(--accent-text);
  animation: dotPulse 1.4s ease-in-out infinite;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes dotPulse {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.15; }
  40% { transform: scale(1); opacity: 1; }
}

.thinking-panel-body {
  border: 1px solid rgba(129,140,248,0.12);
  border-top: none;
  border-radius: 0 0 12px 12px;
  background: var(--bg-overlay);
  padding: 0; max-height: 60vh; overflow-y: auto;
}
.thinking-panel-agent-group {
  padding: 10px 16px;
  border-bottom: 1px solid rgba(129,140,248,0.06);
  animation: chunkIn 0.3s ease both;
}
.thinking-panel-agent-group:last-child { border-bottom: none; }
.thinking-panel-agent-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
}
.thinking-panel-agent-name {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
  font-weight: 600; color: var(--accent-text);
}
.thinking-panel-chunk-text {
  font-size: 13px; line-height: 1.65; color: var(--text-secondary);
  padding-left: 26px;
}
.thinking-panel-chunk-text :deep(pre) {
  background: var(--bg-code); border-radius: 8px; padding: 12px; margin: 8px 0;
  overflow-x: auto; font-size: 12px;
}
.thinking-panel-chunk-text :deep(code) {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.stream-cursor {
  display: inline-block; width: 2px; height: 14px;
  background: var(--text-secondary);
  animation: blinkCursor 0.7s step-end infinite;
  vertical-align: text-bottom; margin-left: 2px;
}
@keyframes blinkCursor { 50% { opacity: 0; } }
@keyframes chunkIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Summary (collapsed) */
.thinking-panel-summary {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px;
  background: rgba(129,140,248,0.06);
  border: 1px solid rgba(129,140,248,0.12);
  border-radius: 10px;
  cursor: pointer; transition: background 0.15s;
  animation: msgIn 0.3s cubic-bezier(0.16,1,0.3,1) both;
}
.thinking-panel-summary:hover { background: rgba(129,140,248,0.1); }
.thinking-panel-summary-icon { width: 18px; height: 18px; flex-shrink: 0; opacity: 0.7; }
.thinking-panel-summary-text { font-size: 13px; color: var(--text-tertiary); }
.thinking-panel-summary-expand { font-size: 12px; color: var(--accent-text); margin-left: auto; }
</style>
