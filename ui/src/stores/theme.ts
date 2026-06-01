import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const THEME_KEY = 'aw-theme'

export const useThemeStore = defineStore('theme', () => {
  const saved = localStorage.getItem(THEME_KEY) as 'dark' | 'light' | null
  const theme = ref<'dark' | 'light'>(saved || 'dark')

  function applyTheme(t: 'dark' | 'light') {
    document.documentElement.setAttribute('data-theme', t)
  }

  // Apply on init
  applyTheme(theme.value)

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  // Persist + apply on change
  watch(theme, (t) => {
    localStorage.setItem(THEME_KEY, t)
    applyTheme(t)
  })

  return { theme, toggleTheme }
})
