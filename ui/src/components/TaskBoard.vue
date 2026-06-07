<script setup lang="ts">
import ConvAvatar from './ConvAvatar.vue'

export interface TaskItem {
  agent: string
  task: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  state?: 'idle' | 'thinking' | 'working' | 'delegating' | 'aggregating' | 'done' | 'failed'
  startedAt?: number
  endedAt?: number
  elapsedMs?: number
}

defineProps<{
  tasks: TaskItem[]
}>()

const STATUS_LABELS: Record<string, string> = {
  pending: '等待',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
}
</script>

<template>
  <div v-if="tasks.length" class="task-board">
    <div class="task-board-hdr">
      <div class="task-board-icon-wrap">
        <ConvAvatar type="supervisor" :size="20" />
      </div>
      <div class="task-board-title">Supervisor · 调度计划</div>
      <div class="task-board-status">
        <span class="status-dot" :class="{ active: tasks.some(t => t.status === 'running') }"></span>
        {{ tasks.filter(t => t.status === 'completed').length }}/{{ tasks.length }}
      </div>
    </div>
    <div v-for="(task, i) in tasks" :key="i" :class="['task-item', task.status]">
      <div class="task-item-icon">
        <ConvAvatar :type="task.agent" :size="26" />
      </div>
      <div class="task-item-info">
        <div class="task-item-name">{{ task.task }}</div>
        <div class="task-item-sub">{{ task.agent }}</div>
        <div class="task-item-bar">
          <div :class="['task-item-fill', task.status]"></div>
        </div>
      </div>
      <div :class="['task-item-status', task.status]">
        <span class="status-text">{{ STATUS_LABELS[task.status] || task.status }}</span>
        <span v-if="task.elapsedMs" class="status-time">{{ (task.elapsedMs / 1000).toFixed(1) }}s</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-board {
  align-self: flex-start; max-width: 85%; width: 100%;
  margin: 10px 0;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 16px; 
  padding: 18px 18px;
  animation: taskBoardIn 0.4s cubic-bezier(0.34,1.56,0.64,1) both;
  box-shadow: 0 4px 20px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,0.04);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}
.task-board::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), rgba(99,102,241,0.3), transparent);
}
.task-board:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 32px rgba(0,0,0,0.1), inset 0 1px 0 rgba(255,255,255,0.04);
}
@keyframes taskBoardIn {
  from { opacity: 0; transform: translateY(10px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.task-board-hdr {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 14px; 
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}
.task-board-icon-wrap {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(99,102,241,0.15), rgba(129,140,248,0.1));
  border-radius: 8px;
}
.task-board-title {
  font-size: 13.5px; 
  color: var(--text-secondary); 
  font-weight: 560;
  flex: 1;
}
.task-board-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  font-family: 'SF Mono', monospace;
  font-weight: 500;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-faint);
  transition: all 0.3s ease;
}
.status-dot.active {
  background: var(--accent);
  animation: statusPulse 1.5s ease-in-out infinite;
}
@keyframes statusPulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(99,102,241,0.4); }
  50% { opacity: 0.7; box-shadow: 0 0 0 6px rgba(99,102,241,0); }
}

.task-item {
  display: flex; 
  align-items: center; 
  gap: 14px;
  padding: 12px 14px; 
  border-radius: 12px;
  margin-bottom: 8px; 
  transition: all 0.3s cubic-bezier(0.34,1.56,0.64,1);
  border: 1px solid transparent;
  animation: taskItemIn 0.35s cubic-bezier(0.34,1.56,0.64,1) both;
}
.task-item:last-child {
  margin-bottom: 0;
}
.task-item:hover {
  transform: translateX(8px) scale(1.005);
  background: rgba(129,140,248,0.03);
  border-color: rgba(129,140,248,0.1);
}
.task-item.running {
  background: rgba(129,140,248,0.06);
  border-color: rgba(129,140,248,0.18);
  animation: taskItemIn 0.35s cubic-bezier(0.34,1.56,0.64,1) both, taskRunning 2.5s ease-in-out infinite;
}
.task-item.completed {
  background: rgba(52,211,153,0.04);
  border-color: rgba(52,211,153,0.12);
}
.task-item.failed {
  background: rgba(239,68,68,0.04);
  border-color: rgba(239,68,68,0.12);
}
@keyframes taskItemIn {
  from { opacity: 0; transform: translateX(-14px); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes taskRunning {
  0%, 100% { border-color: rgba(129,140,248,0.18); box-shadow: 0 0 12px rgba(129,140,248,0.08); }
  50% { border-color: rgba(129,140,248,0.35); box-shadow: 0 0 20px rgba(129,140,248,0.12); }
}

.task-item-icon { 
  width: 26px; 
  height: 26px; 
  flex-shrink: 0; 
}
.task-item-info { 
  flex: 1; 
  min-width: 0; 
}
.task-item-name { 
  font-size: 14.5px; 
  font-weight: 530; 
  color: var(--text-primary); 
}
.task-item-sub {
  font-size: 12px;
  color: var(--text-faint);
  margin-top: 2px;
}
.task-item-bar {
  margin-top: 8px; 
  height: 5px; 
  border-radius: 3px;
  background: var(--bg-hover); 
  overflow: hidden;
  position: relative;
}
.task-item-fill {
  height: 100%; 
  border-radius: 3px;
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1), background 0.3s, opacity 0.3s;
  position: relative;
}
.task-item-fill::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
  animation: barShimmer 2s ease-in-out infinite;
}
@keyframes barShimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
.task-item-fill.running {
  width: 0%;
  background: linear-gradient(90deg, #818cf8, #6366f1, #818cf8);
  background-size: 200% 100%;
  animation: taskProgress 2s ease-in-out forwards, shimmer 2.5s ease-in-out infinite;
}
.task-item-fill.completed { 
  width: 100%; 
  background: linear-gradient(90deg, #34d399, #10b981);
}
.task-item-fill.failed { 
  width: 100%; 
  background: linear-gradient(90deg, #ef4444, #dc2626);
}
@keyframes taskProgress {
  0% { width: 8%; opacity: 0.6; }
  30% { width: 35%; opacity: 1; }
  60% { width: 55%; opacity: 0.9; }
  100% { width: 45%; opacity: 0.85; }
}
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.task-item-status {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  flex-shrink: 0;
}
.status-text {
  font-size: 12px; 
  font-weight: 540; 
  padding: 5px 12px; 
  border-radius: 8px; 
  letter-spacing: 0.3px;
}
.status-time {
  font-size: 11px;
  color: var(--text-faint);
  font-family: 'SF Mono', monospace;
}
.task-item-status.pending .status-text { 
  color: var(--text-faint); 
  background: var(--bg-hover);
}
.task-item-status.running .status-text { 
  color: var(--accent); 
  background: rgba(129,140,248,0.1);
}
.task-item-status.completed .status-text { 
  color: var(--color-green); 
  background: rgba(52,211,153,0.1);
}
.task-item-status.failed .status-text { 
  color: var(--color-red); 
  background: rgba(239,68,68,0.1);
}
</style>
