import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [vue()],
  root: resolve(process.cwd(), 'frontend/app'),
  base: '/static/app/',
  build: {
    outDir: resolve(process.cwd(), 'boekhouding/static/app'),
    emptyOutDir: true,
    sourcemap: true,
  },
})
