<template>
  <div class="migration-container">
    <el-button @click="showLog" class="log-button">查看日志</el-button>
    <el-steps :active="activeStep" finish-status="success" align-center>
      <el-step title="填写基本信息" :icon="Edit" />
      <el-step title="核对种子详情" :icon="DocumentChecked" />
      <el-step title="选择发布站点" :icon="Promotion" />
      <el-step title="完成发布" :icon="UploadFilled" />
    </el-steps>
    <div class="content-card" :class="{ 'narrow-card': activeStep === 0 || activeStep === 2 || activeStep === 3 }">
      <!-- 步骤 0: 填写基本信息 -->
      <div v-if="activeStep === 0" class="form-container">
        <el-form label-position="top" label-width="100px">
          <el-row :gutter="20">
            <el-col>
              <el-form-item label="源站点 (需配置Cookie)">
                <el-select
                  v-model="sourceSite"
                  placeholder="请选择源站点"
                  style="width: 100%"
                  :disabled="isLoading"
                >
                  <el-option
                    v-for="site in sourceSitesList"
                    :key="site"
                    :label="site"
                    :value="site"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="种子名称 或 源站ID">
            <el-input
              v-model="searchTerm"
              placeholder="输入完整的种子名称或其在源站的ID"
              :disabled="isLoading"
            />
          </el-form-item>
        </el-form>
        <div class="button-group">
          <el-button type="primary" @click="handleNextStep" :loading="isLoading">
            下一步：获取种子信息
          </el-button>
        </div>
      </div>

      <!-- 步骤 1: 核对种子详情 -->
      <div v-if="activeStep === 1" class="details-container">
        <el-tabs v-model="activeTab" type="border-card" class="details-tabs">
           <el-tab-pane label="主要信息" name="main">
            <div class="main-info-container">
              <div class="form-column">
                <el-form label-position="top" class="fill-height-form">
                  <el-form-item label="原始/待解析标题">
                    <el-input v-model="torrentData.original_main_title">
                      <template #append>
                        <el-button :icon="Refresh" @click="reparseTitle" :loading="isReparsing">
                          重新解析
                        </el-button>
                      </template>
                    </el-input>
                  </el-form-item>

                  <div class="title-components-grid">
                    <el-form-item
                      v-for="param in torrentData.title_components"
                      :key="param.key"
                      :label="param.key"
                    >
                      <el-input v-model="param.value" />
                    </el-form-item>
                  </div>

                  <el-form-item label="副标题">
                    <el-input v-model="torrentData.subtitle" />
                  </el-form-item>
                  <el-form-item label="IMDb链接">
                    <el-input v-model="torrentData.imdb_link" />
                  </el-form-item>
                  <el-form-item label="海报">
                    <el-input type="textarea" v-model="torrentData.intro.poster" :rows="1" />
                  </el-form-item>
                </el-form>
              </div>
              <div class="preview-column">
                <el-form label-position="top" class="fill-height-form">
                  <el-form-item label="声明">
                    <el-input type="textarea" v-model="torrentData.intro.statement" :rows="7" />
                  </el-form-item>
                  <div class="image-preview-pane" style="max-height: 400px">
                    <template v-if="posterImages.length">
                      <img
                        v-for="(url, index) in posterImages"
                        :key="'poster-' + index"
                        :src="url"
                        alt="海报预览"
                        class="preview-image"
                        style="width: 280px; margin: 0 auto"
                        @error="handleImageError(url, 'poster', index)"
                      />
                    </template>
                    <div v-else class="preview-placeholder">海报预览</div>
                  </div>
                </el-form>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="视频截图" name="images">
            <div class="screenshot-container">
              <div class="form-column">
                <el-form label-position="top" class="fill-height-form">
                  <el-form-item label="截图" class="is-flexible">
                    <el-input type="textarea" v-model="torrentData.intro.screenshots" :rows="18" />
                  </el-form-item>
                </el-form>
              </div>
              <div class="preview-column">
                <div class="image-preview-pane">
                  <template v-if="screenshotImages.length"
                    ><el-scrollbar style="height: 525px">
                      <img
                        v-for="(url, index) in screenshotImages"
                        :key="'ss-' + index"
                        :src="url"
                        alt="截图预览"
                        class="preview-image"
                        @error="handleImageError(url, 'screenshot', index)"
                    /></el-scrollbar>
                  </template>
                  <div v-else class="preview-placeholder">截图预览</div>
                </div>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="简介详情" name="intro">
            <el-form label-position="top" class="fill-height-form">
              <el-form-item label="正文" class="is-flexible">
                <el-input type="textarea" v-model="torrentData.intro.body" :rows="24" />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="媒体信息" name="mediainfo">
            <el-form label-position="top" class="fill-height-form">
              <el-form-item label="Mediainfo" class="is-flexible">
                <el-input
                  type="textarea"
                  class="code-font"
                  v-model="torrentData.mediainfo"
                  :rows="25"
                />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="源站参数" name="params" class="params-pane">
            <pre class="code-block fill-height-pre">{{
              JSON.stringify(torrentData.source_params, null, 2)
            }}</pre>
          </el-tab-pane>
        </el-tabs>
        <div class="button-group">
          <el-button @click="handlePreviousStep" :disabled="isLoading">上一步</el-button>
          <el-button type="primary" @click="goToSelectSiteStep" :disabled="isLoading">
            下一步：选择发布站点
          </el-button>
        </div>
      </div>
      
      <!-- 步骤 2: 选择发布站点 -->
      <div v-if="activeStep === 2" class="form-container">
        <div class="site-selection-container">
            <h3 class="selection-title">请选择要发布的目标站点 (可多选)</h3>
            <div class="site-buttons-group">
            <el-button
                v-for="site in targetSitesList"
                :key="site"
                :type="selectedTargetSites.includes(site) ? 'primary' : 'default'"
                @click="toggleSiteSelection(site)"
                class="site-button"
            >
                {{ site }}
            </el-button>
            </div>
        </div>
        <div class="button-group">
            <el-button @click="handlePreviousStep" :disabled="isLoading">上一步</el-button>
            <el-button type="success" @click="handlePublish" :loading="isLoading" :disabled="selectedTargetSites.length === 0">
              确认并发布种子
            </el-button>
        </div>
      </div>
      
      <!-- 步骤 3: 完成发布 -->
      <div v-if="activeStep === 3" class="form-container">
        <div v-for="(result, index) in finalResultsList" :key="index" class="result-item">
            <el-result
              :icon="result.success ? 'success' : 'error'"
              :title="`${result.siteName}: ${result.success ? '发布成功' : '发布失败'}`"
              :sub-title="result.message || (result.success ? '种子已成功发布！' : '发布失败，请检查日志。')"
            >
              <template #extra>
                <el-link
                  v-if="result.url"
                  :href="result.url"
                  type="primary"
                  target="_blank"
                  :underline="false"
                >
                  点击此处跳转到新种子页面
                </el-link>
              </template>
            </el-result>
        </div>
        <div class="button-group">
          <el-button type="primary" @click="resetMigration">开始新的迁移</el-button>
        </div>
      </div>

    </div>
    <div v-if="showLogCard" class="log-card-overlay" @click="hideLog"></div>
    <el-card v-if="showLogCard" class="log-card" shadow="xl">
      <template #header>
        <div class="card-header">
          <span>操作日志</span>
          <el-button type="danger" :icon="Close" circle @click="hideLog" />
        </div>
      </template>
      <pre class="log-content-pre">{{ logContent }}</pre>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElNotification, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { Edit, DocumentChecked, UploadFilled, Close, Refresh, Promotion } from '@element-plus/icons-vue'

