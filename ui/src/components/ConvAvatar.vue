<script setup lang="ts">
defineProps<{
  type: string
  size?: number
  animated?: 'bob' | 'wave' | 'think' | 'work' | 'breathe' | false
}>()
</script>

<template>
  <div
    class="conv-avatar"
    :class="{
      'robot-bob': animated === 'bob',
      'robot-wave': animated === 'wave',
      'robot-think': animated === 'think',
      'robot-work': animated === 'work',
      'robot-breathe': animated === 'breathe' || animated === undefined,
    }"
    :style="{ width: (size || 46) + 'px', height: (size || 46) + 'px' }"
  >
    <!-- Supervisor -->
    <svg v-if="type === 'supervisor'" viewBox="0 0 48 48">
      <rect x="13" y="12" width="22" height="20" rx="6" fill="#6366f1" opacity=".9" class="head"/>
      <circle cx="20" cy="20" r="2.5" fill="#fff" class="eye eye-l"/>
      <circle cx="28" cy="20" r="2.5" fill="#fff" class="eye eye-r"/>
      <circle cx="20" cy="20" r="5" fill="none" stroke="rgba(255,255,255,.3)" stroke-width="1.5" class="halo"/>
      <circle cx="28" cy="20" r="5" fill="none" stroke="rgba(255,255,255,.3)" stroke-width="1.5" class="halo"/>
      <line x1="25" y1="20" x2="23" y2="20" stroke="rgba(255,255,255,.3)" stroke-width="1.5" class="nose"/>
      <path d="M20 27 Q24 30, 28 27" fill="none" stroke="rgba(255,255,255,.8)" stroke-width="1.5" stroke-linecap="round" class="mouth"/>
      <rect x="11" y="18" width="2" height="6" rx="1" fill="#6366f1" opacity=".7" class="antenna antenna-l"/>
      <rect x="35" y="18" width="2" height="6" rx="1" fill="#6366f1" opacity=".7" class="antenna antenna-r"/>
    </svg>
    <!-- Coder -->
    <svg v-else-if="type === 'coder'" viewBox="0 0 48 48">
      <rect x="13" y="10" width="22" height="18" rx="5" fill="#34d399" opacity=".8" class="head"/>
      <rect x="16" y="13" width="16" height="12" rx="2" fill="#0a0a1a" opacity=".5"/>
      <text x="24" y="20" text-anchor="middle" fill="#34d399" font-size="7" font-family="monospace" class="code-text">&lt;/&gt;</text>
      <circle cx="20" cy="18" r="1" fill="#34d399" class="eye eye-l"/>
      <circle cx="28" cy="18" r="1" fill="#34d399" class="eye eye-r"/>
      <line x1="24" y1="10" x2="24" y2="5" stroke="#34d399" stroke-width="1.5" opacity=".6" class="antenna"/>
      <circle cx="24" cy="4" r="1.8" fill="#34d399" opacity=".8" class="signal-dot"/>
    </svg>
    <!-- Researcher -->
    <svg v-else-if="type === 'researcher'" viewBox="0 0 48 48">
      <rect x="15" y="13" width="18" height="17" rx="7" fill="#fbbf24" opacity=".85" class="head"/>
      <circle cx="21" cy="20" r="3.5" fill="#fff" class="eye eye-l"/>
      <circle cx="27" cy="20" r="3.5" fill="#fff" class="eye eye-r"/>
      <circle cx="21" cy="20" r="1.8" fill="#0a0a1a" class="pupil pupil-l"/>
      <circle cx="27" cy="20" r="1.8" fill="#0a0a1a" class="pupil pupil-r"/>
      <circle cx="36" cy="36" r="7" fill="none" stroke="#fbbf24" stroke-width="2" opacity=".4" class="lens"/>
      <line x1="41" y1="41" x2="45" y2="45" stroke="#fbbf24" stroke-width="2" opacity=".4" stroke-linecap="round"/>
      <path d="M21 27 Q24 29, 27 27" fill="none" stroke="rgba(255,255,255,.9)" stroke-width="1.2" stroke-linecap="round" class="mouth"/>
    </svg>
    <!-- Analyst -->
    <svg v-else-if="type === 'analyst'" viewBox="0 0 48 48">
      <rect x="14" y="12" width="20" height="16" rx="6" fill="#fb7185" opacity=".85" class="head"/>
      <circle cx="24" cy="19" r="3" fill="#fff" class="eye"/>
      <circle cx="24" cy="19" r="1.5" fill="#0a0a1a" class="pupil"/>
      <rect x="15" y="6" width="4" height="8" rx="1" fill="#fb7185" opacity=".6" class="bar bar-1"/>
      <rect x="21" y="4" width="4" height="10" rx="1" fill="#fb7185" opacity=".8" class="bar bar-2"/>
      <rect x="27" y="7" width="4" height="7" rx="1" fill="#fb7185" opacity=".6" class="bar bar-3"/>
      <path d="M21 25 L24 27 L27 25" fill="none" stroke="rgba(255,255,255,.7)" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" class="mouth"/>
      <circle cx="14" cy="22" r="1.2" fill="rgba(255,255,255,.3)"/>
      <circle cx="34" cy="22" r="1.2" fill="rgba(255,255,255,.3)"/>
    </svg>
    <!-- OpenCode -->
    <svg v-else-if="type === 'opencode'" viewBox="0 0 48 48">
      <rect x="12" y="10" width="24" height="20" rx="6" fill="#059669" opacity=".85" class="head"/>
      <rect x="15" y="13" width="18" height="14" rx="3" fill="#0a0a1a" opacity=".5"/>
      <text x="24" y="22" text-anchor="middle" fill="#34d399" font-size="7" font-family="monospace" class="code-text">OC</text>
      <circle cx="18" cy="18" r="1" fill="#34d399" class="eye eye-l"/>
      <circle cx="30" cy="18" r="1" fill="#34d399" class="eye eye-r"/>
      <line x1="24" y1="10" x2="24" y2="5" stroke="#059669" stroke-width="1.5" opacity=".6" class="antenna"/>
      <circle cx="24" cy="4" r="1.8" fill="#059669" opacity=".8" class="signal-dot"/>
    </svg>
    <!-- Claude Agent -->
    <svg v-else-if="type === 'claude-agent'" viewBox="0 0 48 48">
      <rect x="12" y="10" width="24" height="20" rx="6" fill="#d97706" opacity=".85" class="head"/>
      <rect x="15" y="13" width="18" height="14" rx="3" fill="#0a0a1a" opacity=".5"/>
      <text x="24" y="22" text-anchor="middle" fill="#fbbf24" font-size="7" font-family="monospace" class="code-text">CL</text>
      <circle cx="18" cy="18" r="1" fill="#fbbf24" class="eye eye-l"/>
      <circle cx="30" cy="18" r="1" fill="#fbbf24" class="eye eye-r"/>
      <line x1="24" y1="10" x2="24" y2="5" stroke="#d97706" stroke-width="1.5" opacity=".6" class="antenna"/>
      <circle cx="24" cy="4" r="1.8" fill="#d97706" opacity=".8" class="signal-dot"/>
    </svg>
    <!-- Helper (default) -->
    <svg v-else viewBox="0 0 48 48">
      <rect x="15" y="14" width="18" height="15" rx="7" fill="#a78bfa" opacity=".85" class="head"/>
      <circle cx="20" cy="20" r="3.5" fill="#fff" class="eye eye-l"/>
      <circle cx="28" cy="20" r="3.5" fill="#fff" class="eye eye-r"/>
      <circle cx="20" cy="20" r="1.5" fill="#0a0a1a" class="pupil pupil-l"/>
      <circle cx="28" cy="20" r="1.5" fill="#0a0a1a" class="pupil pupil-r"/>
      <circle cx="16" cy="24" r="2.5" fill="#a78bfa" opacity=".2" class="cheek cheek-l"/>
      <circle cx="32" cy="24" r="2.5" fill="#a78bfa" opacity=".2" class="cheek cheek-r"/>
      <path d="M24 14 L24 10 Q24 6, 21 7 Q18 8, 21 10 L24 14" fill="#f472b6" opacity=".7" class="bow"/>
      <path d="M21 26 Q24 29, 27 26" fill="none" stroke="rgba(255,255,255,.85)" stroke-width="1.2" stroke-linecap="round" class="mouth"/>
    </svg>
  </div>
