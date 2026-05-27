import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listTools } from '../utils/api'

export const useAgentsStore = defineStore('agents', () => {
  const tools = ref<Array<{ name: string; description: string }>>([])
  const isLoading = ref(false)

  async function fetchTools() {
    isLoading.value = true
    try {
      tools.value = await listTools()
    } finally {
      isLoading.value = false
    }
  }

  return { tools, isLoading, fetchTools }
})
