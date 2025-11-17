<template>
  <!-- Update Dialog -->
  <el-dialog
    v-model="updateDialogVisible"
    title="版本更新"
    width="800px"
    :close-on-click-modal="false"
    class="update-dialog"
  >
    <el-card shadow="never" class="update-card">
      <div class="update-content">
        <!-- Version Info -->
        <div class="version-info-box">
          <div class="version-item">
            <div class="version-label">当前版本</div>
            <div class="version-value">{{ updateInfo.currentVersion }}</div>
          </div>
          <div v-if="updateInfo.hasUpdate" class="version-arrow">→</div>
          <div v-if="updateInfo.hasUpdate" class="version-item">
            <div class="version-label">最新版本</div>
            <div class="version-value new-version">{{ updateInfo.remoteVersion }}</div>
          </div>
          <div v-if="!updateInfo.hasUpdate" class="version-status">
            <el-icon color="#67c23a" size="20"><SuccessFilled /></el-icon>
            <span>已是最新版本</span>
          </div>
        </div>

        <!-- All Versions Timeline -->
        <div class="all-versions-section">
          <div v-if="updateInfo.history.length === 0" class="no-history">暂无版本记录</div>
          <div v-else class="history-timeline">
            <div
              v-for="(version, versionIndex) in updateInfo.history"
              :key="versionIndex"
              class="history-version"
              :class="{
                'latest-version': compareVersions(version.version, updateInfo.currentVersion) > 0,
              }"
            >
              <div class="version-header">
                <div class="version-title">
                  <span class="version-name">{{ version.version }}</span>
                  <span class="version-date"
                    >{{ version.date
                    }}{{
                      compareVersions(version.version, updateInfo.currentVersion) > 0 ? ' 新' : ''
                    }}</span
                  >
                </div>
              </div>
              <div
                v-if="version.note"
                class="version-note"
                v-html="version.note.replace(/\n/g, '<br>')"
              ></div>
              <div class="version-changes">
                <div
                  v-for="(change, changeIndex) in version.changes"
                  :key="changeIndex"
                  class="changelog-item"
                >
                  <div class="changelog-number">{{ changeIndex + 1 }}</div>
                  <div class="changelog-text" v-html="change.replace(/\n/g, '<br>')"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <template #footer>
      <div class="dialog-footer">
        <!-- 进度条容器 -->
        <div v-if="isUpdating" class="progress-container">
          <el-progress
            :percentage="updateProgress < 0 ? 0 : updateProgress"
            :status="updateProgress === 100 ? 'success' : undefined"
            :stroke-width="8"
            :show-text="false"
            :indeterminate="updateProgress < 0"
          />
          <span class="progress-text">
            {{ updateStatus }}
            <span v-if="updateProgress >= 0"> {{ updateProgress }}%</span>
          </span>
        </div>

        <!-- 按钮组 -->
        <div class="button-group">
          <el-button @click="updateDialogVisible = false" :disabled="isUpdating">
            {{ updateInfo.hasUpdate ? '稍后更新' : '确定' }}
          </el-button>
          <el-button
            v-if="updateInfo.hasUpdate"
            type="primary"
            @click="performUpdate"
            :loading="isUpdating"
            :disabled="isUpdating"
          >
            {{ isUpdating ? '更新中...' : '立即更新' }}
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { SuccessFilled } from '@element-plus/icons-vue'
import axios from 'axios'

// 更新状态
const isUpdating = ref(false)
const updateProgress = ref(0)
const updateStatus = ref('')

// 输出版本信息和显示对话框事件
const emit = defineEmits<{
  'version-loaded': [version: string]
}>()

// 版本信息
const currentVersion = ref('加载中...')

// 更新对话框状态
const updateDialogVisible = ref(false)
const activeUpdateTab = ref('latest')
const updateInfo = reactive({
  hasUpdate: false,
  currentVersion: '',
  remoteVersion: '',
  changelog: [] as string[],
  history: [] as Array<{
    version: string
    date: string
    changes: string[]
    note?: string
  }>,
})

// 版本比较函数
const compareVersions = (v1: string, v2: string): number => {
  const v1parts = v1.split('.').map(Number)
  const v2parts = v2.split('.').map(Number)

  for (let i = 0; i < Math.max(v1parts.length, v2parts.length); i++) {
    const a = v1parts[i] || 0
    const b = v2parts[i] || 0
    if (a > b) return 1
    if (a < b) return -1
  }
  return 0
}

