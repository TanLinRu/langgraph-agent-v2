<script setup lang="ts">import { ref, onMounted } from 'vue';
import { fetchWorkflows, fetchWorkflow, upsertWorkflow, deleteWorkflow as deleteWorkflowApi } from '../utils/api';
import type { WorkflowInfo } from '../utils/api/types';
interface NodeConfig {
 id: string;
 type: 'agent' | 'approval' | 'finish' | 'start';
 label: string;
 agent_type?: string;
 agent_id?: string;
 description?: string;
}
interface EdgeConfig {
 source: string;
 target: string;
 condition?: string;
}
interface WorkflowForm {
 id: string;
 name: string;
 description: string;
 nodes: NodeConfig[];
 edges: EdgeConfig[];
 start_node: string;
}
const workflows = ref<WorkflowInfo[]>([]);
const loading = ref(false);
const selectedWorkflow = ref<WorkflowInfo | null>(null);
const showForm = ref(false);
const showJsonEditor = ref(false);
const form = ref<WorkflowForm>({
 id: '',
 name: '',
 description: '',
 nodes: [],
 edges: [],
 start_node: ''
});
const jsonContent = ref('');
const activeTab = ref<'list' | 'editor'>('list');
const nodeTypes = [
 { value: 'agent', label: 'Agent 节点', icon: '🤖' },
 { value: 'approval', label: '审批节点', icon: '✅' },
 { value: 'finish', label: '结束节点', icon: '🏁' },
];
const agentTypes = [
 { value: 'single', label: 'Single Agent' },
 { value: 'multi', label: 'Multi Agent' },
 { value: 'acp', label: 'ACP Agent' },
];
const defaultAgents = ['supervisor', 'coder', 'researcher', 'analyst', 'direct', 'opencode', 'claude'];
async function loadWorkflows() {
 loading.value = true;
 try {
 workflows.value = await fetchWorkflows();
 }
 catch (error) {
 console.error('Failed to load workflows:', error);
 }
 loading.value = false;
}
async function selectWorkflow(wf: WorkflowInfo) {
 loading.value = true;
 try {
 const fullWorkflow = await fetchWorkflow(wf.id);
 selectedWorkflow.value = fullWorkflow as unknown as WorkflowInfo;
 activeTab.value = 'editor';
 form.value = {
 id: fullWorkflow.id,
 name: fullWorkflow.name || '',
 description: fullWorkflow.description || '',
 nodes: (fullWorkflow as any).nodes || [],
 edges: (fullWorkflow as any).edges || [],
 start_node: (fullWorkflow as any).start_node || ''
 };
 updateJsonContent();
 } catch (error) {
 console.error('Failed to load workflow:', error);
 alert('加载工作流失败');
 } finally {
 loading.value = false;
 }
}
function createNewWorkflow() {
 selectedWorkflow.value = null;
 form.value = {
 id: '',
 name: '',
 description: '',
 nodes: [],
 edges: [],
 start_node: ''
 };
 activeTab.value = 'editor';
 showForm.value = true;
 jsonContent.value = '';
}
function addNode() {
 const newNode: NodeConfig = {
 id: `node_${Date.now()}`,
 type: 'agent',
 label: '新节点',
 agent_type: 'single',
 agent_id: 'supervisor'
 };
 form.value.nodes.push(newNode);
 updateJsonContent();
}
function removeNode(nodeId: string) {
 form.value.nodes = form.value.nodes.filter(n => n.id !== nodeId);
 form.value.edges = form.value.edges.filter(e => e.source !== nodeId && e.target !== nodeId);
 if (form.value.start_node === nodeId) {
 form.value.start_node = '';
 }
 updateJsonContent();
}
function addEdge() {
 if (form.value.nodes.length >= 2) {
 const source = form.value.nodes[0].id;
 const target = form.value.nodes[form.value.nodes.length - 1].id;
 if (source !== target) {
 form.value.edges.push({ source, target });
 updateJsonContent();
 }
 }
}
function removeEdge(index: number) {
 form.value.edges.splice(index, 1);
 updateJsonContent();
}
function updateJsonContent() {
 jsonContent.value = JSON.stringify({
 name: form.value.name,
 description: form.value.description,
 nodes: form.value.nodes,
 edges: form.value.edges,
 start_node: form.value.start_node
 }, null, 2);
}
function applyJson() {
 try {
 const data = JSON.parse(jsonContent.value);
 form.value.name = data.name || '';
 form.value.description = data.description || '';
 form.value.nodes = data.nodes || [];
 form.value.edges = data.edges || [];
 form.value.start_node = data.start_node || '';
 }
 catch (error) {
 alert('Invalid JSON');
 }
}
async function saveWorkflow() {
 if (!form.value.name.trim()) {
 alert('请输入工作流名称');
 return;
 }
 if (form.value.nodes.length === 0) {
 alert('请至少添加一个节点');
 return;
 }
 loading.value = true;
 try {
 const workflowId = form.value.id || form.value.name.toLowerCase().replace(/\s+/g, '_');
 await upsertWorkflow(workflowId, {
 name: form.value.name,
 description: form.value.description,
 nodes: form.value.nodes,
 edges: form.value.edges,
 start_node: form.value.start_node
 });
 await loadWorkflows();
 alert('保存成功');
 activeTab.value = 'list';
 }
 catch (error) {
 console.error('Failed to save workflow:', error);
 alert('保存失败');
 }
 loading.value = false;
}
async function deleteWorkflow(workflowId: string) {
 if (!confirm('确定要删除这个工作流吗？'))
 return;
 loading.value = true;
 try {
 await deleteWorkflowApi(workflowId);
 await loadWorkflows();
 if (selectedWorkflow.value?.id === workflowId) {
 selectedWorkflow.value = null;
 form.value = {
 id: '',
 name: '',
 description: '',
 nodes: [],
 edges: [],
 start_node: ''
 };
 }
 }
 catch (error) {
 console.error('Failed to delete workflow:', error);
 alert('删除失败');
 }
 loading.value = false;
}
function goBack() {
 activeTab.value = 'list';
 selectedWorkflow.value = null;
}
onMounted(() => {
 loadWorkflows();
});
</script>

