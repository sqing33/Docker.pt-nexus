<template>
  <div class="settings-view" v-loading="isLoading">
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
            <el-button
              type="danger"
              :icon="Delete"
              circle
              @click="confirmDeleteDownloader(downloader.id)"
            />
          </div>
        </template>

        <el-form :model="downloader" label-position="top">
          <el-form-item label="启用此下载器">
            <el-switch v-model="downloader.enabled" />
          </el-form-item>

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
            <el-input v-model="downloader.host" placeholder="例如：192.168.1.10:8080"></el-input>
          </el-form-item>

          <!-- [REMOVED] 独立的端口设置区域已被移除 -->

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

        <div class="card-footer">
          <el-button type="primary" plain @click="testConnection(downloader)">
            <el-icon><Connection /></el-icon>
            测试连接
          </el-button>
          <div v-if="testResults[downloader.id]" class="test-result">
            <el-text :type="testResults[downloader.id].success ? 'success' : 'danger'">
              {{ testResults[downloader.id].message }}
            </el-text>
          </div>
        </div>
      </el-card>

      <div class="add-card-container">
        <el-button class="add-button" type="primary" dashed @click="addDownloader">
          <el-icon><Plus /></el-icon>
          <span>添加下载器</span>
        </el-button>
      </div>
    </div>

    <div class="save-footer">
      <el-button type="success" size="large" @click="saveSettings" :loading="isSaving">
        <el-icon><Select /></el-icon>
        保存所有设置
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Connection, Select } from '@element-plus/icons-vue'

// --- 状态管理 ---
const settings = ref({ downloaders: [] })
const isLoading = ref(true)
const isSaving = ref(false)
const testResults = ref({})

// --- API 基础 URL ---
const API_BASE_URL = '/api'

// --- 生命周期钩子 ---
onMounted(() => {
  fetchSettings()
})

// --- 方法 ---
const fetchSettings = async () => {
  isLoading.value = true
  try {
    const response = await axios.get(`${API_BASE_URL}/settings`)
    response.data.downloaders.forEach((d) => {
      if (!d.id) d.id = `client_${Date.now()}_${Math.random()}`
    })
    settings.value = response.data
  } catch (error) {
    ElMessage.error('加载设置失败！')
    console.error(error)
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
    // [REMOVED] 不再默认设置 port
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

const testConnection = async (downloader) => {
  testResults.value[downloader.id] = { message: '正在测试...' }

  try {
    const response = await axios.post(`${API_BASE_URL}/test_connection`, downloader)
    testResults.value[downloader.id] = response.data
  } catch (error) {
    testResults.value[downloader.id] = {
      success: false,
      message: '测试请求失败，请检查网络或后端服务。',
    }
    console.error(error)
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
</script>

<style scoped>
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
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
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

.el-form {
  margin-bottom: auto; /* 让表单占据空间，将页脚推到底部 */
}

.card-footer {
  margin-top: 20px;
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 15px;
}

.test-result {
  margin-top: 10px;
  word-break: break-all;
}

.add-card-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px; /* 与卡片高度保持一致 */
  border: 2px dashed var(--el-border-color);
  border-radius: 4px;
  cursor: pointer;
  transition:
    border-color 0.3s,
    background-color 0.3s;
}

.add-card-container:hover {
  border-color: var(--el-color-primary);
  background-color: var(--el-color-primary-light-9);
}

.add-button {
  width: 100%;
  height: 100%;
  flex-direction: column;
  gap: 10px;
  font-size: 16px;
}

.save-footer {
  margin-top: 32px;
  text-align: center;
}
</style>
