<template>
  <!-- Update Dialog -->
  <el-dialog
    v-model="updateDialogVisible"
    title="PT Nexus 版本更新"
    width="800px"
    :close-on-click-modal="!isForceUpdate"
    :close-on-press-escape="!isForceUpdate"
    :show-close="!isForceUpdate"
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

        <!-- 强制更新提示 -->
        <div
          v-if="isForceUpdate && !updateInfo.updateControl.disable_update"
          class="force-update-notice"
          style="color: #f56c6c; background: #fef0f0; border-color: #fde2e2"
        >
          <el-icon color="#f56c6c" size="18"><WarningFilled /></el-icon>
          <span>检测到关键更新，系统将自动执行升级流程，请勿关闭页面。</span>
        </div>

        <div
          v-else-if="updateInfo.updateControl.disable_update && updateInfo.hasUpdate"
          class="force-update-notice"
        >
          <el-icon color="#e6a23c" size="18"><WarningFilled /></el-icon>
          <span>此版本需要更新Docker镜像，请手动更新镜像后使用</span>
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
                @click="handleNoteClick"
                v-html="formatNote(version.note)"
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
          <!-- 修复：如果是强制更新且没被禁用，才隐藏取消按钮 -->
          <el-button
            v-if="!isForceUpdate || updateInfo.updateControl.disable_update"
            @click="updateDialogVisible = false"
            :disabled="isUpdating"
          >
            {{ updateInfo.hasUpdate ? '稍后更新' : '确定' }}
          </el-button>

          <!-- 修复核心：强制更新时总是显示按钮，disable_update 时禁用 -->
          <el-button
            v-if="updateInfo.hasUpdate || isForceUpdate"
            type="primary"
            @click="performUpdate"
            :loading="isUpdating"
            :disabled="isUpdating || updateInfo.updateControl.disable_update"
            :title="
              updateInfo.updateControl.disable_update
                ? '当前版本需要更新镜像，请手动更新Docker镜像'
                : ''
            "
          >
            {{ isUpdating ? '更新中...' : '立即更新' }}
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { SuccessFilled, WarningFilled } from '@element-plus/icons-vue'
import axios from 'axios'

// 更新状态
const isUpdating = ref(false)
const updateProgress = ref(0)
const updateStatus = ref('')

const emit = defineEmits<{
  'version-loaded': [version: string]
}>()

const currentVersion = ref('加载中...')
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
  updateControl: {
    force_update: false,
    disable_update: false,
    schedule: {
      enabled: false,
      timezone: 'Asia/Shanghai',
      time: '06:00',
      last_run: null,
    },
  },
})

// 计算属性：判断是否为强制更新
const isForceUpdate = computed(() => {
  return updateInfo.updateControl.force_update
})

