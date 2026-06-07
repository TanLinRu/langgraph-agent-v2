<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  steps: Array<{ agent: string; task: string }>
  reasoning?: string
  collapsed?: boolean
}>()

const isCollapsed = ref(props.collapsed ?? false)

const AGENT_COLORS: Record<string, string> = {
  supervisor: '#818cf8',
  coder: '#34d399',
  researcher: '#fbbf24',
  analyst: '#fb7185',
  direct: '#60a5fa',
  opencode: '#059669',
  'claude-agent': '#d97706',
}
function agentColor(name?: string): string {
  return AGENT_COLORS[name || ''] || 'var(--accent)'
}
</script>

<template>
  <div class="plan-card" :class="{ collapsed: isCollapsed }">
    <div class="plan-header" @click="isCollapsed = !isCollapsed">
      <div class="plan-icon">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
      </div>
      <span class="plan-title">执行计划</span>
      <span class="plan-step-count">{{ steps.length }} 个步骤</span>
      <span class="plan-toggle">{{ isCollapsed ? '展开' : '收起' }}</span>
    </div>
    <div v-if="!isCollapsed" class="plan-body">
      <div v-if="reasoning" class="plan-reasoning">{{ reasoning }}</div>
      <div class="plan-steps">
        <div v-for="(step, i) in steps" :key="i" class="plan-step-row">
          <div class="step-index" :style="{ background: agentColor(step.agent) }">{{ i + 1 }}</div>
          <div class="step-info">
            <span class="step-agent" :style="{ color: agentColor(step.agent) }">{{ step.agent }}</span>
            <span class="step-arrow">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
            </span>
            <span class="step-task">{{ step.task }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.plan-card {
  margin: 8px 0;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-card);
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.plan-card:hover {
  border-color: var(--border-accent);
  box-shadow: 0 4px 16px rgba(99,102,241,0.1);
}
.plan-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}
.plan-header:hover { background: var(--bg-glass); }
.plan-icon {
  display: flex; align-items: center;
  color: var(--accent);
  opacity: 0.7;
}
.plan-title {
  font-size: 13px; font-weight: 600;
  color: var(--text-primary);
}
.plan-step-count {
  margin-left: auto;
  font-size: 11px; color: var(--text-tertiary);
  background: var(--bg-glass); padding: 2px 8px;
  border-radius: 6px;
}
.plan-toggle {
  font-size: 11px; color: var(--accent-text);
  opacity: 0.7;
}
.plan-body {
  border-top: 1px solid var(--border);
  padding: 10px 14px;
  animation: planExpand 0.25s cubic-bezier(0.34,1.56,0.64,1) both;
}
@keyframes planExpand {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}
.plan-reasoning {
  font-size: 12px; color: var(--text-tertiary);
  margin-bottom: 10px;
  padding: 8px 10px;
  background: var(--bg-glass);
  border-radius: 8px;
  font-style: italic;
}
.plan-steps {
  display: flex; flex-direction: column; gap: 6px;
}
.plan-step-row {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 8px;
  border-radius: 8px;
  transition: background 0.2s ease;
}
.plan-step-row:hover { background: var(--bg-glass); }
.step-index {
  width: 22px; height: 22px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.step-info {
  display: flex; align-items: center; gap: 6px;
  flex: 1; min-width: 0;
}
.step-agent {
  font-size: 12px; font-weight: 600;
  white-space: nowrap;
  letter-spacing: 0.3px;
}
.step-arrow {
  display: flex; align-items: center;
  color: var(--text-tertiary);
  opacity: 0.5;
  flex-shrink: 0;
}
.step-task {
  font-size: 12px; color: var(--text-secondary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
