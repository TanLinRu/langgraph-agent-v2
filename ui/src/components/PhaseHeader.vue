<script setup lang="ts">
import type { TaskPhaseUpdate } from '../utils/api'

defineProps<{
  phase: TaskPhaseUpdate | null
}>()
</script>

<template>
  <div v-if="phase" class="phase-header">
    <span class="phase-badge">{{ phase.step }}/{{ phase.totalSteps }}</span>
    <span class="phase-desc">{{ phase.description }}</span>
  </div>
</template>

<style scoped>
.phase-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  background: rgba(251, 191, 36, 0.05);
  border-bottom: 1px solid var(--border-light);
  font-size: 12px;
  color: var(--accent-text);
  animation: phaseIn 0.3s ease;
}
@keyframes phaseIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.phase-badge {
  background: var(--bg-card);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 10px;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.phase-desc {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
