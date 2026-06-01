<script setup lang="ts">
import { computed } from 'vue'
import ConvAvatar from './ConvAvatar.vue'

interface TaskItem {
  agent: string
  task: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  elapsedMs?: number
  startedAt?: number
}

const props = defineProps<{
  tasks: TaskItem[]
  flashing?: Set<string>
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

const AGENT_LABELS: Record<string, string> = {
  supervisor: 'Supervisor',
  coder: 'Coder',
  researcher: 'Researcher',
  analyst: 'Analyst',
  writer: 'Writer',
  direct: 'Direct',
  helper: 'Helper',
  opencode: 'OpenCode',
  'claude-agent': 'Claude',
}

function color(agent: string): string {
  return AGENT_COLORS[agent] || 'var(--accent)'
}

function label(agent: string): string {
  return AGENT_LABELS[agent] || agent
}

function taskKey(t: TaskItem): string {
  return `${t.agent}::${t.task}`
}

// Layout config
const NODE_W = 64   // worker node width
const NODE_H = 64   // worker node height
const SUP_W = 80    // supervisor node width
const SUP_H = 80    // supervisor node height
const TOP_PAD = 16
const BOTTOM_PAD = 16
const SIDE_PAD = 12
const ROW_GAP = 70  // vertical gap between supervisor row and worker row
const COL_GAP_MIN = 12

// Compute layout: 1 row if <=5 workers, 2 rows if more
const layout = computed(() => {
  const n = props.tasks.length
  if (n === 0) return null

  // Use a reference container width assumption (we set viewBox to this)
  const VB_W = 520
  let rows: TaskItem[][]

  if (n <= 5) {
    rows = [props.tasks]
  } else if (n <= 10) {
    const half = Math.ceil(n / 2)
    rows = [props.tasks.slice(0, half), props.tasks.slice(half)]
  } else {
    const third = Math.ceil(n / 3)
    rows = [
      props.tasks.slice(0, third),
      props.tasks.slice(third, third * 2),
      props.tasks.slice(third * 2),
    ]
  }

  const rowCount = rows.length
  const rowHeight = NODE_H + 24 // node + label space
  const VB_H = TOP_PAD + SUP_H + ROW_GAP + rowHeight * rowCount + BOTTOM_PAD

  // For each row, compute x positions
  const rowLayouts = rows.map((row) => {
    const count = row.length
    const totalNodeW = count * NODE_W + (count - 1) * COL_GAP_MIN
    const startX = Math.max(SIDE_PAD, (VB_W - totalNodeW) / 2)
    return row.map((t, i) => {
      const x = startX + i * (NODE_W + COL_GAP_MIN)
      // y for this row (first row starts right after the supervisor + gap)
      const rowIdx = rows.indexOf(row)
      const y = TOP_PAD + SUP_H + ROW_GAP + rowIdx * rowHeight
      return { task: t, x, y }
    })
  })

  // Supervisor position: centered, top
  const supX = (VB_W - SUP_W) / 2
  const supY = TOP_PAD

  // Edges: from supervisor bottom-center to each worker top-center
  const supCenterX = supX + SUP_W / 2
  const supBottomY = supY + SUP_H
  const edges = rowLayouts.flat().map(({ task, x, y }) => ({
    task,
    fromX: supCenterX,
    fromY: supBottomY,
    toX: x + NODE_W / 2,
    toY: y,
  }))

  return {
    VB_W,
    VB_H,
    supX, supY, supW: SUP_W, supH: SUP_H,
    rowLayouts,
    edges,
  }
})

function statusColor(t: TaskItem): string {
  if (t.status === 'running') return color(t.agent)
  if (t.status === 'completed') return '#34d399'
  if (t.status === 'failed') return '#ef4444'
  return 'var(--text-faint)'
}

function nodeAnim(t: TaskItem): 'breathe' | 'think' | 'work' | 'wave' {
  switch (t.status) {
    case 'running': return 'work'
    case 'pending': return 'think'
    case 'completed': return 'breathe'
    case 'failed': return 'breathe'
    default: return 'breathe'
  }
}

function truncTask(s: string, n = 16): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}

