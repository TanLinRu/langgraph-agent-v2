<script setup lang="ts">
import ConvAvatar from './ConvAvatar.vue'

defineProps<{
  sessionTitle: string
  agentType: string
  isProcessing: boolean
  isThinking?: boolean
  elapsedTime: string
  projectPath?: string
}>()
</script>

<template>
  <div class="chat-header">
    <ConvAvatar :type="agentType" :size="38" :animated="isProcessing ? 'bob' : (!isProcessing && elapsedTime !== '0s' ? 'wave' : false)" />
    <div class="chat-header-info">
      <div class="chat-header-name">{{ sessionTitle || 'New conversation' }}</div>
      <div class="chat-header-status">
        <span :class="['status-dot', isProcessing ? 'busy' : 'online']"></span>
        <span v-if="isThinking">Agent 思考中... {{ elapsedTime }}</span>
        <span v-else-if="isProcessing">● 运行中 · {{ elapsedTime }}</span>
        <span v-else>● 在线</span>
        <span v-if="projectPath" class="header-project-path" :title="projectPath">{{ projectPath }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-header {
  padding: 16px 28px;
  display: flex; align-items: center; gap: 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  flex-shrink: 0;
}
.chat-header-info { flex: 1; }
.chat-header-name {
  font-size: 19px; font-weight: 570; letter-spacing: -0.01em;
  color: var(--text-primary);
}
.chat-header-status {
  font-size: 14px; color: var(--text-tertiary);
  display: flex; align-items: center; gap: 8px;
}
.header-project-path {
  margin-left: auto; font-size: 12px; color: var(--text-faint);
  font-family: 'SF Mono', 'Fira Code', monospace;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 200px; direction: rtl; text-align: right;
}
.status-dot {
  width: 7px; height: 7px; border-radius: 50%; display: inline-block;
}
.status-dot.online {
  background: var(--accent);
  box-shadow: 0 0 6px rgba(129,140,248,0.5);
}
.status-dot.busy {
  background: var(--accent);
  box-shadow: 0 0 6px rgba(129,140,248,0.5);
  animation: avatarPulse 0.8s ease-in-out infinite;
}
@keyframes avatarPulse {
  0%,100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.35); opacity: 0.6; }
}
</style>
