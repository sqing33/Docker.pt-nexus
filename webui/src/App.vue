<!-- src/App.vue -->
<template>
  <el-menu
    v-if="!isLoginPage"
    :default-active="activeRoute"
    class="main-nav glass-nav"
    mode="horizontal"
    router
  >
    <div style="padding: 5px 15px; line-height: 32px">
      <img
        src="/favicon.ico"
        alt="Logo"
        height="32"
        style="margin-right: 8px; vertical-align: middle"
      />
      PT Nexus
    </div>
    <el-menu-item index="/">首页</el-menu-item>
    <el-menu-item index="/info">流量统计</el-menu-item>
    <el-menu-item index="/torrents">一种多站</el-menu-item>
    <el-menu-item index="/data">一站多种</el-menu-item>
    <el-menu-item index="/sites">做种检索</el-menu-item>
    <el-menu-item index="/settings">设置</el-menu-item>
    <div class="page-hint-container">
      <span v-if="activeRoute === '/torrents'" class="page-hint">
        <span class="hint-green">做种且可跳转种子详情页</span> -
        <span class="hint-blue">做种但无详情页</span> - <span class="hint-red">可铺种但未做种</span>
      </span>
      <span v-else-if="activeRoute === '/data'" class="page-hint">
        <span class="hint-red">种子有误/不存在/禁转</span> -
        <span class="hint-yellow">待检查信息的种子</span>
      </span>
    </div>
    <div class="right-buttons-container">
      <el-link
        href="https://github.com/sqing33/Docker.pt-nexus"
        target="_blank"
        :underline="false"
        style="margin-right: 8px"
      >
        <el-icon><Link /></el-icon>
        GitHub
      </el-link>
      <el-tag size="small" style="cursor: pointer; margin-right: 15px" @click="showUpdateDialog">{{
        currentVersion
      }}</el-tag>
      <el-button type="primary" @click="feedbackDialogVisible = true" plain>反馈</el-button>
      <el-button
        type="success"
        @click="handleGlobalRefresh"
        :loading="isRefreshing"
        :disabled="isRefreshing"
        plain
      >
        刷新
      </el-button>
    </div>
  </el-menu>
  <main :class="['main-content', isLoginPage ? 'no-nav' : '']">
    <router-view v-slot="{ Component }">
      <component :is="Component" @ready="handleComponentReady" />
    </router-view>
  </main>

  <el-dialog
    v-model="feedbackDialogVisible"
    title="意见反馈"
    width="700px"
    @close="resetFeedbackForm"
  >
    <el-form :model="feedbackForm" label-position="top">
      <el-form-item label="反馈内容（支持富文本编辑，可直接粘贴图片）">
        <div class="editor-wrapper">
          <QuillEditor
            ref="quillEditor"
            v-model:content="feedbackForm.html"
            contentType="html"
            theme="snow"
            :options="editorOptions"
            @paste="handlePaste"
          />
        </div>
      </el-form-item>
      <el-form-item label="联系方式 (可选)" style="margin-top: 50px">
        <el-input v-model="feedbackForm.contact" placeholder="如 QQ, Telegram, Email 等" />
      </el-form-item>
    </el-form>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="feedbackDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitFeedback" :loading="isSubmittingFeedback">
          提交
        </el-button>
      </span>
    </template>
  </el-dialog>

  <!-- Update Dialog -->
  <el-dialog
    v-model="updateDialogVisible"
    title="版本更新"
    width="650px"
    :close-on-click-modal="false"
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

        <!-- Changelog -->
        <div class="changelog-section">
          <div class="changelog-title">更新内容</div>
          <div class="changelog-list">
            <div v-if="updateInfo.changelog.length === 0" class="no-changelog">暂无更新内容</div>
            <div v-for="(item, index) in updateInfo.changelog" :key="index" class="changelog-item">
              <div class="changelog-number">{{ index + 1 }}</div>
              <div class="changelog-text">{{ item }}</div>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <template #footer>
      <span class="dialog-footer">
        <el-button @click="updateDialogVisible = false">
          {{ updateInfo.hasUpdate ? '稍后更新' : '确定' }}
        </el-button>
        <el-button v-if="updateInfo.hasUpdate" type="primary" @click="performUpdate">
          立即更新
        </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Link, SuccessFilled } from '@element-plus/icons-vue'
import { QuillEditor } from '@vueup/vue-quill'
import '@vueup/vue-quill/dist/vue-quill.snow.css'
import axios from 'axios'

const route = useRoute()

// 背景图片
const backgroundUrl = ref('https://pic.pting.club/i/2025/10/07/68e4fbfe9be93.jpg')

// 版本信息
const currentVersion = ref('加载中...')

const isLoginPage = computed(() => route.path === '/login')

const activeRoute = computed(() => {
  if (route.matched.length > 0) {
    return route.matched[0].path
  }
  return route.path
})

const isRefreshing = ref(false)

// Feedback Dialog State
const feedbackDialogVisible = ref(false)
const isSubmittingFeedback = ref(false)
const quillEditor = ref<InstanceType<typeof QuillEditor> | null>(null)
const feedbackForm = reactive({
  html: '',
  contact: '',
})

