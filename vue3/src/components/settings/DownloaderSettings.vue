<template>
  <div class="top-actions">
    <el-button type="primary" size="large" @click="addDownloader" :icon="Plus">
      添加下载器
    </el-button>
    <el-button type="success" size="large" @click="saveSettings" :loading="isSaving">
      <el-icon><Select /></el-icon>
      保存所有设置
    </el-button>
    <div class="realtime-switch-container">
      <el-tooltip
        content="开启后，图表页将每秒获取一次数据以显示“近1分钟”实时速率。关闭后将每分钟获取一次，以降低系统负载。"
        placement="bottom"
        :hide-after="0"
      >
        <el-form-item label="开启实时速率" class="switch-form-item">
          <el-switch
            v-model="settings.realtime_speed_enabled"
            size="large"
            inline-prompt
            active-text="是"
            inactive-text="否"
          />
        </el-form-item>
      </el-tooltip>
    </div>
  </div>
  <div class="settings-view" v-loading="isLoading">
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
              :placeholder="downloader.type === 'transmission' ? '例如：192.168.1.10:9091 或 http://192.168.1.10:9091' : '例如：192.168.1.10:8080'"
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
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Select, Link } from '@element-plus/icons-vue'

const settings = ref({
  downloaders: [],
  realtime_speed_enabled: true,
})
const isLoading = ref(true)
const isSaving = ref(false)
const testingConnectionId = ref(null)
const connectionTestResults = ref({})
const API_BASE_URL = '/api'

onMounted(() => {
  fetchSettings()
})

const fetchSettings = async () => {
  isLoading.value = true
  try {
    const response = await axios.get(`${API_BASE_URL}/settings`)
    if (response.data) {
      if (!response.data.downloaders) response.data.downloaders = []
      if (typeof response.data.realtime_speed_enabled !== 'boolean')
        response.data.realtime_speed_enabled = true
      response.data.downloaders.forEach((d) => {
        if (!d.id) d.id = `client_${Date.now()}_${Math.random()}`
      })
      settings.value = response.data
    }
  } catch (error) {
    ElMessage.error('加载设置失败！')
    console.error(error)
  } finally {
    isLoading.value = false
  }
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

const resetConnectionStatus = (downloaderId) => {
  if (connectionTestResults.value[downloaderId]) {
    delete connectionTestResults.value[downloaderId]
  }
}

const testConnection = async (downloader) => {
  resetConnectionStatus(downloader.id)
  testingConnectionId.value = downloader.id
  try {
    const response = await axios.post(`${API_BASE_URL}/test_connection`, downloader)
    const result = response.data
    if (result.success) {
      ElMessage.success(result.message)
      connectionTestResults.value[downloader.id] = 'success'
    } else {
      ElMessage.error(result.message)
      connectionTestResults.value[downloader.id] = 'error'
    }
  } catch (error) {
    ElMessage.error('测试连接请求失败，请检查网络或后端服务。')
    console.error('Test connection error:', error)
    connectionTestResults.value[downloader.id] = 'error'
  } finally {
    testingConnectionId.value = null
  }
}
</script>

<style scoped>
.top-actions {
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 10;
  background-color: var(--el-bg-color-page);
  padding: 16px 24px;
  border-bottom: 1px solid var(--el-border-color);
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 16px;
}
.settings-view {
  padding: 24px;
  overflow-y: auto;
  flex-grow: 1;
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
.switch-form-item {
  margin-bottom: 0;
  margin-left: 8px;
}
</style>
