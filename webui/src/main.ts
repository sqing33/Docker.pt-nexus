// src/main.ts

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import axios from 'axios'

// 引入 Element Plus
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

// 引入公共毛玻璃样式
import './assets/styles/glass-morphism.scss'

// 如果需要，可以引入 ECharts
import * as echarts from 'echarts'

// fetch 全局包装：为所有 /api 请求自动附加 Bearer Token，并在 401 时跳转登录
const originalFetch = window.fetch.bind(window)
window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = typeof input === 'string' || input instanceof URL ? String(input) : input.url
  const token = localStorage.getItem('token')

  // 合并并设置 Authorization 头
  const mergedHeaders = new Headers(
    (typeof input !== 'string' && !(input instanceof URL)
      ? (input as Request).headers
      : undefined) ||
      init?.headers ||
      {},
  )
  if (token && url.startsWith('/api') && !mergedHeaders.has('Authorization')) {
    mergedHeaders.set('Authorization', `Bearer ${token}`)
  }

  const finalInit: RequestInit = { ...init, headers: mergedHeaders }
  const finalInput =
    typeof input === 'string' || input instanceof URL ? url : new Request(input, finalInit)

  const resp = await originalFetch(
    finalInput as any,
    typeof input === 'string' || input instanceof URL ? finalInit : undefined,
  )
  if (resp.status === 401 && !url.startsWith('/api/auth/')) {
    const current = router.currentRoute.value
    const redirect = encodeURIComponent(current.fullPath)
    router.replace(`/login?redirect=${redirect}`)
  }
  return resp
}

// Axios 全局拦截：为所有请求附加 Bearer Token，并处理 401
axios.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers = config.headers || {}
    config.headers['Authorization'] = `Bearer ${token}`
  }
  
  // 修复cookie泄露问题：确保不发送不必要的cookie
  config.withCredentials = false
  
  // 设置更严格的请求头，避免携带其他应用的cookie
  if (config.headers) {
    config.headers['X-Requested-With'] = 'XMLHttpRequest'
  }
  
  return config
})

axios.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (error?.response?.status === 401) {
      const current = router.currentRoute.value
      const redirect = encodeURIComponent(current.fullPath)
      router.replace(`/login?redirect=${redirect}`)
    }
    return Promise.reject(error)
  },
)

const app = createApp(App)

app.use(createPinia())

// 将 echarts 挂载到全局，方便组件中使用
app.config.globalProperties.$echarts = echarts

app.use(router)

app.use(ElementPlus, {
  locale: zhCn,
})

app.mount('#app')
