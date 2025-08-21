<template>
  <div class="settings-container">
    <el-alert
      title="设置说明"
      type="info"
      description="在此处配置您的下载客户端。密码字段留空则表示不更改现有密码。每个客户端的设置需要单独应用。"
      show-icon
      :closable="false"
      class="info-alert"
    />

    <!-- qBittorrent 设置 -->
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span><i class="fas fa-cube"></i> qBittorrent</span>
          <el-switch v-model="config.qbittorrent.enabled" active-text="启用" inactive-text="禁用" />
        </div>
      </template>
      <!-- 移除了这里的 :disabled 属性 -->
      <el-form :model="config.qbittorrent" label-width="120px">
        <el-form-item label="主机地址">
          <!-- 将 :disabled 属性移到了具体的输入组件上 -->
          <el-input
            v-model="config.qbittorrent.host"
            placeholder="例如: http://192.168.1.10:8080"
            :disabled="!config.qbittorrent.enabled"
          />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="config.qbittorrent.username" :disabled="!config.qbittorrent.enabled" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="config.qbittorrent.password"
            type="password"
            show-password
            placeholder="留空以保持不变"
            :disabled="!config.qbittorrent.enabled"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            @click="testConnection('qbittorrent')"
            :disabled="!config.qbittorrent.enabled"
            >测试连接</el-button
          >
          <!-- 这个按钮现在只受 loading 状态影响，不再被表单禁用 -->
          <el-button
            type="success"
            @click="saveClientSettings('qbittorrent')"
            :loading="isSaving.qbittorrent"
          >
            <i class="fas fa-save"></i>&nbsp;应用 qBittorrent 设置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Transmission 设置 -->
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span><i class="fas fa-circle-nodes"></i> Transmission</span>
          <el-switch
            v-model="config.transmission.enabled"
            active-text="启用"
            inactive-text="禁用"
          />
        </div>
      </template>
      <!-- 移除了这里的 :disabled 属性 -->
      <el-form :model="config.transmission" label-width="120px">
        <el-form-item label="主机地址">
          <!-- 将 :disabled 属性移到了具体的输入组件上 -->
          <el-input
            v-model="config.transmission.host"
            placeholder="例如: 192.168.1.11"
            :disabled="!config.transmission.enabled"
          />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number
            v-model="config.transmission.port"
            :min="1"
            :max="65535"
            :disabled="!config.transmission.enabled"
          />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input
            v-model="config.transmission.username"
            :disabled="!config.transmission.enabled"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="config.transmission.password"
            type="password"
            show-password
            placeholder="留空以保持不变"
            :disabled="!config.transmission.enabled"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            @click="testConnection('transmission')"
            :disabled="!config.transmission.enabled"
            >测试连接</el-button
          >
          <!-- 这个按钮现在只受 loading 状态影响，不再被表单禁用 -->
          <el-button
            type="success"
            @click="saveClientSettings('transmission')"
            :loading="isSaving.transmission"
          >
            <i class="fas fa-save"></i>&nbsp;应用 Transmission 设置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const isSaving = reactive({
  qbittorrent: false,
  transmission: false,
})

const config = ref({
  qbittorrent: {
    enabled: false,
    host: '',
    username: '',
    password: '',
  },
  transmission: {
    enabled: false,
    host: '',
    port: 9091,
    username: '',
    password: '',
  },
})

const fetchSettings = async () => {
  try {
    const response = await axios.get('/api/settings')
    if (response.data.qbittorrent) {
      config.value.qbittorrent = { ...config.value.qbittorrent, ...response.data.qbittorrent }
    }
    if (response.data.transmission) {
      config.value.transmission = { ...config.value.transmission, ...response.data.transmission }
    }
  } catch (error) {
    ElMessage.error('获取设置失败！')
    console.error(error)
  }
}

const testConnection = async (clientType) => {
  let payload
  if (clientType === 'qbittorrent') {
    payload = {
      type: 'qbittorrent',
      config: config.value.qbittorrent,
    }
  } else if (clientType === 'transmission') {
    payload = {
      type: 'transmission',
      config: {
        host: config.value.transmission.host,
        port: config.value.transmission.port,
        username: config.value.transmission.username,
        password: config.value.transmission.password,
      },
    }
  } else {
    return
  }

  try {
    const response = await axios.post('/api/test_connection', payload)
    if (response.data.success) {
      ElMessage.success(`[${clientType}] ${response.data.message}`)
    } else {
      ElMessage.error(`[${clientType}] ${response.data.message}`)
    }
  } catch (error) {
    ElMessage.error(`[${clientType}] 测试请求失败: ${error.message}`)
    console.error(error)
  }
}

const saveClientSettings = async (clientType) => {
  isSaving[clientType] = true
  const payload = {
    [clientType]: config.value[clientType],
  }

  try {
    const response = await axios.post('/api/settings', payload)
    ElMessage.success(response.data.message || '设置已保存！')
  } catch (error) {
    ElMessage.error(error.response?.data?.error || '保存设置失败！')
    console.error(error)
  } finally {
    isSaving[clientType] = false
  }
}

onMounted(() => {
  fetchSettings()
})
</script>

<style scoped>
.settings-container {
  padding: 20px;
}
.box-card {
  margin-bottom: 20px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}
.card-header span i {
  margin-right: 8px;
}
.info-alert {
  margin-bottom: 20px;
}
</style>