const getInitialTorrentData = () => ({
  title_components: [],
  original_main_title: '',
  subtitle: '',
  imdb_link: '',
  intro: { statement: '', poster: '', body: '', screenshots: '' },
  mediainfo: '',
  source_params: {},
})

const parseImageUrls = (text: string) => {
  if (!text || typeof text !== 'string') return []
  const regex = /\[img\](https?:\/\/[^\s[\]]+)\[\/img\]/gi
  const matches = [...text.matchAll(regex)]
  return matches.map((match) => match[1])
}

const activeStep = ref(0)
const activeTab = ref('main')
const sourceSitesList = ref([])
const targetSitesList = ref([])
const sourceSite = ref('')
const selectedTargetSites = ref<string[]>([])
const searchTerm = ref('')
const isLoading = ref(false)
const torrentData = ref(getInitialTorrentData())
const taskId = ref(null)
const finalResultsList = ref<any[]>([])
const logContent = ref('')
const showLogCard = ref(false)
const isReparsing = ref(false)
const reportedFailedScreenshots = ref(false)
const posterImages = computed(() => parseImageUrls(torrentData.value.intro.poster))
const screenshotImages = computed(() => parseImageUrls(torrentData.value.intro.screenshots))

const handleImageError = async (url: string, type: 'poster' | 'screenshot', index: number) => {
  if (type === 'screenshot' && reportedFailedScreenshots.value) {
    return
  }

  console.error(`图片加载失败: 类型=${type}, URL=${url}, 索引=${index}`)

  if (type === 'screenshot') {
    reportedFailedScreenshots.value = true
    ElNotification.warning({
      title: '截图失效',
      message: '检测到截图链接失效，正在尝试从视频重新生成...',
    })
  }

  const payload = {
    type: type === 'screenshot' ? 'screenshot' : 'poster',
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: sourceSite.value,
    },
  }

  try {
    const response = await axios.post('/api/media/validate', payload)
    
    if (response.data.success && type === 'screenshot' && response.data.screenshots) {
      console.log('成功从后端获取了新的截图链接。');
      torrentData.value.intro.screenshots = response.data.screenshots;
      ElNotification.success({
        title: '截图已更新',
        message: '已成功生成并加载了新的截图。',
      });
    } else {
      console.log(`已成功将失效 ${type} 信息报告给后端。`)
    }
  } catch (error) {
    console.error('发送失效图片信息请求时发生网络错误:', error)
  }
}

