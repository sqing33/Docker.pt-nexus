<!-- src/App.vue -->
<template>
  <el-menu :default-active="activeRoute" class="main-nav" mode="horizontal" router>
    <el-menu-item index="/">下载统计</el-menu-item>
    <el-menu-item index="/torrents">种子查询</el-menu-item>
    <el-menu-item index="/sites">站点信息</el-menu-item>
    <el-menu-item index="/settings">设置</el-menu-item>
    <div class="refresh-button-container">
      <el-button
        type="success"
        @click="handleGlobalRefresh"
        :loading="isRefreshing"
        :disabled="isRefreshing"
        plain
      >
        刷新
      </el-button>
    </div>
  </el-menu>

  <main class="main-content">
    <router-view v-slot="{ Component }">
      <keep-alive>
        <component :is="Component" @ready="handleComponentReady" />
      </keep-alive>
    </router-view>
  </main>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const route = useRoute()
const activeRoute = computed(() => route.path)
const isRefreshing = ref(false)
const activeComponentRefresher = ref<(() => Promise<void>) | null>(null)

// --- 背景设置逻辑 ---
const applyBackgroundSettings = async () => {
  try {
    const response = await axios.get('/api/settings')
    const background = response.data?.background

    if (background) {
      // 清理旧样式
      document.body.style.backgroundColor = ''
      document.body.style.backgroundImage = ''
      document.body.style.backgroundSize = ''
      document.body.style.backgroundRepeat = ''
      document.body.style.backgroundAttachment = ''

      if (background.type === 'color' && background.value) {
        document.body.style.backgroundColor = background.value
      } else if (background.type === 'image' && background.value) {
        document.body.style.backgroundImage = `url(${background.value})`
        // 可以根据需要添加更多样式
        document.body.style.backgroundSize = 'cover'
        document.body.style.backgroundRepeat = 'no-repeat'
        document.body.style.backgroundAttachment = 'fixed'
      }
    }
  } catch (error) {
    console.error('应用背景设置失败', error)
  }
}

// 在组件挂载时应用背景并监听设置更新
onMounted(() => {
  applyBackgroundSettings()
  window.addEventListener('settings-updated', applyBackgroundSettings)
})

// 在组件卸载时移除监听器
onUnmounted(() => {
  window.removeEventListener('settings-updated', applyBackgroundSettings)
})

// --- 原有逻辑 ---
const handleComponentReady = (refreshMethod: () => Promise<void>) => {
  activeComponentRefresher.value = refreshMethod
}

const handleGlobalRefresh = async () => {
  if (isRefreshing.value) return

  const currentPath = route.path
  if (currentPath === '/torrents' || currentPath === '/sites') {
    isRefreshing.value = true
    ElMessage.info('后台正在刷新缓存...')

    try {
      const response = await fetch('/api/refresh_data', { method: 'POST' })
      if (!response.ok) {
        throw new Error('触发刷新失败')
      }

      setTimeout(async () => {
        try {
          if (activeComponentRefresher.value) {
            await activeComponentRefresher.value()
          }
          ElMessage.success('数据已刷新！')
        } catch (e: any) {
          ElMessage.error(`数据更新失败: ${e.message}`)
        } finally {
          isRefreshing.value = false
        }
      }, 2500)
    } catch (e: any) {
      ElMessage.error(e.message)
      isRefreshing.value = false
    }
  } else {
    ElMessage.warning('当前页面不支持刷新操作。')
  }
}
</script>

<style>
#app {
  height: 100vh;
}

body {
  margin: 0;
  padding: 0;
  /* 添加过渡效果，使背景切换更平滑 */
  transition: background 0.5s ease;
}
</style>

<style scoped>
.main-nav {
  border-bottom: solid 1px var(--el-menu-border-color);
  flex-shrink: 0;
  height: 40px;
  display: flex;
  align-items: center;
}

.main-content {
  flex-grow: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: calc(100% - 40px);
}

.refresh-button-container {
  position: absolute;
  right: 20px;
  top: 3px;
}
</style>
