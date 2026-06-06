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
      <ConvAvatar type="supervisor" :size="20" />
      Supervisor · 调度计划
    </div>
    <div v-for="(task, i) in tasks" :key="i" :class="['task-item', task.status]">
      <div class="task-item-icon">
        <ConvAvatar :type="task.agent" :size="24" />
      </div>
      <div class="task-item-info">
        <div class="task-item-name">{{ task.task }}</div>
        <div class="task-item-bar">
          <div :class="['task-item-fill', task.status]"></div>
        </div>
      </div>
      <span :class="['task-item-status', task.status]">{{ STATUS_LABELS[task.status] || task.status }}</span>
    </div>
  </div>
</template>

<style scoped>
.task-board {
  align-self: flex-start; max-width: 85%; width: 100%;
  margin: 8px 0;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 14px; padding: 16px 16px;
  animation: msgIn 0.35s cubic-bezier(0.16,1,0.3,1) both;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.04);
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}
.task-board:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.12), inset 0 1px 0 rgba(255,255,255,0.04);
}
@keyframes msgIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.task-board-hdr {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--text-secondary); font-weight: 560;
  margin-bottom: 12px; padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
}

.task-item {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px; border-radius: 10px;
  margin-bottom: 6px; transition: all 0.3s cubic-bezier(0.34,1.56,0.64,1);
  border: 1px solid transparent;
  animation: taskItemIn 0.35s cubic-bezier(0.34,1.56,0.64,1) both;
}
.task-item:hover {
  transform: translateX(6px) scale(1.01);
  background: rgba(129,140,248,0.04);
}
.task-item.running {
  background: rgba(129,140,248,0.06);
  border-color: rgba(129,140,248,0.15);
  animation: taskItemIn 0.35s cubic-bezier(0.34,1.56,0.64,1) both, taskRunning 2s ease-in-out infinite;
}
.task-item.completed {
  background: rgba(52,211,153,0.04);
  border-color: rgba(52,211,153,0.1);
}
@keyframes taskItemIn {
  from { opacity: 0; transform: translateX(-12px); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes taskRunning {
  0%, 100% { border-color: rgba(129,140,248,0.15); }
  50% { border-color: rgba(129,140,248,0.35); }
}

.task-item-icon { width: 24px; height: 24px; flex-shrink: 0; }
.task-item-info { flex: 1; min-width: 0; }
.task-item-name { font-size: 14px; font-weight: 530; color: var(--text-primary); }
.task-item-bar {
  margin-top: 6px; height: 4px; border-radius: 2px;
  background: var(--bg-hover); overflow: hidden;
}
.task-item-fill {
  height: 100%; border-radius: 2px;
  transition: width 0.5s ease, background 0.3s, opacity 0.3s;
}
.task-item-fill.running {
  width: 0%;
  background: linear-gradient(90deg, #818cf8, #6366f1, #818cf8);
  background-size: 200% 100%;
  animation: taskProgress 1.8s ease-in-out forwards, shimmer 2s ease-in-out infinite;
}
.task-item-fill.completed { width: 100%; background: var(--color-green); }
@keyframes taskProgress {
  0% { width: 5%; opacity: 0.6; }
  50% { width: 65%; opacity: 1; }
  100% { width: 45%; opacity: 0.8; }
}
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.task-item-status {
  font-size: 12px; font-weight: 540; flex-shrink: 0;
  padding: 4px 10px; border-radius: 6px; letter-spacing: 0.3px;
}
.task-item-status.pending { color: var(--text-faint); }
.task-item-status.running { color: var(--accent); background: rgba(129,140,248,0.08); }
.task-item-status.completed { color: var(--color-green); background: rgba(52,211,153,0.08); }
</style>
