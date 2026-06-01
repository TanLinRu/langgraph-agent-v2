<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { fetchFileTree, fetchFileContent } from '../utils/api'

interface OpenFile {
  path: string
  content: string
  language: string
  lines: Array<{ num: number; text: string; hl: string }>
}

const props = defineProps<{
  open: boolean
  initialPath?: string
}>()

const emit = defineEmits<{
  close: []
}>()

const drawerWidth = ref(420)
const showTree = ref(false)
const searchQuery = ref('')
const searchMatchIdx = ref(0)
const searchMatches = ref<number[]>([])
const openFiles = ref<OpenFile[]>([])
const activeTab = ref(0)
const isLoading = ref(false)

// Tree state
const currentDir = ref('')
const expandedDirs = ref<Set<string>>(new Set())
const fileTree = ref<Record<string, string[]>>({})

// Load file tree from API
async function loadTree() {
  try {
    fileTree.value = await fetchFileTree()
  } catch (e) {
    console.warn('[FileDrawer] loadTree failed:', e)
  }
}

function getLanguage(path: string): string {
  if (path.endsWith('.py')) return 'Python'
  if (path.endsWith('.ts') || path.endsWith('.vue')) return 'TypeScript'
  if (path.endsWith('.js')) return 'JavaScript'
  if (path.endsWith('.md')) return 'Markdown'
  if (path.endsWith('.html')) return 'HTML'
  if (path.endsWith('.json')) return 'JSON'
  if (path.endsWith('.toml')) return 'TOML'
  return 'Text'
}

function getLanguageBadgeColor(lang: string): string {
  const colors: Record<string, string> = {
    Python: 'var(--color-green)',
    TypeScript: 'var(--accent)',
    JavaScript: 'var(--accent)',
    Markdown: 'var(--accent)',
    HTML: 'var(--color-amber)',
    JSON: 'var(--accent)',
    TOML: 'var(--color-amber)',
  }
  return colors[lang] || 'var(--text-muted)'
}

async function loadFile(path: string) {
  // Check if already open
  const existing = openFiles.value.findIndex(f => f.path === path)
  if (existing >= 0) {
    activeTab.value = existing
    return
  }

  isLoading.value = true
  try {
    const data = await fetchFileContent(path)
    const openFile: OpenFile = {
      path: data.path,
      content: data.lines.map(l => l.text).join('\n'),
      language: data.language,
      lines: data.lines,
    }
    openFiles.value.push(openFile)
    activeTab.value = openFiles.value.length - 1
  } catch (e: any) {
    console.warn('[FileDrawer] loadFile failed:', e)
    const errorMsg = e.message?.includes('404') ? `文件不存在: ${path}` : `加载失败: ${path} (${e.message})`
    const lang = getLanguage(path)
    openFiles.value.push({
      path,
      content: errorMsg,
      language: lang,
      lines: [{ num: 1, text: errorMsg, hl: '' }],
    })
    activeTab.value = openFiles.value.length - 1
  } finally {
    isLoading.value = false
  }
}

function closeTab(index: number) {
  openFiles.value.splice(index, 1)
  if (activeTab.value >= openFiles.value.length) {
    activeTab.value = Math.max(0, openFiles.value.length - 1)
  }
}

// Search functionality
const currentMatchLine = computed(() => {
  if (searchMatches.value.length === 0) return -1
  return searchMatches.value[searchMatchIdx.value] ?? -1
})

function doSearch() {
  if (!searchQuery.value.trim()) {
    searchMatches.value = []
    return
  }
  const q = searchQuery.value.toLowerCase()
  const file = openFiles.value[activeTab.value]
  if (!file) return
  searchMatches.value = file.lines
    .map((line, i) => line.text.toLowerCase().includes(q) ? i : -1)
    .filter(i => i >= 0)
  searchMatchIdx.value = 0
}

function nextMatch() {
  if (searchMatches.value.length === 0) return
  searchMatchIdx.value = (searchMatchIdx.value + 1) % searchMatches.value.length
}

