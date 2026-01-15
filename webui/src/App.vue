<!-- src/App.vue -->
<template>
  <el-menu
    v-if="!isLoginPage"
    :default-active="activeRoute"
    class="main-nav glass-nav"
    mode="horizontal"
    router
  >
    <div style="padding: 5px 15px; line-height: 32px">
      <img
        src="/favicon.ico"
        alt="Logo"
        height="32"
        style="margin-right: 8px; vertical-align: middle"
      />
      PT Nexus
    </div>
    <el-menu-item index="/">首页</el-menu-item>
    <el-menu-item index="/info">流量统计</el-menu-item>
    <el-menu-item index="/torrents">一种多站</el-menu-item>
    <el-menu-item index="/data">一站多种</el-menu-item>
    <el-menu-item index="/sites">做种检索</el-menu-item>
    <el-menu-item index="/settings">设置</el-menu-item>
    <div class="right-buttons-container">
      <el-link
        href="https://github.com/sqing33/PTNexus"
        target="_blank"
        :underline="false"
        style="margin-right: 8px"
      >
        <el-icon><Link /></el-icon>
        GitHub
      </el-link>
      <el-tag size="small" style="cursor: pointer; margin-right: 15px" @click="showVersionDialog">
        {{ currentVersion }}
      </el-tag>
      <el-link
        href="https://github.com/sqing33/PTNexus/issues"
        target="_blank"
        :underline="false"
        style="margin-right: 8px"
      >
        <el-button type="primary" plain>反馈</el-button>
      </el-link>
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
  <main :class="['main-content', isLoginPage ? 'no-nav' : '']">
    <router-view v-slot="{ Component }">
      <component :is="Component" @ready="handleComponentReady" />
    </router-view>
  </main>

  <!-- Version Update Component (outside navigation bar) -->
  <VersionUpdate @version-loaded="(version) => (currentVersion = version)" ref="versionUpdateRef" />
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Link } from '@element-plus/icons-vue'
import axios from 'axios'
import VersionUpdate from '@/components/VersionUpdate.vue'

const route = useRoute()

// 背景图片
const backgroundUrl = ref('https://pic.pting.club/i/2025/10/07/68e4fbfe9be93.jpg')

// 版本信息
const currentVersion = ref('加载中...')

const isLoginPage = computed(() => route.path === '/login')

const activeRoute = computed(() => {
  if (route.matched.length > 0) {
    return route.matched[0].path
  }
  return route.path
})

const isRefreshing = ref(false)

// VersionUpdate组件引用
const versionUpdateRef = ref()

const activeComponentRefresher = ref<(() => Promise<void>) | null>(null)

const handleComponentReady = (refreshMethod: () => Promise<void>) => {
  activeComponentRefresher.value = refreshMethod
}

const handleGlobalRefresh = async () => {
  if (isRefreshing.value) return

  const topLevelPath = route.matched.length > 0 ? route.matched[0].path : ''

  if (
    topLevelPath === '/torrents' ||
    topLevelPath === '/sites' ||
    topLevelPath === '/data' ||
    topLevelPath === '/batch-fetch'
  ) {
    isRefreshing.value = true
    ElMessage.info('后台正在刷新缓存...')

    try {
      await axios.post('/api/refresh_data')

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
    } catch (e: any) {
      ElMessage.error(e.message)
      isRefreshing.value = false
    }
  } else {
    ElMessage.warning('当前页面不支持刷新操作。')
  }
}

// 加载背景设置
const loadBackgroundSettings = async () => {
  try {
    const response = await axios.get('/api/settings')
    if (response.data?.ui_settings?.background_url) {
      backgroundUrl.value = response.data.ui_settings.background_url
      updateBackground(backgroundUrl.value)
    }
  } catch (error) {
    console.error('加载背景设置失败:', error)
  }
}

// 更新背景图片
const updateBackground = (url: string) => {
  const appElement = document.getElementById('app')
  if (appElement) {
    if (url) {
      appElement.style.backgroundImage = `url('${url}')`
    } else {
      appElement.style.backgroundImage = `url('${backgroundUrl.value}')`
    }
  }
}

// 监听背景更新事件
const handleBackgroundUpdate = (event: any) => {
  const { backgroundUrl: newUrl } = event.detail
  backgroundUrl.value = newUrl
  updateBackground(newUrl)
}

// 显示版本更新对话框
const showVersionDialog = () => {
  if (versionUpdateRef.value) {
    versionUpdateRef.value.show()
  }
}

onMounted(() => {
  loadBackgroundSettings()
  window.addEventListener('background-updated', handleBackgroundUpdate)
})
</script>

<style>
#app {
  height: 100vh;
  position: relative;
  background-image: url('https://pic.pting.club/i/2025/10/07/68e4fbfe9be93.jpg');
  background-size: cover;
  background-position: center;
  background-attachment: fixed;
}

#app::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(255, 255, 255, 0.5);
  pointer-events: none;
  z-index: 0;
}

body {
  margin: 0;
  padding: 0;
}
</style>

<style scoped>
.main-nav {
  border-bottom: solid 1px var(--el-menu-border-color);
  flex-shrink: 0;
  height: 40px;
  display: flex;
  align-items: center;
  position: relative;
  z-index: 1;
}

.main-content {
  flex-grow: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: calc(100% - 40px);
  position: relative;
  z-index: 1;
}

.main-content.no-nav {
  height: 100%;
}

.right-buttons-container {
  position: absolute;
  right: 20px;
  top: 3px;
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