// 加载版本信息并自动检测更新
const loadVersionInfo = async () => {
  try {
    const response = await axios.get('/update/check')
    const data = response.data
    if (data.success) {
      currentVersion.value = data.local_version
      emit('version-loaded', currentVersion.value)

      // 只有当远程版本高于本地版本时才提示更新
      const isReallyHasUpdate = compareVersions(data.remote_version || '', data.local_version) > 0
      if (isReallyHasUpdate) {
        setTimeout(() => {
          showUpdateDialog()
        }, 1000)
      }
    }
  } catch (error) {
    console.error('加载版本信息失败:', error)
    currentVersion.value = 'unknown'
    emit('version-loaded', currentVersion.value)
  }
}

// 显示更新对话框
const showUpdateDialog = async () => {
  try {
    const [changelogResponse, versionResponse] = await Promise.all([
      axios.get('/update/changelog'),
      axios.get('/update/check'),
    ])

    const changelogData = changelogResponse.data
    const versionData = versionResponse.data

    updateInfo.hasUpdate = compareVersions(versionData.remote_version, currentVersion.value) > 0
    updateInfo.currentVersion = currentVersion.value
    updateInfo.remoteVersion = versionData.remote_version
    updateInfo.changelog = changelogData.changelog || []
    updateInfo.history = changelogData.history || []

    // 重置为最新版本标签
    activeUpdateTab.value = 'latest'

    updateDialogVisible.value = true
  } catch (error) {
    console.error('检查更新失败:', error)
    ElMessage.error('检查更新失败，请稍后重试')
  }
}

// 执行更新
const performUpdate = async () => {
  try {
    // 初始化更新状态
    isUpdating.value = true
    updateProgress.value = 0
    updateStatus.value = '准备更新'

    // 阶段1: 拉取更新 (0-50%)
    // 使用不确定进度模式,因为 git 拉取时间不可预测
    updateStatus.value = '正在连接远程仓库'
    updateProgress.value = -1 // -1 表示不确定进度(显示动画)

    const pullResponse = await axios.post('/update/pull')
    const pullData = pullResponse.data

    if (!pullData.success) {
      ElMessage.error('拉取更新失败: ' + pullData.error)
      isUpdating.value = false
      updateProgress.value = 0
      return
    }

    updateProgress.value = 50
    updateStatus.value = '代码拉取成功'
    await new Promise((resolve) => setTimeout(resolve, 500))

    // 阶段2: 安装更新 (50-90%)
    updateStatus.value = '正在安装更新'
    updateProgress.value = 60

    const installResponse = await axios.post('/update/install')
    const installData = installResponse.data

    if (installData.success) {
      updateProgress.value = 90
      updateStatus.value = '安装完成'
      await new Promise((resolve) => setTimeout(resolve, 300))

      // 阶段3: 完成 (90-100%)
      updateProgress.value = 100
      updateStatus.value = '更新成功'

      ElMessage.success('更新成功！页面将在5秒后刷新...')

      setTimeout(() => {
        updateDialogVisible.value = false
        window.location.reload()
      }, 5000)
    } else {
      ElMessage.error('安装更新失败: ' + installData.error)
      isUpdating.value = false
      updateProgress.value = 0
    }
  } catch (error) {
    console.error('更新失败:', error)
    ElMessage.error('更新失败，请稍后重试')
    isUpdating.value = false
    updateProgress.value = 0
    updateStatus.value = ''
  }
}

// 暴露方法给父组件
const show = () => {
  showUpdateDialog()
}

// 暴露版本号给父组件
const getCurrentVersion = () => {
  return currentVersion.value
}

// 暴露方法给父组件
defineExpose({
  show,
  getCurrentVersion,
})

// 初始化时加载版本信息
onMounted(() => {
  loadVersionInfo()
})
</script>

<style scoped>
/* Update Dialog Styles */
.update-card {
  border: none;
}

.update-content {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.version-info-box {
  display: inline-flex;
  align-items: center;
  gap: 15px;
  padding: 12px 20px;
  background: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #e0e0e0;
  margin-bottom: 12px;
}

.version-item {
  text-align: center;
}

.version-label {
  font-size: 13px;
  color: #666;
  margin-bottom: 6px;
}

.version-value {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.version-value.new-version {
  color: #67c23a;
}

.version-arrow {
  font-size: 20px;
  color: #999;
}

.version-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #67c23a;
  font-weight: 500;
}

.changelog-section {
  width: 100%;
  max-width: 600px;
}

.changelog-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 15px;
  text-align: center;
}