const fetchSitesList = async () => {
  try {
    const response = await axios.get('/api/sites_list')
    sourceSitesList.value = response.data.source_sites
    targetSitesList.value = response.data.target_sites
  } catch (error) {
    ElNotification.error({ title: '错误', message: '无法从服务器获取站点列表' })
  }
}

const handleNextStep = async () => {
  reportedFailedScreenshots.value = false

  if (!sourceSite.value || !searchTerm.value.trim()) {
    ElNotification.warning({ title: '提示', message: '请填写所有必填项' })
    return
  }
  isLoading.value = true
  ElNotification({
    title: '正在获取',
    message: '正在从源站点抓取种子信息，请稍候...',
    type: 'info',
    duration: 0,
  })

  try {
    const response = await axios.post('/api/migrate/fetch_info', {
      sourceSite: sourceSite.value,
      searchTerm: searchTerm.value.trim(),
    })

    if (response.data.logs) {
      logContent.value = response.data.logs
    }

    ElNotification.closeAll()

    if (response.data.success) {
      ElNotification.success({ title: '获取成功', message: '种子信息已成功加载，请核对。' })
      torrentData.value = response.data.data
      taskId.value = response.data.task_id
      activeStep.value = 1
    } else {
      ElNotification.error({
        title: '获取失败',
        message: response.data.logs,
        duration: 0,
        showClose: true,
      })
    }
  } catch (error) {
    ElNotification.closeAll()
    handleApiError(error, '获取种子信息时发生网络错误')
  } finally {
    isLoading.value = false
  }
}

const goToSelectSiteStep = () => {
    activeStep.value = 2;
}

const toggleSiteSelection = (siteName: string) => {
  const index = selectedTargetSites.value.indexOf(siteName)
  if (index > -1) {
    selectedTargetSites.value.splice(index, 1)
  } else {
    selectedTargetSites.value.push(siteName)
  }
}

const handlePublish = async () => {
  isLoading.value = true
  finalResultsList.value = []
  ElNotification({
    title: '正在发布',
    message: `准备向 ${selectedTargetSites.value.length} 个站点发布种子...`,
    type: 'info',
    duration: 0,
  })

  const publishPromises = selectedTargetSites.value.map(siteName => {
    return axios.post('/api/migrate/publish', {
      task_id: taskId.value,
      upload_data: torrentData.value,
      targetSite: siteName,
    }).then(response => ({
        siteName,
        ...response.data
    })).catch(error => ({
        siteName,
        success: false,
        logs: error.response?.data?.logs || error.message,
        url: null,
        message: `发布到 ${siteName} 时发生网络错误。`
    }));
  });

  try {
    const results = await Promise.all(publishPromises)
    finalResultsList.value = results
    
    ElNotification.closeAll()
    const successCount = results.filter(r => r.success).length
    ElNotification.success({
        title: '发布完成',
        message: `成功发布到 ${successCount} / ${selectedTargetSites.value.length} 个站点。`
    })
    
    logContent.value = results.map(r => `--- Log for ${r.siteName} ---\n${r.logs || 'No logs available.'}`).join('\n\n')

  } catch (error) {
    ElNotification.closeAll()
    handleApiError(error, '发布种子时发生严重错误')
  } finally {
    activeStep.value = 3
    isLoading.value = false
  }
}

