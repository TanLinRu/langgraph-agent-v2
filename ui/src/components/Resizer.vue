<script setup lang="ts">
const emit = defineEmits<{
  resize: [newWidth: number]
}>()

const props = defineProps<{
  minWidth?: number
  maxWidth?: number
}>()

function onMouseDown(e: MouseEvent) {
  const startX = e.clientX
  const startWidth = (e.target as HTMLElement).parentElement!.getBoundingClientRect().width
  const min = props.minWidth || 300
  const max = props.maxWidth || 600

  function onMouseMove(e: MouseEvent) {
    const delta = startX - e.clientX // left resize = dragging left increases right panel
    const newWidth = Math.min(max, Math.max(min, startWidth + delta))
    emit('resize', newWidth)
  }

  function onMouseUp() {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}
</script>

<template>
  <div class="resizer" @mousedown="onMouseDown"></div>
</template>

<style scoped>
.resizer {
  width: 8px; min-width: 8px; cursor: col-resize;
  background: transparent; position: relative; z-index: 10;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s;
}
.resizer::after {
  content: ''; width: 2px; height: 36px;
  background: var(--bg-input); border-radius: 1px;
  transition: all 0.2s; flex-shrink: 0;
}
.resizer:hover::after, .resizer:active::after {
  background: rgba(99,102,241,0.25); height: 52px;
}
.resizer:hover { background: var(--bg-surface); }
</style>