<template>
  <div class="workflows-panel">
    <!-- List View -->
    <div v-if="activeTab === 'list'" class="wf-list">
      <div class="wf-list-header">
        <h3 class="wf-title">工作流配置</h3>
        <button class="wf-new-btn" @click="createNewWorkflow">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          新建
        </button>
      </div>
      
      <div v-if="loading" class="wf-loading">加载中...</div>
      
      <div v-else-if="workflows.length === 0" class="wf-empty">
        <div class="wf-empty-icon">📋</div>
        <div class="wf-empty-text">暂无工作流配置</div>
        <div class="wf-empty-hint">点击上方按钮创建新工作流</div>
      </div>
      
      <div v-else class="wf-grid">
        <div 
          v-for="wf in workflows" 
          :key="wf.id" 
          class="wf-card"
          @click="selectWorkflow(wf)"
        >
          <div class="wf-card-header">
            <div class="wf-card-icon">📊</div>
            <div class="wf-card-info">
              <div class="wf-card-name">{{ wf.name }}</div>
              <div class="wf-card-desc">{{ wf.description || '暂无描述' }}</div>
            </div>
          </div>
          <div class="wf-card-footer">
            <span class="wf-node-count">{{ wf.nodes?.length || 0 }} 个节点</span>
            <button class="wf-card-delete" @click.stop="deleteWorkflow(wf.id)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Editor View -->
    <div v-else class="wf-editor">
      <div class="wf-editor-header">
        <button class="wf-back-btn" @click="goBack">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          返回
        </button>
        <h3 class="wf-title">{{ form.name || '新建工作流' }}</h3>
        <button class="wf-save-btn" :disabled="loading" @click="saveWorkflow">
          <svg v-if="loading" class="wf-spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" stroke-linecap="round">
              <animateTransform attributeName="transform" type="rotate" dur="1s" repeatCount="indefinite" from="0 12 12" to="360 12 12"/>
            </circle>
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 19V5"/><path d="M5 12l7-7 7 7"/>
          </svg>
          保存
        </button>
      </div>

      <div class="wf-editor-body">
        <!-- Basic Info -->
        <div class="wf-section">
          <div class="wf-section-title">基本信息</div>
          <div class="wf-form-group">
            <label>工作流名称</label>
            <input v-model="form.name" type="text" placeholder="输入工作流名称" class="wf-input" />
          </div>
          <div class="wf-form-group">
            <label>描述</label>
            <textarea v-model="form.description" placeholder="输入工作流描述" class="wf-textarea"></textarea>
          </div>
        </div>

        <!-- Nodes -->
        <div class="wf-section">
          <div class="wf-section-header">
            <div class="wf-section-title">节点配置</div>
            <button class="wf-add-btn" @click="addNode">+ 添加节点</button>
          </div>
          
          <div v-if="form.nodes.length === 0" class="wf-nodes-empty">
            暂无节点，点击上方按钮添加
          </div>
          
          <div v-else class="wf-nodes-list">
            <div v-for="(node, index) in form.nodes" :key="node.id" class="wf-node-item">
              <div class="wf-node-header">
                <span class="wf-node-index">{{ index + 1 }}</span>
                <span class="wf-node-icon">{{ node.type === 'agent' ? '🤖' : node.type === 'approval' ? '✅' : '🏁' }}</span>
                <button class="wf-node-delete" @click="removeNode(node.id)">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
                  </svg>
                </button>
              </div>
              
              <div class="wf-node-form">
                <div class="wf-row">
                  <div class="wf-col">
                    <label>节点ID</label>
                    <input v-model="node.id" type="text" class="wf-input-sm" />
                  </div>
                  <div class="wf-col">
                    <label>节点类型</label>
                    <select v-model="node.type" class="wf-select">
                      <option v-for="t in nodeTypes" :key="t.value" :value="t.value">
                        {{ t.icon }} {{ t.label }}
                      </option>
                    </select>
                  </div>
                </div>
                
                <div class="wf-row">
                  <div class="wf-col">
                    <label>节点标签</label>
                    <input v-model="node.label" type="text" placeholder="显示名称" class="wf-input-sm" />
                  </div>
                  <div v-if="node.type === 'agent'" class="wf-col">
                    <label>Agent类型</label>
                    <select v-model="node.agent_type" class="wf-select">
                      <option v-for="t in agentTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
                    </select>
                  </div>
                  <div v-if="node.type === 'agent'" class="wf-col">
                    <label>Agent ID</label>
                    <select v-model="node.agent_id" class="wf-select">
                      <option v-for="a in defaultAgents" :key="a" :value="a">{{ a }}</option>
                    </select>
                  </div>
                </div>
                
                <div v-if="node.type === 'approval'" class="wf-row">
                  <div class="wf-col-full">
                    <label>审批描述</label>
                    <input v-model="node.description" type="text" placeholder="审批提示信息" class="wf-input-sm" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Edges -->
        <div class="wf-section">
          <div class="wf-section-header">
            <div class="wf-section-title">连接关系</div>
            <button class="wf-add-btn" @click="addEdge" :disabled="form.nodes.length < 2">+ 添加连接</button>
          </div>
          
          <div v-if="form.edges.length === 0" class="wf-nodes-empty">
            暂无连接，添加至少两个节点后可创建连接
          </div>
          
          <div v-else class="wf-edges-list">
            <div v-for="(edge, index) in form.edges" :key="index" class="wf-edge-item">
              <select v-model="edge.source" class="wf-select-sm">
                <option v-for="node in form.nodes" :key="node.id" :value="node.id">{{ node.label }}</option>
              </select>
              <span class="wf-edge-arrow">→</span>
              <select v-model="edge.target" class="wf-select-sm">
                <option v-for="node in form.nodes" :key="node.id" :value="node.id">{{ node.label }}</option>
              </select>
              <button class="wf-edge-delete" @click="removeEdge(index)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
                </svg>
              </button>
            </div>
          </div>
        </div>

        <!-- Start Node -->
        <div class="wf-section">
          <div class="wf-section-title">起始节点</div>
          <select v-model="form.start_node" class="wf-select">
            <option value="">请选择起始节点</option>
            <option v-for="node in form.nodes" :key="node.id" :value="node.id">{{ node.label }}</option>
          </select>
        </div>

        <!-- JSON Editor -->
        <div class="wf-section">
          <div class="wf-section-header">
            <div class="wf-section-title">JSON 配置</div>
            <button class="wf-add-btn" @click="showJsonEditor = !showJsonEditor">
              {{ showJsonEditor ? '隐藏' : '显示' }}
            </button>
          </div>
          
          <div v-if="showJsonEditor" class="wf-json-editor">
            <textarea v-model="jsonContent" class="wf-json-textarea" rows="12"></textarea>
            <button class="wf-apply-btn" @click="applyJson">应用 JSON</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflows-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* List View */
