<script setup lang="ts">
import { computed } from 'vue'
import ConvAvatar from './ConvAvatar.vue'
import type { TaskUpdate, MetricsData } from '../utils/api'

const props = defineProps<{
  tasks: TaskUpdate[]
  metrics: MetricsData | null
}>()

const AGENT_COLORS: Record<string, string> = {
  supervisor: '#818cf8',
  coder: '#34d399',
  researcher: '#fbbf24',
  analyst: '#fb7185',
  writer: '#f472b6',
  direct: '#60a5fa',
  helper: '#a78bfa',
  opencode: '#059669',
  'claude-agent': '#d97706',
}

function color(agent: string): string {
  return AGENT_COLORS[agent] || 'var(--accent)'
}

function formatElapsed(ms?: number): string {
  if (!ms || ms < 0) return ''
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const sec = s % 60
  if (m < 60) return `${m}m${sec.toString().padStart(2, '0')}s`
  const h = Math.floor(m / 60)
  const min = m % 60
  return `${h}h${min.toString().padStart(2, '0')}m${sec.toString().padStart(2, '0')}s`
}

const STATUS_LABELS: Record<string, string> = {
  pending: '等待',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
}

function anim(t: TaskUpdate): 'breathe' | 'think' | 'work' {
  if (t.status === 'running') return 'work'
  if (t.status === 'pending') return 'think'
  return 'breathe'
}

function agentTokens(agent: string): { input: number; output: number } | null {
  if (!props.metrics?.tokens) return null
  const t = props.metrics.tokens[agent]
  return t ?? null
}
</script>

<template>
  <div class="agent-task-panel">
    <div
      v-for="(t, i) in tasks"
      :key="`${t.agent}::${t.task}::${i}`"
      :class="['task-row', t.status, t.state || '']"
      :style="{ '--agent-color': color(t.agent) }"
    >
      <div class="task-avatar">
        <ConvAvatar :type="t.agent" :size="24" :animated="anim(t)" />
      </div>
      <div class="task-info">
        <div class="task-name-row">
          <span class="task-agent-name" :style="{ color: color(t.agent) }">{{ t.agent }}</span>
          <span v-if="t.elapsedMs" class="task-elapsed">{{ formatElapsed(t.elapsedMs) }}</span>
        </div>
        <div class="task-bar">
          <div :class="['task-bar-fill', t.status]"></div>
        </div>
        <div class="task-meta-row">
          <span :class="['task-status', t.status]">{{ STATUS_LABELS[t.status] || t.status }}</span>
          <span v-if="agentTokens(t.agent)" class="task-tokens">
            {{ agentTokens(t.agent)!.input.toLocaleString() }} in · {{ agentTokens(t.agent)!.output.toLocaleString() }} out
          </span>
        </div>
      </div>
    </div>
    <div v-if="tasks.length === 0" class="task-empty">暂无调度任务</div>
  </div>
</template>

<style scoped>
.agent-task-panel {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
}

.task-row {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-secondary);
  border-left: 3px solid transparent;
  transition: all 0.25s;
}
.task-row.running {
  background: color-mix(in srgb, var(--agent-color, var(--accent)) 8%, transparent);
  border-left-color: var(--agent-color, var(--accent));
}
.task-row.completed {
  border-left-color: var(--color-green);
}
.task-row.failed {
  border-left-color: var(--color-red);
}

.task-avatar {
  width: 24px; height: 24px;
  flex-shrink: 0;
  margin-top: 2px;
}

.task-info {
  flex: 1;
  min-width: 0;
}

.task-name-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.task-agent-name {
  font-weight: 600;
  font-size: 12px;
}
.task-elapsed {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 10px;
  color: var(--text-faint);
  flex-shrink: 0;
}

.task-bar {
  height: 3px;
  background: var(--border-light);
  border-radius: 2px;
  overflow: hidden;
  margin: 4px 0;
}
.task-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
.task-bar-fill.running {
  width: 70%;
  background: var(--agent-color, var(--accent));
  animation: barPulse 1.2s ease-in-out infinite;
}
.task-bar-fill.completed {
  width: 100%;
  background: var(--color-green);
}
.task-bar-fill.failed {
  width: 30%;
  background: var(--color-red);
}
@keyframes barPulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}

.task-meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
}
.task-status {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--bg-card);
}
.task-status.running {
  color: var(--agent-color, var(--accent));
  font-weight: 600;
}
.task-status.completed {
  color: var(--color-green);
}
.task-status.failed {
  color: var(--color-red);
}
.task-status.pending {
  color: var(--text-faint);
}
.task-tokens {
  font-size: 10px;
  color: var(--text-faint);
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.task-empty {
  font-size: 12px;
  color: var(--text-faint);
  padding: 16px;
  text-align: center;
}
</style>
