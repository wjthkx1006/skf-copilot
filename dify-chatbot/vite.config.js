import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 4000,
    allowedHosts: ['helpdesk.gokarla.net', 'localhost', '127.0.0.1', '8.213.146.237'],
    proxy: {
      // SSO auth server
      '/api/auth': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      },
      // SKF Copilot (local LangChain RAG)
      '/api/skf': {
        target: 'http://localhost:8005',
        changeOrigin: true,
      },
      // Guardrail server: rules, checks, events, logs
      '/api/guardrail': {
        target: 'http://localhost:8003',
        changeOrigin: true,
      },
      '/api/guardrail-events': {
        target: 'http://localhost:8003',
        changeOrigin: true,
      },
      '/api/logs': {
        target: 'http://localhost:8003',
        changeOrigin: true,
      },
      // Agent backend: tickets, chat, categories
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
