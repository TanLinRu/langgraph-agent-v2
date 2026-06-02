<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useChatStore } from '../stores/chat'
import ConvAvatar from './ConvAvatar.vue'
import PhaseHeader from './PhaseHeader.vue'
import DispatchIndicator from './DispatchIndicator.vue'
import AgentTaskPanel from './AgentTaskPanel.vue'
import EventLog from './EventLog.vue'

const chat = useChatStore()

// Session timer
const sessionElapsedMs = ref(0)
let sessionTimer: ReturnType<typeof setInterval> | null = null
const sessionStart = ref(Date.now())

onMounted(() => {
  sessionTimer = setInterval(() => {
    sessionElapsedMs.value = Date.now() - sessionStart.value
  }, 1000)
})
onUnmounted(() => {
  if (sessionTimer) clearInterval(sessionTimer)
})

function formatTime(ms: number): string {
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
  if (m > 0) return `${m}:${sec.toString().padStart(2, '0')}`
  return `${sec}s`
}

// Metrics from SSE events
const metrics = computed(() => chat.metrics)

const processingMs = computed(() => metrics.value?.elapsed_ms ?? 0)
const agentCalls = computed(() => metrics.value?.agent_calls ?? 0)
const tokenBreakdown = computed(() => metrics.value?.tokens ?? {})
const totalTokens = computed(() => {
  let total = 0
  for (const agent of Object.values(tokenBreakdown.value)) {
    total += (agent.input || 0) + (agent.output || 0)
  }
  return total
})
const estimatedCost = computed(() => (totalTokens.value * 0.000003).toFixed(4))

// Task items from SSE events
const taskItems = computed(() => chat.taskItems)
const eventLog = computed(() => chat.eventLog)
const currentPhase = computed(() => chat.currentPhase)
const currentDispatch = computed(() => chat.currentDispatch)

// Flash tracking for agent completion events
const completedTaskKeys = ref<Set<string>>(new Set())
let flashTimers: Map<string, ReturnType<typeof setTimeout>> = new Map()

watch(() => chat.taskItems, (newItems, oldItems) => {
  if (!oldItems) return
  for (const n of newItems) {
    const prev = oldItems.find(o => o.agent === n.agent && o.task === n.task)
    if (prev && prev.status === 'running' && n.status === 'completed') {
      const key = `${n.agent}::${n.task}`
      completedTaskKeys.value.add(key)
      const prevTimer = flashTimers.get(key)
      if (prevTimer) clearTimeout(prevTimer)
      const t = setTimeout(() => {
        completedTaskKeys.value.delete(key)
        completedTaskKeys.value = new Set(completedTaskKeys.value)
        flashTimers.delete(key)
      }, 1200)
      flashTimers.set(key, t)
    }
  }
}, { deep: true })

onUnmounted(() => {
  for (const t of flashTimers.values()) clearTimeout(t)
  flashTimers.clear()
})
</script>

