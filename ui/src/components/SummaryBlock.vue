<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  agentName?: string
  content: string
  childrenCount?: number
}>()

const expanded = ref(true)
const preview = computed(() => {
  if (!props.content) return ''
  return props.content.length > 80 ? props.content.slice(0, 80) + '...' : props.content
})
</script>

<template>
  <div class="summary-block">
    <button class="summary-header" @click="expanded = !expanded" :class="{ open: expanded }">
      <span class="icon">📋</span>
      <span class="label">汇总</span>
      <span v-if="childrenCount && childrenCount > 1" class="meta">{{ childrenCount }} 个子任务</span>
      <span v-if="!expanded" class="preview">{{ preview }}</span>
      <span class="toggle">{{ expanded ? '▴' : '▾' }}</span>
    </button>
    <div v-if="expanded" class="summary-body">
      {{ content }}
    </div>
  </div>
</template>

<style scoped>
.summary-block {
  margin: 8px 0 0 38px;
  max-width: 700px;
  align-self: flex-start;
}
.summary-header {
  display: inline-flex; align-items: center; gap: 8px;
  background: linear-gradient(135deg, rgba(251, 191, 36, 0.1), rgba(167, 139, 250, 0.08));
  border: 1px solid rgba(251, 191, 36, 0.25);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
  max-width: 100%;
  font-family: inherit;
}
.summary-header:hover { background: linear-gradient(135deg, rgba(251, 191, 36, 0.15), rgba(167, 139, 250, 0.12)); }
.summary-header.open { background: linear-gradient(135deg, rgba(251, 191, 36, 0.18), rgba(167, 139, 250, 0.14)); }

.icon { font-size: 13px; }
.label { color: #fbbf24; font-weight: 600; }
.meta {
  color: var(--text-faint); font-size: 10.5px;
  background: rgba(251, 191, 36, 0.1); padding: 1px 6px; border-radius: 3px;
}
.preview {
  color: var(--text-faint); font-size: 11px;
  max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.toggle { color: var(--text-faint); font-size: 10px; }

.summary-body {
  margin-top: 6px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(251, 191, 36, 0.04), rgba(167, 139, 250, 0.03));
  border-left: 2px solid rgba(251, 191, 36, 0.4);
  border-radius: 0 6px 6px 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-wrap: break-word;
  max-width: 700px;
  animation: slideIn 0.3s ease-out;
}
@keyframes slideIn { from { opacity: 0; transform: translateY(-2px); } to { opacity: 1; transform: translateY(0); } }
</style>
