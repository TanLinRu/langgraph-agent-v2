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
        <div class="tool-icon">⚙</div>
        <h3>{{ tool.name }}</h3>
        <p>{{ tool.description }}</p>
      </div>
      <div v-if="store.tools.length === 0 && !store.isLoading" class="empty">
        No tools available. Make sure the server is running.
      </div>
    </div>
  </div>
</template>

<style scoped>
.agents-tab {
  padding: 28px;
  overflow-y: auto;
  height: 100%;
}

.agents-tab h2 {
  margin-bottom: 20px;
  font-size: 16px;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.5px;
}

.tools-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.tool-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 20px;
  transition: all 0.25s;
}

.tool-card:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.15);
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.tool-icon {
  font-size: 24px;
  margin-bottom: 12px;
  opacity: 0.6;
}

.tool-card h3 {
  font-size: 14px;
  color: #818cf8;
  margin-bottom: 8px;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.tool-card p {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
  line-height: 1.5;
}

.empty {
  color: rgba(255, 255, 255, 0.3);
  text-align: center;
  padding: 60px;
  grid-column: 1 / -1;
}
</style>
