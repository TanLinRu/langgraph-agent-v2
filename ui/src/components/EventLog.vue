<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { LogEntry } from '../utils/api'

const props = defineProps<{
  entries: LogEntry[]
}>()

const listRef = ref<HTMLElement | null>(null)

watch(() => props.entries.length, async () => {
  await nextTick()
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
})

const TYPE_LABELS: Record<string, string> = {
  start: 'start',
  thinking: 'think',
  tool_call: 'tool',
  result: 'result',
  summary: 'sumry',
  handoff: 'hand',
  decision: 'plan',
  error: 'err',
  phase: 'phase',
}

function typeClass(type: string): string {
  const m: Record<string, string> = {
    start: 't1',
    thinking: 't6',
    tool_call: 't7',
    result: 't8',
    summary: 't9',
    error: 't11',
    handoff: 't12',
    decision: 't13',
    phase: 't14',
  }
  return m[type] || ''
}

function fmtTime(ts: number): string {
  const d = new Date(ts)
  return d.toTimeString().slice(0, 8)
}
</script>

<template>
  <div class="event-log">
    <div class="log-list" ref="listRef">
      <div v-for="(e, i) in entries" :key="i" class="log-item">
        <span class="log-time">{{ fmtTime(e.timestamp) }}</span>
        <span :class="['log-type', typeClass(e.type)]">{{ TYPE_LABELS[e.type] || e.type }}</span>
        <span class="log-content">{{ e.content }}</span>
      </div>
      <div v-if="entries.length === 0" class="log-empty">暂无事件</div>
    </div>
  </div>
</template>

<style scoped>
.event-log {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.log-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 6px;
  max-height: 180px;
}
.log-list::-webkit-scrollbar { width: 3px; }
.log-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

.log-item {
  display: flex; gap: 6px; align-items: flex-start;
  padding: 3px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  color: var(--text-dim);
  animation: logIn 0.2s ease;
}
@keyframes logIn {
  from { opacity: 0; transform: translateX(-4px); }
  to { opacity: 1; transform: translateX(0); }
}
.log-item:hover { background: var(--bg-card); }

.log-time { color: var(--text-faint); flex-shrink: 0; }
.log-type { font-weight: 600; min-width: 36px; flex-shrink: 0; }
.log-type.t1 { color: var(--accent-text); }
.log-type.t6 { color: #60a5fa; }
.log-type.t7 { color: #fb923c; }
.log-type.t8 { color: var(--color-green); }
.log-type.t9 { color: var(--accent); }
.log-type.t11 { color: var(--color-red); }
.log-type.t12 { color: var(--color-amber); }
.log-type.t13 { color: #f472b6; }
.log-type.t14 { color: var(--accent-text); }

.log-content { color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }

.log-empty {
  font-size: 11px;
  color: var(--text-faint);
  padding: 16px;
  text-align: center;
}
</style>
