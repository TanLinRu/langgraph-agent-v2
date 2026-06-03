import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import {
  listSessions as apiListSessions,
  createSession as apiCreateSession,
  deleteSessionById as apiDeleteSession,
  renameSessionById as apiRenameSession,
  updateSessionProjectPath as apiUpdateProjectPath,
  type SessionInfo,
} from '../utils/api'
import { useChatStore } from './chat'

export const useSessionsStore = defineStore('sessions', () => {
  const sessions = ref<SessionInfo[]>([])
  const activeSessionId = ref<string | null>(null)
  const search = ref('')
  const statusFilter = ref<'all' | 'active' | 'completed'>('all')
  const isLoading = ref(false)

  const filteredSessions = computed(() => {
    let list = sessions.value
    if (statusFilter.value === 'active') {
      list = list.filter(s => s.status === 'active' || s.status === 'processing')
    } else if (statusFilter.value === 'completed') {
      list = list.filter(s => s.status === 'completed')
    }
    if (search.value.trim()) {
      const q = search.value.toLowerCase()
      list = list.filter(
        s => s.title.toLowerCase().includes(q) || s.session_id.toLowerCase().includes(q),
      )
    }
    return list
  })

  // Persist activeSessionId to localStorage
  watch(activeSessionId, (id) => {
    if (id) {
      localStorage.setItem('chat_session_id', id)
    } else {
      localStorage.removeItem('chat_session_id')
    }
  })

  async function fetchSessions() {
    isLoading.value = true
    try {
      sessions.value = await apiListSessions()
    } catch (e) {
      console.warn('[SESSIONS] fetch failed:', e)
    } finally {
      isLoading.value = false
    }
  }

  async function initSession() {
    // Step 1: Fetch all sessions from backend
    await fetchSessions()

    // Step 2: Check if saved session still exists on backend
    const savedId = localStorage.getItem('chat_session_id')
    if (savedId) {
      const exists = sessions.value.some(s => s.session_id === savedId)
      if (exists) {
        activeSessionId.value = savedId
        // chat store watcher will restore this session
        return
      }
    }

    // Step 3: No valid saved session — pick the most recent one
    if (sessions.value.length > 0) {
      activeSessionId.value = sessions.value[0].session_id
    } else {
      activeSessionId.value = null
    }
  }

  async function createSession(title?: string, projectPath?: string) {
    // Prevent creating duplicate empty sessions
    const existingEmpty = sessions.value.find(
      s => (s.title === '' || s.title === 'New conversation') && s.status === 'active' && s.summary === '',
    )
    if (existingEmpty && !title && !projectPath) {
      switchSession(existingEmpty.session_id)
      return existingEmpty.session_id
    }
    try {
      const result = await apiCreateSession(title || '新会话', projectPath)
      await fetchSessions()
      switchSession(result.session_id)
      return result.session_id
    } catch (e) {
      console.warn('[SESSIONS] create failed:', e)
      return null
    }
  }

  async function deleteSessionById(sessionId: string) {
    try {
      await apiDeleteSession(sessionId)
      if (activeSessionId.value === sessionId) {
        activeSessionId.value = null
        // Switch to next available session
        await fetchSessions()
        if (sessions.value.length > 0) {
          switchSession(sessions.value[0].session_id)
        }
      } else {
        await fetchSessions()
      }
    } catch (e) {
      console.warn('[SESSIONS] delete failed:', e)
    }
  }

  function switchSession(sessionId: string) {
    activeSessionId.value = sessionId
    // Chat store will react via watch
  }

  async function renameSession(sessionId: string, title: string) {
    const existing = sessions.value.find(s => s.session_id === sessionId)
    if (!existing) return
    const oldTitle = existing.title
    existing.title = title
    try {
      await apiRenameSession(sessionId, title)
    } catch (e) {
      existing.title = oldTitle
      console.warn('[SESSIONS] rename failed:', e)
    }
  }

  async function setProjectPath(sessionId: string, projectPath: string) {
    const existing = sessions.value.find(s => s.session_id === sessionId)
    if (!existing) return
    const oldPath = existing.project_path
    existing.project_path = projectPath
    try {
      await apiUpdateProjectPath(sessionId, projectPath)
    } catch (e) {
      existing.project_path = oldPath
      console.warn('[SESSIONS] setProjectPath failed:', e)
    }
  }

  function getSessionById(sessionId: string): SessionInfo | undefined {
    return sessions.value.find(s => s.session_id === sessionId)
  }

  return {
    sessions,
    activeSessionId,
    search,
    statusFilter,
    isLoading,
    filteredSessions,
    fetchSessions,
    initSession,
    createSession,
    deleteSessionById,
    switchSession,
    renameSession,
    setProjectPath,
    getSessionById,
  }
})
