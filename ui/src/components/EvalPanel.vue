<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  listEvalCases, buildEvalCases, runEvalCase, runAllEval,
  listEvalRuns, getEvalTrend, listEvalSuggestions, runEvalAnalysis,
} from '../utils/api'
import type { EvalCase, EvalRun, EvalSuggestion } from '../utils/api/types'

const cases = ref<EvalCase[]>([])
const runs = ref<EvalRun[]>([])
const suggestions = ref<EvalSuggestion[]>([])
const loading = ref(false)
const running = ref<Set<string>>(new Set())
const selectedCase = ref<string | null>(null)
const expandedCase = ref<string | null>(null)
const activeSubTab = ref<'cases' | 'runs' | 'suggestions'>('cases')
const trend = ref<{ total: number; passed: number; rate: number } | null>(null)
const statusMsg = ref<string | null>(null)
let statusTimer: ReturnType<typeof setTimeout> | undefined

function flashStatus(msg: string) {
  statusMsg.value = msg
  if (statusTimer) clearTimeout(statusTimer)
  statusTimer = setTimeout(() => { statusMsg.value = null }, 4000)
}

async function loadAll() {
  loading.value = true
  try {
    cases.value = await listEvalCases()
    runs.value = await listEvalRuns()
    suggestions.value = await listEvalSuggestions()
  } catch (e) { console.error('eval load error', e) }
  loading.value = false
}

async function handleBuild() {
  loading.value = true
  try {
    const r = await buildEvalCases(50)
    await loadAll()
  } catch (e) { console.error('build error', e) }
  loading.value = false
}

async function handleRunAll() {
  loading.value = true
  try {
    const r = await runAllEval(true)
    await loadAll()
  } catch (e) { console.error('run-all error', e) }
  loading.value = false
}

async function handleRunCase(caseId: string) {
  running.value.add(caseId)
  try {
    const r = await runEvalCase(caseId, true)
    const failCount = r.failures?.length || 0
    flashStatus(r.passed ? `PASS: ${caseId}` : `FAIL: ${caseId} (${failCount} failures)`)
    await loadAll()
  } catch (e: any) {
    flashStatus(e?.message || 'Run failed')
  }
  running.value.delete(caseId)
}

async function handleAnalyze() {
  loading.value = true
  try {
    await runEvalAnalysis(7)
    await loadAll()
  } catch (e) { console.error('analyze error', e) }
  loading.value = false
}

async function handleTrend(caseId: string) {
  try {
    trend.value = await getEvalTrend(caseId)
  } catch (e) { console.error('trend error', e) }
}

function toggleCase(id: string) {
  expandedCase.value = expandedCase.value === id ? null : id
  if (expandedCase.value === id) {
    handleTrend(id)
  }
}

function caseStatus(c: EvalCase): 'pass' | 'fail' | 'unknown' {
  const lastRun = latestRun(c)
  if (!lastRun) return 'unknown'
  return lastRun.passed ? 'pass' : 'fail'
}

function latestRun(c: EvalCase): EvalRun | undefined {
  return runs.value.find(r => r.case_id === c.case_id)
}

const passRate = computed(() => {
  if (runs.value.length === 0) return 0
  return runs.value.filter(r => r.passed).length / runs.value.length
})

onMounted(loadAll)
</script>

