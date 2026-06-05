import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listTools, fetchAgents, updateAgentConfig, type AgentInfo } from '../utils/api'

export const useAgentsStore = defineStore('agents', () => {
  const tools = ref<Array<{ name: string; description: string; type: string; icon: string; category?: string; enabled?: boolean; usage: number; lastUsed: string | null }>>([])
  const agents = ref<AgentInfo[]>([])
  const isLoading = ref(false)
  const selectedAgentId = ref<string | null>(null)

  async function fetchTools() {
    isLoading.value = true
    try {
      tools.value = await listTools()
    } finally {
      isLoading.value = false
    }
  }

  async function loadAgents() {
    try {
      agents.value = await fetchAgents()
    } catch (e) {
      console.warn('[AGENTS] loadAgents failed:', e)
    }
  }

  async function saveAgentConfig(agentId: string, config: Record<string, unknown>) {
    try {
      await updateAgentConfig(agentId, config)
    } catch (e) {
      console.warn('[AGENTS] saveAgentConfig failed:', e)
    }
  }

  function selectAgent(id: string | null) {
    selectedAgentId.value = id
  }

  return {
    tools, agents, isLoading, selectedAgentId,
    fetchTools, loadAgents, saveAgentConfig, selectAgent,
  }
})
