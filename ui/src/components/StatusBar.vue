<script setup lang="ts">
defineProps<{
  isProcessing: boolean
}>()
</script>

<template>
  <div v-if="isProcessing" class="status-bar">
    <div class="status-bar-progress"></div>
  </div>
</template>

<style scoped>
.status-bar {
  height: 2px; position: relative; overflow: hidden;
  background: var(--bg-glass); flex-shrink: 0;
}
.status-bar-progress {
  height: 100%; width: 28%;
  background: linear-gradient(90deg, #6366f1, #818cf8, #6366f1);
  background-size: 200% 100%;
  animation: barSlide 1.6s ease-in-out infinite;
  border-radius: 1px;
}
@keyframes barSlide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(450%); }
}
</style>
