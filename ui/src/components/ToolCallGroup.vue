<script setup lang="ts">
import { ref, computed } from 'vue'
import ToolCallBlock from './ToolCallBlock.vue'

interface ToolCallShape {
  name: string
  args?: Record<string, unknown> | string
  status?: 'pending' | 'running' | 'done' | 'failed'
}

const props = defineProps<{
  tools: ToolCallShape[]
}>()

const expanded = ref(false)

const allDone = computed(() => props.tools.every(t => t.status === 'done' || t.status === 'failed'))
const runningCount = computed(() => props.tools.filter(t => t.status === 'running' || t.status === 'pending' || !t.status).length)

const groupLabel = computed(() => {
  const names = [...new Set(props.tools.map(t => t.name))]
  if (names.length <= 2) return names.join(', ')
  return `${names[0]} +${names.length - 1} more`
})

const groupIcon = computed(() => {
  const n = props.tools[0]?.name?.toLowerCase() || ''
  if (n.includes('search')) return '🔍'
  if (n.includes('read')) return '📄'
  if (n.includes('write') || n.includes('create')) return '✏️'
  return '🔨'
})

const progressText = computed(() => {
  const done = props.tools.filter(t => t.status === 'done' || t.status === 'failed').length
  return `${done}/${props.tools.length}`
})
</script>

<template>
  <div class="tool-call-group" :class="{ 'all-done': allDone }">
    <button class="group-header" @click="expanded = !expanded">
      <span class="group-icon">{{ groupIcon }}</span>
      <span class="group-label">{{ groupLabel }}</span>
      <span class="group-count">{{ progressText }}</span>
      <span v-if="runningCount > 0" class="group-running">
        <span class="running-dot"></span>
        {{ runningCount }} 执行中
      </span>
      <span v-else class="group-done-badge">全部完成</span>
      <span class="group-toggle">{{ expanded ? '▴' : '▾' }}</span>
    </button>
    <div v-if="expanded" class="group-body">
      <ToolCallBlock v-for="(tool, i) in tools" :key="i" :tool="tool as any" />
    </div>
  </div>
</template>

<style scoped>
.tool-call-group {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.2s ease;
}
.tool-call-group:hover {
  border-color: var(--border-accent);
}
.tool-call-group.all-done {
  opacity: 0.75;
}
.group-header {
  display: flex; align-items: center; gap: 8px;
  width: 100%;
  padding: 7px 12px;
  background: var(--bg-glass);
  border: none;
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s ease;
  font-family: inherit;
}
.group-header:hover { background: var(--bg-hover); }
.group-icon { font-size: 13px; flex-shrink: 0; }
.group-label {
  font-weight: 600;
  color: var(--accent-text);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.group-count {
  margin-left: auto;
  font-size: 10px; color: var(--text-tertiary);
  background: var(--bg-card);
  padding: 1px 6px; border-radius: 4px;
  flex-shrink: 0;
}
.group-running {
  display: flex; align-items: center; gap: 4px;
  font-size: 10px; color: #fbbf24;
  flex-shrink: 0;
}
.running-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: #fbbf24;
  animation: runningPulse 0.8s ease-in-out infinite;
}
@keyframes runningPulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.5); opacity: 0.5; }
}
.group-done-badge {
  font-size: 10px; color: var(--color-green);
  flex-shrink: 0;
}
.group-toggle { font-size: 10px; color: var(--text-faint); flex-shrink: 0; }
.group-body {
  border-top: 1px solid var(--border);
  padding: 6px 10px;
  display: flex; flex-direction: column; gap: 3px;
  animation: groupExpand 0.2s ease-out;
}
@keyframes groupExpand {
  from { opacity: 0; max-height: 0; }
  to { opacity: 1; max-height: 500px; }
}
</style>