<template>
  <div class="eval-panel">
    <!-- Status line -->
    <div v-if="statusMsg" class="eval-status-msg">{{ statusMsg }}</div>
    <!-- Toolbar -->
    <div class="eval-toolbar">
      <button class="eval-btn" @click="loadAll" :disabled="loading" title="Refresh">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
        </svg>
      </button>
      <button class="eval-btn eval-btn-primary" @click="handleBuild" :disabled="loading">Build Cases</button>
      <button class="eval-btn eval-btn-accent" @click="handleRunAll" :disabled="loading">Run All</button>
      <button class="eval-btn" @click="handleAnalyze" :disabled="loading">Analyze</button>
    </div>

    <!-- Sub-tabs -->
    <div class="eval-subtabs">
      <button :class="['eval-subtab', { active: activeSubTab === 'cases' }]" @click="activeSubTab = 'cases'">
        Cases ({{ cases.length }})
      </button>
      <button :class="['eval-subtab', { active: activeSubTab === 'runs' }]" @click="activeSubTab = 'runs'">
        Runs ({{ runs.length }})
      </button>
      <button :class="['eval-subtab', { active: activeSubTab === 'suggestions' }]" @click="activeSubTab = 'suggestions'">
        Suggestions ({{ suggestions.length }})
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="eval-loading">Loading...</div>

    <!-- Cases Tab -->
    <div v-else-if="activeSubTab === 'cases'" class="eval-cases">
      <div v-if="cases.length === 0" class="eval-empty">
        <div class="eval-empty-text">No eval cases yet</div>
        <div class="eval-empty-hint">Click "Build Cases" (all sessions) or "+Session" (current chat)</div>
      </div>
      <div v-for="c in cases" :key="c.case_id" class="eval-case-row" :class="caseStatus(c)" @click="toggleCase(c.case_id)">
        <div class="eval-case-header">
          <span class="eval-case-status-dot"></span>
          <span v-if="caseStatus(c) === 'pass'" class="eval-case-badge pass">PASS</span>
          <span v-else-if="caseStatus(c) === 'fail'" class="eval-case-badge fail">FAIL</span>
          <span v-else class="eval-case-badge unknown">—</span>
          <span class="eval-case-id">{{ c.case_id }}</span>
          <span class="eval-case-tags">{{ c.tags?.join(', ') }}</span>
          <span v-if="running.has(c.case_id)" class="eval-spinner"></span>
          <button class="eval-run-btn" :class="caseStatus(c)" :disabled="running.has(c.case_id)" @click.stop="handleRunCase(c.case_id)">
            <template v-if="running.has(c.case_id)">…</template>
            <template v-else-if="caseStatus(c) === 'pass'">PASS</template>
            <template v-else-if="caseStatus(c) === 'fail'">FAIL</template>
            <template v-else>Run</template>
          </button>
        </div>
        <div class="eval-case-task">{{ c.task.slice(0, 100) }}{{ c.task.length > 100 ? '...' : '' }}</div>
        <div v-if="expandedCase === c.case_id" class="eval-case-detail">
          <div class="eval-detail-section">
            <div class="eval-detail-label">Expectations</div>
            <div class="eval-detail-grid">
              <div>Tools: {{ c.expected.must_call_tools?.join(', ') || '—' }}</div>
              <div>Language: {{ c.expected.language || '—' }}</div>
              <div>Min output: {{ c.expected.min_output_length || '—' }}</div>
              <div>Plan steps: {{ c.expected.plan_steps ?? '—' }}</div>
              <div>Forbid hallucinated refs: {{ c.expected.forbid_hallucinated_refs ? 'Yes' : 'No' }}</div>
              <div>Must contain: {{ c.expected.must_contain?.slice(0, 3).join(', ') || '—' }}</div>
            </div>
          </div>
          <div v-if="latestRun(c) && latestRun(c)!.failures.length > 0" class="eval-detail-section">
            <div class="eval-detail-label">Failures ({{ latestRun(c)!.failures.length }})</div>
            <div class="eval-failure-list">
              <div v-for="f in latestRun(c)!.failures" :key="f.assertion" class="eval-failure-item-detail">
                <span class="eval-fail-icon">✗</span>
                <span class="eval-fail-name">{{ f.assertion }}</span>
                <span class="eval-fail-desc">{{ f.detail }}</span>
              </div>
            </div>
          </div>
          <div v-if="trend" class="eval-detail-section">
            <div class="eval-detail-label">Trend (30d)</div>
            <div class="eval-trend-bar">
              <div class="eval-trend-pass" :style="{ flex: trend.passed }"></div>
              <div class="eval-trend-fail" :style="{ flex: trend.total - trend.passed }"></div>
            </div>
            <div class="eval-trend-text">{{ trend.passed }}/{{ trend.total }} ({{ (trend.rate * 100).toFixed(0) }}%)</div>
          </div>
          <div class="eval-detail-section">
            <div class="eval-detail-label">Source</div>
            <div class="eval-detail-source">{{ c.source_type }}{{ c.source_session_id ? ' · ' + c.source_session_id.slice(0, 12) + '…' : '' }}</div>
          </div>
        </div>
      </div>
      <div class="eval-summary-bar">
        Pass rate: <strong>{{ (passRate * 100).toFixed(0) }}%</strong> ({{ runs.filter(r => r.passed).length }}/{{ runs.length }})
      </div>
    </div>

    <!-- Runs Tab -->
    <div v-else-if="activeSubTab === 'runs'" class="eval-runs">
      <div v-if="runs.length === 0" class="eval-empty">
        <div class="eval-empty-text">No runs yet</div>
      </div>
      <div v-for="r in runs" :key="r.task_id" class="eval-run-row" :class="r.passed ? 'pass' : 'fail'">
        <div class="eval-run-header">
          <span class="eval-run-status">{{ r.passed ? 'PASS' : 'FAIL' }}</span>
          <span class="eval-run-case">{{ r.case_id }}</span>
          <span class="eval-run-date">{{ r.created_at?.slice(0, 10) }}</span>
        </div>
        <div v-if="r.failures.length > 0" class="eval-run-failures">
          <div v-for="f in r.failures" :key="f.assertion" class="eval-failure-item">
            <span class="eval-fail-icon">✗</span>
            {{ f.assertion }}: {{ f.detail }}
          </div>
        </div>
      </div>
    </div>

    <!-- Suggestions Tab -->
    <div v-else-if="activeSubTab === 'suggestions'" class="eval-suggestions">
      <div v-if="suggestions.length === 0" class="eval-empty">
        <div class="eval-empty-text">No suggestions yet</div>
        <div class="eval-empty-hint">Click "Analyze" to generate optimization suggestions</div>
      </div>
      <div v-for="s in suggestions" :key="s.id" class="eval-suggestion-row" :class="{ dim: s.dismissed || s.applied }">
        <div class="eval-sug-header">
          <span class="eval-sug-dimension" :class="'dim-' + s.dimension">{{ s.dimension }}</span>
          <span class="eval-sug-conf">{{ (s.confidence * 100).toFixed(0) }}%</span>
          <span v-if="s.applied" class="eval-sug-badge applied">Applied</span>
          <span v-else-if="s.dismissed" class="eval-sug-badge dismissed">Dismissed</span>
        </div>
        <div class="eval-sug-target">{{ s.target }}</div>
        <div class="eval-sug-desc">{{ s.reasoning }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.eval-panel { height: 100%; display: flex; flex-direction: column; font-size: 13px; }
.eval-status-msg { background: var(--accent-bg); color: var(--accent-text); padding: 6px 12px; font-size: 12px; border-radius: 4px; margin-bottom: 6px; animation: fadeIn 0.2s; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
.eval-toolbar { display: flex; gap: 6px; flex-wrap: wrap; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
.eval-btn { padding: 6px 12px; background: var(--bg-hover); border: 1px solid var(--border); border-radius: 6px; color: var(--text-secondary); font-size: 12px; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; gap: 4px; }
.eval-btn:hover:not(:disabled) { border-color: var(--border-accent); }
.eval-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.eval-btn-primary { background: var(--accent-bg); color: var(--accent-text); }
.eval-btn-accent { background: rgba(52,211,153,0.12); color: #34d399; border-color: rgba(52,211,153,0.3); }
.eval-subtabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 8px; }
.eval-subtab { padding: 8px 12px; background: none; border: none; color: var(--text-muted); font-size: 12px; cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s; }
.eval-subtab.active { color: var(--accent-text); border-bottom-color: var(--accent); }
.eval-subtab:hover { color: var(--text-secondary); }
.eval-loading { text-align: center; padding: 40px; color: var(--text-faint); }
.eval-empty { text-align: center; padding: 40px 20px; }
.eval-empty-text { font-size: 14px; color: var(--text-secondary); margin-bottom: 6px; }
.eval-empty-hint { font-size: 12px; color: var(--text-faint); }
.eval-cases, .eval-runs, .eval-suggestions { flex: 1; overflow-y: auto; overflow-x: hidden; }

/* Case rows */
.eval-case-row { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 6px; cursor: pointer; transition: all 0.2s; border-left: 3px solid var(--text-faint); }
.eval-case-row.pass { border-left-color: #34d399; }
.eval-case-row.fail { border-left-color: #ef4444; }
.eval-case-row:hover { border-color: var(--border-accent); }
.eval-case-header { display: flex; align-items: center; gap: 8px; }
.eval-case-status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--text-faint); }
.eval-case-row.pass .eval-case-status-dot { background: #34d399; }
.eval-case-row.fail .eval-case-status-dot { background: #ef4444; }
.eval-case-badge { font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 4px; letter-spacing: 0.5px; }
.eval-case-badge.pass { background: rgba(52,211,153,0.15); color: #34d399; }
.eval-case-badge.fail { background: rgba(239,68,68,0.15); color: #ef4444; }
.eval-case-badge.unknown { background: var(--bg-hover); color: var(--text-faint); }
.eval-case-id { font-weight: 560; color: var(--text-primary); font-size: 13px; }
.eval-case-tags { font-size: 11px; color: var(--text-faint); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.eval-run-btn { padding: 3px 10px; background: var(--accent-bg); border: none; border-radius: 4px; color: var(--accent-text); font-size: 11px; cursor: pointer; font-weight: 600; }
.eval-run-btn.pass { background: rgba(52,211,153,0.15); color: #34d399; }
.eval-run-btn.fail { background: rgba(239,68,68,0.15); color: #ef4444; }
.eval-run-btn:disabled { opacity: 0.5; }
.eval-case-task { font-size: 12px; color: var(--text-muted); margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Detail */
.eval-case-detail { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border-light); }
.eval-detail-section { margin-bottom: 8px; }
.eval-detail-label { font-size: 11px; font-weight: 600; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.3px; margin-bottom: 4px; }
.eval-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 3px 12px; font-size: 11px; color: var(--text-muted); }
.eval-detail-source { font-size: 11px; color: var(--text-muted); font-family: monospace; }
.eval-failure-list { margin-top: 2px; }
.eval-failure-item-detail { display: flex; align-items: flex-start; gap: 6px; padding: 4px 0; font-size: 11px; color: #ef4444; border-bottom: 1px solid var(--border-light); }
.eval-failure-item-detail:last-child { border-bottom: none; }
.eval-fail-name { font-weight: 600; flex-shrink: 0; min-width: 80px; }
.eval-fail-desc { color: var(--text-secondary); word-break: break-word; }

/* Trend bar */
.eval-trend-bar { display: flex; height: 6px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; margin-bottom: 3px; }
.eval-trend-pass { background: #34d399; }
.eval-trend-fail { background: #ef4444; }
.eval-trend-text { font-size: 11px; color: var(--text-muted); }

/* Summary bar */
.eval-summary-bar { position: sticky; bottom: 0; padding: 8px 0; background: var(--bg-card); border-top: 1px solid var(--border); font-size: 12px; color: var(--text-muted); text-align: center; }

/* Run rows */
.eval-run-row { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 6px; border-left: 3px solid var(--text-faint); }
.eval-run-row.pass { border-left-color: #34d399; }
.eval-run-row.fail { border-left-color: #ef4444; }
.eval-run-header { display: flex; align-items: center; gap: 8px; }
.eval-run-status { font-size: 11px; font-weight: 630; padding: 1px 6px; border-radius: 3px; }
.eval-run-row.pass .eval-run-status { color: #34d399; background: rgba(52,211,153,0.1); }
.eval-run-row.fail .eval-run-status { color: #ef4444; background: rgba(239,68,68,0.1); }
.eval-run-case { font-weight: 500; color: var(--text-primary); font-size: 12px; flex: 1; }
.eval-run-date { font-size: 11px; color: var(--text-faint); }
.eval-run-failures { margin-top: 6px; }
.eval-failure-item { font-size: 11px; color: #ef4444; padding: 2px 0; }
.eval-fail-icon { margin-right: 4px; }

/* Suggestion rows */
.eval-suggestion-row { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-bottom: 6px; }
.eval-suggestion-row.dim { opacity: 0.5; }
.eval-sug-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.eval-sug-dimension { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 3px; text-transform: uppercase; }
.dim-prompt { background: rgba(129,140,248,0.12); color: #818cf8; }
.dim-agent { background: rgba(52,211,153,0.12); color: #34d399; }
.dim-workflow { background: rgba(251,191,36,0.12); color: #fbbf24; }
.dim-context { background: rgba(96,165,250,0.12); color: #60a5fa; }
.dim-skill { background: rgba(167,139,250,0.12); color: #a78bfa; }
.eval-sug-conf { font-size: 11px; color: var(--text-faint); margin-left: auto; }
.eval-sug-badge { font-size: 10px; padding: 1px 6px; border-radius: 3px; }
.eval-sug-badge.applied { background: rgba(52,211,153,0.1); color: #34d399; }
.eval-sug-badge.dismissed { background: rgba(148,163,184,0.1); color: #94a3b8; }
.eval-sug-target { font-size: 12px; font-weight: 500; color: var(--text-primary); }
.eval-sug-desc { font-size: 11px; color: var(--text-muted); margin-top: 3px; }

.eval-spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid var(--text-faint); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
