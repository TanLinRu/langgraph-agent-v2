<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { browseDirectories, listDrives, type BrowseNode } from '../utils/api'

const props = defineProps<{
  initialPath?: string
}>()

const emit = defineEmits<{
  select: [path: string]
}>()

// 'drives' | 'browse' (browse a specific path)
const rootPath = ref<string>('')
const drives = ref<Array<{ path: string; label: string }>>([])
const currentNode = ref<BrowseNode | null>(null)
const expanded = ref<Set<string>>(new Set())
const loading = ref(false)
const errorMsg = ref('')
const childrenCache = ref<Map<string, BrowseNode[]>>(new Map())
const search = ref('')
const flatList = ref<BrowseNode[]>([])

async function loadDrives() {
  try {
    drives.value = await listDrives()
  } catch (e: any) {
    errorMsg.value = e.message || '无法读取驱动器列表'
  }
}

async function loadRoot(path: string, depth = 2) {
  loading.value = true
  errorMsg.value = ''
  currentNode.value = null
  expanded.value = new Set()
  childrenCache.value = new Map()
  rootPath.value = path
  try {
    currentNode.value = await browseDirectories(path, depth, false)
  } catch (e: any) {
    errorMsg.value = e.message || '无法读取目录'
  } finally {
    loading.value = false
  }
}

async function loadChildren(node: BrowseNode) {
  if (childrenCache.value.has(node.path)) return
  try {
    const child = await browseDirectories(node.path, 1, false)
    childrenCache.value.set(node.path, child.children || [])
  } catch (e: any) {
    childrenCache.value.set(node.path, [])
  }
}

function toggleNode(node: BrowseNode) {
  if (expanded.value.has(node.path)) {
    expanded.value.delete(node.path)
  } else {
    expanded.value.add(node.path)
    if (!childrenCache.value.has(node.path)) {
      void loadChildren(node)
    }
  }
  expanded.value = new Set(expanded.value)
}

function selectNode(node: BrowseNode) {
  emit('select', node.path)
}

function selectCurrent() {
  if (currentNode.value) emit('select', currentNode.value.path)
}

function goUp() {
  if (!currentNode.value) return
  const p = currentNode.value.path
  let parent: string
  if (p.length <= 3 && (p[1] === ':' || p.startsWith('\\\\'))) {
    // At drive root, go back to drives view
    currentNode.value = null
    rootPath.value = ''
    return
  }
  // Strip last path segment
  const idx = p.replace(/[\\/]+$/, '').lastIndexOf('\\')
  if (idx < 0) {
    parent = p.substring(0, 2)  // e.g., "C:" for "C:\Users"
  } else {
    parent = p.substring(0, idx)
  }
  void loadRoot(parent, 2)
}

function breadcrumbParts(): Array<{ label: string; path: string }> {
  if (!currentNode.value) return []
  const parts: Array<{ label: string; path: string }> = []
  const full = currentNode.value.path
  if (full.length >= 2 && full[1] === ':') {
    parts.push({ label: full.substring(0, 3), path: full.substring(0, 3) })  // "C:\"
    let rest = full.substring(3)
    let acc = full.substring(0, 3)
    const segs = rest.split(/[\\/]+/).filter(Boolean)
    for (const s of segs) {
      acc = acc.endsWith('\\') ? acc + s : acc + '\\' + s
      parts.push({ label: s, path: acc })
    }
  } else {
    const segs = full.split('/').filter(Boolean)
    let acc = ''
    for (const s of segs) {
      acc = acc + '/' + s
      parts.push({ label: s, path: acc })
    }
  }
  return parts
}

function onSearchInput() {
  const q = search.value.trim().toLowerCase()
  if (!q) {
    flatList.value = []
    return
  }
  if (!currentNode.value) return
  // Flatten current 2-level tree, filter by name
  const results: BrowseNode[] = []
  function walk(n: BrowseNode) {
    if (n.type === 'dir' && n.name.toLowerCase().includes(q) && n !== currentNode.value) {
      results.push(n)
    }
    if (n.children) for (const c of n.children) walk(c)
  }
  walk(currentNode.value)
  flatList.value = results.slice(0, 50)
}

function clearSearch() {
  search.value = ''
  flatList.value = []
}

onMounted(async () => {
  await loadDrives()
  if (props.initialPath) {
    void loadRoot(props.initialPath, 2)
  }
})
</script>

