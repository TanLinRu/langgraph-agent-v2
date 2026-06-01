<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAgentsStore } from '../stores/agents'
import { fetchAgents, updateAgentConfig, listTools, type AgentInfo } from '../utils/api'
import ConvAvatar from './ConvAvatar.vue'

const store = useAgentsStore()
const agents = ref<AgentInfo[]>([])
const selectedAgent = ref<string | null>(null)
const agentConfig = ref<Record<string, any>>({})
const tools = ref<Array<{ name: string; type: string; usage: number }>>([])
const saveStatus = ref<'idle' | 'saving' | 'saved'>('idle')

const AGENT_COLORS: Record<string, string> = {
  supervisor: '#818cf8',
  coder: '#34d399',
  researcher: '#fbbf24',
  analyst: '#fb7185',
  direct: '#60a5fa',
  helper: '#a78bfa',
}

async function loadAgents() {
  try {
    agents.value = await fetchAgents()
  } catch (e) {
    console.warn('[AgentsPanel] loadAgents failed:', e)
  }
}

async function loadTools() {
  try {
    tools.value = await listTools()
  } catch (e) {
    console.warn('[AgentsPanel] loadTools failed:', e)
  }
}

onMounted(() => {
  loadAgents()
  loadTools()
})

const groupedAgents = computed(() => {
  const groups: Record<string, AgentInfo[]> = { online: [], offline: [] }
  for (const a of agents.value) {
    if (a.enabled !== false) {
      groups.online.push(a)
    } else {
      groups.offline.push(a)
    }
  }
  return groups
})

function selectAgent(id: string) {
  if (selectedAgent.value === id) {
    selectedAgent.value = null
    return
  }
  selectedAgent.value = id
  const agent = agents.value.find(a => a.id === id)
  if (agent) {
    agentConfig.value = {
      name: agent.name,
      type: agent.type,
      desc: agent.desc,
      tools: agent.tools || [],
      system_prompt: agent.system_prompt || '',
      model: agent.model || '',
      temperature: agent.temperature ?? 0.7,
      max_tokens: agent.max_tokens ?? 4096,
      enabled: agent.enabled !== false,
    }
  }
}

async function saveConfig() {
  if (!selectedAgent.value) return
  saveStatus.value = 'saving'
  try {
    await updateAgentConfig(selectedAgent.value, agentConfig.value)
    saveStatus.value = 'saved'
    await loadAgents()
    setTimeout(() => { saveStatus.value = 'idle' }, 2000)
  } catch (e) {
    console.warn('[AgentsPanel] saveConfig failed:', e)
    saveStatus.value = 'idle'
  }
}

function resetConfig() {
  if (!selectedAgent.value) return
  const agent = agents.value.find(a => a.id === selectedAgent.value)
  if (agent) {
    agentConfig.value = {
      name: agent.name,
      type: agent.type,
      desc: agent.desc,
      tools: agent.tools || [],
      system_prompt: agent.system_prompt || '',
      model: agent.model || '',
      temperature: agent.temperature ?? 0.7,
      max_tokens: agent.max_tokens ?? 4096,
      enabled: agent.enabled !== false,
    }
  }
}

function getToolsForAgent(agentId: string): string[] {
  const agent = agents.value.find(a => a.id === agentId)
  return agent?.tools || []
}
</script>

