<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  dispatch: { from: string; to: string; fromLabel?: string; toLabel?: string } | null
}>()

const visible = ref(false)
const fading = ref(false)
let hideTimer: ReturnType<typeof setTimeout> | null = null

watch(() => props.dispatch, (val) => {
  if (hideTimer) clearTimeout(hideTimer)
  if (val) {
    visible.value = true
    fading.value = false
    hideTimer = setTimeout(() => {
      fading.value = true
      setTimeout(() => { visible.value = false }, 400)
    }, 2000)
  }
})
</script>

<template>
  <div v-if="visible" :class="['dispatch-indicator', { fading }]">
    <span class="dispatch-arrow">▶</span>
    <span class="dispatch-from">{{ dispatch?.fromLabel || dispatch?.from || '—' }}</span>
    <span class="dispatch-arrow-body">→</span>
    <span class="dispatch-to">{{ dispatch?.toLabel || dispatch?.to || '—' }}</span>
  </div>
</template>

<style scoped>
.dispatch-indicator {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-light);
  animation: dispatchIn 0.3s ease;
  min-height: 28px;
}
.dispatch-indicator.fading {
  opacity: 0.3;
  transition: opacity 0.4s ease;
}
@keyframes dispatchIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.dispatch-arrow { font-size: 9px; color: var(--accent-text); }
.dispatch-from { color: var(--accent-text); font-weight: 600; }
.dispatch-arrow-body { color: var(--color-amber); font-weight: 700; }
.dispatch-to { color: var(--accent); font-weight: 600; }
</style>
