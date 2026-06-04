<template>
  <Teleport to="body">
    <div v-if="request" class="permission-overlay" @click.self="() => {}">
      <div class="permission-dialog">
        <div class="permission-header">
          <span class="permission-icon">🔒</span>
          <h3>权限请求</h3>
        </div>
        <div class="permission-body">
          <p>
            <strong>{{ request.agent_id || '外部 Agent' }}</strong>
            请求执行工具:
          </p>
          <div class="tool-call-info">
            <code>{{ request.toolCall?.name }}</code>
            <pre v-if="request.toolCall?.args">{{ JSON.stringify(request.toolCall.args, null, 2) }}</pre>
          </div>
        </div>
        <div class="permission-options">
          <button
            v-for="opt in request.options"
            :key="opt.id"
            class="permission-btn"
            :class="{ primary: opt.id === 'allow' || opt.id === 'allowOnce' }"
            @click="resolve(opt.id)"
          >
            {{ opt.label }}
            <span v-if="opt.description" class="opt-desc">{{ opt.description }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import type { PermissionRequest } from '../utils/api'

defineProps<{ request: PermissionRequest | null }>()
const emit = defineEmits<{ resolve: [optionId: string] }>()

function resolve(optionId: string) {
  emit('resolve', optionId)
}
</script>

<style scoped>
.permission-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0, 0, 0, 0.5);
  display: flex; align-items: center; justify-content: center;
}
.permission-dialog {
  background: var(--bg-primary, #1e1e2e);
  border: 1px solid var(--border-color, #313244);
  border-radius: 12px;
  padding: 24px;
  max-width: 480px;
  width: 90%;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
.permission-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 16px;
}
.permission-icon { font-size: 24px; }
.permission-header h3 { margin: 0; font-size: 18px; }
.permission-body { margin-bottom: 20px; }
.tool-call-info {
  background: var(--bg-secondary, #181825);
  border-radius: 8px; padding: 12px; margin-top: 8px;
}
.tool-call-info code { font-size: 14px; color: var(--accent, #89b4fa); }
.tool-call-info pre {
  font-size: 12px; margin: 8px 0 0; white-space: pre-wrap;
  color: var(--text-secondary, #a6adc8);
}
.permission-options { display: flex; gap: 8px; flex-wrap: wrap; }
.permission-btn {
  padding: 8px 16px; border-radius: 8px; border: 1px solid var(--border-color, #45475a);
  background: var(--bg-secondary, #313244); color: var(--text-primary, #cdd6f4);
  cursor: pointer; font-size: 14px; display: flex; flex-direction: column; align-items: center;
}
.permission-btn.primary { background: var(--accent, #89b4fa); color: #1e1e2e; border-color: var(--accent, #89b4fa); }
.permission-btn:hover { filter: brightness(1.15); }
.opt-desc { font-size: 11px; opacity: 0.7; margin-top: 2px; }
</style>
