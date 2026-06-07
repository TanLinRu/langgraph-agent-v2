<script setup lang="ts">
defineProps<{
  from: string
  to: string
}>()

const LABELS: Record<string, string> = {
  supervisor: 'Supervisor',
  researcher: 'Researcher',
  coder: 'Coder',
  analyst: 'Analyst',
  writer: 'Writer',
  opencode: 'OpenCode',
  'claude-agent': 'Claude',
  direct: 'Direct',
}

function labelFor(agent: string): string {
  return LABELS[agent] || agent
}
</script>

<template>
  <div class="handoff-badge">
    <span class="icon">🔗</span>
    <span>从 <strong>{{ labelFor(from) }}</strong> 交接</span>
    <span class="arrow">→</span>
    <strong>{{ labelFor(to) }}</strong>
    <span class="suffix">· 接收任务</span>
  </div>
</template>

<style scoped>
.handoff-badge {
  display: inline-flex; align-items: center; gap: 6px;
  align-self: flex-start; margin: 4px 0 8px 0;
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-dim);
  animation: badgeIn 0.35s cubic-bezier(0.16, 1, 0.3, 1) both;
}
@keyframes badgeIn {
  from { opacity: 0; transform: translateX(-4px); }
  to { opacity: 1; transform: translateX(0); }
}
.handoff-badge .icon { font-size: 12px; }
.handoff-badge .arrow { color: #fbbf24; font-weight: 600; }
.handoff-badge strong { color: var(--text-primary); font-weight: 600; }
.handoff-badge .suffix { color: var(--text-faint); }
</style>
