<script setup lang="ts">
/**
 * 智能体消息气泡
 *
 * 完整的 AI 助手消息渲染,包含:
 * - 左侧头像列 (ConvAvatar + 状态指示器)
 * - 右侧气泡 (header + handoff + thinking + tool_calls + results + summary + 正文 + file_refs + error)
 *
 * 依赖已有的 ThinkingBlock / ToolCallBlock / ToolResultBlock / SummaryBlock / ErrorBlock / HandoffBadge / ConvAvatar。
 */
import { inject } from 'vue'
import ConvAvatar from '../ConvAvatar.vue'
import ThinkingBlock from '../ThinkingBlock.vue'
import ToolCallBlock from '../ToolCallBlock.vue'
import ToolResultBlock from '../ToolResultBlock.vue'
import SummaryBlock from '../SummaryBlock.vue'
import ErrorBlock from '../ErrorBlock.vue'
import HandoffBadge from '../HandoffBadge.vue'
import { renderMd } from '../../utils/useMarkdown'
import type { ChatMessage } from '../../utils/api'

const props = defineProps<{
  msg: ChatMessage
  index: number
  isTyping: boolean
}>()

const emit = defineEmits<{
  fileClick: [path: string]
}>()

const openFile = inject<(path: string) => void>('openFile')

const AGENT_COLORS: Record<string, string> = {
  supervisor: '#818cf8',
  coder: '#34d399',
  researcher: '#fbbf24',
  analyst: '#fb7185',
  direct: '#60a5fa',
  opencode: '#059669',
  'claude-agent': '#d97706',
}
const AGENT_LABELS: Record<string, string> = {
  supervisor: 'Supervisor',
  coder: 'Coder',
  researcher: 'Researcher',
  analyst: 'Analyst',
  direct: 'Direct',
  opencode: 'OpenCode',
  'claude-agent': 'Claude',
}
const STATUS_LABELS: Record<string, string> = {
  idle: '空闲',
  receiving: '接收任务',
  deciding: '决策中',
  thinking: '思考中',
  delegating: '派发中',
  aggregating: '汇总中',
  waiting: '等待',
  working: '工作中',
  done: '完成',
  failed: '失败',
}

function agentColor(name?: string): string {
  return AGENT_COLORS[name || ''] || 'var(--accent)'
}
function agentLabel(name?: string): string {
  return AGENT_LABELS[name || ''] || name || 'assistant'
}
function agentType(name?: string): string {
  return name || 'helper'
}
function statusLabel(s?: string): string {
  if (!s) return ''
  return STATUS_LABELS[s] || s
}
</script>

