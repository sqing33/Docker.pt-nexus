// vite.config.ts
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      // 字符串简写写法
      // '/foo': 'http://localhost:4567',
      // 选项写法
      '/api': {
        target: 'http://localhost:35274', // <--- 指向你的 Flask 后端地址
        changeOrigin: true, // <--- 必须设置为 true
        // rewrite: (path) => path.replace(/^\/api/, '') // 如果后端路由本身不带 /api, 则需要重写
      },
    },
  },
})
