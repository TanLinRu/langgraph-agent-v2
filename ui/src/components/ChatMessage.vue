<script setup lang="ts">
/**
 * ChatMessage — 消息路由组件
 *
 * 根据 msg.role 分发到对应的子组件:
 * - user      → UserMessage
 * - system    → SystemMessage
 * - assistant → AgentMessage
 */
import type { ChatMessage } from '../utils/api'
import UserMessage from './message/UserMessage.vue'
import SystemMessage from './message/SystemMessage.vue'
import AgentMessage from './message/AgentMessage.vue'

defineProps<{
  msg: ChatMessage
  index: number
  isTyping: boolean
}>()

const emit = defineEmits<{
  fileClick: [path: string]
}>()
</script>

<template>
  <UserMessage v-if="msg.role === 'user'" :content="msg.content" />
  <SystemMessage v-else-if="msg.role === 'system'" :content="msg.content" :isError="msg.isError" />
  <AgentMessage v-else :msg="msg" :index="index" :isTyping="isTyping" @fileClick="emit('fileClick', $event)" />
</template>
