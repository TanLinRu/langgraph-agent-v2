<script setup lang="ts">
defineProps<{
  message: string
  agentName?: string
  errorType?: string
}>()
</script>

<template>
  <div class="error-block">
    <div class="error-header">
      <span class="icon">⚠</span>
      <span class="label">执行错误</span>
      <span v-if="errorType" class="error-type">{{ errorType }}</span>
    </div>
    <div class="error-body">{{ message }}</div>
  </div>
</template>

<style scoped>
.error-block {
  margin: 4px 0 4px 38px;
  max-width: 700px;
  align-self: flex-start;
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-left: 3px solid #ef4444;
  border-radius: 6px;
  padding: 8px 12px;
  animation: shakeIn 0.4s cubic-bezier(0.36, 0.07, 0.19, 0.97) both;
}
@keyframes shakeIn {
  0% { opacity: 0; transform: translateX(-6px); }
  40% { transform: translateX(3px); }
  100% { opacity: 1; transform: translateX(0); }
}
.error-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; font-weight: 600;
  color: #ef4444;
  margin-bottom: 4px;
}
.icon { font-size: 14px; }
.error-type {
  font-size: 10px; color: var(--text-faint);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  background: rgba(239, 68, 68, 0.1);
  padding: 1px 5px; border-radius: 3px;
}
.error-body {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
  white-space: pre-wrap;
  word-wrap: break-word;
}
</style>