// Quill 编辑器配置
const editorOptions = {
  modules: {
    toolbar: [
      ['bold', 'italic', 'underline', 'strike'],
      ['blockquote', 'code-block'],
      [{ list: 'ordered' }, { list: 'bullet' }],
      [{ header: [1, 2, 3, 4, 5, 6, false] }],
      [{ color: [] }, { background: [] }],
      ['link', 'image'],
      ['clean'],
    ],
  },
  placeholder: '请输入您的宝贵意见或建议，支持粘贴图片...',
}

// 处理图片粘贴事件
const handlePaste = async (event: ClipboardEvent) => {
  const items = event.clipboardData?.items
  if (!items) return

  for (let i = 0; i < items.length; i++) {
    const item = items[i]

    // 检查是否为图片
    if (item.type.indexOf('image') !== -1) {
      event.preventDefault()

      const file = item.getAsFile()
      if (!file) continue

      // 显示上传提示
      ElMessage.info('正在上传图片...')

      try {
        // 创建 FormData 并上传
        const formData = new FormData()
        formData.append('file', file)

        const response = await axios.post('/api/upload_image', formData, {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        })

        const data = response.data
        const imageUrl = data.url

        // 将图片插入到编辑器
        const quill = quillEditor.value?.getQuill()
        if (quill) {
          const range = quill.getSelection()
          const index = range ? range.index : quill.getLength()
          quill.insertEmbed(index, 'image', imageUrl)
          quill.setSelection(index + 1, 0)
        }

        ElMessage.success('图片上传成功！')
      } catch (error) {
        console.error('Image upload failed:', error)
        ElMessage.error('图片上传失败，请稍后重试')
      }
    }
  }
}

const resetFeedbackForm = () => {
  feedbackForm.html = ''
  feedbackForm.contact = ''

  // 清空 Quill 编辑器的内容
  const quill = quillEditor.value?.getQuill()
  if (quill) {
    quill.setText('')
  }
}

const submitFeedback = async () => {
  // 从 HTML 中提取纯文本和图片链接
  const tempDiv = document.createElement('div')
  tempDiv.innerHTML = feedbackForm.html

  const textContent = tempDiv.textContent || tempDiv.innerText || ''
  const images = tempDiv.querySelectorAll('img')

  if (!textContent.trim() && images.length === 0) {
    ElMessage.warning('反馈内容不能为空！')
    return
  }

  // 构建提交内容：包含文本和图片链接
  let combinedText = textContent.trim()

  if (images.length > 0) {
    const imageUrls = Array.from(images)
      .map((img) => `[img]${img.src}[/img]`)
      .join('\n')
    combinedText += `\n\n${imageUrls}`
  }

  isSubmittingFeedback.value = true
  try {
    await axios.post('https://ptn-feedback.sqing33.dpdns.org/', {
      text: combinedText,
      contact: feedbackForm.contact,
    })

    ElMessage.success('反馈已提交，感谢您的支持！')
    feedbackDialogVisible.value = false
  } catch (error) {
    console.error('Feedback submission failed:', error)
    ElMessage.error('提交失败，请稍后再试。')
  } finally {
    isSubmittingFeedback.value = false
  }
}

const activeComponentRefresher = ref<(() => Promise<void>) | null>(null)

const handleComponentReady = (refreshMethod: () => Promise<void>) => {
  activeComponentRefresher.value = refreshMethod
}

const handleGlobalRefresh = async () => {
  if (isRefreshing.value) return

  const topLevelPath = route.matched.length > 0 ? route.matched[0].path : ''

  if (
    topLevelPath === '/torrents' ||
    topLevelPath === '/sites' ||
    topLevelPath === '/data' ||
    topLevelPath === '/batch-fetch'
  ) {
    isRefreshing.value = true
    ElMessage.info('后台正在刷新缓存...')

    try {
      await axios.post('/api/refresh_data')

      try {
        if (activeComponentRefresher.value) {
          await activeComponentRefresher.value()
        }
        ElMessage.success('数据已刷新！')
      } catch (e: any) {
        ElMessage.error(`数据更新失败: ${e.message}`)
      } finally {
        isRefreshing.value = false
      }
    } catch (e: any) {
      ElMessage.error(e.message)
      isRefreshing.value = false
    }
  } else {
    ElMessage.warning('当前页面不支持刷新操作。')
  }
}

// 加载背景设置
const loadBackgroundSettings = async () => {
  try {
    const response = await axios.get('/api/settings')
    if (response.data?.ui_settings?.background_url) {
      backgroundUrl.value = response.data.ui_settings.background_url
      updateBackground(backgroundUrl.value)
    }
  } catch (error) {
    console.error('加载背景设置失败:', error)
  }
}

// 更新背景图片
const updateBackground = (url: string) => {
  const appElement = document.getElementById('app')
  if (appElement) {
    if (url) {
      appElement.style.backgroundImage = `url('${url}')`
    } else {
      appElement.style.backgroundImage = `url('${backgroundUrl.value}')`
    }
  }
}

