<script setup lang="ts">
import { ref, computed } from 'vue'

interface ToolCall {
  name: string
  args?: Record<string, any> | string
  status?: 'pending' | 'running' | 'done' | 'failed'
}

const props = defineProps<{
  tool: ToolCall
}>()

const expanded = ref(false)
const argsText = computed(() => {
  if (!props.tool.args) return ''
  if (typeof props.tool.args === 'string') return props.tool.args
  try {
    return JSON.stringify(props.tool.args, null, 2)
  } catch {
    return String(props.tool.args)
  }
})

const toolIcon = computed(() => {
  const n = (props.tool.name || '').toLowerCase()
  if (n.includes('search') || n.includes('query')) return '🔍'
  if (n.includes('read') || n.includes('get')) return '📄'
  if (n.includes('write') || n.includes('create')) return '✏️'
  if (n.includes('edit') || n.includes('modify')) return '🔧'
  if (n.includes('exec') || n.includes('run') || n.includes('bash') || n.includes('command')) return '⚡'
  if (n.includes('fetch') || n.includes('http')) return '🌐'
  if (n.includes('file')) return '📁'
  if (n.includes('agent') || n.includes('task')) return '🤖'
  return '🔨'
})
</script>

<template>
  <div class="tool-call-block" :class="tool.status || 'pending'">
    <button class="tool-header" @click="expanded = !expanded" :class="{ open: expanded }">
      <span class="icon">{{ toolIcon }}</span>
      <span class="name">{{ tool.name }}</span>
      <span class="status">
        <span v-if="tool.status === 'pending' || !tool.status" class="badge pending">调用中</span>
        <span v-else-if="tool.status === 'running'" class="badge running">执行中</span>
        <span v-else-if="tool.status === 'done'" class="badge done">完成</span>
        <span v-else-if="tool.status === 'failed'" class="badge failed">失败</span>
      </span>
      <span v-if="argsText" class="toggle">{{ expanded ? '▴' : '▾' }}</span>
    </button>
    <div v-if="expanded && argsText" class="tool-body">
      <pre>{{ argsText }}</pre>
    </div>
  </div>
</template>

<style scoped>
.tool-call-block {
  margin: 3px 0 3px 38px;
  max-width: 700px;
  align-self: flex-start;
}
.tool-header {
  display: inline-flex; align-items: center; gap: 8px;
  background: rgba(167, 139, 250, 0.07);
  border: 1px solid rgba(167, 139, 250, 0.18);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
  max-width: 100%;
  font-family: inherit;
  min-width: 0;
}
.tool-header:hover { background: rgba(167, 139, 250, 0.12); }
.tool-header.open { background: rgba(167, 139, 250, 0.14); }

.icon { font-size: 13px; flex-shrink: 0; }
.name {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  font-weight: 600;
  color: #c084fc;
  flex-shrink: 0;
}
.status { flex-shrink: 0; }
.badge {
  font-size: 10px; padding: 1px 6px; border-radius: 4px;
  font-weight: 600;
}
.badge.pending { background: rgba(167, 139, 250, 0.18); color: #c084fc; }
.badge.running { background: rgba(251, 191, 36, 0.18); color: #fbbf24; animation: pulse 1.4s ease-in-out infinite; }
.badge.done { background: rgba(52, 211, 153, 0.18); color: #34d399; }
.badge.failed { background: rgba(239, 68, 68, 0.18); color: #ef4444; }
@keyframes pulse {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}

.toggle { color: var(--text-faint); font-size: 10px; flex-shrink: 0; }

.tool-body {
  margin-top: 4px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.25);
  border-radius: 0 0 6px 6px;
  border-top: 1px solid rgba(167, 139, 250, 0.1);
  max-width: 700px;
  animation: slideIn 0.2s ease-out;
}
@keyframes slideIn { from { opacity: 0; max-height: 0; } to { opacity: 1; max-height: 400px; } }
.tool-body pre {
  margin: 0;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-wrap: break-word;
  line-height: 1.5;
}
</style>
