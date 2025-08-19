// src/main.ts

import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

// 引入 Element Plus
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

// 如果需要，可以引入 ECharts
import * as echarts from 'echarts'

const app = createApp(App)

// 将 echarts 挂载到全局，方便组件中使用
app.config.globalProperties.$echarts = echarts

app.use(router)

app.use(ElementPlus, {
  locale: zhCn,
})

app.mount('#app')