const compareVersions = (v1: string, v2: string): number => {
  if (!v1 || !v2) return 0
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

/**
 * 格式化注意信息
 */
const formatNote = (note: string) => {
  if (!note) return ''
  
  let html = note.replace(/\n/g, '<br>')
  
  // 匹配 curl 命令
  const cmdRegex = /(curl -sL https:\/\/github\.com\/sqing33\/Docker\.pt-nexus.*?\| sudo bash)/g
  
  // 修改结构：使用 div 布局，添加提示文本
  html = html.replace(cmdRegex, (match) => {
    return `<div class="cmd-copy-wrapper" title="点击复制整段命令" data-cmd="${match}">
              <div class="cmd-header">
                <span class="cmd-icon">➜</span>
                <span class="cmd-hint">点击复制</span>
              </div>
              <div class="cmd-code">${match}</div>
            </div>`
  })
  
  return html
}

/**
 * 处理 Note 区域的点击事件（事件委托）
 */
const handleNoteClick = async (e: MouseEvent) => {
  const target = e.target as HTMLElement
  // 查找最近的带有 cmd-copy-wrapper 类的祖先元素
  const cmdBlock = target.closest('.cmd-copy-wrapper')
  
  if (cmdBlock) {
    const cmd = cmdBlock.getAttribute('data-cmd')
    if (cmd) {
      try {
        await navigator.clipboard.writeText(cmd)
        ElMessage.success({
          message: '命令已复制到剪贴板',
          duration: 2000
        })
      } catch (err) {
        console.error('复制失败:', err)
        ElMessage.error('复制失败，请手动复制')
      }
    }
  }
}

const loadVersionInfo = async () => {
  try {
    const timestamp = new Date().getTime()
    const response = await axios.get(`/update/check?t=${timestamp}`)
    const data = response.data

    if (data.success) {
      currentVersion.value = data.local_version
      emit('version-loaded', currentVersion.value)

      // 计算版本差异
      // compareResult > 0 : 远程 > 本地 (有更新)
      // compareResult < 0 : 远程 < 本地 (本地是开发版或更新版)
      const compareResult = compareVersions(data.remote_version || '', data.local_version)
      const isReallyHasUpdate = compareResult > 0
      const isLocalNewer = compareResult < 0 

      console.log('版本检查结果:', {
        local: data.local_version,
        remote: data.remote_version,
        hasUpdate: isReallyHasUpdate,
        isLocalNewer: isLocalNewer, // 调试看是否识别为本地更新
        forceUpdate: data.update_control?.force_update
      })

      // 核心修复：
      // 只有在 (有真实更新 OR (强制更新 AND 本地不比远程新)) 时才弹窗
      // 这样就屏蔽了 3.3.4 (Local) > 3.3.3 (Remote) 但带有 force_update 标志的情况
      const shouldShowDialog = isReallyHasUpdate || 
        ((data.update_control?.force_update) && !isLocalNewer)

      if (shouldShowDialog) {
        await showUpdateDialog(data)

        if (
          data.update_control &&
          data.update_control.force_update &&
          !data.update_control.disable_update &&
          !isLocalNewer // 再次确保本地较新时不自动更新
        ) {
          console.log('检测到强制更新，自动触发更新流程...')
          nextTick(() => {
            performUpdate()
          })
        }
      }
    }
  } catch (error) {
    console.error('加载版本信息失败:', error)
    currentVersion.value = 'unknown'
    emit('version-loaded', currentVersion.value)
  }
}

// 修改：接收可选的 preLoadedData
const showUpdateDialog = async (preLoadedData: any = null) => {
  try {
    const timestamp = new Date().getTime()
    const changelogPromise = axios.get(`/update/changelog?t=${timestamp}`)

    let versionData = preLoadedData
    if (!versionData) {
      const versionResponse = await axios.get(`/update/check?t=${timestamp}`)
      versionData = versionResponse.data
    }

    const changelogResponse = await changelogPromise
    const changelogData = changelogResponse.data

    const compareResult = compareVersions(versionData.remote_version, currentVersion.value)
    // 如果 compareResult < 0，说明本地版本比远程新
    const isLocalNewer = compareResult < 0 

    updateInfo.hasUpdate = compareResult > 0
    updateInfo.currentVersion = currentVersion.value
    updateInfo.remoteVersion = versionData.remote_version
    updateInfo.changelog = changelogData.changelog || []
    updateInfo.history = changelogData.history || []

    updateInfo.updateControl = {
      // 修复：如果本地版本比远程新，强行关闭 force_update 标志，防止UI显示错误
      force_update: isLocalNewer ? false : (versionData.update_control?.force_update || false),
      disable_update: versionData.update_control?.disable_update || false,
      schedule: versionData.update_control?.schedule || {
        enabled: false,
        timezone: 'Asia/Shanghai',
        time: '06:00',
        last_run: null,
      },
    }

    activeUpdateTab.value = 'latest'
    
    // 如果是手动点击检查更新(versionData为空进来)，且本地比远程新，可以弹窗提示"已是最新"
    // 但如果是自动检查(loadVersionInfo)，上面的逻辑已经拦截了
    updateDialogVisible.value = true
  } catch (error) {
    console.error('检查更新失败:', error)
    ElMessage.error('检查更新失败，请稍后重试')
  }
}

// 实际执行更新的逻辑 (发送请求)
const performUpdate = async () => {
  // 防卫：如果已经禁止更新，直接返回
  if (updateInfo.updateControl.disable_update) {
    ElMessage.warning('当前版本需要更新Docker镜像，不支持在线热更新')
    return
  }

  try {
    isUpdating.value = true
    updateProgress.value = 0
    updateStatus.value = '准备更新'

    // 阶段1: 拉取
    updateStatus.value = '正在连接远程仓库'
    updateProgress.value = -1

    // 调用后端接口执行真正的更新
    const pullResponse = await axios.post('/update/pull')
    if (!pullResponse.data.success) {
      ElMessage.error('拉取更新失败: ' + pullResponse.data.error)
      isUpdating.value = false
      updateProgress.value = 0
      return
    }

    updateProgress.value = 50
    updateStatus.value = '代码拉取成功'
    await new Promise((resolve) => setTimeout(resolve, 500))

    // 阶段2: 安装
    updateStatus.value = '正在安装更新'
    updateProgress.value = 60

    const installResponse = await axios.post('/update/install')
    if (installResponse.data.success) {
      updateProgress.value = 90
      updateStatus.value = '安装完成，服务正在重启...'
      await new Promise((resolve) => setTimeout(resolve, 300))

      updateProgress.value = 100
      updateStatus.value = '更新成功'
      ElMessage.success('更新成功！页面将在5秒后刷新...')

      setTimeout(() => {
        // 如果不是强制更新，可以让用户自己点，或者自动关闭
        // 强制更新一般自动刷新
        updateDialogVisible.value = false
        window.location.reload()
      }, 5000)
    } else {
      ElMessage.error('安装更新失败: ' + installResponse.data.error)
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

const show = () => {
  showUpdateDialog()
}

const getCurrentVersion = () => {
  return currentVersion.value
}

defineExpose({
  show,
  getCurrentVersion,
})

onMounted(() => {
  loadVersionInfo()
})
</script>

<style scoped>
/* 原有样式保持不变 */
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

.force-update-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 6px;
  color: #e6a23c;
  font-size: 14px;
  font-weight: 500;
  margin-top: 12px;
  margin-bottom: 12px;
}

.all-versions-section {
  height: 400px;
  overflow-y: auto;
  overflow-x: hidden;
  width: 100%;
  margin: 0 20px;
}

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

.version-changes {
  padding-left: 20px;
}

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

:deep(.el-card__body) {
  padding: 20px 0;
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
  width: 100%;
}

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

.button-group {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
  margin-left: auto;
}

:deep(.el-progress-bar__outer) {
  background-color: #f0f2f5;
}

:deep(.el-progress-bar__inner) {
  transition: width 0.3s ease;
}

:deep(.el-button.is-loading::before) {
  display: none !important;
}

/* 1. 外层容器：改为块级元素，增加上间距，改为亮色背景 */
.version-note :deep(.cmd-copy-wrapper) {
  display: block;                  /* 独占一行 */
  margin-top: 10px;               /* 与上方文字拉开距离 */
  background: #ffffff;            /* 纯白背景，在黄色的 note 中很清晰 */
  border: 1px solid #e4e7ed;      /* 浅灰边框 */
  border-left: 4px solid #409eff; /* 左侧蓝色竖条，增加设计感 */
  border-radius: 4px;
  padding: 10px 15px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

/* 2. 鼠标悬停效果 */
.version-note :deep(.cmd-copy-wrapper:hover) {
  background: #f5f7fa;            /* 悬停微灰 */
  border-color: #c0c4cc;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05); /* 轻微浮起阴影 */
  transform: translateY(-1px);
}

/* 3. 点击时的按压效果 */
.version-note :deep(.cmd-copy-wrapper:active) {
  transform: translateY(0);
  background: #eef1f6;
}

/* 4. 顶部栏（图标 + 提示语） */
.version-note :deep(.cmd-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  font-size: 12px;
  color: #909399;
}

.version-note :deep(.cmd-icon) {
  color: #409eff;
  font-weight: bold;
}

.version-note :deep(.cmd-hint) {
  font-size: 12px;
  color: #409eff;
  background: #ecf5ff;
  padding: 2px 8px;
  border-radius: 10px;
}

/* 5. 核心代码区域：允许换行，等宽字体 */
.version-note :deep(.cmd-code) {
  font-family: Consolas, Monaco, 'Courier New', monospace;
  font-size: 13px;
  color: #303133;           /* 深灰字体，清晰易读 */
  line-height: 1.6;         /* 增加行高 */
  word-break: break-all;    /* 核心：强制换行，防止溢出 */
  white-space: pre-wrap;    /* 保留空格但允许换行 */
}
</style>
