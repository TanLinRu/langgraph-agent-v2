<script setup lang="ts">
import { ref, computed, onMounted, useTemplateRef, nextTick, watch } from 'vue'
import DirectoryTreeBrowser from './DirectoryTreeBrowser.vue'

const emit = defineEmits<{
  select: [path: string]
  close: []
}>()

const props = defineProps<{
  initialPath?: string
}>()

const pickerMode = ref<'auto' | 'tree' | 'manual'>('auto')
const picking = ref(true)
const errorMsg = ref('')
const manualPath = ref('')
const manualError = ref('')
const manualSubmitting = ref(false)
const inputRef = useTemplateRef<HTMLInputElement>('inputRef')

const initialTreePath = computed(() => {
  if (props.initialPath) return props.initialPath
  try {
    const recent = localStorage.getItem('recent_project_path')
    if (recent) return recent
  } catch {}
  return ''
})

async function pickDirectory() {
  picking.value = true
  errorMsg.value = ''
  try {
    const res = await fetch('/api/files/pick-directory', { method: 'POST' })
    if (!res.ok) {
      let detail = ''
      try {
        const body = await res.json()
        detail = body?.detail || ''
      } catch {
        detail = await res.text().catch(() => '')
      }
      const friendly = res.status === 504
        ? '文件夹选择器超时 — 当前会话可能没有图形桌面'
        : res.status === 503
          ? '系统文件夹选择器不可用'
          : detail || `HTTP ${res.status}`
      throw new Error(friendly)
    }
    const data = await res.json()
    if (data.path) {
      emit('select', data.path)
    } else {
      emit('close')
    }
  } catch (e: any) {
    errorMsg.value = e.message || '无法打开系统文件夹选择器'
    picking.value = false
    pickerMode.value = 'tree'
  }
}

function openManual() {
  errorMsg.value = ''
  manualError.value = ''
  pickerMode.value = 'manual'
  nextTick(() => inputRef.value?.focus())
}

function openTree() {
  errorMsg.value = ''
  pickerMode.value = 'tree'
}