<template>
  <div class="msg-agent-wrap" :style="{ '--agent-color': agentColor(msg.agentName) }">
    <!-- 左侧头像列 -->
    <div class="msg-avatar-col">
      <ConvAvatar :type="agentType(msg.agentName)" :size="32" />
      <div :class="['msg-avatar-state', isTyping ? 'streaming' : (msg.agentStatus === 'failed' ? 'failed' : 'done')]"></div>
    </div>

    <!-- 右侧气泡 -->
    <div :class="['msg-agent-bubble', !isTyping && (msg.content || msg.toolCalls?.length) ? 'done-anim' : '']"
         :style="{ borderLeftColor: agentColor(msg.agentName) }">

      <!-- Header: 名称 + 状态徽章 -->
      <div class="msg-agent-header">
        <span class="msg-agent-name" :style="{ color: agentColor(msg.agentName) }">{{ agentLabel(msg.agentName) }}</span>
        <span v-if="msg.agentStatus" class="msg-state-badge" :class="msg.agentStatus">
          {{ statusLabel(msg.agentStatus) }}
        </span>
      </div>

      <!-- Handoff 交接徽章 -->
      <HandoffBadge
        v-if="msg.handoffFrom && msg.handoffTo"
        :from="msg.handoffFrom"
        :to="msg.handoffTo"
      />

      <!-- 思考过程 -->
      <ThinkingBlock
        v-if="msg.thinking"
        :content="msg.thinking"
        :streaming="!!isTyping && !!msg.isThinking"
        :done="!!msg.thinkingDone"
      />

      <!-- 工具调用 -->
      <div v-if="msg.toolCalls?.length" class="tool-calls">
        <ToolCallBlock
          v-for="(tc, j) in msg.toolCalls"
          :key="j"
          :tool="{
            name: tc.name,
            args: tc.args,
            status: tc.status || (isTyping && j === msg.toolCalls!.length - 1 ? 'running' : 'done'),
          }"
        />
      </div>

      <!-- 工具结果 -->
      <ToolResultBlock
        v-for="(tr, j) in (msg.toolResults || [])"
        :key="'tr-' + j"
        :result="tr.content"
        :success="tr.success !== false"
      />

      <!-- 汇总结论 -->
      <SummaryBlock
        v-if="msg.summary"
        :agentName="msg.agentName"
        :content="msg.summary"
        :childrenCount="msg.toolResults?.length || 0"
      />

      <!-- 正文 (Markdown 渲染) -->
      <div class="msg-text md-body" v-if="msg.content || isTyping">
        <span v-html="renderMd(msg.content || '')"></span>
        <span v-if="isTyping && !msg.thinking" class="stream-cursor"></span>
      </div>

      <!-- 文件引用列表 -->
      <div v-if="msg.fileRefs?.length" class="file-refs">
        <span
          v-for="fileRef in msg.fileRefs"
          :key="fileRef"
          class="file-ref"
          @click="openFile ? openFile(fileRef) : emit('fileClick', fileRef)"
        >
          <span class="file-ref-icon">📄</span>
          {{ fileRef }}
        </span>
      </div>

      <!-- 行内错误 (assistant 消息包含错误负载时) -->
      <ErrorBlock
        v-if="msg.isError && msg.role === 'assistant' && msg.content"
        :message="msg.content"
        :agentName="msg.agentName"
      />
    </div>
  </div>
</template>

<style scoped>
@import 'highlight.js/styles/github-dark.css';
@import 'katex/dist/katex.min.css';

/* Agent message wrapper */
.msg-agent-wrap {
  display: flex; gap: 12px; align-items: flex-start;
  align-self: flex-start; width: 85%;
  animation: msgIn 0.35s cubic-bezier(0.16,1,0.3,1) both;
}
@keyframes msgIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

/* Avatar column */
.msg-avatar-col { display: flex; flex-direction: column; align-items: center; width: 32px; flex-shrink: 0; position: relative; }
.msg-avatar-state { position: absolute; bottom: -2px; right: -2px; width: 9px; height: 9px; border-radius: 50%; border: 2px solid var(--avatar-border); }
.msg-avatar-state.streaming { background: var(--accent); box-shadow: 0 0 10px rgba(129,140,248,0.6); animation: avatarPulse 0.8s ease-in-out infinite; }
.msg-avatar-state.done { background: var(--color-green); }
.msg-avatar-state.failed { background: #ef4444; box-shadow: 0 0 8px rgba(239,68,68,0.5); }
@keyframes avatarPulse { 0%,100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.35); opacity: 0.6; } }

/* Bubble */
.msg-agent-bubble {
  flex: 1; min-width: 0;
  padding: 13px 20px; border-radius: 14px;
  border: 1px solid var(--border);
  background: var(--bg-glass);
  border-bottom-left-radius: 5px;
  border-left: 3px solid var(--agent-color, var(--accent));
  display: flex; flex-direction: column;
}
.msg-agent-bubble.done-anim { animation: bubbleDone 0.4s cubic-bezier(0.34,1.56,0.64,1) both; }
@keyframes bubbleDone { 0% { transform: scale(1); } 50% { transform: scale(1.015); } 100% { transform: scale(1); } }

