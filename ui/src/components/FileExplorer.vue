<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { fetchFileTree, fetchFileContent } from '../utils/api'
import { useSessionsStore } from '../stores/sessions'

const emit = defineEmits<{
  fileSelect: [path: string]
}>()

const sessions = useSessionsStore()

// Configurable root path
const rootPath = ref(localStorage.getItem('file-explorer-root') || '')
const isLoading = ref(false)
const searchQuery = ref('')

const fileTree = ref<Record<string, string[]>>({})
const currentPath = ref('')
const expandedDirs = ref<Set<string>>(new Set())

const fullCurrentPath = computed(() => {
  const root = rootPath.value
  const sub = currentPath.value
  if (!root && !sub) return ''
  if (!root) return sub
  if (!sub) return root
  return `${root.replace(/\\$/, '')}\\${sub.replace(/^[\\/]/, '')}`
})

async function loadTree() {
  isLoading.value = true
  try {
    fileTree.value = await fetchFileTree(rootPath.value || undefined)
    localStorage.setItem('file-explorer-root', rootPath.value)
  } catch (e) {
    console.warn('[FileExplorer] loadTree failed:', e)
  } finally {
    isLoading.value = false
  }
}

function setAsProjectPath() {
  const id = sessions.activeSessionId
  const path = fullCurrentPath.value
  if (!id || !path) return
  sessions.setProjectPath(id, path)
}

function toggleDir(path: string) {
  if (expandedDirs.value.has(path)) {
    expandedDirs.value.delete(path)
  } else {
    expandedDirs.value.add(path)
  }
}

function isDir(name: string): boolean {
  return name.endsWith('/')
}

function fileIcon(name: string): string {
  if (name.endsWith('/')) return '📁'
  if (name.endsWith('.py')) return '🐍'
  if (name.endsWith('.md')) return '📝'
  if (name.endsWith('.html')) return '🌐'
  if (name.endsWith('.ts') || name.endsWith('.vue')) return '🔷'
  if (name.endsWith('.json')) return '📋'
  if (name.endsWith('.toml') || name.endsWith('.yaml') || name.endsWith('.yml')) return '⚙'
  if (name.endsWith('.js')) return '🟡'
  return '📄'
}

function navigateTo(path: string) {
  currentPath.value = path
  expandedDirs.value.add(path)
}

function selectFile(name: string) {
  const fullPath = currentPath.value ? `${currentPath.value}/${name}` : name
  emit('fileSelect', fullPath)
}

function getEntries(): string[] {
  const entries = fileTree.value[currentPath.value] || []
  if (!searchQuery.value.trim()) return entries
  const q = searchQuery.value.toLowerCase()
  return entries.filter(e => e.toLowerCase().includes(q))
}

function breadcrumbs(): string[] {
  if (!currentPath.value) return []
  return currentPath.value.split('/')
}

onMounted(() => {
  loadTree()
})
</script>

<template>
  <div class="file-explorer">
    <!-- Root path config -->
    <div class="fe-config">
      <input
        v-model="rootPath"
        class="fe-root-input"
        placeholder="Root path (empty = project root)"
        @keydown.enter="loadTree"
      />
      <button class="fe-refresh-btn" @click="loadTree" :disabled="isLoading" title="Reload">
        <svg :class="{ spinning: isLoading }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
      </button>
      <button v-if="fullCurrentPath" class="fe-set-path-btn" @click="setAsProjectPath" title="Set as session project path">
        📌
      </button>
    </div>

    <!-- Search -->
    <input
      v-model="searchQuery"
      class="fl-search"
      placeholder="搜索文件..."
    />

    <!-- Breadcrumb -->
    <div class="file-breadcrumb">
      <span class="file-crumb" :class="{ last: !currentPath }" @click="currentPath = ''">root</span>
      <template v-for="(crumb, i) in breadcrumbs()" :key="i">
        <span class="file-crumb-sep">/</span>
        <span class="file-crumb" :class="{ last: i === breadcrumbs().length - 1 }" @click="currentPath = breadcrumbs().slice(0, i + 1).join('/')">{{ crumb }}</span>
      </template>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="fe-loading">Loading...</div>

    <!-- File list -->
    <template v-else>
      <div v-for="entry in getEntries()" :key="entry">
        <div v-if="isDir(entry)" class="fl-dir" @click="navigateTo(entry.slice(0, -1))">
          <span class="fl-arrow" :class="{ open: expandedDirs.has(entry.slice(0, -1)) }">▶</span>
          <span class="fl-icon">{{ fileIcon(entry) }}</span>
          <span class="fl-name dir">{{ entry }}</span>
        </div>
        <div v-else class="fl-item" @click="selectFile(entry)">
          <span class="fl-icon">{{ fileIcon(entry) }}</span>
          <span class="fl-name">{{ entry }}</span>
        </div>
      </div>

      <div v-if="getEntries().length === 0" class="fl-empty">
        {{ currentPath ? 'Empty directory' : 'No files loaded. Configure root path above.' }}
      </div>
    </template>
  </div>
