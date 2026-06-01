<script setup lang="ts">
import { onMounted } from 'vue'
import { useAgentsStore } from '../stores/agents'

const store = useAgentsStore()

onMounted(() => {
  store.fetchTools()
})
</script>

<template>
  <div class="agents-tab">
    <h2>Available Tools</h2>
    <div class="tools-list">
      <div v-for="tool in store.tools" :key="tool.name" class="tool-card">
        <div class="tool-icon-s">⚙</div>
        <div class="tool-info-s">
          <div class="tool-name-s">{{ tool.name }}</div>
          <div class="tool-desc-s">{{ tool.description }}</div>
        </div>
      </div>
      <div v-if="store.tools.length === 0 && !store.isLoading" class="empty">
        No tools available. Make sure the server is running.
      </div>
    </div>
  </div>
</template>

<style scoped>
.agents-tab {
  padding: 18px;
  overflow-y: auto;
  height: 100%;
}

.agents-tab h2 {
  margin-bottom: 16px;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text-tertiary);
  font-weight: 650;
}

.tools-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-card {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 13px; border-radius: 9px;
  border: 1px solid var(--border-light);
  background: var(--bg-card);
  cursor: pointer; transition: all 0.15s;
}
.tool-card:hover { background: var(--bg-hover); }

.tool-icon-s {
  width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 7px; font-size: 15px; flex-shrink: 0;
}

.tool-info-s { flex: 1; min-width: 0; }
.tool-name-s {
  font-size: 14px; font-weight: 540; color: var(--accent-text);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.tool-desc-s {
  font-size: 13px; color: var(--text-tertiary); margin-top: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.empty {
  color: var(--text-muted);
  text-align: center;
  padding: 40px 20px;
  font-size: 13px;
}
</style>
