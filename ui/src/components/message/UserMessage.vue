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
  padding: 13px 20px; border-radius: 16px;
  max-width: 85%; width: fit-content;
  word-break: break-word;
  border: 1px solid transparent;
  background:
    linear-gradient(135deg, rgba(99,102,241,0.22), rgba(129,140,248,0.12), rgba(167,139,250,0.1)) padding-box,
    linear-gradient(135deg, rgba(99,102,241,0.3), rgba(129,140,248,0.15)) border-box;
  align-self: flex-end;
  border-bottom-right-radius: 6px;
  animation: msgIn 0.35s cubic-bezier(0.16,1,0.3,1) both;
  line-height: 1.65;
  box-shadow: 0 2px 12px rgba(99,102,241,0.1);
  position: relative;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.msg.user:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 20px rgba(99,102,241,0.15),
              0 0 30px rgba(129,140,248,0.1);
}
.msg-text { 
  font-size: 16px; 
  line-height: 1.7; 
  font-weight: 450; 
  color: var(--text-primary); 
  white-space: pre-wrap; 
}
@keyframes msgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

@media (max-width: 640px) {
  .msg.user {
    max-width: 95%; padding: 10px 14px; border-radius: 12px;
    border-bottom-right-radius: 5px;
  }
  .msg-text { font-size: 15px; }
}
</style>
