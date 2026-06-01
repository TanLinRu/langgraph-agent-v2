<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  result: string
  success?: boolean
}>()

const expanded = ref(false)
const preview = computed(() => {
  if (!props.result) return ''
  if (props.result.length <= 60) return props.result.replace(/\n/g, ' ')
  return props.result.slice(0, 60).replace(/\n/g, ' ') + '...'
})
const hasMore = computed(() => props.result && props.result.length > 60)
</script>

<template>
  <div class="tool-result-block" :class="{ failed: success === false }">
    <button class="result-header" @click="expanded = !expanded" :class="{ open: expanded }">
      <span class="icon">{{ success === false ? '⚠' : '✓' }}</span>
      <span class="label">{{ success === false ? '工具失败' : '工具返回' }}</span>
      <span v-if="!expanded && hasMore" class="preview">{{ preview }}</span>
      <span v-if="hasMore" class="toggle">{{ expanded ? '▴' : '▾' }}</span>
    </button>
    <div v-if="expanded && hasMore" class="result-body">
      <pre>{{ result }}</pre>
    </div>
  </div>
</template>

<style scoped>
.tool-result-block {
  margin: 0 0 6px 38px;
  max-width: 700px;
  align-self: flex-start;
}
.result-header {
  display: inline-flex; align-items: center; gap: 8px;
  background: rgba(52, 211, 153, 0.07);
  border: 1px solid rgba(52, 211, 153, 0.18);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11.5px;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.2s;
  max-width: 100%;
  font-family: inherit;
}
.tool-result-block.failed .result-header {
  background: rgba(239, 68, 68, 0.07);
  border-color: rgba(239, 68, 68, 0.2);
}
.result-header:hover { background: rgba(52, 211, 153, 0.12); }
.result-header.open { background: rgba(52, 211, 153, 0.14); }
.tool-result-block.failed .result-header:hover { background: rgba(239, 68, 68, 0.12); }

.icon { font-size: 12px; color: #34d399; }
.tool-result-block.failed .icon { color: #ef4444; }
.label { color: #34d399; font-weight: 600; }
.tool-result-block.failed .label { color: #ef4444; }
.preview {
  color: var(--text-faint); font-size: 11px;
  max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.toggle { color: var(--text-faint); font-size: 10px; }

.result-body {
  margin-top: 4px;
  padding: 8px 12px;
  background: rgba(52, 211, 153, 0.04);
  border-left: 2px solid rgba(52, 211, 153, 0.3);
  border-radius: 0 6px 6px 0;
  max-width: 700px;
  animation: slideIn 0.2s ease-out;
}
.tool-result-block.failed .result-body {
  background: rgba(239, 68, 68, 0.04);
  border-left-color: rgba(239, 68, 68, 0.3);
}
@keyframes slideIn { from { opacity: 0; } to { opacity: 1; } }
.result-body pre {
  margin: 0;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-wrap: break-word;
  line-height: 1.5;
  max-height: 300px; overflow-y: auto;
}
</style>
