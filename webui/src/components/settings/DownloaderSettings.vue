<template>
  <div class="top-actions glass-pagination">
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
        class="downloader-card glass-card glass-rounded glass-transparent-header glass-transparent-body"
      >
        <template #header>
          <div class="card-header">
            <span>{{ downloader.name || '新下载器' }}</span>
            <div class="header-controls">
              <el-button
                :type="
                  connectionTestResults[downloader.id] === 'success'
                    ? 'success'
                    : connectionTestResults[downloader.id] === 'error'
                      ? 'danger'
                      : 'info'
                "
                :plain="!connectionTestResults[downloader.id]"
                style="width: 90px"
                @click="testConnection(downloader)"
                :loading="testingConnectionId === downloader.id"
                :icon="Link"
              >
                测试连接
              </el-button>
              <el-button
                type="warning"
                :icon="FolderOpened"
                style="width: 90px"
                @click="openPathMappingDialog(downloader)"
              >
                路径映射
              </el-button>
              <el-switch v-model="downloader.enabled" style="margin: 0 10px" />

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
          <el-form-item label="名称">
            <div class="name-and-client-row">
              <el-input
                v-model="downloader.name"
                placeholder="例如：家庭服务器 qB"
                class="name-input"
                @input="resetConnectionStatus(downloader.id)"
              ></el-input>
              <el-select
                v-model="downloader.type"
                placeholder="请选择类型"
                class="client-type-select"
                @change="resetConnectionStatus(downloader.id)"
              >
                <el-option label="qBittorrent" value="qbittorrent"></el-option>
                <el-option label="Transmission" value="transmission"></el-option>
              </el-select>
            </div>
          </el-form-item>
          <el-form-item label="代理设置">
            <div class="proxy-settings-row">
              <el-input
                v-model="downloader.proxy_port"
                type="number"
                placeholder="9090"
                class="proxy-port-input"
                :min="1"
                :max="65535"
                :disabled="downloader.type === 'transmission'"
                @input="resetConnectionStatus(downloader.id)"
              >
                <template #prepend>端口</template>
              </el-input>
              <el-tooltip
                :content="
                  downloader.type === 'transmission'
                    ? 'Transmission 暂不支持代理功能'
                    : '通过Go语言编写的专用代理连接，可解决网络延迟、获取数据不准等问题。'
                "
                placement="top"
                :hide-after="0"
              >
                <el-switch
                  v-model="downloader.use_proxy"
                  size="large"
                  inline-prompt
                  active-text="远程"
                  inactive-text="本地"
                  :disabled="downloader.type === 'transmission'"
                  @change="resetConnectionStatus(downloader.id)"
                />
              </el-tooltip>
            </div>
          </el-form-item>
          <el-form-item label="主机地址">
            <el-input
              v-model="downloader.host"
              :placeholder="
                downloader.type === 'transmission'
                  ? '例如：192.168.1.10:9091 或 http://192.168.1.10:9091'
                  : '例如：192.168.1.10:8080'
              "
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

  <!-- 路径映射对话框 -->
  <el-dialog
    v-model="pathMappingDialogVisible"
    :title="`路径映射配置 - ${currentDownloader?.name || ''}`"
    width="700px"
    :close-on-click-modal="false"
  >
    <div class="path-mapping-container">
      <el-alert title="路径映射说明" type="info" :closable="false" style="margin-bottom: 16px">
        <p>配置下载器路径到 PT Nexus 容器内路径的映射关系。</p>
        <p><strong>下载器路径：</strong>下载器中显示的种子保存路径</p>
        <p><strong>视频文件路径：</strong>挂载到 PT Nexus 容器内的路径或者盒子本地路径的路径</p>
      </el-alert>

      <div class="mapping-list">
        <div v-for="(mapping, index) in currentPathMappings" :key="index" class="mapping-item">
          <el-input v-model="mapping.remote" placeholder="例如：/downloads" class="mapping-input">
            <template #prepend>下载器路径</template>
          </el-input>
          <el-input v-model="mapping.local" placeholder="例如：/app/data/qb1" class="mapping-input">
            <template #prepend>视频文件路径</template>
          </el-input>
          <el-button type="danger" :icon="Delete" circle @click="deletePathMapping(index)" />
        </div>
      </div>

      <el-button
        type="primary"
        :icon="Plus"
        style="width: 100%; margin-top: 16px"
        @click="addPathMapping"
      >
        添加映射规则
      </el-button>
    </div>

    <template #footer>
      <el-button @click="pathMappingDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="savePathMappings">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Select, Link, FolderOpened } from '@element-plus/icons-vue'

const settings = ref({
  downloaders: [],
  realtime_speed_enabled: true,
})
const isLoading = ref(true)
const isSaving = ref(false)
const testingConnectionId = ref(null)
const connectionTestResults = ref({})
const API_BASE_URL = '/api'

// 路径映射相关状态
const pathMappingDialogVisible = ref(false)
const currentDownloader = ref(null)
const currentPathMappings = ref([])

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
        if (typeof d.use_proxy !== 'boolean') d.use_proxy = false
        if (!d.proxy_port) d.proxy_port = 9090
        // 初始化 path_mappings 字段
        if (!d.path_mappings || !Array.isArray(d.path_mappings)) {
          d.path_mappings = []
        }
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
    use_proxy: false,
    proxy_port: 9090,
    path_mappings: [], // 初始化空的路径映射数组
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

// 路径映射相关函数
const openPathMappingDialog = (downloader) => {
  currentDownloader.value = downloader
  // 初始化路径映射数据，如果不存在则创建空数组
  if (!downloader.path_mappings || !Array.isArray(downloader.path_mappings)) {
    downloader.path_mappings = []
  }
  // 深拷贝映射数据，避免直接修改
  currentPathMappings.value = JSON.parse(JSON.stringify(downloader.path_mappings))
  pathMappingDialogVisible.value = true
}

const addPathMapping = () => {
  currentPathMappings.value.push({
    remote: '',
    local: '',
  })
}

const deletePathMapping = (index) => {
  currentPathMappings.value.splice(index, 1)
}

const savePathMappings = async () => {
  // 过滤掉空的映射规则
  const validMappings = currentPathMappings.value.filter(
    (mapping) => mapping.remote.trim() !== '' && mapping.local.trim() !== '',
  )
  // 更新当前下载器的路径映射
  currentDownloader.value.path_mappings = validMappings

  // 立即保存到配置文件
  isSaving.value = true
  try {
    await axios.post(`${API_BASE_URL}/settings`, settings.value)
    pathMappingDialogVisible.value = false
    ElMessage.success('路径映射已保存！')
    fetchSettings()
  } catch (error) {
    ElMessage.error('保存路径映射失败！')
    console.error(error)
  } finally {
    isSaving.value = false
  }
}
</script>

<style scoped>
.top-actions {
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 10;
  padding: 16px 24px;
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 16px;
}

.settings-view {
  padding: 24px;
  overflow-y: auto;
  flex-grow: 1;
  background-color: transparent;
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

.name-and-client-row {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 12px;
}

.name-input {
  flex: 1;
  /* 名称输入框占一半 */
}

.client-type-select {
  flex: 1;
  /* 客户端选择占一半 */
}

.proxy-settings-row {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 12px;
}

.proxy-port-input {
  flex: 1;
  /* 占据剩余空间 */
}

.switch-form-item {
  margin-bottom: 0;
  margin-left: 8px;
}

/* 路径映射对话框样式 */
.path-mapping-container {
  padding: 8px 0;
}

.mapping-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mapping-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mapping-input {
  flex: 1;
}
</style>