function prevMatch() {
  if (searchMatches.value.length === 0) return
  searchMatchIdx.value = (searchMatchIdx.value - 1 + searchMatches.value.length) % searchMatches.value.length
}

function isMatchLine(lineNum: number): boolean {
  return searchMatches.value.includes(lineNum - 1)
}

function isCurrentMatch(lineNum: number): boolean {
  return currentMatchLine.value === lineNum - 1
}

// Tree navigation
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
  return '📄'
}

function getTreeEntries(): string[] {
  return fileTree.value[currentDir.value] || []
}

function toggleTreeDir(dir: string) {
  const clean = dir.slice(0, -1)
  if (expandedDirs.value.has(clean)) {
    expandedDirs.value.delete(clean)
  } else {
    expandedDirs.value.add(clean)
  }
}

function navigateTreeTo(path: string) {
  currentDir.value = path
  expandedDirs.value.add(path)
}

function selectTreeFile(name: string) {
  const fullPath = currentDir.value ? `${currentDir.value}/${name}` : name
  loadFile(fullPath)
}

// Copy file content
function copyContent() {
  const file = openFiles.value[activeTab.value]
  if (!file) return
  navigator.clipboard.writeText(file.content)
}

// Copy file path
function copyPath() {
  const file = openFiles.value[activeTab.value]
  if (!file) return
  navigator.clipboard.writeText(file.path)
}

// Escape key handler
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) {
    emit('close')
  }
}

// Load initial file and tree
watch(() => props.open, (isOpen) => {
  if (isOpen) {
    loadTree()
    if (props.initialPath) {
      loadFile(props.initialPath)
    }
  }
})

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})

