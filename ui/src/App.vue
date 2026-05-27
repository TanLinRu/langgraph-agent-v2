<script setup lang="ts">
import { ref } from 'vue'
import AgentsTab from './components/AgentsTab.vue'
import ChatTab from './components/ChatTab.vue'

const currentTab = ref<'chat' | 'agents'>('chat')
</script>

<template>
  <div class="app">
    <div class="bg-orbs">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
    </div>
    <header class="header">
      <h1>LangGraph Agent v2</h1>
      <nav class="nav">
        <button :class="{ active: currentTab === 'chat' }" @click="currentTab = 'chat'">Chat</button>
        <button :class="{ active: currentTab === 'agents' }" @click="currentTab = 'agents'">Agents</button>
      </nav>
    </header>
    <main class="main">
      <ChatTab v-if="currentTab === 'chat'" />
      <AgentsTab v-if="currentTab === 'agents'" />
    </main>
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #0a0a1a;
  color: rgba(255, 255, 255, 0.9);
  overflow: hidden;
}

.app {
  height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
}

/* ── Animated background orbs ──────────────────────────────────── */
.bg-orbs {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.5;
  animation: float 20s ease-in-out infinite;
}

.orb-1 {
  width: 400px; height: 400px;
  background: radial-gradient(circle, #6366f1, #8b5cf6);
  top: -10%; left: -5%;
  animation-duration: 22s;
}

.orb-2 {
  width: 350px; height: 350px;
  background: radial-gradient(circle, #06b6d4, #3b82f6);
  bottom: -10%; right: -5%;
  animation-duration: 18s;
  animation-delay: -5s;
}

.orb-3 {
  width: 300px; height: 300px;
  background: radial-gradient(circle, #ec4899, #f43f5e);
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  animation-duration: 25s;
  animation-delay: -10s;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  25% { transform: translate(30px, -40px) scale(1.05); }
  50% { transform: translate(-20px, 20px) scale(0.95); }
  75% { transform: translate(15px, 35px) scale(1.02); }
}

/* ── Glass header ──────────────────────────────────────────────── */
.header {
  position: relative;
  z-index: 10;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  gap: 24px;
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.header h1 {
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(135deg, #c7d2fe, #a5b4fc);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.nav { display: flex; gap: 4px; }

.nav button {
  padding: 6px 16px;
  border: 1px solid transparent;
  background: transparent;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  border-radius: 8px;
  font-size: 14px;
  transition: all 0.2s;
}

.nav button:hover {
  color: rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.05);
}

.nav button.active {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.12);
  color: #fff;
  backdrop-filter: blur(12px);
}

.main { flex: 1; overflow: hidden; position: relative; z-index: 1; }

/* ── Scrollbar ─────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.15); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.25); }
</style>
