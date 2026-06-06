<script setup lang="ts">
import { ref, provide, onMounted } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatTab from './components/ChatTab.vue'
import RightPanel from './components/RightPanel.vue'
import Resizer from './components/Resizer.vue'
import FileDrawer from './components/FileDrawer.vue'
import SessionCreateModal from './components/SessionCreateModal.vue'
import { useSessionsStore } from './stores/sessions'

const sessions = useSessionsStore()
const sidebarOpen = ref(true)
const rightPanelOpen = ref(true)
const rightPanelWidth = ref(360)
const drawerOpen = ref(false)
const drawerPath = ref('')
const showCreateModal = ref(false)

// Initialize sessions BEFORE any child component mounts
onMounted(async () => {
  await sessions.initSession()
})

function handleResize(newWidth: number) {
  rightPanelWidth.value = newWidth
}

function openFileDrawer(path: string) {
  drawerPath.value = path
  drawerOpen.value = true
}

function closeFileDrawer() {
  drawerOpen.value = false
}

function openCreateModal() {
  showCreateModal.value = true
}

function closeCreateModal() {
  showCreateModal.value = false
}

// Provide file click handler + create modal trigger to all descendants
provide('openFile', openFileDrawer)
provide('openCreateModal', openCreateModal)
</script>

<template>
  <div class="app">
    <div class="bg-orbs">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="orb orb-3"></div>
    </div>
    <Sidebar :open="sidebarOpen" @toggle="sidebarOpen = !sidebarOpen" />
    <div class="center-col">
      <!-- Floating sidebar toggle when collapsed -->
      <button v-if="!sidebarOpen" class="sidebar-reveal-btn" @click="sidebarOpen = true" title="Expand sidebar">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </button>
      <!-- Floating right-panel toggle when collapsed -->
      <button v-if="!rightPanelOpen" class="rightpanel-reveal-btn" @click="rightPanelOpen = true" title="Expand panel">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
      </button>
      <ChatTab />
    </div>
    <Resizer v-if="rightPanelOpen" :minWidth="300" :maxWidth="600" @resize="handleResize" />
    <div class="right-panel" :class="{ collapsed: !rightPanelOpen }"
         :style="rightPanelOpen ? { width: rightPanelWidth + 'px', minWidth: rightPanelWidth + 'px' } : {}">
      <RightPanel :open="rightPanelOpen" @toggle="rightPanelOpen = !rightPanelOpen" />
    </div>
    <FileDrawer :open="drawerOpen" :initialPath="drawerPath" @close="closeFileDrawer" />
    <SessionCreateModal v-if="showCreateModal" @close="closeCreateModal" />
  </div>
</template>

<style>
/* ═══════════════════════════════════════════════════════════════
   Theme System — CSS Variables (from agent-workspace.html)
   ═══════════════════════════════════════════════════════════════ */
* { margin: 0; padding: 0; box-sizing: border-box; }

