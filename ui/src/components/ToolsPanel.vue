<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAgentsStore } from '../stores/agents'

const store = useAgentsStore()

interface ToolInfo {
  name: string
  description: string
  type: string
  icon: string
  usage: number
  lastUsed: string | null
}

const selectedTool = ref<ToolInfo | null>(null)

onMounted(() => {
  store.fetchTools()
})

const TOOL_CATEGORIES: Record<string, { icon: string; color: string; tools: string[] }> = {
  Core: { icon: '⚙', color: '#818cf8', tools: ['execute_code', 'read_file', 'write_file', 'list_directory', 'search_files'] },
  Skill: { icon: '📄', color: '#fbbf24', tools: [] },
  MCP: { icon: '🔌', color: '#34d399', tools: [] },
}

function getCategory(toolName: string): string {
  for (const [cat, info] of Object.entries(TOOL_CATEGORIES)) {
    if (info.tools.includes(toolName)) return cat
  }
  return 'Skill'
}

function getToolsByCategory(cat: string): ToolInfo[] {
  return store.tools.filter(t => getCategory(t.name) === cat) as ToolInfo[]
}

function selectTool(tool: ToolInfo) {
  selectedTool.value = selectedTool.value?.name === tool.name ? null : tool
}

function formatLastUsed(dateStr: string | null): string {
  if (!dateStr) return '从未'
  const d = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `${diffH}小时前`
  return `${Math.floor(diffH / 24)}天前`
}
</script>

<template>
  <div class="tools-panel">
    <template v-for="(info, cat) in TOOL_CATEGORIES" :key="cat">
      <div class="tools-group">
        <div class="tools-group-h">
          <span :style="{ color: info.color }">{{ info.icon }}</span>
          {{ cat === 'Core' ? '核心工具' : cat === 'Skill' ? '技能' : 'MCP' }}
          <span :class="['tools-type-badge', cat.toLowerCase()]">{{ getToolsByCategory(cat).length }}</span>
        </div>
        <div
          v-for="tool in getToolsByCategory(cat)"
          :key="tool.name"
          :class="['tool-card', { selected: selectedTool?.name === tool.name }]"
          @click="selectTool(tool)"
        >
          <div class="tool-icon-s" :style="{ background: info.color + '18', color: info.color }">{{ info.icon }}</div>
          <div class="tool-info-s">
            <div class="tool-name-s">{{ tool.name }}</div>
            <div class="tool-desc-s">{{ tool.description }}</div>
          </div>
          <div class="tool-usage">
            <span class="tool-usage-badge">{{ tool.usage || 0 }}</span>
          </div>
        </div>
        <div v-if="getToolsByCategory(cat).length === 0" class="tool-empty">
          {{ cat === 'Skill' ? '技能从 skills/*.md 运行时加载' : cat === 'MCP' ? 'MCP 工具连接后显示' : '' }}
        </div>
      </div>
    </template>

    <!-- Tool detail view -->
    <div v-if="selectedTool" class="tool-detail-card">
      <div class="tool-detail-header">
        <span class="tool-detail-name">{{ selectedTool.name }}</span>
        <button class="tool-detail-close" @click="selectedTool = null">×</button>
      </div>
      <div class="tool-detail-desc">{{ selectedTool.description }}</div>
      <div class="tool-detail-rows">
        <div class="tool-detail-row">
          <span class="tool-detail-label">类型</span>
          <span class="tool-detail-value">{{ getCategory(selectedTool.name) }}</span>
        </div>
        <div class="tool-detail-row">
          <span class="tool-detail-label">调用次数</span>
          <span class="tool-detail-value">{{ selectedTool.usage || 0 }}</span>
        </div>
        <div class="tool-detail-row">
          <span class="tool-detail-label">最后使用</span>
          <span class="tool-detail-value">{{ formatLastUsed(selectedTool.lastUsed) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tools-panel { padding: 0; }
.tools-group { margin-bottom: 14px; }
.tools-group-h {
  display: flex; align-items: center; gap: 7px;
  font-size: 13px; font-weight: 620; text-transform: uppercase; letter-spacing: 0.6px;
  color: var(--text-tertiary); margin-bottom: 8px; padding: 0 2px;
}
.tools-type-badge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px;
  padding: 2px 7px; border-radius: 4px; margin-left: auto;
}
.tools-type-badge.core { background: rgba(129,140,248,0.12); color: var(--accent-text); }
.tools-type-badge.skill { background: rgba(251,191,36,0.12); color: #fbbf24; }
.tools-type-badge.mcp { background: rgba(52,211,153,0.12); color: #34d399; }

.tool-card {
  display: flex; align-items: center; gap: 12px; padding: 11px 13px; border-radius: 9px;
  border: 1px solid var(--border-light); background: var(--bg-card);
  margin-bottom: 8px; cursor: pointer; transition: all 0.15s;
}
.tool-card:hover { background: var(--bg-hover); }
.tool-card.selected { border-color: var(--accent-border); background: var(--accent-bg); }
.tool-icon-s {
  width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 7px; font-size: 15px; flex-shrink: 0;
}
.tool-info-s { flex: 1; min-width: 0; }
.tool-name-s {
  font-size: 14px; font-weight: 540; color: var(--accent-text);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
}
.tool-desc-s {
  font-size: 13px; color: var(--text-tertiary); margin-top: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tool-usage { flex-shrink: 0; }
.tool-usage-badge {
  background: var(--bg-hover); padding: 2px 7px; border-radius: 4px;
  font-family: 'SF Mono', monospace; font-size: 12px; color: var(--text-muted);
}
.tool-empty { font-size: 12px; color: var(--text-faint); padding: 8px 0; font-style: italic; }

/* Tool detail */
.tool-detail-card {
  background: var(--bg-card); border: 1px solid var(--border-light);
  border-radius: 11px; padding: 16px; margin-top: 12px;
  border-left: 2px solid var(--accent-border);
  animation: msgIn 0.3s cubic-bezier(0.16,1,0.3,1) both;
}
@keyframes msgIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
.tool-detail-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--border-light);
}
.tool-detail-name {
  font-size: 15px; font-weight: 560; color: var(--accent-text);
  font-family: 'SF Mono', monospace;
}
.tool-detail-close {
  width: 24px; height: 24px; display: flex; align-items: center; justify-content: center;
  background: transparent; border: none; color: var(--text-faint); cursor: pointer;
  border-radius: 4px; font-size: 16px;
}
.tool-detail-close:hover { background: var(--bg-hover); color: var(--text-primary); }
.tool-detail-desc { font-size: 13px; color: var(--text-secondary); margin-bottom: 12px; }
.tool-detail-rows { display: flex; flex-direction: column; gap: 0; }
.tool-detail-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 0; border-bottom: 1px solid var(--border-light);
}
.tool-detail-row:last-child { border-bottom: none; }
.tool-detail-label { font-size: 13px; color: var(--text-muted); }
.tool-detail-value {
  font-size: 13px; color: var(--text-primary);
  font-family: 'SF Mono', monospace;
}
</style>
