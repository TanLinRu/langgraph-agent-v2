<template>
  <Teleport to="body">
    <div v-if="review" class="review-overlay" @click.self="() => {}">
      <div class="review-dialog">
        <div class="review-header">
          <span class="review-icon">📋</span>
          <h3>审批计划</h3>
        </div>
        <div class="review-body">
          <p class="review-label">监督者已生成执行计划，请审批：</p>
          <div class="plan-preview" v-if="review.plan">
            <div v-for="(step, i) in (review.plan as any)?.steps" :key="i" class="plan-step">
              <span class="step-agent">{{ step.agent }}</span>
              <span class="step-task">{{ step.task }}</span>
            </div>
            <div v-if="!(review.plan as any)?.steps?.length" class="plan-empty">(无步骤)</div>
          </div>
          <div class="plan-preview" v-else>
            <div class="plan-empty">(计划数据不可用)</div>
          </div>
          <div class="review-actions">
            <button class="review-btn approve" @click="submit('approve')" title="批准执行">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            </button>
            <button class="review-btn revise" @click="startRevise" title="修改计划">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            <button class="review-btn reject" @click="submit('reject')" title="拒绝">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div v-if="showFeedback" class="feedback-row">
            <input v-model="feedback" class="feedback-input" placeholder="输入修改意见..." @keydown.enter="submit('revise')" />
            <button class="review-btn revise small" @click="submit('revise')" title="发送">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  review: { threadId: string; plan: Record<string, unknown> | null } | null
}>()

const emit = defineEmits<{
  resolve: [decision: 'approve' | 'revise' | 'reject', feedback?: string]
}>()

const showFeedback = ref(false)
const feedback = ref('')

function submit(decision: 'approve' | 'revise' | 'reject') {
  emit('resolve', decision, feedback.value)
  showFeedback.value = false
  feedback.value = ''
}

function startRevise() {
  showFeedback.value = !showFeedback.value
}
</script>

<style scoped>
.review-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0, 0, 0, 0.5);
  display: flex; align-items: center; justify-content: center;
}
.review-dialog {
  background: var(--bg-primary, #1a1a2e);
  border-radius: 16px; padding: 28px;
  min-width: 420px; max-width: 560px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  border: 1px solid var(--border, #2a2a4a);
}
.review-header {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 20px;
}
.review-header h3 {
  margin: 0; font-size: 18px;
  color: var(--text-primary, #e0e0e0);
}
.review-icon { font-size: 22px; }
.review-label {
  font-size: 14px; color: var(--text-secondary, #a0a0c0);
  margin-bottom: 16px;
}
.plan-preview {
  background: var(--bg-elevated, #222244);
  border-radius: 10px; padding: 14px;
  margin-bottom: 18px;
  max-height: 240px; overflow-y: auto;
}
.plan-step {
  display: flex; gap: 10px; padding: 6px 0;
  border-bottom: 1px solid var(--border, #2a2a4a);
  font-size: 13px;
}
.plan-step:last-child { border-bottom: none; }
.step-agent {
  font-weight: 600; color: var(--accent, #7c5cfc);
  white-space: nowrap;
  min-width: 80px;
}
.step-task { color: var(--text-primary, #e0e0e0); }
.plan-empty { color: var(--text-muted, #6a6a8a); font-style: italic; font-size: 13px; }
.review-actions {
  display: flex; gap: 10px; margin-bottom: 12px;
}
.review-btn {
  flex: 1; padding: 10px 14px; border: none; border-radius: 10px;
  font-size: 14px; font-weight: 600; cursor: pointer;
  display: flex; align-items: center; justify-content: center; gap: 6px;
  transition: all 0.2s;
}
.review-btn.approve { background: #1a6b3c; color: #b0f0c0; }
.review-btn.approve:hover { background: #228b4a; }
.review-btn.revise { background: #7a5a00; color: #f0d080; }
.review-btn.revise:hover { background: #9a7400; }
.review-btn.reject { background: #6b1a1a; color: #f0b0b0; }
.review-btn.reject:hover { background: #8b2222; }
.review-btn.small { flex: 0; padding: 8px 16px; }
.feedback-row {
  display: flex; gap: 8px;
}
.feedback-input {
  flex: 1; padding: 10px 14px;
  background: var(--bg-input, #1a1a3a);
  border: 1px solid var(--border-input, #3a3a5a);
  border-radius: 10px;
  color: var(--text-primary, #e0e0e0);
  font-size: 14px; outline: none;
}
.feedback-input:focus { border-color: var(--accent-focus, #7c5cfc); }
</style>
