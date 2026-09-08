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
    <div class="realtime-switch-container">
      <el-tooltip
        content="开启后按设定间隔自动调用“刷新种子信息”，从下载器同步最新种子状态；关闭后需手动刷新。"
        placement="bottom"
        :hide-after="0"
      >
        <el-form-item label="定时刷新种子" class="switch-form-item">
          <el-switch
            v-model="settings.torrent_refresh_enabled"
            size="large"
            inline-prompt
            active-text="是"
            inactive-text="否"
          />
        </el-form-item>
      </el-tooltip>
      <el-form-item label="间隔(分钟)" class="switch-form-item">
        <el-input-number
          v-model="settings.torrent_refresh_interval_minutes"
          :min="5"
          :max="1440"
          :step="5"
          :disabled="!settings.torrent_refresh_enabled"
          size="large"
          controls-position="right"
        />
      </el-form-item>
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
            <el-tag
              class="downloader-name-tag"
              size="default"
              :style="downloaderNameTagStyle(downloader)"
            >
              {{ downloader.name || '新下载器' }}
            </el-tag>
            <div class="header-controls">
              <div class="downloader-color-controls">
                <el-popover trigger="click" placement="bottom-start" popper-class="downloader-color-popover">
                  <template #reference>
                    <button
                      type="button"
                      class="downloader-color-trigger"
                      :style="{ backgroundColor: downloader.color }"
                      aria-label="选择下载器颜色"
                    />
                  </template>
                  <el-color-picker-panel
                    v-model="downloader.color"
                    :predefine="predefinedDownloaderColors"
                    :border="false"
                    :validate-event="false"
                  >
                    <template #footer>
                      <el-button
                        size="small"
                        text
                        class="downloader-color-random-btn"
                        :icon="Refresh"
                        @click="downloader.color = randomDownloaderColor()"
                      >
                        随机
                      </el-button>
                    </template>
                  </el-color-picker-panel>
                </el-popover>
              </div>
              <el-button
                :type="
                  connectionTestResults[downloader.id] === 'success'
                    ? 'success'
                    : connectionTestResults[downloader.id] === 'error'
                      ? 'danger'
                      : 'info'
                "
                :plain="!connectionTestResults[downloader.id]"
                style="width: 70px"
                @click="testConnection(downloader)"
                :loading="testingConnectionId === downloader.id"
                :icon="Link"
              >
                测试
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
          <el-form-item label="盒子端口">
            <div class="proxy-settings-row">
              <el-tooltip
                :content="
                  downloader.type === 'transmission'
                    ? '通过代理获取截图、MediaInfo等媒体信息。注意：TR代理不包括统计数据获取。'
                    : '通过Go语言编写的专用代理连接，可解决网络延迟、获取数据不准等问题。'
                "
                placement="top"
                :hide-after="0"
              >
                <el-input
                  v-model="downloader.proxy_port"
                  type="number"
                  placeholder="9090"
                  class="proxy-port-input"
                  :min="1"
                  :max="65535"
                  @input="resetConnectionStatus(downloader.id)"
                >
                  <template #append>
                    <div class="input-append-wrapper">
                      <el-switch
                        v-model="downloader.use_proxy"
                        inline-prompt
                        active-text="远程"
                        inactive-text="本地"
                        @change="resetConnectionStatus(downloader.id)"
                      />
                    </div>
                  </template>
                </el-input>
              </el-tooltip>
              <el-tooltip
                content="开启后，此下载器将参与基于站点分享率阈值的出种限速"
                placement="top"
                :hide-after="0"
              >
                <span class="ratio-limiter-label">
                  <span class="ratio-limiter-text">出种限速</span>
                  <el-switch
                    v-model="downloader.enable_ratio_limiter"
                    inline-prompt
                    active-text="开"
                    inactive-text="关"
                  />
                </span>
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
          <el-form-item label="发布节奏">
            <div class="publish-controls-row">
              <el-input-number
                v-model="downloader.publish_interval_minutes"
                :min="0"
                :max="1440"
                controls-position="right"
                class="publish-control"
              />
              <span class="publish-control-unit">分钟间隔</span>
              <el-input-number
                v-model="downloader.publish_concurrency"
                :min="1"
                :max="20"
                controls-position="right"
                class="publish-control"
              />
              <span class="publish-control-unit">并发数</span>
            </div>
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

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessageBox } from 'element-plus'
import { Plus, Delete, Select, Link, FolderOpened, Refresh } from '@element-plus/icons-vue'
import { useTorrentsViewState } from '@/stores/torrentsViewState'
import { ElMessage } from '@/utils/uiNotify'

