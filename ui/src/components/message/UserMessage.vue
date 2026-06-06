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
  padding: 13px 20px; border-radius: 16px; width: 78%;
  word-break: break-word;
  border: 1px solid rgba(99,102,241,0.2);
  background: linear-gradient(135deg, rgba(99,102,241,0.22), rgba(129,140,248,0.12), rgba(167,139,250,0.1));
  align-self: flex-end;
  border-bottom-right-radius: 6px;
  animation: msgIn 0.35s cubic-bezier(0.16,1,0.3,1) both;
  line-height: 1.65;
  box-shadow: 0 2px 12px rgba(99,102,241,0.1);
  position: relative;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.msg.user::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 16px;
  padding: 1px;
  background: linear-gradient(135deg, rgba(99,102,241,0.3), rgba(129,140,248,0.15));
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
}
.msg.user:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 20px rgba(99,102,241,0.15),
              0 0 30px rgba(129,140,248,0.1);
  border-color: rgba(99,102,241,0.3);
}
.msg-text { 
  font-size: 16px; 
  line-height: 1.7; 
  font-weight: 450; 
  color: var(--text-primary); 
  white-space: pre-wrap; 
  position: relative;
  z-index: 1;
}
@keyframes msgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
</style>
