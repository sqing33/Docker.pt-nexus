<!-- views/SettingsView.vue -->
<template>
  <el-container class="settings-container">
    <el-aside width="200px" class="settings-aside">
      <el-menu :default-active="route.path" class="settings-menu" router>
        <el-menu-item index="/settings/general">
          <el-icon>
            <Setting />
          </el-icon>
          <span>设置</span>
        </el-menu-item>
        <el-menu-item index="/settings/downloader">
          <el-icon>
            <Download />
          </el-icon>
          <span>下载器</span>
        </el-menu-item>
        <el-menu-item index="/settings/cookie">
          <el-icon>
            <Tickets />
          </el-icon>
          <span>站点管理</span>
        </el-menu-item>
        <el-menu-item index="/settings/source-priority">
          <el-icon>
            <Sort />
          </el-icon>
          <span>源站点优先级</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-main class="settings-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { useRoute } from 'vue-router'
import { Download, Setting, Tickets, Sort } from '@element-plus/icons-vue'

const route = useRoute()
</script>

<style scoped>
.settings-container {
  height: 100vh;
}

.settings-aside {
  border-right: 1px solid var(--el-border-color);
}

.settings-menu {
  height: 100%;
  border-right: none;
}

.settings-main {
  padding: 0;
  display: flex;
  flex-direction: column;
  /* 确保子组件可以正确地 flex 布局 */
  overflow: auto;
}
</style>
