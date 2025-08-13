// src/main.ts

import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

// 引入 Element Plus
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

// 如果需要，可以引入 ECharts
import * as echarts from 'echarts'

const app = createApp(App)

// 将 echarts 挂载到全局，方便组件中使用
// 不推荐的做法，但对于迁移来说最快。更好的方式是在需要的组件中单独引入。
app.config.globalProperties.$echarts = echarts

app.use(router)
app.use(ElementPlus)

app.mount('#app')
