// vite.config.ts
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 根据 DEV_ENV 环境变量设置代理目标
const isDevEnv = process.env.DEV_ENV == 'true'
const proxyTarget = isDevEnv ? 'http://localhost:35274' : 'http://localhost:5274'

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
        target: proxyTarget, // <--- 根据 DEV_ENV 环境变量动态设置
        changeOrigin: true, // <--- 必须设置为 true
        // rewrite: (path) => path.replace(/^\/api/, '') // 如果后端路由本身不带 /api, 则需要重写
      },
    },
  },
})
