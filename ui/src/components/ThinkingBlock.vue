<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'

const props = defineProps<{
  content: string
  streaming?: boolean
  done?: boolean
}>()

const collapsed = ref(true)
const visibleChars = ref(0)
let rafHandle: number | null = null

const preview = computed(() => {
  if (props.content.length <= 80) return props.content
  return props.content.slice(0, 80) + '...'
})

const hasMore = computed(() => props.content.length > 80)
const charCount = computed(() => props.content.length)

function toggle() {
  collapsed.value = !collapsed.value
}

function startStreaming() {
  if (rafHandle !== null) cancelAnimationFrame(rafHandle)
  visibleChars.value = 0
  const total = props.content.length
  function tick() {
    if (visibleChars.value < total) {
      visibleChars.value = Math.min(visibleChars.value + 12, total)
      rafHandle = requestAnimationFrame(tick)
    } else {
      rafHandle = null
    }
  }
  rafHandle = requestAnimationFrame(tick)
}

watch(() => props.content, () => {
  if (props.streaming && !props.done) startStreaming()
}, { immediate: true })

onMounted(() => {
  if (props.streaming && !props.done && props.content) startStreaming()
})
</script>

<template>
  <div class="thinking-block">
    <button class="thinking-header" @click="toggle" :class="{ active: !collapsed, streaming: streaming && !done, done: done }">
      <span class="dot" />
      <span class="label">
        <span v-if="streaming && !done">思考中</span>
        <span v-else>思考</span>
        <span class="char-count">{{ charCount }}</span>
      </span>
      <span v-if="hasMore && collapsed" class="preview">{{ preview }}</span>
      <span class="toggle">{{ collapsed ? '展开' : '收起' }}</span>
    </button>
    <div v-if="!collapsed" class="thinking-body">
      <div v-if="streaming && !done" class="stream-content">{{ content.slice(0, visibleChars) }}<span class="caret">▍</span></div>
      <div v-else class="final-content">{{ content }}</div>
    </div>
  </div>
</template>

<style scoped>
.thinking-block {
  display: block;
  width: 100%;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-secondary);
}
.thinking-header {
  display: inline-flex; align-items: center; gap: 8px;
  background: transparent;
  border: none;
  border-left: 2px solid rgba(129, 140, 248, 0.5);
  padding: 4px 10px;
  font-size: 11.5px;
  color: var(--text-faint);
  cursor: pointer;
  transition: all 0.2s;
  max-width: 100%;
  font-family: inherit;
  border-radius: 0 4px 4px 0;
  margin: 2px 0;
}
.thinking-header:hover {
  background: rgba(129, 140, 248, 0.05);
  color: var(--text-secondary);
}
.thinking-header.active {
  background: rgba(129, 140, 248, 0.08);
  color: var(--text-secondary);
  border-left-color: #818cf8;
}
.thinking-header.streaming { border-left-color: #818cf8; }
.thinking-header.done { border-left-color: rgba(52, 211, 153, 0.5); }

.dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: #818cf8;
  flex-shrink: 0;
}
.thinking-header.streaming .dot { animation: pulse 1.4s ease-in-out infinite; }
.thinking-header.done .dot { background: rgba(52, 211, 153, 0.8); }
@keyframes pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.15); }
}

.label { color: #818cf8; font-weight: 600; flex-shrink: 0; display: inline-flex; align-items: center; gap: 6px; }
.thinking-header.done .label { color: rgba(52, 211, 153, 0.85); }
.char-count {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 10px;
  font-weight: 500;
  color: var(--text-faint);
  background: rgba(129, 140, 248, 0.1);
  padding: 1px 5px;
  border-radius: 3px;
  min-width: 32px; text-align: center;
}
.thinking-header.done .char-count { background: rgba(52, 211, 153, 0.1); }

.preview {
  color: var(--text-faint); font-size: 11px;
  max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.toggle { color: var(--text-faint); font-size: 10px; flex-shrink: 0; margin-left: 2px; }

.thinking-body {
  margin: 4px 0 6px 0;
  padding: 8px 12px 8px 14px;
  background: rgba(129, 140, 248, 0.04);
  border-left: 2px solid rgba(129, 140, 248, 0.3);
  border-radius: 0 4px 4px 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-wrap: break-word;
  max-width: 100%;
  animation: fadeIn 0.25s ease-out;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.caret {
  display: inline-block;
  animation: blink 1s steps(2) infinite;
  color: #818cf8;
}
@keyframes blink { 50% { opacity: 0; } }
</style>