<template>
  <div class="dtb">
    <!-- Drives selector -->
    <div v-if="!currentNode" class="dtb-drives">
      <div class="dtb-section-label">选择驱动器</div>
      <div class="dtb-drives-grid">
        <button
          v-for="d in drives"
          :key="d.path"
          class="dtb-drive-btn"
          :disabled="loading"
          @click="loadRoot(d.path, 2)"
        >
          <span class="dtb-drive-icon">💾</span>
          <span class="dtb-drive-path">{{ d.path }}</span>
        </button>
      </div>
      <div v-if="errorMsg" class="dtb-error">{{ errorMsg }}</div>
      <div v-if="loading" class="dtb-loading">加载中...</div>
    </div>

    <!-- Tree browser -->
    <div v-else class="dtb-tree">
      <!-- Breadcrumb + up -->
      <div class="dtb-toolbar">
        <button class="dtb-up-btn" @click="goUp" :disabled="loading" title="上一级">←</button>
        <div class="dtb-breadcrumb">
          <template v-for="(p, i) in breadcrumbParts()" :key="p.path">
            <span v-if="i > 0" class="dtb-bc-sep">/</span>
            <button class="dtb-bc-link" @click="loadRoot(p.path, 2)">{{ p.label }}</button>
          </template>
        </div>
      </div>

      <!-- Search -->
      <div class="dtb-search-wrap">
        <input
          v-model="search"
          class="dtb-search"
          placeholder="筛选当前层目录..."
          @input="onSearchInput"
        />
        <button v-if="search" class="dtb-search-clear" @click="clearSearch">✕</button>
      </div>

      <!-- Error -->
      <div v-if="errorMsg" class="dtb-error">{{ errorMsg }}</div>
      <div v-if="loading" class="dtb-loading">加载中...</div>

      <!-- Flat search results -->
      <div v-if="search && flatList.length" class="dtb-list">
        <button
          v-for="n in flatList"
          :key="n.path"
          class="dtb-item"
          @click="selectNode(n)"
          @dblclick="toggleNode(n)"
        >
          <span class="dtb-item-icon">📁</span>
          <span class="dtb-item-name">{{ n.name }}</span>
        </button>
        <div v-if="!flatList.length" class="dtb-empty">无匹配</div>
      </div>

      <!-- Tree (no search active) -->
      <div v-else-if="!search && currentNode" class="dtb-list">
        <button
          class="dtb-item dtb-item-current"
          @click="selectCurrent"
          title="点击选择此目录"
        >
          <span class="dtb-item-icon dtb-item-current-icon">📂</span>
          <span class="dtb-item-name dtb-item-current-name">{{ currentNode.name || currentNode.path }}</span>
          <span class="dtb-item-action">使用此目录</span>
        </button>
        <div
          v-for="n in (currentNode.children || []).filter(c => c.type === 'dir')"
          :key="n.path"
          class="dtb-branch"
        >
          <button class="dtb-item" @click="toggleNode(n)" @dblclick="selectNode(n)">
            <span class="dtb-item-caret" :class="{ open: expanded.has(n.path) }">▸</span>
            <span class="dtb-item-icon">📁</span>
            <span class="dtb-item-name">{{ n.name }}</span>
            <button class="dtb-item-pick" @click.stop="selectNode(n)" title="选择此目录">→</button>
          </button>
          <div v-if="expanded.has(n.path) && childrenCache.get(n.path)?.length" class="dtb-children">
            <button
              v-for="c in childrenCache.get(n.path) || []"
              :key="c.path"
              class="dtb-item dtb-item-child"
              @click="selectNode(c)"
              @dblclick="toggleNode(c)"
            >
              <span class="dtb-item-caret" :class="{ open: expanded.has(c.path), empty: !childrenCache.get(c.path)?.length }">
                {{ childrenCache.get(c.path)?.length ? '▸' : '·' }}
              </span>
              <span class="dtb-item-icon">📁</span>
              <span class="dtb-item-name">{{ c.name }}</span>
              <button class="dtb-item-pick" @click.stop="selectNode(c)" title="选择此目录">→</button>
            </button>
          </div>
          <div v-else-if="expanded.has(n.path) && !childrenCache.has(n.path)" class="dtb-children-loading">加载...</div>
          <div v-else-if="expanded.has(n.path) && childrenCache.has(n.path) && !childrenCache.get(n.path)?.length" class="dtb-children-empty">(空目录)</div>
        </div>
        <div v-if="!(currentNode.children || []).filter(c => c.type === 'dir').length" class="dtb-empty">无子目录</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dtb {
  display: flex; flex-direction: column;
  min-height: 280px; max-height: 50vh;
  background: var(--bg-elevated, rgba(0,0,0,0.15));
  border-radius: 8px;
  overflow: hidden;
}
.dtb-drives {
  padding: 16px;
  display: flex; flex-direction: column; gap: 12px;
}
.dtb-section-label {
  font-size: 11px; color: var(--text-faint); font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.dtb-drives-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
  gap: 8px;
}
.dtb-drive-btn {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: 12px 8px;
  background: var(--bg-message, rgba(255,255,255,0.04));
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  color: var(--text-primary);
  font-family: inherit;
}
.dtb-drive-btn:hover:not(:disabled) {
  background: rgba(129, 140, 248, 0.1);
  border-color: var(--accent);
}
.dtb-drive-icon { font-size: 22px; }
.dtb-drive-path { font-size: 12px; font-weight: 500; font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; }