</template>

<style scoped>
.conv-avatar {
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
  border-radius: 50%;
}
.conv-avatar svg {
  width: 100%;
  height: 100%;
  display: block;
  overflow: hidden;
}

/* ── idle / breathe — gentle scale on the whole head ── */
.robot-breathe .head {
  animation: breathe 4s ease-in-out infinite;
  transform-origin: center;
  transform-box: fill-box;
}
@keyframes breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.03); }
}
.robot-breathe .eye-l, .robot-breathe .eye-r {
  animation: blink 5.2s ease-in-out infinite;
  transform-origin: center;
  transform-box: fill-box;
}
.robot-breathe .pupil-l, .robot-breathe .pupil-r {
  animation: scanSlow 6s ease-in-out infinite;
  transform-origin: center;
  transform-box: fill-box;
}
@keyframes blink {
  0%, 92%, 100% { transform: scaleY(1); }
  95% { transform: scaleY(0.1); }
}
@keyframes scanSlow {
  0%, 100% { transform: translate(0, 0); }
  25% { transform: translate(0.5px, -0.5px); }
  50% { transform: translate(0, 0.5px); }
  75% { transform: translate(-0.5px, -0.5px); }
}

/* ── bob — vertical float ── */
.robot-bob {
  animation: robotBob 3s ease-in-out infinite;
}
@keyframes robotBob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