function formatElapsed(ms?: number): string {
  if (!ms || ms < 0) return ''
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m${(s % 60).toString().padStart(2, '0')}s`
}

const supAnim = computed(() => {
  const anyRunning = props.tasks.some(t => t.status === 'running')
  if (anyRunning) return 'wave'
  const allDone = props.tasks.every(t => t.status === 'completed' || t.status === 'failed')
  if (allDone && props.tasks.length > 0) return 'breathe'
  return 'think'
})
</script>

<template>
  <div v-if="layout" class="task-graph">
    <svg
      class="task-graph-svg"
      :viewBox="`0 0 ${layout.VB_W} ${layout.VB_H}`"
      preserveAspectRatio="xMidYMid meet"
    >
      <!-- Edges (rendered first, so nodes overlay) -->
      <g class="edges">
        <line
          v-for="(e, i) in layout.edges"
          :key="`bg-${i}`"
          :x1="e.fromX" :y1="e.fromY" :x2="e.toX" :y2="e.toY"
          class="edge-bg"
        />
        <line
          v-for="(e, i) in layout.edges"
          :key="`fg-${i}`"
          :x1="e.fromX" :y1="e.fromY" :x2="e.toX" :y2="e.toY"
          :class="['edge-fg', e.task.status, e.task.status === 'running' ? 'active' : '']"
          :stroke="statusColor(e.task)"
        />
      </g>

      <!-- Supervisor node -->
      <g class="sup-node" :transform="`translate(${layout.supX}, ${layout.supY})`">
        <rect
          :width="layout.supW" :height="layout.supH" rx="14"
          class="sup-rect"
        />
        <foreignObject x="14" y="10" :width="layout.supW - 28" :height="40">
          <div class="sup-avatar-wrap">
            <ConvAvatar type="supervisor" :size="40" :animated="supAnim" />
          </div>
        </foreignObject>
        <text :x="layout.supW / 2" :y="layout.supH - 12" class="sup-label" text-anchor="middle">Supervisor</text>
      </g>

      <!-- Worker nodes -->
      <g
        v-for="(item, i) in layout.rowLayouts.flat()"
        :key="`w-${i}`"
        :transform="`translate(${item.x}, ${item.y})`"
        :class="['worker-node', item.task.status, props.flashing?.has(taskKey(item.task)) ? 'flash-success' : '']"
      >
        <rect :width="NODE_W" :height="NODE_H" rx="12" class="worker-rect" :stroke="statusColor(item.task)" />
        <foreignObject x="10" y="8" :width="NODE_W - 20" :height="32">
          <div class="worker-avatar-wrap" :style="{ '--c': color(item.task.agent) }">
            <ConvAvatar :type="item.task.agent" :size="30" :animated="nodeAnim(item.task)" />
          </div>
        </foreignObject>
        <text :x="NODE_W / 2" :y="NODE_H - 18" class="worker-name" text-anchor="middle" :fill="color(item.task.agent)">
          {{ label(item.task.agent) }}
        </text>
        <text :x="NODE_W / 2" :y="NODE_H - 4" class="worker-task" text-anchor="middle">
          {{ truncTask(item.task.task) }}
        </text>
      </g>
    </svg>

    <!-- Status legend -->
    <div class="task-legend">
      <div
        v-for="(t, i) in tasks"
        :key="`leg-${i}`"
        class="legend-item"
      >
        <span class="legend-dot" :style="{ background: statusColor(t) }"></span>
        <span class="legend-name">{{ label(t.agent) }} · {{ t.status === 'running' ? '执行中' : t.status === 'completed' ? '已完成' : t.status === 'failed' ? '失败' : '等待' }}</span>
        <span v-if="t.elapsedMs" class="legend-elapsed">⏱ {{ formatElapsed(t.elapsedMs) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-graph {
  display: flex; flex-direction: column; gap: 6px;
}
.task-graph-svg {
  width: 100%;
  height: auto;
  display: block;
}

/* Edges */
.edge-bg {
  stroke: var(--border-light);
  stroke-width: 1.5;
  stroke-dasharray: 4 4;
  fill: none;
}
.edge-fg {
  stroke-width: 2;
  stroke-dasharray: 5 4;
  fill: none;
  opacity: 0;
  transition: opacity 0.3s;
}
.edge-fg.running {
  opacity: 0.9;
  animation: edgeDash 1.0s linear infinite;
}
.edge-fg.completed { opacity: 0.4; stroke-dasharray: 0; }
.edge-fg.failed { opacity: 0.4; stroke-dasharray: 0; }
.edge-fg.pending { opacity: 0.2; stroke-dasharray: 4 4; }
@keyframes edgeDash {
  to { stroke-dashoffset: -18; }
}

/* Supervisor */
.sup-rect {
  fill: var(--bg-message);
  stroke: var(--accent);
  stroke-width: 1.5;
}
.sup-avatar-wrap {
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 100%;
  overflow: hidden;
}
.sup-label {
  font-size: 10px;
  font-weight: 600;
  fill: var(--accent);
  letter-spacing: 0.3px;
}

/* Worker node */
.worker-rect {
  fill: var(--bg-message);
  stroke-width: 1.5;
  transition: stroke 0.3s;
}
.worker-node.completed .worker-rect { fill: rgba(52, 211, 153, 0.06); }
.worker-node.failed .worker-rect { fill: rgba(239, 68, 68, 0.06); }
.worker-node.flash-success .worker-rect {
  animation: nodeFlash 1.2s ease-out;
}
@keyframes nodeFlash {
  0% { fill: rgba(52, 211, 153, 0.3); }
  100% { fill: var(--bg-message); }
}
.worker-avatar-wrap {
  --c: var(--accent);
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 100%;
  overflow: hidden;
  border-radius: 50%;
  position: relative;
}
.worker-node.running .worker-avatar-wrap::after {
  content: '';
  position: absolute; inset: 0;
  border-radius: 50%;
  border: 1.5px solid var(--c);
  opacity: 0;
  animation: avatarScan 1.4s ease-out infinite;
  box-sizing: border-box;
}
@keyframes avatarScan {
  0% { opacity: 0.8; transform: scale(0.85); }
  100% { opacity: 0; transform: scale(1.25); }
}
.worker-name {
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.2px;
}
.worker-task {
  font-size: 8.5px;
  fill: var(--text-faint);
}

/* Legend */
.task-legend {
  display: flex; flex-direction: column; gap: 2px;
  padding-top: 4px;
  border-top: 1px dashed var(--border-light);
}
.legend-item {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  padding: 1px 0;
}
.legend-dot {
  width: 6px; height: 6px; border-radius: 50%;
  flex-shrink: 0;
}
.legend-name { flex: 1; }
.legend-elapsed {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 10px;
  color: var(--text-faint);
}
</style>
