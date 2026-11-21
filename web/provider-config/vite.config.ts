import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../../videocreate/src/videocreate/config_web/static',
    emptyOutDir: true,
    sourcemap: false
  }
})
