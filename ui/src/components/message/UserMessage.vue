<script setup lang="ts">
/**
 * 用户消息气泡
 *
 * 显示用户发送的消息内容,右对齐,带淡入动画。
 */
import { renderMd } from '../../utils/useMarkdown'

defineProps<{
  content: string
}>()
</script>

<template>
  <div class="msg user">
    <div class="msg-text" v-html="renderMd(content)"></div>
  </div>
</template>

<style scoped>
.msg.user {
  padding: 13px 20px; border-radius: 14px; width: 78%;
  word-break: break-word;
  border: 1px solid var(--border-accent-soft);
  background: var(--accent-bg);
  align-self: flex-end;
  border-bottom-right-radius: 5px;
  animation: msgIn 0.35s cubic-bezier(0.16,1,0.3,1) both;
  line-height: 1.65;
}
.msg-text { font-size: 16px; line-height: 1.7; font-weight: 450; color: var(--text-primary); white-space: pre-wrap; }
@keyframes msgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
</style>
