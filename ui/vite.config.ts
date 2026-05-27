import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      // Non-streaming endpoints still go through proxy
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
