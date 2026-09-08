import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/health': 'http://localhost:8010',
      '/ask': 'http://localhost:8010',
      '/stream': 'http://localhost:8010',
      '/evaluation': 'http://localhost:8010',
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  }
})
