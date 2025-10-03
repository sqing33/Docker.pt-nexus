<!-- src/App.vue -->
<template>
  <el-menu v-if="!isLoginPage" :default-active="activeRoute" class="main-nav" mode="horizontal" router>
    <div style="padding: 5px 15px;line-height: 32px;">
      <img src="/favicon.ico" alt="Logo" height="32" style="margin-right: 8px; vertical-align: middle;" />
      PT Nexus
    </div>
    <el-menu-item index="/">首页</el-menu-item>
    <el-menu-item index="/info">流量统计</el-menu-item>
    <el-menu-item index="/torrents">一种多站</el-menu-item>
    <el-menu-item index="/data">一站多种</el-menu-item>
    <el-menu-item index="/sites">做种检索</el-menu-item>
    <el-menu-item index="/settings">设置</el-menu-item>
    <div class="refresh-button-container">
      <el-button type="success" @click="handleGlobalRefresh" :loading="isRefreshing" :disabled="isRefreshing" plain>
        刷新
      </el-button>
    </div>
  </el-menu>
  <main :class="['main-content', isLoginPage ? 'no-nav' : '']">
    <router-view v-slot="{ Component }">
      <keep-alive>
        <component :is="Component" @ready="handleComponentReady" />
      </keep-alive>
    </router-view>
  </main>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'

const route = useRoute()

const isLoginPage = computed(() => route.path === '/login')

const activeRoute = computed(() => {
  if (route.matched.length > 0) {
    return route.matched[0].path
  }
  return route.path
})

const isRefreshing = ref(false)

const activeComponentRefresher = ref<(() => Promise<void>) | null>(null)

const handleComponentReady = (refreshMethod: () => Promise<void>) => {
  activeComponentRefresher.value = refreshMethod
}

const handleGlobalRefresh = async () => {
  if (isRefreshing.value) return

  const topLevelPath = route.matched.length > 0 ? route.matched[0].path : ''

  if (topLevelPath === '/torrents' || topLevelPath === '/sites' || topLevelPath === '/data' || topLevelPath === '/batch-fetch') {
    isRefreshing.value = true
    ElMessage.info('后台正在刷新缓存...')

    try {
      const response = await fetch('/api/refresh_data', { method: 'POST' })
      if (!response.ok) {
        throw new Error('触发刷新失败')
      }

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
</script>

<style>
#app {
  height: 100vh;
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
}

.main-content {
  flex-grow: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: calc(100% - 40px);
}

.main-content.no-nav {
  height: 100%;
}

.refresh-button-container {
  position: absolute;
  right: 20px;
  top: 3px;
}
</style>
