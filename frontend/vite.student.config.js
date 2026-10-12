import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const frontendRoot = fileURLToPath(new URL('.', import.meta.url))
const appRoot = fileURLToPath(new URL('./apps/student/', import.meta.url))
const publicDir = fileURLToPath(new URL('./public/', import.meta.url))
const outDir = fileURLToPath(new URL('./dist/student/', import.meta.url))

export default defineConfig({
  base: '/student/',
  root: appRoot,
  publicDir,
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3002,
    strictPort: true,
    fs: {
      allow: [frontendRoot],
    },
    proxy: {
      '/api/v1': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4002,
    strictPort: true,
  },
  build: {
    outDir,
    emptyOutDir: true,
  },
})