.changelog-list {
  max-height: 300px;
  overflow-y: auto;
}

.no-changelog {
  text-align: center;
  padding: 20px;
  color: #909399;
}

.changelog-item {
  display: flex;
  align-items: flex-start;
  padding: 12px 15px;
  margin-bottom: 10px;
  background: #fafafa;
  border-radius: 6px;
  border: 1px solid #e8e8e8;
}

.changelog-number {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  background: #409eff;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 12px;
  margin-right: 12px;
}

.changelog-text {
  flex: 1;
  line-height: 24px;
  font-size: 14px;
  color: #303133;
}

/* Update Tabs Styles */
.update-tabs {
  width: 100%;
}

.update-tabs :deep(.el-tabs__content) {
  padding: 0;
}

.update-tabs :deep(.el-tab-pane) {
  padding: 0;
}

/* History Section Styles */
.history-section {
  height: 500px;
  overflow-y: auto;
  width: 100%;
}

.no-history {
  text-align: center;
  padding: 40px 20px;
  color: #909399;
  font-size: 16px;
}

.history-timeline {
  width: 100%;
}

.history-version {
  margin-bottom: 30px;
  position: relative;
  margin: 0 10px;
}

.history-version:not(.latest-version) {
  margin: 0 33px;
}

.history-version:last-child {
  margin-bottom: 0;
}

/* 版本标题区域 */
.version-header {
  margin-bottom: 15px;
  padding-left: 12px;
  position: relative;
}

.version-header::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  background: linear-gradient(to bottom, #c79081 0%, #dfa579 100%);
  border-radius: 2px;
}

.version-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.version-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  background: linear-gradient(0deg, #c79081 0%, #dfa579 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.version-date {
  font-size: 13px;
  color: #909399;
  background: #f5f7fa;
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
}

/* 版本变更内容区域 */
.version-changes {
  padding-left: 20px;
}

/* 特殊note样式 */
.version-note {
  background: #fff3cd;
  border: 1px solid #ffeaa7;
  color: #856404;
  padding: 12px;
  border-radius: 6px;
  margin-bottom: 15px;
  font-size: 13px;
  font-weight: 500;
}

.version-note::before {
  content: '📢 ';
  margin-right: 4px;
}

/* All Versions Section */
.all-versions-section {
  height: 400px;
  overflow-y: auto;
  overflow-x: hidden;
  width: 100%;
  margin: 0 20px;
}

/* 自定义滚动条样式 */
.all-versions-section::-webkit-scrollbar {
  width: 6px;
}

.all-versions-section::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.all-versions-section::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.all-versions-section::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

.no-history {
  text-align: center;
  padding: 40px 20px;
  color: #909399;
  font-size: 16px;
}

/* Latest Version Highlight */
.latest-version {
  position: relative;
  border-radius: 12px;
  padding: 10px 20px;
  margin-bottom: 15px;
  background: linear-gradient(-20deg, #e9defa 0%, #fbfcdb 100%);
}

.latest-version .version-header {
  margin-bottom: 15px;
  padding-left: 12px;
  position: relative;
}

.latest-version .version-header::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 4px;
  background: linear-gradient(120deg, #ad67ee 0%, #50a6fd 100%);
  border-radius: 2px;
  box-shadow: 0 0 10px rgba(64, 158, 255, 0.5);
}

.latest-version .version-name {
  font-weight: 700;
  background: linear-gradient(120deg, #ad67ee 0%, #50a6fd 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-shadow: 0 2px 4px rgba(64, 158, 255, 0.3);
}

.latest-version .version-date {
  background: linear-gradient(120deg, #e0c3fc 0%, #8ec5fc 100%);
  color: white;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
}

:deep(.el-card__body) {
  padding: 20px 0;
}

/* 对话框底部样式 */
.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
  width: 100%;
}

/* 进度条容器 */
.progress-container {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.progress-container :deep(.el-progress) {
  flex: 1;
  min-width: 0;
}

.progress-text {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
  white-space: nowrap;
  min-width: 120px;
}

/* 按钮组 */
.button-group {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
  margin-left: auto;
}

/* 进度条样式 */
:deep(.el-progress-bar__outer) {
  background-color: #f0f2f5;
}

:deep(.el-progress-bar__inner) {
  transition: width 0.3s ease;
}

/* 移除按钮默认的加载动画边框 */
:deep(.el-button.is-loading::before) {
  display: none !important;
}
</style>