async function submitManual() {
  const raw = manualPath.value.trim().replace(/^["']|["']$/g, '')
  if (!raw) {
    manualError.value = '请输入路径'
    return
  }
  manualSubmitting.value = true
  manualError.value = ''
  try {
    const res = await fetch('/api/files/validate-directory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: raw }),
    })
    if (!res.ok) {
      let detail = ''
      try {
        const body = await res.json()
        detail = body?.detail || ''
      } catch {
        detail = await res.text().catch(() => '')
      }
      throw new Error(detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    if (data.valid && data.path) {
      emit('select', data.path)
    } else {
      manualError.value = '路径无效'
    }
  } catch (e: any) {
    manualError.value = e.message || '验证失败'
  } finally {
    manualSubmitting.value = false
  }
}

function onManualKey(e: KeyboardEvent) {
  if (e.key === 'Enter') submitManual()
  else if (e.key === 'Escape') emit('close')
}

function onTreeSelect(path: string) {
  emit('select', path)
}

onMounted(() => {
  if (pickerMode.value === 'auto') {
    void pickDirectory()
  }
})
</script>

<template>
  <div class="dp-overlay" @click.self="emit('close')">
    <div class="dp-dialog" :class="{ 'dp-dialog-wide': pickerMode === 'tree' }">
      <div class="dp-header">
        <h3>选择项目目录</h3>
        <div class="dp-mode-tabs" v-if="!picking">
          <button
            class="dp-tab"
            :class="{ active: pickerMode === 'tree' }"
            @click="openTree"
          >🌳 浏览</button>
          <button
            class="dp-tab"
            :class="{ active: pickerMode === 'manual' }"
            @click="openManual"
          >⌨️ 手动输入</button>
        </div>
      </div>
      <div class="dp-body">
        <div v-if="errorMsg && pickerMode !== 'tree' && pickerMode !== 'manual'" class="dp-error">
          <span class="dp-error-icon">⚠️</span>
          <div class="dp-error-text">
            <div class="dp-error-msg">{{ errorMsg }}</div>
            <div class="dp-link-row">
              <button class="dp-link-btn" @click="openTree">用目录树浏览 →</button>
              <button class="dp-link-btn" @click="openManual">手动输入路径 →</button>
            </div>
          </div>
        </div>
        <div v-else-if="picking" class="dp-picking">
          <span class="dp-spinner"></span>
          <span>正在打开系统文件夹选择器...</span>
        </div>
        <div v-else-if="pickerMode === 'tree'" class="dp-tree">
          <DirectoryTreeBrowser
            :initial-path="initialTreePath"
            @select="onTreeSelect"
          />
        </div>
        <div v-else-if="pickerMode === 'manual'" class="dp-manual">
          <label class="dp-label">目录绝对路径</label>
          <input
            ref="inputRef"
            v-model="manualPath"
            class="dp-input"
            :class="{ 'has-error': manualError }"
            placeholder="例如: D:\project\my-app"
            spellcheck="false"
            @keydown="onManualKey"
          />
          <div v-if="manualError" class="dp-field-error">{{ manualError }}</div>
        </div>
      </div>
      <div class="dp-footer">
        <button class="dp-cancel-btn" @click="emit('close')">取消</button>
        <button v-if="pickerMode === 'auto' && errorMsg" class="dp-retry-btn" @click="pickDirectory">重试系统选择器</button>
        <button v-if="pickerMode === 'manual'" class="dp-retry-btn" :disabled="manualSubmitting" @click="submitManual">
          {{ manualSubmitting ? '验证中...' : '使用此目录' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dp-overlay {
  position: fixed; inset: 0; z-index: 1100;
  background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center;
  backdrop-filter: blur(4px);
  animation: fadeIn 0.2s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.dp-dialog {
  width: 480px; max-width: 90vw;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  box-shadow: var(--shadow-lg);
  animation: slideUp 0.25s cubic-bezier(0.16,1,0.3,1);
}
.dp-dialog-wide {
  width: 640px; max-width: 92vw;
}
@keyframes slideUp { from { opacity: 0; transform: translateY(16px) scale(0.96); } to { opacity: 1; transform: translateY(0) scale(1); } }

.dp-header {
  padding: 20px 28px 0;
}
.dp-header h3 {
  margin: 0; font-size: 16px; font-weight: 600;
  color: var(--text-primary); letter-spacing: 0.2px;
}
.dp-mode-tabs {
  display: flex; gap: 4px;
  margin-top: 12px;
  border-bottom: 1px solid var(--border-light);
  padding-bottom: 0;
}
.dp-tab {
  background: none; border: none; padding: 6px 12px;
  color: var(--text-faint); font-size: 12.5px; cursor: pointer;
  font-family: inherit; border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all 0.15s;
}
.dp-tab:hover { color: var(--text-secondary); }
.dp-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  font-weight: 600;
}
.dp-link-row { display: flex; gap: 12px; flex-wrap: wrap; }

.dp-body {
  padding: 20px 28px 16px;
  display: flex; flex-direction: column; gap: 14px;
  min-height: 80px;
}

.dp-picking {
  display: flex; flex-direction: column; align-items: center; gap: 16px;
  color: var(--text-secondary); font-size: 15px;
  padding: 24px 0;
}
.dp-spinner {
  width: 32px; height: 32px;
  border: 3px solid var(--border);
  border-top-color: var(--accent-bg-strong);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.dp-error {
  display: flex; align-items: flex-start; gap: 10px;
  color: var(--color-red, #ef4444); font-size: 14px;
  padding: 12px 14px; background: rgba(239,68,68,0.06);
  border: 1px solid rgba(239,68,68,0.18);
  border-radius: 8px;
}
.dp-error-icon { font-size: 18px; flex-shrink: 0; line-height: 1.4; }
.dp-error-text { display: flex; flex-direction: column; gap: 6px; min-width: 0; flex: 1; }
.dp-error-msg { line-height: 1.5; }

.dp-link-btn {
  background: none; border: none; padding: 0;
  color: var(--accent); font-size: 13px; cursor: pointer;
  text-align: left; font-family: inherit;
  text-decoration: none;
}
.dp-link-btn:hover { text-decoration: underline; }
.dp-tree {
  min-height: 320px;
}

.dp-manual {
  display: flex; flex-direction: column; gap: 6px;
  animation: manualIn 0.25s ease-out;
}
@keyframes manualIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
.dp-label { font-size: 12px; color: var(--text-faint); font-weight: 500; }
.dp-input {
  width: 100%;
  padding: 10px 12px;
  background: var(--bg-input, var(--bg-elevated));
  border: 1.5px solid var(--border);
  border-radius: 8px;
  font-size: 14px;
  color: var(--text-primary);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  outline: none; transition: all 0.15s;
  box-sizing: border-box;
}
.dp-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(129,140,248,0.12);
}
.dp-input.has-error {
  border-color: #ef4444;
}
.dp-field-error {
  font-size: 12px; color: #ef4444;
  padding: 2px 4px 0;
}

.dp-footer {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 0 28px 22px;
}
.dp-cancel-btn {
  padding: 8px 20px; border: 1px solid var(--border); border-radius: 8px;
  background: transparent; color: var(--text-tertiary);
  font-size: 14px; cursor: pointer;
}
.dp-cancel-btn:hover { background: var(--bg-hover); color: var(--text-secondary); }
.dp-retry-btn {
  padding: 8px 20px; border: none; border-radius: 8px;
  background: var(--accent-bg-strong); color: var(--accent-text);
  font-size: 14px; font-weight: 600; cursor: pointer;
  transition: all 0.15s;
}
.dp-retry-btn:hover:not(:disabled) { background: var(--bg-accent-hover); }
.dp-retry-btn:active:not(:disabled) { transform: scale(0.96); }
.dp-retry-btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