// Resizer
function onResizerMouseDown(e: MouseEvent) {
  const startX = e.clientX
  const startWidth = drawerWidth.value

  function onMouseMove(e: MouseEvent) {
    const delta = startX - e.clientX
    drawerWidth.value = Math.min(800, Math.max(280, startWidth + delta))
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

// Tree resizer
const treeWidth = ref(220)
function onTreeResizerMouseDown(e: MouseEvent) {
  const startX = e.clientX
  const startWidth = treeWidth.value

  function onMouseMove(e: MouseEvent) {
    const delta = e.clientX - startX
    treeWidth.value = Math.min(400, Math.max(160, startWidth + delta))
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
  <template v-if="open">
    <!-- Overlay backdrop -->
    <div class="file-drawer-overlay" @click="emit('close')"></div>

    <!-- Drawer -->
    <div class="file-drawer" :style="{ width: drawerWidth + 'px' }">
      <!-- Resizer -->
      <div class="file-drawer-resizer" @mousedown="onResizerMouseDown"></div>

      <!-- Header -->
      <div class="file-drawer-header">
        <button class="fd-btn" @click="showTree = !showTree" :class="{ active: showTree }" title="Toggle tree">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        </button>

        <!-- File tabs -->
        <div class="file-drawer-tabs">
          <div
            v-for="(file, i) in openFiles"
            :key="file.path"
            :class="['file-drawer-tab', { active: activeTab === i }]"
            @click="activeTab = i"
          >
            <span class="file-drawer-tab-name">{{ file.path.split('/').pop() }}</span>
            <span
              class="file-drawer-tab-lang"
              :style="{ color: getLanguageBadgeColor(file.language), background: getLanguageBadgeColor(file.language) + '18' }"
            >{{ file.language.slice(0, 3) }}</span>
            <button class="file-drawer-tab-close" @click.stop="closeTab(i)">×</button>
          </div>
        </div>

        <div class="file-drawer-header-actions">
          <button class="fd-btn" @click="copyContent" title="复制内容">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          </button>
          <button class="fd-btn" @click="copyPath" title="复制路径">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
          </button>
          <button class="fd-btn close-btn" @click="emit('close')" title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>

      <div class="file-drawer-content">
        <!-- Tree sidebar (optional) -->
        <div v-if="showTree" class="file-drawer-tree" :style="{ width: treeWidth + 'px' }">
          <div class="file-drawer-tree-header">
            <span class="file-drawer-tree-title">📁 目录</span>
            <select class="file-drawer-tree-select" v-model="currentDir" @change="expandedDirs.add(currentDir)">
              <option value="">root</option>
              <option v-for="(_entries, dir) in fileTree" :key="dir" :value="dir" v-show="dir">{{ dir }}</option>
            </select>
          </div>
          <!-- Back navigation -->
          <div v-if="currentDir" class="fl-dir back" @click="currentDir = currentDir.split('/').slice(0, -1).join('/')">
            <span class="fl-icon">↩</span>
            <span>..</span>
          </div>
          <div class="file-drawer-tree-body">
            <div v-for="entry in getTreeEntries()" :key="entry">
              <div v-if="isDir(entry)" class="fl-dir" @click="toggleTreeDir(entry); navigateTreeTo(entry.slice(0, -1))">
                <span class="fl-arrow" :class="{ open: expandedDirs.has(entry.slice(0, -1)) }">▶</span>
                <span class="fl-icon">{{ fileIcon(entry) }}</span>
                <span>{{ entry }}</span>
              </div>
              <div v-else class="fl-item" @click="selectTreeFile(entry)">
                <span class="fl-icon">{{ fileIcon(entry) }}</span>
                <span>{{ entry }}</span>
              </div>
            </div>
          </div>
          <!-- Tree resizer -->
          <div class="file-drawer-tree-resizer" @mousedown="onTreeResizerMouseDown"></div>
        </div>

        <!-- Code area -->
        <div class="file-drawer-code-area">
          <!-- Search bar -->
          <div v-if="openFiles.length > 0" class="file-drawer-search">
            <input
              v-model="searchQuery"
              placeholder="Search in file..."
              @input="doSearch"
              @keydown.enter="nextMatch"
            />
            <span v-if="searchMatches.length" class="search-count">{{ searchMatchIdx + 1 }}/{{ searchMatches.length }}</span>
            <button class="search-nav-btn" @click="prevMatch" :disabled="!searchMatches.length">▲</button>
            <button class="search-nav-btn" @click="nextMatch" :disabled="!searchMatches.length">▼</button>
          </div>

          <!-- Loading -->
          <div v-if="isLoading" class="file-drawer-loading">Loading...</div>

          <!-- File content -->
          <div v-else-if="openFiles.length > 0 && openFiles[activeTab]" class="file-drawer-code-view">
            <div class="file-drawer-code-header">
              <span class="file-drawer-file-path">{{ openFiles[activeTab].path }}</span>
              <span
                class="file-drawer-lang-badge"
                :style="{ color: getLanguageBadgeColor(openFiles[activeTab].language) }"
              >{{ openFiles[activeTab].language }}</span>
            </div>
            <div class="file-drawer-code-body">
              <div class="file-line-nums">
                <div
                  v-for="line in openFiles[activeTab].lines"
                  :key="line.num"
                  :class="['file-line-num', { match: isMatchLine(line.num), current: isCurrentMatch(line.num) }]"
                >{{ line.num }}</div>
              </div>
              <div class="file-drawer-code-content">
                <div
                  v-for="line in openFiles[activeTab].lines"
                  :key="line.num"
                  :class="['file-drawer-line', { match: isMatchLine(line.num), current: isCurrentMatch(line.num) }]"
                  v-html="line.text || '&nbsp;'"
                ></div>
              </div>
            </div>
          </div>

          <!-- Empty state -->
          <div v-else class="file-drawer-empty">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <p>Select a file to preview</p>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>

<style scoped>
/* ── Overlay ── */
.file-drawer-overlay {
  position: fixed; inset: 0; z-index: 99;
  background: rgba(0,0,0,0.15);
}

/* ── Drawer ── */
.file-drawer {
  position: fixed; top: 0; right: 0; bottom: 0;
  z-index: 100;
  background: var(--bg-surface);
  border-left: 1px solid var(--border-strong);
  box-shadow: -4px 0 24px rgba(0,0,0,0.2);
  display: flex; flex-direction: column;
  animation: drawerIn 0.3s cubic-bezier(0.16,1,0.3,1) both;
}
@keyframes drawerIn {
  from { opacity: 0; transform: translateX(100%); }
  to { opacity: 1; transform: translateX(0); }
}

/* ── Resizer ── */
.file-drawer-resizer {
  position: absolute; left: -4px; top: 0; bottom: 0;
  width: 8px; cursor: col-resize; z-index: 101;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s;
}
.file-drawer-resizer::after {
  content: ''; width: 2px; height: 36px;
  background: var(--bg-input); border-radius: 1px; transition: all 0.2s;
}
.file-drawer-resizer:hover::after, .file-drawer-resizer:active::after {
  background: rgba(99,102,241,0.35); height: 52px;
}
.file-drawer-resizer:hover { background: rgba(99,102,241,0.05); }

/* ── Header ── */
.file-drawer-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-glass);
  flex-shrink: 0;
}
.file-drawer-header-actions { display: flex; gap: 4px; margin-left: auto; }
.fd-btn {
  width: 30px; height: 30px;
  display: flex; align-items: center; justify-content: center;
  background: transparent; border: 1px solid var(--border-light); border-radius: 6px;
  color: var(--text-tertiary); cursor: pointer; transition: all 0.15s; flex-shrink: 0;
}
.fd-btn:hover { background: var(--bg-hover); color: var(--text-secondary); }
.fd-btn.active { background: var(--accent-bg); color: var(--accent-text); border-color: var(--accent-border); }
.close-btn:hover { background: rgba(239,68,68,0.1); color: var(--color-red); }

/* ── Tabs ── */
.file-drawer-tabs {
  display: flex; gap: 4px; overflow-x: auto; flex: 1; min-width: 0;
}
.file-drawer-tab {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 10px; border-radius: 6px; cursor: pointer;
  background: var(--bg-glass); border: 1px solid var(--border-light);
  font-size: 12px; color: var(--text-secondary); transition: all 0.15s; flex-shrink: 0;
}
.file-drawer-tab.active {
  background: var(--accent-bg); border-color: var(--border-accent); color: var(--accent-text);
}
.file-drawer-tab:hover:not(.active) { background: var(--bg-hover); }
.file-drawer-tab-name {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.file-drawer-tab-lang {
  font-size: 10px; padding: 1px 5px; border-radius: 3px; font-weight: 600;
}
.file-drawer-tab-close {
  background: none; border: none; color: var(--text-faint); cursor: pointer;
  font-size: 14px; line-height: 1; padding: 0 2px;
}
.file-drawer-tab-close:hover { color: var(--color-red); }

/* ── Content ── */
.file-drawer-content {
  display: flex; flex: 1; min-height: 0; overflow: hidden;
}

/* ── Tree sidebar ── */
.file-drawer-tree {
  flex-shrink: 0;
  border-right: 1px solid var(--border-light);
  background: var(--bg-glass);
  display: flex; flex-direction: column; overflow: hidden;
  position: relative;
}
.file-drawer-tree-header {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px; border-bottom: 1px solid var(--border-light);
}
.file-drawer-tree-title {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px;
  font-weight: 600; color: var(--text-tertiary); flex-shrink: 0;
}
.file-drawer-tree-select {
  flex: 1; min-width: 0;
  padding: 3px 6px; background: var(--bg-input); border: 1px solid var(--border-input);
  border-radius: 5px; color: var(--text-secondary); font-size: 11px; outline: none;
  font-family: 'SF Mono', monospace;
}
.fl-dir.back {
  padding: 6px 12px; cursor: pointer; border-radius: 6px;
  font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 7px;
  transition: all 0.12s;
}
.fl-dir.back:hover { background: var(--bg-hover); color: var(--text-secondary); }
.file-drawer-tree-body {
  flex: 1; overflow-y: auto; padding: 6px;
}
.file-drawer-tree-resizer {
  position: absolute; right: -4px; top: 0; bottom: 0;
  width: 8px; cursor: col-resize; z-index: 101;
  display: flex; align-items: center; justify-content: center;
}
.file-drawer-tree-resizer:hover { background: rgba(99,102,241,0.05); }

/* ── Code area ── */
.file-drawer-code-area {
  flex: 1; display: flex; flex-direction: column; min-width: 0; overflow: hidden;
}

/* ── Search ── */
.file-drawer-search {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}
.file-drawer-search input {
  flex: 1; padding: 6px 10px;
  background: var(--bg-input); border: 1px solid var(--border-input); border-radius: 6px;
  color: var(--text-primary); font-size: 13px; outline: none;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.file-drawer-search input:focus { border-color: var(--accent-focus); }
.search-count {
  font-size: 12px; color: var(--text-muted);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; flex-shrink: 0;
}
.search-nav-btn {
  width: 26px; height: 26px;
  display: flex; align-items: center; justify-content: center;
  background: transparent; border: 1px solid var(--border-light); border-radius: 5px;
  color: var(--text-tertiary); cursor: pointer; font-size: 11px; transition: all 0.15s;
}
.search-nav-btn:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-secondary); }
.search-nav-btn:disabled { opacity: 0.3; cursor: not-allowed; }

/* ── Loading ── */
.file-drawer-loading {
  flex: 1; display: flex; align-items: center; justify-content: center;
  color: var(--text-muted); font-size: 13px;
}

/* ── Code view ── */
.file-drawer-code-view {
  display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden;
}
.file-drawer-code-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 14px;
  background: var(--bg-glass);
  border-bottom: 1px solid var(--border-light);
  font-size: 12px; color: var(--text-tertiary); flex-shrink: 0;
}
.file-drawer-file-path {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px; color: var(--text-muted);
}
.file-drawer-lang-badge {
  font-size: 11px; font-weight: 600; letter-spacing: 0.3px;
}
.file-drawer-code-body {
  display: flex; flex: 1; overflow: auto;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12.5px; line-height: 1.6;
  background: var(--bg-code);
}
.file-line-nums {
  padding: 10px 0; text-align: right; user-select: none;
  border-right: 1px solid var(--border-light);
  min-width: 42px; flex-shrink: 0;
}
.file-line-num {
  padding: 0 12px 0 0; color: var(--text-faint); font-size: 12px;
}
.file-line-num.match { color: var(--accent); font-weight: 600; }
.file-line-num.current { color: #fbbf24; font-weight: 700; }

.file-drawer-code-content {
  padding: 10px 16px; flex: 1; overflow-x: auto; white-space: pre; color: var(--text-secondary);
}
.file-drawer-line { transition: background 0.15s; padding: 0 4px; border-radius: 2px; }
.file-drawer-line.match { background: rgba(99,102,241,0.08); }
.file-drawer-line.current { background: rgba(251,191,36,0.12); }

/* ── Syntax highlight tokens ── */
:deep(.hl-key) { color: var(--accent); }
:deep(.hl-str) { color: var(--color-amber); }
:deep(.hl-fn) { color: var(--color-green); }
:deep(.hl-com) { color: var(--text-faint); font-style: italic; }
:deep(.hl-dec) { color: var(--color-amber); }
:deep(.hl-cls) { color: var(--accent-text); }

/* ── Empty state ── */
.file-drawer-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; padding: 30px; color: var(--text-muted); font-size: 13px;
}

/* ── Tree entries ── */
.fl-dir {
  display: flex; align-items: center; gap: 7px;
  padding: 6px 10px; cursor: pointer; border-radius: 6px;
  font-size: 13px; color: var(--accent-text); font-weight: 540;
  transition: all 0.12s; user-select: none;
}
.fl-dir:hover { background: var(--bg-active); }
.fl-arrow {
  font-size: 12px; color: var(--text-faint); width: 14px; flex-shrink: 0;
  transition: transform 0.15s;
}
.fl-arrow.open { transform: rotate(90deg); }
.fl-item {
  display: flex; align-items: center; gap: 7px;
  padding: 5px 10px; cursor: pointer; border-radius: 6px;
  font-size: 12px; color: var(--text-secondary); transition: all 0.12s; white-space: nowrap;
}
.fl-item:hover { background: var(--bg-hover); color: var(--text-primary); }
.fl-icon { font-size: 13px; width: 18px; text-align: center; flex-shrink: 0; }
</style>
