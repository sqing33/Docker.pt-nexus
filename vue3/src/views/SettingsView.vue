<!-- src/views/Settings.vue -->
<template>
  <el-container class="settings-container">
    <!-- 左侧导航栏 -->
    <el-aside width="200px" class="settings-aside">
      <el-menu :default-active="activeMenu" class="settings-menu" @select="handleMenuSelect">
        <el-menu-item index="background">
          <el-icon><Picture /></el-icon>
          <span>背景</span>
        </el-menu-item>
        <el-menu-item index="downloader">
          <el-icon><Download /></el-icon>
          <span>下载器</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-main>
      <!-- 背景设置 -->
      <div v-if="activeMenu === 'background'" class="settings-view" v-loading="isLoading">
        <div class="header">
          <h1>背景设置</h1>
          <p>自定义应用程序的全局背景。所有更改都需要点击底部的按钮进行保存。</p>
        </div>
        <el-card class="setting-card">
          <template #header>
            <span>背景样式</span>
          </template>
          <el-form
            v-if="settings.background"
            :model="settings.background"
            label-position="left"
            label-width="auto"
          >
            <el-form-item label="背景类型">
              <el-radio-group v-model="settings.background.type">
                <el-radio-button label="color">纯色背景</el-radio-button>
                <el-radio-button label="image">图片背景</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item v-if="settings.background.type === 'color'" label="背景颜色">
              <el-color-picker v-model="settings.background.value" show-alpha />
            </el-form-item>

            <el-form-item v-if="settings.background.type === 'image'" label="图片URL">
              <el-input
                v-model="settings.background.value"
                placeholder="请输入图片的URL地址"
              ></el-input>
            </el-form-item>
          </el-form>
        </el-card>
      </div>

      <!-- 下载器设置 -->
      <div v-if="activeMenu === 'downloader'" class="settings-view" v-loading="isLoading">
        <div class="header">
          <h1>下载器设置</h1>
          <p>在此处添加和管理您的下载客户端。所有更改都需要点击底部的按钮进行保存。</p>
        </div>

        <div class="downloader-grid">
          <el-card
            v-for="downloader in settings.downloaders"
            :key="downloader.id"
            class="downloader-card"
          >
            <template #header>
              <div class="card-header">
                <span>{{ downloader.name || '新下载器' }}</span>
                <div class="header-controls">
                  <el-switch v-model="downloader.enabled" style="margin-right: 12px" />
                  <el-button
                    type="danger"
                    :icon="Delete"
                    circle
                    @click="confirmDeleteDownloader(downloader.id)"
                  />
                </div>
              </div>
            </template>

            <el-form :model="downloader" label-position="left" label-width="auto">
              <el-form-item label="自定义名称">
                <el-input v-model="downloader.name" placeholder="例如：家庭服务器 qB"></el-input>
              </el-form-item>
              <el-form-item label="客户端类型">
                <el-select v-model="downloader.type" placeholder="请选择类型" style="width: 100%">
                  <el-option label="qBittorrent" value="qbittorrent"></el-option>
                  <el-option label="Transmission" value="transmission"></el-option>
                </el-select>
              </el-form-item>
              <el-form-item label="主机地址">
                <el-input
                  v-model="downloader.host"
                  placeholder="例如：http://192.168.1.10:8080"
                ></el-input>
              </el-form-item>
              <el-form-item label="用户名">
                <el-input v-model="downloader.username" placeholder="登录用户名"></el-input>
              </el-form-item>
              <el-form-item label="密码">
                <el-input
                  v-model="downloader.password"
                  type="password"
                  show-password
                  placeholder="登录密码（未修改则留空）"
                ></el-input>
              </el-form-item>
            </el-form>
          </el-card>
        </div>
      </div>

      <!-- 统一的页脚 -->
      <div class="save-footer">
        <el-button
          v-if="activeMenu === 'downloader'"
          type="primary"
          size="large"
          @click="addDownloader"
          :icon="Plus"
        >
          添加下载器
        </el-button>
        <el-button type="success" size="large" @click="saveSettings" :loading="isSaving">
          <el-icon><Select /></el-icon>
          保存所有设置
        </el-button>
      </div>
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Select, Download, Picture } from '@element-plus/icons-vue'

// --- 状态管理 ---
const settings = ref({ downloaders: [], background: null })
const isLoading = ref(true)
const isSaving = ref(false)
const activeMenu = ref('background') // 默认显示背景设置

// --- API 基础 URL ---
const API_BASE_URL = '/api'

// --- 生命周期钩子 ---
onMounted(() => {
  fetchSettings()
})

// --- 方法 ---
const handleMenuSelect = (index) => {
  activeMenu.value = index
}

const fetchSettings = async () => {
  isLoading.value = true
  try {
    const response = await axios.get(`${API_BASE_URL}/settings`)
    const data = response.data || {}

    // 初始化下载器设置
    if (data.downloaders) {
      data.downloaders.forEach((d) => {
        if (!d.id) d.id = `client_${Date.now()}_${Math.random()}`
      })
    } else {
      data.downloaders = []
    }

    // 初始化背景设置，提供默认值
    if (!data.background) {
      data.background = {
        type: 'color', // 'color' or 'image'
        value: '#ffffff', // color code or image url
      }
    }

    settings.value = data
  } catch (error) {
    ElMessage.error('加载设置失败！')
    console.error(error)
    // 出错时也提供默认值
    settings.value = {
      downloaders: [],
      background: { type: 'color', value: '#ffffff' },
    }
  } finally {
    isLoading.value = false
  }
}

const addDownloader = () => {
  settings.value.downloaders.push({
    id: `new_${Date.now()}`,
    enabled: true,
    name: '新下载器',
    type: 'qbittorrent',
    host: '',
    username: '',
    password: '',
  })
}

const confirmDeleteDownloader = (downloaderId) => {
  ElMessageBox.confirm('您确定要删除这个下载器配置吗？此操作不可撤销。', '警告', {
    confirmButtonText: '确定删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(() => {
      deleteDownloader(downloaderId)
      ElMessage({
        type: 'success',
        message: '下载器已删除（尚未保存）。',
      })
    })
    .catch(() => {})
}

const deleteDownloader = (downloaderId) => {
  settings.value.downloaders = settings.value.downloaders.filter((d) => d.id !== downloaderId)
}

const saveSettings = async () => {
  isSaving.value = true
  try {
    await axios.post(`${API_BASE_URL}/settings`, settings.value)
    ElMessage.success('设置已成功保存并应用！')
    // 触发全局事件，通知 App.vue 更新背景
    window.dispatchEvent(new CustomEvent('settings-updated'))
    fetchSettings()
  } catch (error) {
    ElMessage.error('保存设置失败！')
    console.error(error)
  } finally {
    isSaving.value = false
  }
}
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
.settings-view {
  padding: 24px;
}
.header {
  margin-bottom: 24px;
}
.header h1 {
  margin-bottom: 8px;
}
.downloader-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 24px;
}
.downloader-card {
  display: flex;
  flex-direction: column;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-controls {
  display: flex;
  align-items: center;
}
.el-form {
  padding-top: 10px;
}
.save-footer {
  margin-top: 32px;
  display: flex;
  justify-content: center;
  gap: 16px;
}
.setting-card {
  max-width: 600px;
}
</style>