<template>
  <div class="agents-panel">
    <!-- Agent list -->
    <template v-for="(list, status) in groupedAgents" :key="status">
      <div v-if="list.length" class="agent-group">
        <div class="agent-group-h">
          <span class="agent-group-dot" :style="{ background: status === 'online' ? 'var(--color-green)' : 'var(--text-faint)' }"></span>
          {{ status === 'online' ? 'ONLINE' : 'OFFLINE' }}
          <span class="agent-group-count">{{ list.length }}</span>
        </div>
        <div v-for="agent in list" :key="agent.id" class="agent-card" @click="selectAgent(agent.id)">
          <ConvAvatar :type="agent.type || agent.id" :size="36" />
          <div class="agent-info-s">
            <div class="agent-name-s">{{ agent.name }}</div>
            <div class="agent-desc-s">{{ agent.desc }}</div>
            <div class="agent-tools-s">
              <span v-for="t in getToolsForAgent(agent.id).slice(0, 3)" :key="t" class="tool-tag">{{ t }}</span>
              <span v-if="getToolsForAgent(agent.id).length > 3" class="tool-tag more">+{{ getToolsForAgent(agent.id).length - 3 }}</span>
            </div>
          </div>
          <span :class="['agent-status-s', status]">{{ status }}</span>
        </div>
      </div>
    </template>

    <!-- Agent config form -->
    <div v-if="selectedAgent" class="config-card">
      <div class="config-header">
        <button class="config-back-btn" @click="selectedAgent = null">←</button>
        <ConvAvatar :type="agentConfig.type || selectedAgent" :size="32" />
        <span class="config-header-title">{{ agentConfig.name }}</span>
        <span class="config-header-id">{{ selectedAgent }}</span>
      </div>

      <div class="config-row">
        <span class="config-label">Name</span>
        <input class="config-input-wide" v-model="agentConfig.name" />
      </div>
      <div class="config-row">
        <span class="config-label">Type</span>
        <select class="config-select" v-model="agentConfig.type">
          <option value="supervisor">Supervisor</option>
          <option value="coder">Coder</option>
          <option value="researcher">Researcher</option>
          <option value="analyst">Analyst</option>
          <option value="direct">Direct</option>
          <option value="helper">Helper</option>
        </select>
      </div>
      <div class="config-row">
        <span class="config-label">Description</span>
        <input class="config-input-wide" v-model="agentConfig.desc" />
      </div>
      <div class="config-row">
        <span class="config-label">Model</span>
        <select class="config-select" v-model="agentConfig.model">
          <option value="">Default</option>
          <option value="deepseek-r1">deepseek-r1</option>
          <option value="gpt-4o">gpt-4o</option>
          <option value="claude-sonnet">claude-sonnet</option>
        </select>
      </div>
      <div class="config-row">
        <span class="config-label">Temperature</span>
        <div class="config-slider-wrap">
          <input type="range" class="config-slider" min="0" max="2" step="0.1" v-model.number="agentConfig.temperature" />
          <span class="config-val">{{ agentConfig.temperature }}</span>
        </div>
      </div>
      <div class="config-row">
        <span class="config-label">Max tokens</span>
        <input class="config-input" type="number" v-model.number="agentConfig.max_tokens" />
      </div>
      <div class="config-row">
        <span class="config-label">Enabled</span>
        <button :class="['config-toggle', { on: agentConfig.enabled }]" @click="agentConfig.enabled = !agentConfig.enabled"></button>
      </div>

      <div class="config-row">
        <span class="config-label">System Prompt</span>
      </div>
      <textarea class="config-textarea" v-model="agentConfig.system_prompt" rows="4"></textarea>

      <div class="config-actions">
        <button class="config-btn" @click="resetConfig">Reset</button>
        <button class="config-btn primary" @click="saveConfig" :disabled="saveStatus === 'saving'">
          {{ saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? 'Saved!' : 'Save' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agents-panel { padding: 0; }
.agent-group { margin-bottom: 16px; }
.agent-group-h {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 0 8px; cursor: pointer; user-select: none;
  font-size: 13px; text-transform: uppercase; letter-spacing: 0.7px; font-weight: 620;
  border-bottom: 1px solid var(--border-light); color: var(--text-tertiary);
}
.agent-group-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.agent-group-count {
  font-size: 13px; font-weight: 400; margin-left: auto;
  background: var(--bg-hover); padding: 0 8px; border-radius: 4px; color: var(--text-faint);
}
.agent-card {
  display: flex; align-items: center; gap: 14px; padding: 12px 0;
  cursor: pointer; transition: opacity 0.2s;
}
.agent-card:hover { opacity: 0.85; }
.agent-info-s { flex: 1; min-width: 0; }
.agent-name-s { font-size: 15px; font-weight: 550; color: var(--text-primary); }
.agent-desc-s { font-size: 13px; color: var(--text-tertiary); margin-top: 3px; }
.agent-tools-s { display: flex; gap: 4px; margin-top: 4px; flex-wrap: wrap; }
.tool-tag {
  font-size: 10px; padding: 2px 6px; border-radius: 4px;
  background: var(--accent-bg); color: var(--accent-text);
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.tool-tag.more { background: var(--bg-hover); color: var(--text-muted); }
.agent-status-s { font-size: 13px; flex-shrink: 0; }
.agent-status-s.online { color: var(--color-green); }
.agent-status-s.offline { color: var(--text-faint); }


/* Config card */
.config-card {
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: 11px; padding: 16px; margin-top: 12px;
  border-left: 2px solid var(--border); transition: border-color 0.2s;
}
.config-card:hover { border-left-color: var(--accent-border); }
.config-header {
  display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
  padding-bottom: 12px; border-bottom: 1px solid var(--border-light);
}
.config-back-btn {
  width: 28px; height: 28px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-glass-hover); border: 1px solid var(--border-light);
  border-radius: 6px; color: var(--text-secondary); font-size: 15px;
  cursor: pointer; transition: all 0.15s; line-height: 1;
}
.config-back-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.config-header-title { font-size: 15px; font-weight: 560; color: var(--text-primary); }
.config-header-id { margin-left: auto; font-size: 11px; color: var(--text-faint); font-family: 'SF Mono', 'Fira Code', monospace; }
.config-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; }
.config-row + .config-row { border-top: 1px solid var(--border-light); }
.config-label { font-size: 14px; color: var(--text-secondary); white-space: nowrap; }
.config-select {
  padding: 5px 9px; min-width: 0; flex-shrink: 0;
  background: var(--bg-glass-hover); border: 1px solid var(--border-strong); border-radius: 7px;
  color: var(--text-primary); font-size: 14px; outline: none;
  font-family: 'SF Mono', 'Fira Code', monospace; max-width: 50%;
}
.config-input {
  background: var(--bg-glass-hover); color: var(--text-primary);
  border: 1px solid var(--border-strong); border-radius: 7px;
  padding: 5px 9px; font-size: 14px; font-family: 'SF Mono', monospace;
  width: 80px; text-align: right; outline: none; flex-shrink: 0;
}
.config-input-wide {
  background: var(--bg-glass-hover); color: var(--text-primary);
  border: 1px solid var(--border-strong); border-radius: 7px;
  padding: 5px 9px; font-size: 14px; outline: none; flex: 1; max-width: 60%;
}
.config-textarea {
  width: 100%; padding: 8px 10px; margin-top: 4px;
  background: var(--bg-glass-hover); color: var(--text-primary);
  border: 1px solid var(--border-strong); border-radius: 7px;
  font-size: 13px; font-family: 'SF Mono', monospace; outline: none;
  resize: vertical;
}
.config-slider-wrap { display: flex; align-items: center; gap: 8px; }
.config-slider {
  -webkit-appearance: none; appearance: none;
  height: 3px; background: var(--bg-hover); border-radius: 2px; outline: none; width: 90px;
}
.config-slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%;
  background: #818cf8; cursor: pointer; box-shadow: 0 0 10px rgba(129,140,248,0.3);
}
.config-val { font-size: 13px; color: var(--accent-text); font-family: 'SF Mono', monospace; min-width: 26px; text-align: right; }
.config-toggle {
  position: relative; width: 38px; height: 22px; flex-shrink: 0;
  background: var(--border-strong); border-radius: 11px; cursor: pointer; transition: background 0.25s; border: none;
}
.config-toggle.on { background: var(--bg-accent-xstrong); }
.config-toggle::after {
  content: ''; position: absolute; top: 2.5px; left: 2.5px;
  width: 17px; height: 17px; border-radius: 50%;
  background: var(--text-secondary); transition: transform 0.25s cubic-bezier(0.34,1.56,0.64,1);
}
.config-toggle.on::after { transform: translateX(16px); background: #fff; }
.config-actions { display: flex; gap: 8px; margin-top: 16px; }
.config-btn {
  flex: 1; padding: 9px 0; border-radius: 8px;
  font-size: 13px; font-weight: 520; cursor: pointer;
  border: 1px solid var(--border-strong);
  background: var(--bg-glass); color: var(--text-tertiary); transition: all 0.2s;
}
.config-btn:hover { background: var(--bg-glass-hover); color: var(--text-secondary); }
.config-btn.primary { background: var(--accent-bg); border-color: var(--accent-border); color: var(--accent-text); }
.config-btn.primary:hover { background: var(--accent-bg-hover); }
</style>
