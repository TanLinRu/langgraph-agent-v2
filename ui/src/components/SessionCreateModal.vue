<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSessionsStore } from '../stores/sessions'
import DirectoryPicker from './DirectoryPicker.vue'

const emit = defineEmits<{ close: [] }>()

const sessions = useSessionsStore()
const projectPath = ref('')
const title = ref('')
const showPicker = ref(false)
const inputRef = ref<HTMLInputElement | null>(null)

async function handleCreate() {
  const path = projectPath.value.trim()
  if (!path) return
  await sessions.createSession(title.value.trim() || undefined, path)
  emit('close')
}

function handleCancel() {
  sessions.createSession(title.value.trim() || undefined, '')
  emit('close')
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') handleCreate()
  else if (e.key === 'Escape') handleCancel()
}

function onPickerSelect(path: string) {
  projectPath.value = path
  showPicker.value = false
}

onMounted(() => {
  setTimeout(() => inputRef.value?.focus(), 50)
})
</script>

<template>
  <div class="modal-overlay" @click.self="handleCancel">
    <div class="modal-dialog" @keydown="handleKeydown">
      <div class="modal-header">
        <div class="modal-icon">📁</div>
        <div class="modal-title">新建会话</div>
      </div>
      <div class="modal-body">
        <label class="modal-label">会话名称（可选）</label>
        <input v-model="title" class="modal-input" placeholder="输入会话名称..." @keydown.enter="handleCreate" />

        <label class="modal-label">项目路径 <span class="modal-required">*</span></label>
        <div class="modal-path-row">
          <input ref="inputRef" v-model="projectPath" class="modal-input modal-input-path" placeholder="如 D:\project\my-app" @keydown.enter="handleCreate" />
          <button class="modal-browse-btn" @click="showPicker = true" title="浏览文件夹">📂</button>
        </div>
      </div>
      <DirectoryPicker v-if="showPicker" @select="onPickerSelect" @close="showPicker = false" />
      <div class="modal-footer">
        <button class="modal-btn modal-btn-cancel" @click="handleCancel">跳过</button>
        <button class="modal-btn modal-btn-confirm" :disabled="!projectPath.trim()" @click="handleCreate">开始会话</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0, 0, 0, 0.5);
  display: flex; align-items: center; justify-content: center;
  backdrop-filter: blur(4px);
  animation: fadeIn 0.2s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.modal-dialog {
  width: 420px; max-width: 90vw;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  animation: slideUp 0.25s cubic-bezier(0.16,1,0.3,1);
}
@keyframes slideUp { from { opacity: 0; transform: translateY(16px) scale(0.96); } to { opacity: 1; transform: translateY(0) scale(1); } }

.modal-header {
  padding: 24px 28px 0;
  display: flex; align-items: center; gap: 12px;
}
.modal-icon { font-size: 28px; }
.modal-title { font-size: 20px; font-weight: 650; color: var(--text-primary); }

.modal-body {
  padding: 20px 28px;
  display: flex; flex-direction: column; gap: 6px;
}
.modal-label {
  font-size: 14px; font-weight: 550; color: var(--text-secondary);
  margin-top: 8px;
}
.modal-label:first-child { margin-top: 0; }
.modal-required { color: var(--color-red); }
.modal-input {
  width: 100%; padding: 10px 14px;
  background: var(--bg-input); border: 1px solid var(--border-input); border-radius: 10px;
  color: var(--text-secondary); font-size: 15px; outline: none;
  transition: border-color 0.2s;
}
.modal-input:focus { border-color: var(--accent-focus); }
.modal-input-path {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.modal-path-row { display: flex; gap: 6px; }
.modal-path-row .modal-input { flex: 1; }
.modal-browse-btn {
  width: 40px; border: none; border-radius: 10px;
  background: var(--accent-bg-strong); color: var(--accent-text);
  font-size: 18px; cursor: pointer; white-space: nowrap; line-height: 1;
  transition: background 0.2s; display: flex; align-items: center; justify-content: center;
}
.modal-browse-btn:hover { background: var(--bg-accent-hover); }
.modal-browse-btn:active { transform: scale(0.96); }

.modal-hint {
  font-size: 12px; color: var(--text-muted); margin-top: 2px;
}
.modal-hint strong { color: var(--accent-text); }

.modal-footer {
  padding: 0 28px 24px;
  display: flex; justify-content: flex-end; gap: 10px;
}
.modal-btn {
  padding: 10px 22px; border: none; border-radius: 10px;
  font-size: 15px; font-weight: 600; cursor: pointer;
  transition: all 0.2s;
}
.modal-btn:active { transform: scale(0.96); }
.modal-btn-cancel {
  background: var(--bg-glass); color: var(--text-tertiary);
  border: 1px solid var(--border);
}
.modal-btn-cancel:hover { background: var(--bg-hover); color: var(--text-secondary); }
.modal-btn-confirm {
  background: var(--accent-bg-strong); color: var(--accent-text);
}
.modal-btn-confirm:hover:not(:disabled) { background: var(--bg-accent-hover); }
.modal-btn-confirm:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
