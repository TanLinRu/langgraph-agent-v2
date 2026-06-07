<script setup lang="ts">
import { ref } from 'vue'
import MonitorPanel from './MonitorPanel.vue'
import AgentsPanel from './AgentsPanel.vue'
import ToolsPanel from './ToolsPanel.vue'
import FileExplorer from './FileExplorer.vue'
import WorkflowsPanel from './WorkflowsPanel.vue'
import EvalPanel from './EvalPanel.vue'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ toggle: [] }>()

const activeTab = ref<'monitor' | 'agents' | 'tools' | 'files' | 'workflows' | 'eval'>('monitor')

const tabs = [
  { id: 'monitor' as const, label: 'Monitor', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>' },
  { id: 'agents' as const, label: 'Agents', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>' },
  { id: 'tools' as const, label: 'Tools', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>' },
  { id: 'files' as const, label: 'Files', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>' },
  { id: 'workflows' as const, label: 'Workflows', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>' },
  { id: 'eval' as const, label: 'Eval', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>' },
]
</script>

<template>
  <div class="right-panel-inner">
    <div class="panel-tabs-wrap">
    <div class="panel-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="['panel-tab', { active: activeTab === tab.id }]"
        @click="activeTab = tab.id"
      >
        <span class="panel-tab-icon" v-html="tab.icon"></span>
        {{ tab.label }}
      </button>
    </div>
      <button class="collapse-btn" @click="emit('toggle')" :title="open ? 'Collapse panel' : 'Expand panel'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
             :style="{ transform: open ? 'rotate(0deg)' : 'rotate(180deg)' }">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </button>
    </div>
    <div class="panel-body">
      <MonitorPanel v-if="activeTab === 'monitor'" />
      <AgentsPanel v-if="activeTab === 'agents'" />
      <ToolsPanel v-if="activeTab === 'tools'" />
      <FileExplorer v-if="activeTab === 'files'" />
      <WorkflowsPanel v-if="activeTab === 'workflows'" />
      <EvalPanel v-if="activeTab === 'eval'" />
    </div>
  </div>
</template>

<style scoped>
.right-panel-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.panel-tabs-wrap {
  display: flex; border-bottom: 1px solid var(--border); flex-shrink: 0;
  align-items: stretch;
}
.panel-tabs {
  display: flex; flex: 1; min-width: 0;
  overflow-x: auto; overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
}
.panel-tabs::-webkit-scrollbar { height: 3px; }
.panel-tabs::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
.panel-tab {
  flex: 0 0 auto; padding: 14px 8px;
  background: transparent; border: none;
  color: var(--text-tertiary); font-size: 13px; font-weight: 530;
  cursor: pointer; transition: all 0.25s; letter-spacing: 0.3px;
  border-bottom: 2px solid transparent;
  display: flex; align-items: center; justify-content: center; gap: 5px;
}
.panel-tab:hover { color: var(--text-secondary); }
.panel-tab.active { color: var(--accent-text); border-bottom-color: var(--accent); }
.panel-tab-icon { width: 14px; height: 14px; flex-shrink: 0; opacity: 0.5; transition: opacity 0.2s; display: inline-flex; }
.panel-tab.active .panel-tab-icon { opacity: 0.8; }
.panel-tab:hover .panel-tab-icon { opacity: 0.6; }
.collapse-btn {
  flex-shrink: 0; background: none; border: none; color: var(--text-muted);
  cursor: pointer; padding: 0 8px; display: flex; align-items: center;
  transition: all 0.2s; border-bottom: 2px solid transparent;
}
.collapse-btn:hover {
  color: var(--text-secondary);
}
.collapse-btn svg {
  transition: transform 0.3s cubic-bezier(0.16,1,0.3,1);
}

.panel-body {
  flex: 1; overflow-y: auto; padding: 18px;
}
.panel-body > * {
  animation: tabSwitch 0.3s cubic-bezier(0.16,1,0.3,1) both;
}
@keyframes tabSwitch {
  from { opacity: 0; transform: translateY(6px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