<template>
  <div class="monitor-panel">
    <!-- Runtime -->
    <div class="monitor-section">
      <div class="monitor-section-title">运行时</div>
      <div class="monitor-card" style="--mc-color: var(--accent)">
        <div class="monitor-row">
          <span class="monitor-label">
            <svg class="monitor-label-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            会话时间
          </span>
          <span class="monitor-value accent">{{ formatTime(sessionElapsedMs) }}</span>
        </div>
        <div class="monitor-row">
          <span class="monitor-label">
            <svg class="monitor-label-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            处理耗时
          </span>
          <span class="monitor-value">{{ processingMs > 0 ? formatTime(processingMs) : '—' }}</span>
        </div>
        <div class="monitor-row">
          <span class="monitor-label">
            <svg class="monitor-label-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            Agent 调用
          </span>
          <span class="monitor-value">{{ agentCalls }}</span>
        </div>
      </div>
    </div>

    <!-- Sub-task scheduling (card view) -->
    <div v-if="taskItems.length || currentPhase" class="monitor-section">
      <div class="monitor-section-title">子任务调度</div>
      <div class="monitor-card monitor-card-tasks" style="--mc-color: var(--color-green)">
        <PhaseHeader :phase="currentPhase" />
        <DispatchIndicator :dispatch="currentDispatch" />
        <AgentTaskPanel :tasks="taskItems" :metrics="metrics" />
      </div>
      <div class="monitor-card monitor-card-log" style="--mc-color: var(--accent)">
        <div class="monitor-section-subtitle">事件日志</div>
        <EventLog :entries="eventLog" />
      </div>
    </div>

    <!-- Token consumption -->
    <div class="monitor-section">
      <div class="monitor-section-title">Token 消耗</div>
      <div class="monitor-card" style="--mc-color: #fbbf24">
        <div v-for="(agent, name) in tokenBreakdown" :key="name" class="monitor-agent-row">
          <div class="monitor-agent-icon">
            <ConvAvatar :type="name as string" :size="28" />
          </div>
          <div class="monitor-agent-info">
            <div class="monitor-agent-name">{{ name }}</div>
            <div class="monitor-agent-tokens">in {{ agent.input || 0 }} · out {{ agent.output || 0 }}</div>
            <div class="monitor-bar-wrap">
              <div class="monitor-bar-fill thinking" :style="{ width: totalTokens > 0 ? ((agent.input + agent.output) / totalTokens * 100) + '%' : '0%' }"></div>
            </div>
          </div>
          <div class="monitor-agent-right">
            <div class="monitor-agent-total">{{ ((agent.input || 0) + (agent.output || 0)).toLocaleString() }}</div>
            <div class="monitor-agent-ms">{{ agent.ms || 0 }}ms</div>
          </div>
        </div>
        <div v-if="Object.keys(tokenBreakdown).length === 0" class="monitor-empty">暂无数据</div>
      </div>
    </div>

    <!-- Summary -->
    <div class="monitor-section">
      <div class="monitor-section-title">汇总</div>
      <div class="monitor-card" style="--mc-color: var(--color-amber)">
        <div class="monitor-row">
          <span class="monitor-label">总 Token</span>
          <span class="monitor-value accent">{{ totalTokens.toLocaleString() }}</span>
        </div>
        <div class="monitor-row">
          <span class="monitor-label">预估费用</span>
          <span class="monitor-value">${{ estimatedCost }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.monitor-panel { padding: 0; }

.monitor-section { margin-bottom: 16px; }
.monitor-section-title {
  font-size: 13px; text-transform: uppercase; letter-spacing: 0.8px;
  color: var(--text-tertiary); margin-bottom: 8px; font-weight: 650;
}
.monitor-section-subtitle {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--text-faint); margin-bottom: 4px; font-weight: 600;
}
.monitor-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: 11px; padding: 12px 0;
  margin-bottom: 10px;
  border-left: 2px solid var(--mc-color, var(--border));
  overflow: hidden;
}
.monitor-card-tasks {
  padding: 0;
}
.monitor-card-log {
  padding: 10px 0;
}
.monitor-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 7px 14px; border-bottom: 1px solid var(--border-light);
}
.monitor-row:last-child { border-bottom: none; }
.monitor-label {
  font-size: 14px; color: var(--text-secondary);
  display: flex; align-items: center; gap: 7px;
}
.monitor-label-icon { width: 16px; height: 16px; flex-shrink: 0; }
.monitor-value {
  font-size: 14px; color: var(--text-primary);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-weight: 500;
}
.monitor-value.accent { color: var(--accent-text); }

/* Agent breakdown */
.monitor-agent-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 14px; border-bottom: 1px solid var(--border-light);
}
.monitor-agent-row:last-child { border-bottom: none; }
.monitor-agent-icon { width: 28px; height: 28px; flex-shrink: 0; }
.monitor-agent-info { flex: 1; min-width: 0; }
.monitor-agent-name { font-size: 15px; font-weight: 560; color: var(--text-secondary); }
.monitor-agent-tokens { font-size: 14px; font-weight: 550; color: var(--text-muted); margin-top: 2px; }
.monitor-agent-right { text-align: right; flex-shrink: 0; }
.monitor-agent-total { font-size: 14px; font-weight: 600; color: var(--accent-text); font-family: 'SF Mono', monospace; }
.monitor-agent-ms { font-size: 14px; font-weight: 500; color: var(--text-muted); }

/* Bar */
.monitor-bar-wrap { height: 4px; background: var(--bg-hover); border-radius: 2px; margin-top: 4px; overflow: hidden; }
.monitor-bar-fill { height: 100%; border-radius: 2px; transition: width 0.6s ease; }
.monitor-bar-fill.thinking { background: linear-gradient(90deg,#818cf8,#6366f1); }

.monitor-empty { font-size: 12px; color: var(--text-faint); padding: 8px 14px; text-align: center; }
</style>