:root, [data-theme="dark"] {
  --bg-app: #0e0e18;
  --bg-glass: rgba(255,255,255,0.045);
  --bg-glass-hover: rgba(255,255,255,0.09);
  --bg-surface: #11111d;
  --bg-card: rgba(255,255,255,0.07);
  --bg-input: rgba(255,255,255,0.09);
  --bg-hover: rgba(255,255,255,0.10);
  --bg-active: rgba(99,102,241,0.16);
  --bg-elevated: rgba(255,255,255,0.12);
  --bg-accent-strong: rgba(99,102,241,0.25);
  --bg-accent-xstrong: rgba(99,102,241,0.55);
  --bg-accent-hover: rgba(99,102,241,0.35);
  --bg-overlay: rgba(0,0,0,0.25);
  --bg-code: rgba(0,0,0,0.35);
  --border: rgba(255,255,255,0.11);
  --border-light: rgba(255,255,255,0.08);
  --border-input: rgba(255,255,255,0.12);
  --border-strong: rgba(255,255,255,0.15);
  --border-accent: rgba(99,102,241,0.18);
  --border-accent-soft: rgba(99,102,241,0.14);
  --border-purple: rgba(129,140,248,0.12);
  --text-primary: #f0f0f0;
  --text-secondary: #b8b8b4;
  --text-tertiary: #9c9c98;
  --text-muted: #78787a;
  --text-faint: #606062;
  --accent: #818cf8;
  --accent-text: #a5b4fc;
  --accent-bg: rgba(99,102,241,0.12);
  --accent-bg-hover: rgba(99,102,241,0.2);
  --accent-bg-strong: rgba(99,102,241,0.25);
  --accent-border: rgba(99,102,241,0.18);
  --accent-focus: rgba(99,102,241,0.3);
  --color-green: #34d399;
  --color-green-text: #6ee7b7;
  --color-amber: #fbbf24;
  --color-red: #f87171;
  --glass-blur: 32px;
  --avatar-border: #12121e;
  --orb-opacity: 0.4;
  --scrollbar-thumb: rgba(255,255,255,0.12);
  --scrollbar-thumb-hover: rgba(255,255,255,0.2);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
  --shadow-md: 0 4px 16px rgba(0,0,0,0.15);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.2);
}
[data-theme="light"] {
  --bg-app: #f0f0f5;
  --bg-glass: rgba(255,255,255,0.25);
  --bg-glass-hover: rgba(255,255,255,0.35);
  --bg-surface: rgba(255,255,255,0.55);
  --bg-card: rgba(255,255,255,0.35);
  --bg-input: rgba(255,255,255,0.30);
  --bg-hover: rgba(255,255,255,0.08);
  --bg-active: rgba(99,102,241,0.12);
  --bg-elevated: rgba(255,255,255,0.45);
  --bg-accent-strong: rgba(99,102,241,0.20);
  --bg-accent-xstrong: rgba(99,102,241,0.40);
  --bg-accent-hover: rgba(99,102,241,0.25);
  --bg-overlay: rgba(255,255,255,0.35);
  --bg-code: rgba(255,255,255,0.08);
  --border: rgba(0,0,0,0.06);
  --border-light: rgba(0,0,0,0.04);
  --border-input: rgba(0,0,0,0.08);
  --border-strong: rgba(0,0,0,0.09);
  --border-accent: rgba(99,102,241,0.2);
  --border-accent-soft: rgba(99,102,241,0.15);
  --border-purple: rgba(129,140,248,0.15);
  --text-primary: #111114;
  --text-secondary: #4a4a50;
  --text-tertiary: #727278;
  --text-muted: #98989e;
  --text-faint: #b8b8be;
  --accent: #6366f1;
  --accent-text: #6366f1;
  --accent-bg: rgba(99,102,241,0.08);
  --accent-bg-hover: rgba(99,102,241,0.15);
  --accent-bg-strong: rgba(99,102,241,0.2);
  --accent-border: rgba(99,102,241,0.2);
  --accent-focus: rgba(99,102,241,0.35);
  --color-green: #059669;
  --color-green-text: #047857;
  --color-amber: #d97706;
  --color-red: #dc2626;
  --avatar-border: rgba(255,255,255,0.8);
  --glass-blur: 32px;
  --orb-opacity: 0.15;
  --scrollbar-thumb: rgba(0,0,0,0.1);
  --scrollbar-thumb-hover: rgba(0,0,0,0.18);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 16px rgba(0,0,0,0.06);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.08);
}

/* ── Base ── */
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'SF Pro Display', Roboto, 'Noto Sans SC', sans-serif;
  font-size: 16px;
  background: var(--bg-app);
  color: var(--text-primary);
  overflow: hidden;
  height: 100vh;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}