.wf-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.wf-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.wf-new-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: var(--accent-bg-strong);
  border: none;
  border-radius: 8px;
  color: var(--accent-text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.wf-new-btn:hover {
  background: var(--bg-accent-hover);
  transform: scale(1.02);
}

.wf-loading {
  text-align: center;
  padding: 40px;
  color: var(--text-muted);
}

.wf-empty {
  text-align: center;
  padding: 40px 20px;
}
.wf-empty-icon {
  font-size: 48px;
  opacity: 0.3;
  margin-bottom: 12px;
}
.wf-empty-text {
  font-size: 15px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.wf-empty-hint {
  font-size: 13px;
  color: var(--text-faint);
}

.wf-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}
.wf-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.3s;
}
.wf-card:hover {
  border-color: var(--border-accent);
  box-shadow: 0 4px 16px rgba(99,102,241,0.1);
  transform: translateY(-2px);
}
.wf-card-header {
  display: flex;
  gap: 12px;
}
.wf-card-icon {
  font-size: 24px;
}
.wf-card-info {
  flex: 1;
}
.wf-card-name {
  font-size: 14px;
  font-weight: 560;
  color: var(--text-primary);
}
.wf-card-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}
.wf-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-light);
}
.wf-node-count {
  font-size: 12px;
  color: var(--text-faint);
}
.wf-card-delete {
  background: none;
  border: none;
  color: var(--text-faint);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s;
}
.wf-card-delete:hover {
  color: var(--color-red);
  background: rgba(239,68,68,0.1);
}

