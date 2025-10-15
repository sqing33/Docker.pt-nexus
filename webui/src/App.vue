<!-- src/App.vue -->
<template>
  <el-menu v-if="!isLoginPage" :default-active="activeRoute" class="main-nav glass-nav" mode="horizontal" router>
    <div style="padding: 5px 15px;line-height: 32px;">
      <img src="/favicon.ico" alt="Logo" height="32" style="margin-right: 8px; vertical-align: middle;" />
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
        <span class="hint-green">做种且可跳转种子详情页</span> - <span class="hint-blue">做种但无详情页</span> - <span class="hint-red">可铺种但未做种</span>
      </span>
      <span v-else-if="activeRoute === '/data'" class="page-hint">
        <span class="hint-red">种子有误/不存在/禁转</span> - <span class="hint-yellow">未审查种子信息</span>
      </span>
    </div>
    <div class="refresh-button-container">
      <el-button type="primary" @click="feedbackDialogVisible = true" plain>反馈</el-button>
      <el-button type="success" @click="handleGlobalRefresh" :loading="isRefreshing" :disabled="isRefreshing" plain>
        刷新
      </el-button>
    </div>
  </el-menu>
  <main :class="['main-content', isLoginPage ? 'no-nav' : '']">
  <router-view v-slot="{ Component }">
    <component :is="Component" @ready="handleComponentReady" />
  </router-view>
</main>

  <!-- Feedback Dialog -->
  <el-dialog v-model="feedbackDialogVisible" title="意见反馈" width="700px" @close="resetFeedbackForm">
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
      <el-form-item label="联系方式 (可选)" style="margin-top: 50px;">
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
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { QuillEditor } from '@vueup/vue-quill'
import '@vueup/vue-quill/dist/vue-quill.snow.css'
import axios from 'axios'

const route = useRoute()

// 背景图片URL
const backgroundUrl = ref('https://pic.pting.club/i/2025/10/07/68e4fbfe9be93.jpg')

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
  contact: ''
})

// Quill 编辑器配置
const editorOptions = {
  modules: {
    toolbar: [
      ['bold', 'italic', 'underline', 'strike'],
      ['blockquote', 'code-block'],
      [{ 'list': 'ordered' }, { 'list': 'bullet' }],
      [{ 'header': [1, 2, 3, 4, 5, 6, false] }],
      [{ 'color': [] }, { 'background': [] }],
      ['link', 'image'],
      ['clean']
    ]
  },
  placeholder: '请输入您的宝贵意见或建议，支持粘贴图片...'
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

        const response = await fetch('/api/upload_image', {
          method: 'POST',
          body: formData
        })

        if (!response.ok) {
          throw new Error('上传失败')
        }

        const data = await response.json()
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
      .map(img => `img${img.src}img`)
      .join('\n')
    combinedText += `\n\n${imageUrls}`
  }

  isSubmittingFeedback.value = true
  try {
    const response = await fetch('https://ptn-feedback.sqing33.dpdns.org/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        text: combinedText,
        contact: feedbackForm.contact
      })
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

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

  if (topLevelPath === '/torrents' || topLevelPath === '/sites' || topLevelPath === '/data' || topLevelPath === '/batch-fetch') {
    isRefreshing.value = true
    ElMessage.info('后台正在刷新缓存...')

    try {
      const response = await fetch('/api/refresh_data', { method: 'POST' })
      if (!response.ok) {
        throw new Error('触发刷新失败')
      }

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

onMounted(() => {
  loadBackgroundSettings()
  window.addEventListener('background-updated', handleBackgroundUpdate)
})
</script>

<style>
#app {
  height: 100vh;
  position: relative;
  /* 背景图片设置 */
  background-image: url('https://pic.pting.club/i/2025/10/07/68e4fbfe9be93.jpg'); /* 替换为您的图片URL */
  background-size: cover;
  background-position: center;
  background-attachment: fixed;
}

/* 透明蒙层 */
#app::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(255, 255, 255, 0.5); /* 白色半透明蒙层，可调整透明度 */
  pointer-events: none; /* 允许点击穿透 */
  z-index: 0;
}

body {
  margin: 0;
  padding: 0;
}
</style>

<style>
/* Quill 编辑器样式优化 */
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
  color: #e6a23c;
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

.refresh-button-container {
  position: absolute;
  right: 20px;
  top: 3px;
  display: flex;
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
</style>