/* ── Animated background orbs ── */
.bg-orbs {
  position: fixed; inset: 0; z-index: 0; overflow: hidden; pointer-events: none;
}
.orb {
  position: absolute; border-radius: 50%; filter: blur(80px);
  opacity: var(--orb-opacity);
  animation: orbFloat 24s ease-in-out infinite;
  will-change: transform;
}
.orb-1 {
  width: 420px; height: 420px;
  background: radial-gradient(circle, #6366f1, #8b5cf6);
  top: -12%; left: -8%;
  animation-duration: 22s;
  animation-delay: 0s;
}
.orb-2 {
  width: 360px; height: 360px;
  background: radial-gradient(circle, #818cf8, #6366f1);
  bottom: -8%; right: -5%;
  animation-duration: 19s;
  animation-delay: -6s;
}
.orb-3 {
  width: 280px; height: 280px;
  background: radial-gradient(circle, #a78bfa, #818cf8);
  top: 40%; left: 45%;
  animation-duration: 26s;
  animation-delay: -12s;
  opacity: 0.2;
}
.orb-4 {
  width: 200px; height: 200px;
  background: radial-gradient(circle, #c084fc, #a78bfa);
  top: 20%; right: 20%;
  animation-duration: 18s;
  animation-delay: -8s;
  opacity: 0.15;
  filter: blur(60px);
}
@keyframes orbFloat {
  0%, 100% { transform: translate(0, 0) scale(1) rotate(0deg); }
  20% { transform: translate(40px, -50px) scale(1.08) rotate(5deg); }
  40% { transform: translate(-30px, 30px) scale(0.94) rotate(-3deg); }
  60% { transform: translate(25px, 40px) scale(1.04) rotate(2deg); }
  80% { transform: translate(-20px, -25px) scale(1.02) rotate(-4deg); }
}

/* Subtle grid overlay */
.bg-orbs::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size: 60px 60px;
  animation: gridFade 8s ease-in-out infinite;
}
@keyframes gridFade {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0.8; }
}

/* ── App layout: 3-column ── */
.app {
  position: relative; z-index: 1;
  display: flex;
  height: 100vh;
}

/* ── Center column ── */
.center-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}

/* ── Sidebar reveal button (when collapsed) ── */
.sidebar-reveal-btn {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  z-index: 100; width: 28px; height: 64px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 4px;
  background: var(--bg-glass); border: 1px solid var(--border);
  border-left: none; border-radius: 0 8px 8px 0;
  color: var(--text-muted); cursor: pointer;
  transition: all 0.2s;
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
}
.sidebar-reveal-btn:hover { background: var(--bg-hover); color: var(--text-secondary); }
.sidebar-reveal-btn svg { transition: transform 0.2s; }
.sidebar-reveal-btn:hover svg { transform: translateX(2px); }

/* ── Right panel reveal button (when collapsed) ── */
.rightpanel-reveal-btn {
  position: absolute; right: 0; top: 50%; transform: translateY(-50%);
  z-index: 100; width: 28px; height: 64px;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-glass); border: 1px solid var(--border);
  border-right: none; border-radius: 8px 0 0 8px;
  color: var(--text-muted); cursor: pointer;
  transition: all 0.2s;
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
}
.rightpanel-reveal-btn:hover { background: var(--bg-hover); color: var(--text-secondary); }
.rightpanel-reveal-btn svg { transition: transform 0.2s; }
.rightpanel-reveal-btn:hover svg { transform: translateX(-2px); }

/* ── Right panel (placeholder, will be replaced in Phase 4) ── */
.right-panel {
  width: 360px; min-width: 360px;
  background: var(--bg-glass);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.3s cubic-bezier(0.16,1,0.3,1),
              min-width 0.3s cubic-bezier(0.16,1,0.3,1),
              opacity 0.3s ease, margin 0.3s ease;
  animation: slideInR 0.5s cubic-bezier(0.16,1,0.3,1) both;
  animation-delay: 0.08s;
}
.right-panel.collapsed {
  width: 0 !important; min-width: 0 !important;
  opacity: 0; margin: 0; padding: 0;
  border-left: none;
  pointer-events: none;
}
@keyframes slideInR {
  from { opacity: 0; transform: translateX(24px); }
  to { opacity: 1; transform: translateX(0); }
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--scrollbar-thumb-hover); }

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}

@media (max-width: 1200px) {
  .right-panel { width: 320px; min-width: 320px; }
}
</style>