.dtb-tree {
  display: flex; flex-direction: column; flex: 1; min-height: 0;
}
.dtb-toolbar {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-message, rgba(255,255,255,0.02));
}
.dtb-up-btn {
  flex-shrink: 0;
  width: 26px; height: 26px;
  background: var(--bg-message);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer; font-size: 13px;
  color: var(--text-secondary);
}
.dtb-up-btn:hover:not(:disabled) { background: var(--bg-hover); }
.dtb-breadcrumb {
  flex: 1; min-width: 0;
  display: flex; align-items: center; gap: 2px;
  overflow-x: auto;
  font-size: 12px;
  white-space: nowrap;
  scrollbar-width: thin;
}
.dtb-bc-link {
  background: none; border: none; padding: 2px 4px;
  color: var(--text-secondary);
  cursor: pointer; font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 11.5px;
  border-radius: 3px;
}
.dtb-bc-link:hover { background: var(--bg-hover); color: var(--accent); }
.dtb-bc-sep { color: var(--text-faint); font-size: 10px; }

.dtb-search-wrap {
  position: relative;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-light);
}
.dtb-search {
  width: 100%;
  padding: 6px 28px 6px 10px;
  background: var(--bg-input, var(--bg-message));
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  box-sizing: border-box;
  font-family: inherit;
}
.dtb-search:focus {
  border-color: var(--accent);
}
.dtb-search-clear {
  position: absolute; right: 14px; top: 50%; transform: translateY(-50%);
  background: none; border: none;
  color: var(--text-faint); font-size: 12px;
  cursor: pointer; padding: 2px 6px;
}
.dtb-search-clear:hover { color: var(--text-secondary); }

.dtb-list {
  flex: 1; overflow-y: auto;
  padding: 4px 4px 8px;
  min-height: 100px;
}
.dtb-item {
  display: flex; align-items: center; gap: 6px;
  width: 100%;
  padding: 5px 8px;
  background: transparent;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 12.5px;
  text-align: left;
  transition: background 0.1s;
}
.dtb-item:hover { background: var(--bg-hover); }
.dtb-item-current {
  background: rgba(129, 140, 248, 0.08);
  border: 1px solid rgba(129, 140, 248, 0.25);
  margin-bottom: 4px;
}
.dtb-item-current:hover { background: rgba(129, 140, 248, 0.14); }
.dtb-item-current-icon { color: #818cf8; }
.dtb-item-current-name { font-weight: 600; color: var(--text-primary); }
.dtb-item-action {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--accent);
  background: rgba(129, 140, 248, 0.15);
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 500;
}
.dtb-item-caret {
  display: inline-block;
  width: 12px;
  font-size: 9px;
  color: var(--text-faint);
  transition: transform 0.15s;
  text-align: center;
}
.dtb-item-caret.open { transform: rotate(90deg); }
.dtb-item-caret.empty { color: var(--text-faint); opacity: 0.5; }
.dtb-item-icon { font-size: 13px; flex-shrink: 0; }
.dtb-item-name {
  flex: 1; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dtb-item-pick {
  flex-shrink: 0;
  background: rgba(129, 140, 248, 0.1);
  border: 1px solid rgba(129, 140, 248, 0.25);
  color: var(--accent);
  padding: 1px 7px;
  border-radius: 3px;
  font-size: 11px;
  cursor: pointer;
  font-family: inherit;
  opacity: 0; transition: opacity 0.15s;
}
.dtb-item:hover .dtb-item-pick { opacity: 1; }
.dtb-item-pick:hover { background: rgba(129, 140, 248, 0.2); }
.dtb-item-child { padding-left: 22px; font-size: 12px; }
.dtb-children { display: flex; flex-direction: column; }
.dtb-children-loading, .dtb-children-empty {
  font-size: 11px; color: var(--text-faint);
  padding: 4px 8px 4px 32px;
  font-style: italic;
}
.dtb-empty {
  font-size: 12px; color: var(--text-faint);
  padding: 16px 8px; text-align: center;
}
.dtb-error {
  font-size: 12px; color: #ef4444;
  padding: 8px 12px; background: rgba(239,68,68,0.06);
  border-radius: 6px; margin: 8px;
}
.dtb-loading {
  font-size: 12px; color: var(--text-faint);
  padding: 12px; text-align: center;
}
</style>
