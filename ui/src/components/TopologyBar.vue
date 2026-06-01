<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useChatStore } from '../stores/chat'

const chat = useChatStore()

type SupState = 'idle' | 'thinking' | 'delegating' | 'aggregating' | 'done' | 'failed'

const STATUS_TEXTS: Record<SupState, string> = {
  idle: '空闲',
  thinking: '思考中',
  delegating: '派发中',
  aggregating: '汇总中',
  done: '完成',
  failed: '失败',
}

const supState = ref<SupState>('idle')
const supStatusText = computed(() => STATUS_TEXTS[supState.value])

watch([() => chat.taskItems, () => chat.isLoading], () => {
  const items = chat.taskItems
  if (items.length === 0) {
    supState.value = chat.isLoading ? 'thinking' : 'idle'
    return
  }
  const anyRunning = items.some(t => t.status === 'running')
  const allDone = items.every(t => t.status === 'completed' || t.status === 'failed')
  const anyFailed = items.some(t => t.status === 'failed')
  if (anyRunning) {
    supState.value = 'delegating'
  } else if (allDone) {
    if (anyFailed) supState.value = 'failed'
    else supState.value = 'aggregating'
  } else {
    supState.value = 'thinking'
  }
}, { immediate: true, deep: true })

watch(supState, (s, old) => {
  if ((s === 'done' || s === 'aggregating') && old === 'aggregating') {
    setTimeout(() => {
      if (!chat.taskItems.some(t => t.status === 'running')) {
        supState.value = 'done'
      }
    }, 600)
  }
})

const visible = computed(() => chat.isLoading || chat.taskItems.length > 0)
const dotColor = computed(() => {
  switch (supState.value) {
    case 'delegating': return '#fbbf24'
    case 'aggregating':
    case 'done': return '#34d399'
    case 'failed': return '#ef4444'
    case 'thinking': return '#818cf8'
    default: return 'var(--text-faint)'
  }
})
</script>

<template>
  <div v-if="visible" class="topology-bar">
    <div class="status-line">
      <span class="status-dot" :style="{ background: dotColor }"></span>
      <span class="status-label">Supervisor</span>
      <span class="status-sep">·</span>
      <span class="status-text">{{ supStatusText }}</span>
    </div>
  </div>
</template>

<style scoped>
.topology-bar {
  padding: 8px 20px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.status-line {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.status-dot {
  width: 6px; height: 6px; border-radius: 50%;
  flex-shrink: 0;
}
.status-label { font-weight: 600; color: var(--text-primary); letter-spacing: 0.2px; }
.status-sep { color: var(--text-faint); }
.status-text { color: var(--text-dim); }
</style>
