<!-- src/App.vue -->
<template>
  <el-menu :default-active="activeRoute" class="main-nav" mode="horizontal" router>
    <el-menu-item index="/">下载统计</el-menu-item>
    <el-menu-item index="/torrents">种子查询</el-menu-item>
  </el-menu>

  <main class="main-content">
    <!-- 路由匹配到的组件将渲染在这里 -->
    <router-view />
  </main>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const activeRoute = computed(() => route.path)
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
}

.main-content {
  flex-grow: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: calc(100% - 40px);
}
</style>