// 监听背景更新事件
const handleBackgroundUpdate = (event: any) => {
  const { backgroundUrl: newUrl } = event.detail
  backgroundUrl.value = newUrl
  updateBackground(newUrl)
}

// 加载版本信息并自动检测更新
const loadVersionInfo = async () => {
  try {
    const response = await axios.get('/update/check')
    const data = response.data
    if (data.success) {
      currentVersion.value = data.local_version

      // 如果有更新，自动弹出提示
      if (data.has_update) {
        setTimeout(() => {
          showUpdateDialog()
        }, 1000)
      }
    }
  } catch (error) {
    console.error('加载版本信息失败:', error)
    currentVersion.value = 'unknown'
  }
}

// 更新对话框状态
const updateDialogVisible = ref(false)
const updateInfo = reactive({
  hasUpdate: false,
  currentVersion: '',
  remoteVersion: '',
  changelog: [] as string[],
})

// 显示更新对话框
const showUpdateDialog = async () => {
  try {
    const changelogResponse = await axios.get('/update/changelog')
    const changelogData = changelogResponse.data

    const versionResponse = await axios.get('/update/check')
    const versionData = versionResponse.data

    updateInfo.hasUpdate = versionData.has_update
    updateInfo.currentVersion = currentVersion.value
    updateInfo.remoteVersion = versionData.remote_version
    updateInfo.changelog = changelogData.changelog || []

    updateDialogVisible.value = true
  } catch (error) {
    console.error('检查更新失败:', error)
    ElMessage.error('检查更新失败，请稍后重试')
  }
}

// 执行更新
const performUpdate = async () => {
  try {
    ElMessage.info('正在拉取更新代码...')

    // 拉取更新
    const pullResponse = await axios.post('/update/pull')
    const pullData = pullResponse.data

    if (!pullData.success) {
      ElMessage.error('拉取更新失败: ' + pullData.error)
      return
    }

    ElMessage.success('代码拉取成功，正在安装更新...')

    // 安装更新
    const installResponse = await axios.post('/update/install')
    const installData = installResponse.data

    if (installData.success) {
      ElMessage.success('更新成功！页面将在3秒后刷新...')
      updateDialogVisible.value = false
      setTimeout(() => {
        window.location.reload()
      }, 3000)
    } else {
      ElMessage.error('安装更新失败: ' + installData.error)
    }
  } catch (error) {
    console.error('更新失败:', error)
    ElMessage.error('更新失败，请稍后重试')
  }
}

onMounted(() => {
  loadBackgroundSettings()
  loadVersionInfo()
  window.addEventListener('background-updated', handleBackgroundUpdate)
})
</script>

<style>
#app {
  height: 100vh;
  position: relative;
  background-image: url('https://pic.pting.club/i/2025/10/07/68e4fbfe9be93.jpg');
  background-size: cover;
  background-position: center;
  background-attachment: fixed;
}

#app::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(255, 255, 255, 0.5);
  pointer-events: none;
  z-index: 0;
}

body {
  margin: 0;
  padding: 0;
}
</style>

<style>
.ql-container {
  font-size: 14px;
  font-family: inherit;
}

.ql-editor {
  min-height: 250px;
  max-height: 400px;
  overflow-y: auto;
}

.ql-editor.ql-blank::before {
  font-style: normal;
  color: #c0c4cc;
}

.ql-snow .ql-picker {
  font-size: 14px;
}
</style>

<style scoped>
.main-nav {
  border-bottom: solid 1px var(--el-menu-border-color);
  flex-shrink: 0;
  height: 40px;
  display: flex;
  align-items: center;
  position: relative;
  z-index: 1;
}

.main-content {
  flex-grow: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: calc(100% - 40px);
  position: relative;
  z-index: 1;
}

.main-content.no-nav {
  height: 100%;
}

.page-hint-container {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  top: 8px;
  display: flex;
  align-items: center;
}

.page-hint {
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
}

.hint-red {
  color: #f56c6c;
  font-weight: bold;
}

.hint-yellow {
  color: #00aaff;
  font-weight: bold;
}

.hint-green {
  color: #67c23a;
  font-weight: bold;
}

.hint-blue {
  color: #409eff;
  font-weight: bold;
}

.right-buttons-container {
  position: absolute;
  right: 20px;
  top: 3px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.editor-wrapper {
  width: 100%;
  display: flex;
  flex-direction: column;
}

.editor-wrapper :deep(.quill-editor) {
  display: flex;
  flex-direction: column;
}

.editor-wrapper :deep(.ql-toolbar) {
  border: 1px solid #dcdfe6;
  border-bottom: none;
  border-radius: 4px 4px 0 0;
}

.editor-wrapper :deep(.ql-container) {
  border: 1px solid #dcdfe6;
  border-radius: 0 0 4px 4px;
  height: 300px;
}

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
  padding: 20px 30px;
  background: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #e0e0e0;
  margin-bottom: 25px;
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
</style>