/* Header */
.msg-agent-header { display: flex; align-items: center; gap: 7px; margin-bottom: 6px; }
.msg-agent-name { font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px; font-weight: 620; }
.msg-state-badge { font-size: 10.5px; padding: 2px 8px; border-radius: 5px; margin-left: auto; font-weight: 500; letter-spacing: 0.3px; }
.msg-state-badge.idle { background: rgba(148,163,184,0.08); color: var(--text-faint); }
.msg-state-badge.receiving, .msg-state-badge.deciding, .msg-state-badge.thinking, .msg-state-badge.waiting {
  background: rgba(129,140,248,0.1); color: var(--accent); animation: badgePulse 1.2s ease-in-out infinite;
}
.msg-state-badge.delegating { background: rgba(251,191,36,0.1); color: #fbbf24; animation: badgePulse 1.2s ease-in-out infinite; }
.msg-state-badge.aggregating { background: rgba(167,139,250,0.1); color: #c084fc; animation: badgePulse 1.2s ease-in-out infinite; }
.msg-state-badge.working { background: rgba(96,165,250,0.1); color: #60a5fa; animation: badgePulse 1.2s ease-in-out infinite; }
.msg-state-badge.done { background: rgba(52,211,153,0.08); color: var(--color-green); }
.msg-state-badge.failed { background: rgba(239,68,68,0.1); color: #ef4444; }
@keyframes badgePulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }

/* Cursor */
.stream-cursor { display: inline-block; width: 2px; height: 18px; background: var(--text-secondary); animation: blinkCursor 0.7s step-end infinite; vertical-align: text-bottom; margin-left: 2px; }
@keyframes blinkCursor { 50% { opacity: 0; } }

/* File refs */
.file-refs { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
.file-ref { display: inline-flex; align-items: center; gap: 5px; padding: 4px 12px; margin: 1px 2px; background: var(--accent-bg); border: 1px solid var(--border-accent); border-radius: 7px; color: var(--accent-text); font-size: 13px; font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; cursor: pointer; transition: all 0.15s; }
.file-ref:hover { background: var(--accent-bg-hover); border-color: var(--accent-focus); }
.file-ref-icon { font-size: 12px; }

.tool-calls { margin-top: 6px; display: flex; flex-direction: column; gap: 3px; width: 100%; align-items: flex-start; }

.msg-text { font-size: 16px; line-height: 1.7; font-weight: 450; color: var(--text-primary); white-space: pre-wrap; word-wrap: break-word; }

/* Markdown styles */
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3), .md-body :deep(h4) { margin: 16px 0 8px; font-weight: 600; color: var(--text-primary); }
.md-body :deep(h1) { font-size: 1.4em; }
.md-body :deep(h2) { font-size: 1.2em; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
.md-body :deep(h3) { font-size: 1.05em; }
.md-body :deep(p) { margin: 6px 0; }
.md-body :deep(ul), .md-body :deep(ol) { margin: 6px 0; padding-left: 20px; }
.md-body :deep(blockquote) { margin: 8px 0; padding: 4px 12px; border-left: 3px solid var(--accent); background: var(--accent-bg); border-radius: 0 6px 6px 0; color: var(--text-secondary); }
.md-body :deep(code) { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-size: 0.9em; background: var(--bg-code); padding: 1px 5px; border-radius: 4px; color: var(--accent-text); }
.md-body :deep(pre) { margin: 8px 0; padding: 12px; background: var(--bg-code); border-radius: 8px; overflow-x: auto; border: 1px solid var(--border-light); }
.md-body :deep(pre code) { background: none; padding: 0; font-size: 13px; color: var(--text-secondary); }
.md-body :deep(table) { margin: 8px 0; border-collapse: collapse; width: 100%; font-size: 13px; }
.md-body :deep(th), .md-body :deep(td) { padding: 6px 10px; border: 1px solid var(--border); text-align: left; }
.md-body :deep(th) { background: var(--bg-glass); font-weight: 600; }
.md-body :deep(hr) { margin: 12px 0; border: none; border-top: 1px solid var(--border); }
.md-body :deep(a) { color: var(--accent); text-decoration: none; }
.md-body :deep(a:hover) { text-decoration: underline; }
.md-body :deep(strong) { color: var(--text-primary); font-weight: 600; }
.md-body :deep(.katex-display) { margin: 8px 0; padding: 8px 12px; background: var(--bg-code); border-radius: 6px; overflow-x: auto; }
.md-body :deep(.katex) { font-size: 1.05em; color: var(--text-primary); }
</style>