/* Editor View */
.wf-editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.wf-back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}
.wf-back-btn:hover {
  background: var(--bg-glass-hover);
}
.wf-save-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: var(--accent-bg-strong);
  border: none;
  border-radius: 8px;
  color: var(--accent-text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.wf-save-btn:hover:not(:disabled) {
  background: var(--bg-accent-hover);
}
.wf-save-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.wf-spinner {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.wf-editor-body {
  flex: 1;
  overflow-y: auto;
  padding-top: 16px;
}

.wf-section {
  margin-bottom: 20px;
}
.wf-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.wf-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.wf-add-btn {
  padding: 6px 12px;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.wf-add-btn:hover:not(:disabled) {
  background: var(--bg-glass-hover);
  border-color: var(--border-accent);
}
.wf-add-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.wf-form-group {
  margin-bottom: 12px;
}
.wf-form-group label {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.wf-input, .wf-textarea {
  width: 100%;
  padding: 10px 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-input);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  transition: all 0.2s;
}
.wf-input:focus, .wf-textarea:focus {
  border-color: var(--accent-focus);
  background: var(--bg-glass-hover);
}
.wf-textarea {
  min-height: 60px;
  resize: vertical;
}

.wf-nodes-empty {
  padding: 20px;
  text-align: center;
  color: var(--text-faint);
  background: var(--bg-hover);
  border-radius: 8px;
}

.wf-nodes-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.wf-node-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.wf-node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--bg-hover);
  border-bottom: 1px solid var(--border);
}
.wf-node-index {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-bg);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-text);
}
.wf-node-icon {
  font-size: 18px;
}
.wf-node-delete {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-faint);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s;
}
.wf-node-delete:hover {
  color: var(--color-red);
  background: rgba(239,68,68,0.1);
}

.wf-node-form {
  padding: 12px;
}
.wf-row {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}
.wf-row:last-child {
  margin-bottom: 0;
}
.wf-col {
  flex: 1;
}
.wf-col-full {
  flex: 1;
  min-width: 100%;
}
.wf-col label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.wf-input-sm {
  width: 100%;
  padding: 8px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-input);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
}
.wf-input-sm:focus {
  border-color: var(--accent-focus);
}
.wf-select {
  width: 100%;
  padding: 10px 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-input);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  cursor: pointer;
}
.wf-select:focus {
  border-color: var(--accent-focus);
}

.wf-edges-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.wf-edge-item {
  display: flex;
  align-items: center;
  gap: 10px;
}
.wf-select-sm {
  flex: 1;
  padding: 8px 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-input);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  cursor: pointer;
}
.wf-edge-arrow {
  font-size: 16px;
  color: var(--accent);
}
.wf-edge-delete {
  background: none;
  border: none;
  color: var(--text-faint);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}
.wf-edge-delete:hover {
  color: var(--color-red);
}

.wf-json-editor {
  background: var(--bg-code);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
.wf-json-textarea {
  width: 100%;
  min-height: 150px;
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-family: 'SF Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
  resize: vertical;
  outline: none;
}
.wf-apply-btn {
  margin-top: 10px;
  padding: 6px 12px;
  background: var(--accent-bg-strong);
  border: none;
  border-radius: 6px;
  color: var(--accent-text);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}
.wf-apply-btn:hover {
  background: var(--bg-accent-hover);
}
</style>