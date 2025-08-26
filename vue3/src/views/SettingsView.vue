<template>
  <el-container class="settings-container">
    <!-- 左侧导航栏 -->
    <el-aside width="200px" class="settings-aside">
      <el-menu :default-active="activeMenu" class="settings-menu" @select="handleMenuSelect">
        <el-menu-item index="downloader">
          <el-icon><Download /></el-icon>
          <span>下载器</span>
        </el-menu-item>
        <el-menu-item index="cookie">
          <el-icon><Tickets /></el-icon>
          <span>站点Cookie</span>
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
                  placeholder="例如：192.168.1.10:8080"
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

      <!-- [新增] 站点Cookie设置视图 -->
      <div v-if="activeMenu === 'cookie'">
        <!-- 顶部操作栏 -->
        <div class="top-actions cookie-actions">
          <el-form :model="cookieCloudForm" inline class="cookie-cloud-form">
            <el-form-item label="CookieCloud URL">
              <el-input
                v-model="cookieCloudForm.url"
                placeholder="http://127.0.0.1:8088"
                clearable
                style="width: 220px"
              ></el-input>
            </el-form-item>
            <el-form-item label="KEY">
              <el-input
                v-model="cookieCloudForm.key"
                placeholder="CookieCloud 用户 KEY (UUID)"
                clearable
                style="width: 280px"
              ></el-input>
            </el-form-item>
            <el-form-item label="E2E 密码">
              <el-input
                v-model="cookieCloudForm.e2e_password"
                type="password"
                placeholder="端对端加密密码 (可选)"
                show-password
                style="width: 200px"
              ></el-input>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                size="large"
                @click="syncFromCookieCloud"
                :loading="isSyncing"
              >
                <el-icon><Refresh /></el-icon>
                <span>同步</span>
              </el-button>
            </el-form-item>
            <el-form-item>
              <el-button type="success" size="large" @click="saveSettings" :loading="isSaving">
                <el-icon><Select /></el-icon>
                <span>保存配置</span>
              </el-button>
            </el-form-item>
          </el-form>
        </div>

        <!-- 站点列表 -->
        <div class="settings-view" v-loading="isSitesLoading">
          <el-table :data="sitesList" stripe style="width: 100%" max-height="calc(100vh - 160px)">
            <el-table-column prop="nickname" label="站点昵称" width="180" sortable />
            <el-table-column prop="site" label="站点域名" width="250" />
            <el-table-column prop="base_url" label="基础URL" show-overflow-tooltip />
            <el-table-column label="Cookie 状态" width="150" align="center">
              <template #default="scope">
                <el-tag :type="scope.row.has_cookie ? 'success' : 'warning'">
                  {{ scope.row.has_cookie ? '已配置' : '未配置' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" align="center">
              <template #default="scope">
                <el-button type="primary" link @click="editCookie(scope.row)"> 手动更新 </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- 一键引爆视图 -->
      <div v-if="activeMenu === 'indexer'" class="settings-view">
        <h1>一键引爆</h1>
        <div>Boom！</div>
      </div>
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus,
  Delete,
  Select,
  Download,
  User,
  Link,
  Tickets,
  Refresh,
} from '@element-plus/icons-vue'

// --- 状态管理 ---
const settings = ref({
  downloaders: [],
  realtime_speed_enabled: true,
  cookiecloud: { url: '', key: '', e2e_password: '' }, // 确保初始结构存在
})
const isLoading = ref(true)
const isSaving = ref(false)
const activeMenu = ref('downloader')
const testingConnectionId = ref(null)
const connectionTestResults = ref({})

// --- [新增] Cookie 管理状态 ---
const sitesList = ref([])
const isSitesLoading = ref(false)
const isSyncing = ref(false)
const cookieCloudForm = ref({
  url: '',
  key: '',
  e2e_password: '',
})

// --- API 基础 URL ---
const API_BASE_URL = '/api'

// --- 生命周期钩子 ---
onMounted(() => {
  fetchSettings()
  fetchSites()
})

// --- 方法 ---

const handleMenuSelect = (index) => {
  activeMenu.value = index
}

const fetchSettings = async () => {
  isLoading.value = true
  try {
    const response = await axios.get(`${API_BASE_URL}/settings`)
    if (response.data) {
      if (!response.data.downloaders) {
        response.data.downloaders = []
      }
      if (typeof response.data.realtime_speed_enabled !== 'boolean') {
        response.data.realtime_speed_enabled = true
      }
      response.data.downloaders.forEach((d) => {
        if (!d.id) d.id = `client_${Date.now()}_${Math.random()}`
      })

      // [新增] 填充 CookieCloud 表单
      if (response.data.cookiecloud) {
        cookieCloudForm.value.url = response.data.cookiecloud.url || ''
        cookieCloudForm.value.key = response.data.cookiecloud.key || ''
        cookieCloudForm.value.e2e_password = '' // 密码不回显
      }

      settings.value = response.data
    }
  } catch (error) {
    ElMessage.error('加载设置失败！')
    console.error(error)
  } finally {
    isLoading.value = false
  }
}

// --- [新增] Cookie 管理方法 ---

const fetchSites = async () => {
  isSitesLoading.value = true
  try {
    const response = await axios.get(`${API_BASE_URL}/sites`)
    sitesList.value = response.data
  } catch (error) {
    ElMessage.error('获取站点列表失败！')
    console.error('Fetch sites error:', error)
  } finally {
    isSitesLoading.value = false
  }
}

const syncFromCookieCloud = async () => {
  if (!cookieCloudForm.value.url || !cookieCloudForm.value.key) {
    ElMessage.warning('CookieCloud URL 和 KEY 不能为空！')
    return
  }
  isSyncing.value = true
  try {
    const response = await axios.post(`${API_BASE_URL}/cookiecloud/sync`, cookieCloudForm.value)
    if (response.data.success) {
      ElMessage.success(response.data.message)
      await fetchSites() // 同步成功后刷新列表
    } else {
      ElMessage.error(response.data.message || '同步失败！')
    }
  } catch (error) {
    const errorMessage = error.response?.data?.message || '同步请求失败，请检查网络或后端服务。'
    ElMessage.error(errorMessage)
    console.error('CookieCloud sync error:', error)
  } finally {
    isSyncing.value = false
  }
}

const editCookie = (site) => {
  ElMessageBox.prompt(`请输入站点 "${site.nickname}" 的新 Cookie:`, '手动更新 Cookie', {
    confirmButtonText: '保存',
    cancelButtonText: '取消',
    inputType: 'textarea',
    inputPlaceholder: '请在此处粘贴完整的 Cookie 字符串',
  })
    .then(async ({ value }) => {
      if (!value || value.trim() === '') {
        // 用户可能点击了确定但没有输入内容
        ElMessage.info('未输入内容，操作已取消。')
        return
      }
      try {
        const response = await axios.post(`${API_BASE_URL}/sites/update_cookie`, {
          nickname: site.nickname,
          cookie: value,
        })
        if (response.data.success) {
          ElMessage.success(response.data.message)
          await fetchSites() // 更新成功后刷新列表
        } else {
          ElMessage.error(response.data.message || '更新失败！')
        }
      } catch (error) {
        const errorMessage = error.response?.data?.message || '更新 Cookie 请求失败。'
        ElMessage.error(errorMessage)
        console.error('Update cookie error:', error)
      }
    })
    .catch(() => {
      ElMessage.info('操作已取消。')
    })
}

// --- 下载器方法 & 通用方法 ---

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
      ElMessage.success('下载器已删除（尚未保存）。')
    })
    .catch(() => {})
}

const deleteDownloader = (downloaderId) => {
  settings.value.downloaders = settings.value.downloaders.filter((d) => d.id !== downloaderId)
}

const saveSettings = async () => {
  isSaving.value = true
  try {
    // [修改] 在保存前，从表单更新 settings 对象中的 cookiecloud 部分
    settings.value.cookiecloud = cookieCloudForm.value

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
  position: relative;
  display: flex;
  flex-direction: column;
}

.top-actions {
  position: sticky;
  top: 0;
  z-index: 10;
  background-color: var(--el-bg-color);
  padding: 16px 24px;
  border-bottom: 1px solid var(--el-border-color);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
}

.realtime-switch-container {
  display: flex;
  align-items: center;
}
.switch-form-item {
  margin-bottom: 0;
  margin-left: 8px;
}

.settings-view {
  padding: 24px;
  overflow-y: auto; /* 允许内容区滚动 */
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

.el-form {
  padding-top: 10px;
}

/* [新增] CookieCloud 表单样式 */
.cookie-cloud-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
}
.cookie-cloud-form .el-form-item {
  margin-bottom: 0;
  margin-right: 0;
}
</style>