/* ── wave — antenna/head tilt ── */
.robot-wave {
  animation: robotWave 1.8s ease-in-out infinite;
  transform-origin: bottom center;
}
@keyframes robotWave {
  0%, 100% { transform: rotate(0deg); }
  20% { transform: rotate(-14deg); }
  40% { transform: rotate(12deg); }
  60% { transform: rotate(-6deg); }
  80% { transform: rotate(6deg); }
}

/* ── think — eyes scan left-right rapidly + halo pulse ── */
.robot-think .pupil-l, .robot-think .pupil-r {
  animation: scanFast 1.4s ease-in-out infinite;
  transform-origin: center;
  transform-box: fill-box;
}
.robot-think .halo {
  animation: haloPulse 1.4s ease-in-out infinite;
  transform-origin: center;
  transform-box: fill-box;
}
.robot-think .signal-dot {
  animation: signalPulse 0.9s ease-in-out infinite;
  transform-origin: center;
  transform-box: fill-box;
}
@keyframes scanFast {
  0%, 100% { transform: translate(-1.2px, 0); }
  50% { transform: translate(1.2px, 0); }
}
@keyframes haloPulse {
  0%, 100% { opacity: 0.3; transform: scale(1); }
  50% { opacity: 0.9; transform: scale(1.2); }
}
@keyframes signalPulse {
  0%, 100% { opacity: 0.4; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}

/* ── work — code flicker + head nudge + bars up/down ── */
.robot-work .head {
  animation: workNod 0.5s ease-in-out infinite;
  transform-origin: bottom center;
  transform-box: fill-box;
}
.robot-work .code-text {
  animation: codeFlicker 0.8s steps(4) infinite;
}
.robot-work .bar {
  transform-origin: bottom center;
  transform-box: fill-box;
}
.robot-work .bar-1 { animation: barJump 0.7s ease-in-out infinite; }
.robot-work .bar-2 { animation: barJump 0.7s 0.15s ease-in-out infinite; }
.robot-work .bar-3 { animation: barJump 0.7s 0.3s ease-in-out infinite; }
.robot-work .signal-dot {
  animation: signalPulse 0.4s ease-in-out infinite;
  transform-origin: center;
  transform-box: fill-box;
}
@keyframes workNod {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  25% { transform: translateY(-1px) rotate(-2deg); }
  75% { transform: translateY(0) rotate(2deg); }
}
@keyframes codeFlicker {
  0%, 100% { opacity: 1; }
  25% { opacity: 0.6; }
  50% { opacity: 1; }
  75% { opacity: 0.3; }
}
@keyframes barJump {
  0%, 100% { transform: scaleY(0.8); }
  50% { transform: scaleY(1.15); }
}
</style>
