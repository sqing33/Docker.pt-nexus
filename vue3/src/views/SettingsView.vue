<template>
  <el-container class="settings-container">
    <!-- 左侧导航栏 -->
    <el-aside width="200px" class="settings-aside">
      <el-menu :default-active="activeMenu" class="settings-menu" @select="handleMenuSelect">
        <el-menu-item index="downloader">
          <el-icon><Download /></el-icon>
          <span>下载器</span>
        </el-menu-item>
        <el-menu-item index="indexer">
          <el-icon><User /></el-icon>
          <span>一键引爆</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-main class="settings-main">
      <!-- 顶部操作栏 -->
      <div v-if="activeMenu === 'downloader'" class="top-actions">
        <el-button type="primary" size="large" @click="addDownloader" :icon="Plus">
          添加下载器
        </el-button>
        <el-button type="success" size="large" @click="saveSettings" :loading="isSaving">
          <el-icon><Select /></el-icon>
          保存所有设置
        </el-button>
      </div>

      <!-- 下载器设置视图 -->
      <div v-if="activeMenu === 'downloader'" class="settings-view" v-loading="isLoading">
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
                    :type="
                      connectionTestResults[downloader.id] === 'success'
                        ? 'success'
                        : connectionTestResults[downloader.id] === 'error'
                          ? 'danger'
                          : 'info'
                    "
                    :plain="!connectionTestResults[downloader.id]"
                    style="width: 100%"
                    @click="testConnection(downloader)"
                    :loading="testingConnectionId === downloader.id"
                    :icon="Link"
                  >
                    测试连接
                  </el-button>
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
                <el-input
                  v-model="downloader.name"
                  placeholder="例如：家庭服务器 qB"
                  @input="resetConnectionStatus(downloader.id)"
                ></el-input>
              </el-form-item>

              <el-form-item label="客户端类型">
                <el-select
                  v-model="downloader.type"
                  placeholder="请选择类型"
                  style="width: 100%"
                  @change="resetConnectionStatus(downloader.id)"
                >
                  <el-option label="qBittorrent" value="qbittorrent"></el-option>
                  <el-option label="Transmission" value="transmission"></el-option>
                </el-select>
              </el-form-item>

              <el-form-item label="主机地址">
                <el-input
                  v-model="downloader.host"
                  placeholder="例如：http://192.168.1.10:8080"
                  @input="resetConnectionStatus(downloader.id)"
                ></el-input>
              </el-form-item>

              <el-form-item label="用户名">
                <el-input
                  v-model="downloader.username"
                  placeholder="登录用户名"
                  @input="resetConnectionStatus(downloader.id)"
                ></el-input>
              </el-form-item>

              <el-form-item label="密码">
                <el-input
                  v-model="downloader.password"
                  type="password"
                  show-password
                  placeholder="登录密码（未修改则留空）"
                  @input="resetConnectionStatus(downloader.id)"
                ></el-input>
              </el-form-item>
            </el-form>
          </el-card>
        </div>
      </div>

      <!-- 一键引爆视图 -->
      <div v-if="activeMenu === 'indexer'" class="settings-view">
        <h1>一键引爆</h1>
        <div>待办</div>
        <ul>
          <li>路径筛选改成下拉框或者树状</li>
          <li>请求间隔时间</li>
          <li>上传下载显示开关</li>
        </ul>
      </div>
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Select, Download, User, Link } from '@element-plus/icons-vue'

// --- 状态管理 ---
const settings = ref({ downloaders: [] })
const isLoading = ref(true)
const isSaving = ref(false)
const activeMenu = ref('downloader')
const testingConnectionId = ref(null)
// [新增] 用于存储每个下载器的连接测试结果 ('success' | 'error')
const connectionTestResults = ref({})

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
    if (response.data && response.data.downloaders) {
      response.data.downloaders.forEach((d) => {
        if (!d.id) d.id = `client_${Date.now()}_${Math.random()}`
      })
      settings.value = response.data
    } else {
      settings.value = { downloaders: [] }
    }
  } catch (error) {
    ElMessage.error('加载设置失败！')
    console.error(error)
    settings.value = { downloaders: [] }
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
    .catch(() => {
      // 用户取消操作
    })
}

const deleteDownloader = (downloaderId) => {
  settings.value.downloaders = settings.value.downloaders.filter((d) => d.id !== downloaderId)
}

const saveSettings = async () => {
  isSaving.value = true
  try {
    await axios.post(`${API_BASE_URL}/settings`, settings.value)
    ElMessage.success('设置已成功保存并应用！')
    fetchSettings()
  } catch (error) {
    ElMessage.error('保存设置失败！')
    console.error(error)
  } finally {
    isSaving.value = false
  }
}

// [新增] 当用户修改输入时，重置连接状态
const resetConnectionStatus = (downloaderId) => {
  if (connectionTestResults.value[downloaderId]) {
    delete connectionTestResults.value[downloaderId]
  }
}

const testConnection = async (downloader) => {
  resetConnectionStatus(downloader.id) // 开始测试前先重置状态
  testingConnectionId.value = downloader.id // 开始加载状态
  try {
    const response = await axios.post(`${API_BASE_URL}/test_connection`, downloader)
    const result = response.data
    if (result.success) {
      ElMessage.success(result.message)
      // [修改] 保存成功状态
      connectionTestResults.value[downloader.id] = 'success'
    } else {
      ElMessage.error(result.message)
      // [修改] 保存失败状态
      connectionTestResults.value[downloader.id] = 'error'
    }
  } catch (error) {
    ElMessage.error('测试连接请求失败，请检查网络或后端服务。')
    console.error('Test connection error:', error)
    // [修改] 保存失败状态
    connectionTestResults.value[downloader.id] = 'error'
  } finally {
    testingConnectionId.value = null // 结束加载状态
  }
}
</script>

<style scoped>
.settings-container {
  height: 100vh; /* 使布局占满整个视口高度 */
}

.settings-aside {
  border-right: 1px solid var(--el-border-color);
}

.settings-menu {
  height: 100%;
  border-right: none; /* 移除菜单自身的右边框 */
}

.settings-main {
  padding: 0;
  position: relative;
}

.top-actions {
  position: sticky;
  top: 0;
  z-index: 10;
  background-color: #ffffff;
  padding: 16px 24px;
  border-bottom: 1px solid var(--el-border-color);
  display: flex;
  justify-content: flex-start;
  gap: 16px;
}

.settings-view {
  padding: 24px;
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
</style>