</template>

<style scoped>
.file-explorer { padding: 0; }

.fl-search {
  margin-bottom: 10px; padding: 7px 12px; width: 100%;
  background: var(--bg-input); border: 1px solid var(--border-input); border-radius: 8px;
  color: var(--text-secondary); font-size: 13px; outline: none;
  transition: border-color 0.2s;
}
.fl-search::placeholder { color: var(--text-muted); }
.fl-search:focus { border-color: var(--accent-focus); }

.fe-config {
  display: flex; gap: 6px; margin-bottom: 10px;
}
.fe-root-input {
  flex: 1; padding: 6px 10px;
  background: var(--bg-input); border: 1px solid var(--border-input); border-radius: 6px;
  color: var(--text-secondary); font-size: 12px; outline: none;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.fe-root-input::placeholder { color: var(--text-muted); }
.fe-root-input:focus { border-color: var(--accent-focus); }
.fe-refresh-btn {
  width: 30px; height: 30px;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-glass); border: 1px solid var(--border); border-radius: 6px;
  color: var(--text-tertiary); cursor: pointer; transition: all 0.15s; flex-shrink: 0;
}
.fe-refresh-btn:hover { background: var(--bg-hover); color: var(--text-secondary); }
.fe-refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.fe-set-path-btn {
  width: 30px; height: 30px;
  display: flex; align-items: center; justify-content: center;
  background: var(--accent-bg); border: 1px solid var(--border-accent); border-radius: 6px;
  color: var(--accent-text); cursor: pointer; transition: all 0.15s; flex-shrink: 0;
  font-size: 14px;
}
.fe-set-path-btn:hover { background: var(--accent-bg-strong); }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.fe-loading {
  text-align: center; padding: 20px; color: var(--text-muted); font-size: 13px;
}

.file-breadcrumb {
  display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
  padding: 10px 0 12px; border-bottom: 1px solid var(--border-light);
  margin-bottom: 10px; min-height: 40px;
}
.file-crumb {
  font-size: 13px; color: var(--text-muted); cursor: pointer;
  padding: 4px 7px; border-radius: 5px; transition: all 0.15s;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.file-crumb:hover { color: var(--accent-text); background: var(--bg-active); }
.file-crumb.last { color: var(--accent-text); cursor: default; }
.file-crumb.last:hover { background: transparent; }
.file-crumb-sep { color: var(--text-faint); font-size: 13px; }

.fl-dir {
  display: flex; align-items: center; gap: 7px;
  padding: 8px 12px; cursor: pointer; border-radius: 6px;
  font-size: 14px; color: var(--accent-text); font-weight: 540;
  transition: all 0.12s; user-select: none;
}
.fl-dir:hover { background: var(--bg-active); }
.fl-arrow {
  font-size: 13px; color: var(--text-faint); width: 16px; flex-shrink: 0;
  transition: transform 0.15s;
}
.fl-arrow.open { transform: rotate(90deg); }

.fl-item {
  display: flex; align-items: center; gap: 7px;
  padding: 7px 12px; cursor: pointer; border-radius: 6px;
  font-size: 13px; color: var(--text-secondary); transition: all 0.12s; white-space: nowrap;
}
.fl-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.fl-icon { font-size: 14px; width: 20px; text-align: center; flex-shrink: 0; }
.fl-empty { font-size: 12px; color: var(--text-faint); padding: 16px 0; text-align: center; }
</style>