const handlePreviousStep = () => {
    if (activeStep.value > 0) {
        activeStep.value--
    }
}

const resetMigration = () => {
  activeStep.value = 0
  sourceSite.value = ''
  selectedTargetSites.value = []
  searchTerm.value = ''
  isLoading.value = false
  torrentData.value = getInitialTorrentData()
  taskId.value = null
  finalResultsList.value = []
  logContent.value = ''
  fetchSitesList()
}

const handleApiError = (error, defaultMessage) => {
  const message = error.response?.data?.logs || error.message || defaultMessage
  if (error.response?.data?.logs) {
    logContent.value = error.response.data.logs
  }
  ElNotification.error({ title: '操作失败', message, duration: 0, showClose: true })
}

const showLog = () => {
  if (!logContent.value) {
    ElMessageBox.alert('当前没有可供显示的日志。', '提示', {
      confirmButtonText: '确定',
    })
    return
  }
  showLogCard.value = true
}

const hideLog = () => {
  showLogCard.value = false
}

onMounted(fetchSitesList)
</script>

<style scoped>
.migration-container {
  padding: 24px;
  width: 90%;
  margin: 0 auto;
  overflow: auto;
}

.content-card {
  margin-top: 24px;
  padding: 24px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease-in-out;
}

.content-card.narrow-card {
  max-width: 600px;
  margin: 15vh auto;
}

.form-container {
  max-width: 800px;
  margin: 0 auto;
}

.button-group {
  margin-top: 24px;
  display: flex;
  justify-content: center;
  gap: 16px;
}

.code-font :deep(.el-textarea__inner) {
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  background-color: #f8f9fa;
}

.details-tabs {
  min-height: 65vh;
  display: flex;
  flex-direction: column;
}

:deep(.el-tabs__content) {
  flex: 1;
  overflow: auto;
}

.details-tabs .el-tab-pane {
  height: 100%;
}

.fill-height-form {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.is-flexible {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.is-flexible :deep(.el-form-item__content),
.is-flexible :deep(.el-textarea) {
  flex: 1;
}
.is-flexible :deep(.el-textarea__inner) {
  height: 100%;
  resize: none;
}

.main-info-container,
.screenshot-container {
  display: flex;
  gap: 24px;
  height: 100%;
}

.form-column,
.preview-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.screenshot-container .form-column {
  flex: 5;
}
.screenshot-container .preview-column {
  flex: 5;
}

.image-preview-pane {
  flex: 1;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 8px;
  background-color: #f8f9fa;
  overflow-y: auto;
}

.preview-image {
  max-width: 100%;
  display: block;
  margin-bottom: 8px;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
}

.preview-placeholder {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  color: #909399;
  font-size: 14px;
}

.params-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.code-block {
  background-color: #f8f9fa;
  padding: 16px;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}

.fill-height-pre {
  flex: 1;
  overflow: auto;
  margin: 0;
}

.el-result {
  padding-bottom: 0;
}

.log-button {
  position: absolute;
  z-index: 999;
}

.log-card-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  z-index: 1999;
}

.log-card {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 75vw;
  max-width: 900px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  max-height: 80vh;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.log-card :deep(.el-card__body) {
  overflow-y: auto;
  flex: 1;
}

.log-content-pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  margin: 0;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  color: #606266;
}

.title-components-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 0 16px;
}

:deep(.el-form-item) {
  margin-bottom: 8px;
}

.site-selection-container {
  padding: 20px;
  text-align: center;
}

.selection-title {
  margin-bottom: 24px;
  color: #303133;
  font-weight: 500;
}

.site-buttons-group {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}

.site-button {
  min-width: 120px;
  transition: all 0.2s;
}

.result-item {
    border-bottom: 1px solid #e4e7ed;
    margin-bottom: 16px;
    padding-bottom: 16px;
}
.result-item:last-child {
    border-bottom: none;
    margin-bottom: 0;
}
</style>