type ConnectionTestStatus = 'success' | 'error'

type PathMapping = {
  remote: string
  local: string
}

type DownloaderConfig = {
  id: string
  enabled: boolean
  name: string
  type: string
  host: string
  username: string
  password: string
  use_proxy: boolean
  proxy_port: number
  color: string
  path_mappings: PathMapping[]
  enable_ratio_limiter: boolean
  publish_interval_minutes: number
  publish_concurrency: number
  [key: string]: unknown
}

type SettingsState = {
  downloaders: DownloaderConfig[]
  realtime_speed_enabled: boolean
  torrent_refresh_enabled: boolean
  torrent_refresh_interval_minutes: number
  [key: string]: unknown
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const settings = ref<SettingsState>({
  downloaders: [],
  realtime_speed_enabled: false,
  torrent_refresh_enabled: true,
  torrent_refresh_interval_minutes: 30,
})
const isLoading = ref(true)
const isSaving = ref(false)
const testingConnectionId = ref<string | null>(null)
const connectionTestResults = ref<Record<string, ConnectionTestStatus | undefined>>({})
const API_BASE_URL = '/api'
const torrentsViewState = useTorrentsViewState()

const predefinedDownloaderColors = [
  '#409EFF',
  '#67C23A',
  '#E6A23C',
  '#909399',
  '#00C9A7',
  '#6C5CE7',
  '#0984E3',
  '#00B894',
  '#FDCB6E',
  '#A29BFE',
  '#74B9FF',
  '#55EFC4',
]

const clampInt = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

const hslToHex = (h: number, s: number, l: number) => {
  const sat = clampInt(Number(s), 0, 100) / 100
  const lig = clampInt(Number(l), 0, 100) / 100

  const c = (1 - Math.abs(2 * lig - 1)) * sat
  const hp = (((Number(h) % 360) + 360) % 360) / 60
  const x = c * (1 - Math.abs((hp % 2) - 1))

  let r1 = 0
  let g1 = 0
  let b1 = 0
  if (hp >= 0 && hp < 1) [r1, g1, b1] = [c, x, 0]
  else if (hp >= 1 && hp < 2) [r1, g1, b1] = [x, c, 0]
  else if (hp >= 2 && hp < 3) [r1, g1, b1] = [0, c, x]
  else if (hp >= 3 && hp < 4) [r1, g1, b1] = [0, x, c]
  else if (hp >= 4 && hp < 5) [r1, g1, b1] = [x, 0, c]
  else if (hp >= 5 && hp < 6) [r1, g1, b1] = [c, 0, x]

  const m = lig - c / 2
  const toHex = (v: number) => Math.round((v + m) * 255).toString(16).padStart(2, '0')
  return `#${toHex(r1)}${toHex(g1)}${toHex(b1)}`
}

const deriveDownloaderColor = (seed: unknown) => {
  const value = String(seed || '').trim()
  if (!value) return predefinedDownloaderColors[0]
  let hash = 0
  for (let i = 0; i < value.length; i++) {
    hash = value.charCodeAt(i) + ((hash << 5) - hash)
  }
  // 避免纯红色：hue 取 20~339
  const hue = (Math.abs(hash) % 320) + 20
  return hslToHex(hue, 72, 45)
}

const randomDownloaderColor = () => {
  if (Math.random() < 0.35) {
    return predefinedDownloaderColors[Math.floor(Math.random() * predefinedDownloaderColors.length)]
  }
  const hue = Math.floor(Math.random() * 320) + 20
  return hslToHex(hue, 72, 45)
}

const downloaderNameTagStyle = (
  downloader: { color?: string | null } | null | undefined,
): Record<string, string> => {
  const color = String(downloader?.color || '').trim()
  if (!color) return {}
  return {
    '--el-tag-bg-color': color,
    '--el-tag-border-color': color,
    '--el-tag-text-color': '#ffffff',
  }
}

// 路径映射相关状态
const pathMappingDialogVisible = ref(false)
const currentDownloader = ref<DownloaderConfig | null>(null)
const currentPathMappings = ref<PathMapping[]>([])

onMounted(() => {
  fetchSettings()
})

const fetchSettings = async () => {
  isLoading.value = true
  try {
    const response = await axios.get<Record<string, unknown>>(`${API_BASE_URL}/settings`)
    const raw = isRecord(response.data) ? response.data : {}
    const rawDownloaders = Array.isArray(raw.downloaders) ? raw.downloaders : []

    const downloaders = rawDownloaders.map((item) => {
      const record = isRecord(item) ? item : {}
      const id = String(record.id || `client_${Date.now()}_${Math.random()}`)
      const pathMappings = Array.isArray(record.path_mappings)
        ? record.path_mappings
            .map((mapping) => {
              if (!isRecord(mapping)) return null
              return {
                remote: typeof mapping.remote === 'string' ? mapping.remote : '',
                local: typeof mapping.local === 'string' ? mapping.local : '',
              }
            })
            .filter((mapping): mapping is PathMapping => Boolean(mapping))
        : []

      return {
        ...record,
        id,
        enabled: typeof record.enabled === 'boolean' ? record.enabled : true,
        name: typeof record.name === 'string' ? record.name : '新下载器',
        type: typeof record.type === 'string' ? record.type : 'qbittorrent',
        host: typeof record.host === 'string' ? record.host : '',
        username: typeof record.username === 'string' ? record.username : '',
        password: typeof record.password === 'string' ? record.password : '',
        use_proxy: typeof record.use_proxy === 'boolean' ? record.use_proxy : false,
        proxy_port:
          typeof record.proxy_port === 'number' ? record.proxy_port : Number(record.proxy_port) || 9090,
        color: typeof record.color === 'string' && record.color.trim() ? record.color : deriveDownloaderColor(id),
        path_mappings: pathMappings,
        enable_ratio_limiter:
          typeof record.enable_ratio_limiter === 'boolean' ? record.enable_ratio_limiter : false,
        publish_interval_minutes:
          typeof record.publish_interval_minutes === 'number'
            ? record.publish_interval_minutes
            : Number(record.publish_interval_minutes) || 0,
        publish_concurrency:
          typeof record.publish_concurrency === 'number'
            ? record.publish_concurrency
            : Number(record.publish_concurrency) || 1,
      } satisfies DownloaderConfig
    })

    settings.value = {
      ...raw,
      downloaders,
      realtime_speed_enabled:
        typeof raw.realtime_speed_enabled === 'boolean' ? raw.realtime_speed_enabled : false,
      torrent_refresh_enabled:
        typeof raw.torrent_refresh_enabled === 'boolean' ? raw.torrent_refresh_enabled : true,
      torrent_refresh_interval_minutes:
        typeof raw.torrent_refresh_interval_minutes === 'number' &&
        raw.torrent_refresh_interval_minutes > 0
          ? raw.torrent_refresh_interval_minutes
          : 30,
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
    // 关键：删除/停用下载器后，TorrentsView 的下载器筛选列表使用缓存，
    // 不强制刷新会导致“已删除下载器仍可筛选”的错觉。
    await torrentsViewState.fetchDownloadersList(true)
    fetchSettings()
  } catch (error) {
    ElMessage.error('保存设置失败！')
    console.error(error)
  } finally {
    isSaving.value = false
  }
}

const addDownloader = () => {
  const id = `new_${Date.now()}`
  settings.value.downloaders.push({
    id,
    enabled: true,
    name: '新下载器',
    type: 'qbittorrent',
    host: '',
    username: '',
    password: '',
    use_proxy: false,
    proxy_port: 9090,
    color: deriveDownloaderColor(id),
    path_mappings: [], // 初始化空的路径映射数组
    enable_ratio_limiter: false, // 默认关闭出种限速
    publish_interval_minutes: 0,
    publish_concurrency: 1,
  })
}

const confirmDeleteDownloader = (downloaderId: string) => {
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

const deleteDownloader = (downloaderId: string) => {
  settings.value.downloaders = settings.value.downloaders.filter((d) => d.id !== downloaderId)
}

const resetConnectionStatus = (downloaderId: string) => {
  if (connectionTestResults.value[downloaderId]) {
    delete connectionTestResults.value[downloaderId]
  }
}

const testConnection = async (downloader: DownloaderConfig) => {
  resetConnectionStatus(downloader.id)
  testingConnectionId.value = downloader.id
  try {
    const response = await axios.post(`${API_BASE_URL}/test_connection`, downloader)
    const result = response.data as { success?: boolean; message?: string }
    if (result.success) {
      ElMessage.success(result.message || '连接成功')
      connectionTestResults.value[downloader.id] = 'success'
    } else {
      ElMessage.error(result.message || '连接失败')
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
const openPathMappingDialog = (downloader: DownloaderConfig) => {
  currentDownloader.value = downloader
  // 初始化路径映射数据，如果不存在则创建空数组
  if (!downloader.path_mappings || !Array.isArray(downloader.path_mappings)) {
    downloader.path_mappings = []
  }
  // 拷贝映射数据，避免直接修改
  currentPathMappings.value = downloader.path_mappings.map((mapping) => ({
    remote: mapping.remote,
    local: mapping.local,
  }))
  pathMappingDialogVisible.value = true
}

const addPathMapping = () => {
  currentPathMappings.value.push({
    remote: '',
    local: '',
  })
}

const deletePathMapping = (index: number) => {
  currentPathMappings.value.splice(index, 1)
}

const savePathMappings = async () => {
  // 过滤掉空的映射规则
  const validMappings = currentPathMappings.value.filter(
    (mapping) => mapping.remote.trim() !== '' && mapping.local.trim() !== '',
  )
  // 更新当前下载器的路径映射
  if (!currentDownloader.value) {
    ElMessage.error('未选择要保存的下载器')
    return
  }
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

/* 自定义滚动条样式 */
.settings-view::-webkit-scrollbar {
  width: 8px;
}

.settings-view::-webkit-scrollbar-track {
  background: transparent;
  border-radius: 4px;
}

.settings-view::-webkit-scrollbar-thumb {
  background: rgba(144, 147, 153, 0.3);
  border-radius: 4px;
  transition: background 0.3s ease;
}

.settings-view::-webkit-scrollbar-thumb:hover {
  background: rgba(144, 147, 153, 0.5);
}

.downloader-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
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
  gap: 12px;
}

.header-controls {
  display: flex;
  align-items: center;
}

.downloader-name-tag {
  font-weight: 600;
  border-radius: 8px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.downloader-color-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 8px;
}

.downloader-color-trigger {
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 6px;
  border: 1px solid var(--el-border-color-light);
  cursor: pointer;
  outline: none;
}

.downloader-color-trigger:hover {
  border-color: var(--el-border-color);
}

.downloader-color-trigger:focus-visible {
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.25);
}

.downloader-color-popover :deep(.el-color-picker-panel__footer) {
  align-items: center;
}

.downloader-color-random-btn {
  margin-left: 8px;
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
  min-height: 32px;
}

.proxy-port-input {
  flex: 1;
}

.proxy-port-input :deep(.el-input__wrapper) {
  height: 32px;
}

.proxy-port-input :deep(input[type="number"]) {
  -moz-appearance: textfield;
}

.proxy-port-input :deep(input[type="number"]::-webkit-inner-spin-button),
.proxy-port-input :deep(input[type="number"]::-webkit-outer-spin-button) {
  -webkit-appearance: none;
  margin: 0;
}

.proxy-port-input :deep(.el-input-group__append) {
  padding: 0 5px;
}

.proxy-port-input :deep(.el-input-group__prepend) {
  padding: 0 5px;
}

.input-append-wrapper {
  display: flex;
  align-items: center;
  padding: 0 2px !important;
  height: 100%;
}

.input-append-wrapper :deep(.el-switch) {
  margin: 0;
}

.input-append-wrapper :deep(.el-switch__core) {
  min-width: 36px;
  height: 20px;
}

.input-append-wrapper :deep(.el-switch__label) {
  font-size: 11px;
  padding: 0 2px;
}

.ratio-limiter-label {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 32px;
}

.ratio-limiter-text {
  color: #606266;
  white-space: nowrap;
}

.publish-controls-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.publish-control {
  width: 120px;
}

.publish-control-unit {
  color: #606266;
  white-space: nowrap;
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

@media (max-width: 1024px) {
  .top-actions {
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 10px;
  }

  .downloader-grid {
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
  }

  .card-header {
    align-items: flex-start;
    gap: 8px;
  }

  .header-controls {
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
  }
}

@media (max-width: 768px) {
  .top-actions {
    padding: 12px;
    position: static;
  }

  .settings-view {
    padding: 12px;
  }

  .downloader-grid {
    grid-template-columns: 1fr;
  }

  .name-and-client-row,
  .proxy-settings-row,
  .publish-controls-row,
  .mapping-item {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }

  .ratio-limiter-label {
    justify-content: flex-start;
  }

  .header-controls {
    width: 100%;
    justify-content: flex-start;
  }

  .switch-form-item {
    margin-left: 0;
  }
}
</style>
