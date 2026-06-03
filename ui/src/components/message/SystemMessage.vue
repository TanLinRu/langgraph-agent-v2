<script setup lang="ts">
/**
 * 系统消息
 *
 * 显示系统级别的提示 (错误消息、压缩提示等)。
 * 如果 `isError` 为 true,使用 ErrorBlock 渲染。
 */
import ErrorBlock from '../ErrorBlock.vue'

defineProps<{
  content: string
  isError?: boolean
}>()
</script>

<template>
  <div class="msg system-msg">
    <ErrorBlock v-if="isError" :message="content" />
    <template v-else>{{ content }}</template>
  </div>
</template>

<style scoped>
.msg.system-msg {
  padding: 10px 20px; border-radius: 10px; max-width: 90%;
  border: 1px solid var(--border);
  background: var(--bg-glass);
  align-self: center;
  font-size: 13px; text-align: center;
  color: var(--text-muted);
  animation: msgIn 0.35s cubic-bezier(0.16,1,0.3,1) both;
}
@keyframes msgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
</style>
