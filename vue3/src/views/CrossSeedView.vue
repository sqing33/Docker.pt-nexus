<template>
  <div class="migration-container">
    <el-button @click="showLog" class="log-button">查看日志</el-button>
    <el-steps :active="activeStep" finish-status="success" align-center>
      <el-step title="填写基本信息" :icon="Edit" />
      <el-step title="核对种子详情" :icon="DocumentChecked" />
      <el-step title="完成发布" :icon="UploadFilled" />
    </el-steps>

    <div class="content-card" :class="{ 'narrow-card': activeStep === 0 || activeStep === 2 }">
      <!-- ... 您现有的 v-if 内容保持不变 ... -->
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
            <el-col>
              <el-form-item label="目标站点 (需配置Passkey)">
                <el-select
                  v-model="targetSite"
                  placeholder="请选择目标站点"
                  style="width: 100%"
                  :disabled="isLoading"
                >
                  <el-option
                    v-for="site in targetSitesList"
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

      <div v-if="activeStep === 1" class="details-container">
        <el-tabs v-model="activeTab" type="border-card" class="details-tabs">
          <el-tab-pane label="主要信息" name="main">
            <div class="main-info-container">
              <div class="form-column">
                <el-form label-position="top" class="fill-height-form">
                  <el-form-item label="主标题">
                    <el-input v-model="torrentData.main_title" />
                  </el-form-item>
                  <el-form-item label="副标题">
                    <el-input v-model="torrentData.subtitle" />
                  </el-form-item>
                  <el-form-item label="IMDb链接">
                    <el-input v-model="torrentData.imdb_link" />
                  </el-form-item>
                  <el-form-item label="海报" class="is-flexible">
                    <el-input type="textarea" v-model="torrentData.intro.poster" :rows="2" />
                  </el-form-item>
                  <el-form-item label="声明" class="is-flexible">
                    <el-input type="textarea" v-model="torrentData.intro.statement" :rows="5" />
                  </el-form-item>
                </el-form>
              </div>
              <div class="preview-column">
                <div class="image-preview-pane">
                  <template v-if="posterImages.length">
                    <img
                      v-for="(url, index) in posterImages"
                      :key="'poster-' + index"
                      :src="url"
                      alt="海报预览"
                      class="preview-image"
                      style="width: 300px; margin: 0 auto"
                    />
                  </template>
                  <div v-else class="preview-placeholder">海报预览</div>
                </div>
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
                    ><el-scrollbar style="height: 55vh">
                      <img
                        v-for="(url, index) in screenshotImages"
                        :key="'ss-' + index"
                        :src="url"
                        alt="截图预览"
                        class="preview-image"
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
          <el-button type="success" @click="handlePublish" :loading="isLoading">
            确认并发布种子
          </el-button>
        </div>
      </div>

      <div v-if="activeStep === 2" class="form-container">
        <el-result
          :icon="finalResult.success ? 'success' : 'error'"
          :title="finalResult.success ? '发布成功' : '发布失败'"
          :sub-title="finalResult.message"
        >
          <template #extra>
            <el-link
              v-if="finalResult.url"
              :href="finalResult.url"
              type="primary"
              target="_blank"
              :underline="false"
            >
              点击此处跳转到新种子页面
            </el-link>
            <div class="button-group">
              <el-button type="primary" @click="resetMigration">开始新的迁移</el-button>
            </div>
          </template>
        </el-result>
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
import { Edit, DocumentChecked, UploadFilled, Close } from '@element-plus/icons-vue'

const getInitialTorrentData = () => ({
  main_title: '',
  subtitle: '',
  imdb_link: '',
  intro: { statement: '', poster: '', body: '', screenshots: '' },
  mediainfo: '',
  source_params: {},
})

const parseImageUrls = (text) => {
  if (!text || typeof text !== 'string') return []
  const regex = /\[img\](https?:\/\/[^\s[\]]+)\[\/img\]/gi
  const matches = [...text.matchAll(regex)]
  return matches.map((match) => match[1])
}

const activeStep = ref(0)
const activeTab = ref('main')
const sourceSitesList = ref([])
const targetSitesList = ref([])
const sourceSite = ref('铂金学院')
const targetSite = ref('星陨阁-测试站')
const searchTerm = ref('Sunset Boulevard 1950 2160p UHD BluRay x265 DV HDR TrueHD 5.1 mUHD-FRDS')
const isLoading = ref(false)
const torrentData = ref(getInitialTorrentData())
const taskId = ref(null)
const finalResult = ref({ success: false, url: '', message: '' })
const logContent = ref('')

const showLogCard = ref(false)

const posterImages = computed(() => parseImageUrls(torrentData.value.intro.poster))
const screenshotImages = computed(() => parseImageUrls(torrentData.value.intro.screenshots))

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
  if (!sourceSite.value || !targetSite.value || !searchTerm.value.trim()) {
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
      targetSite: targetSite.value,
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

const handlePublish = async () => {
  isLoading.value = true
  ElNotification({
    title: '正在发布',
    message: '正在将种子发布到目标站点...',
    type: 'info',
    duration: 0,
  })

  try {
    const response = await axios.post('/api/migrate/publish', {
      task_id: taskId.value,
      upload_data: torrentData.value,
    })

    if (response.data.logs) {
      logContent.value = response.data.logs
    }

    ElNotification.closeAll()

    finalResult.value = {
      success: response.data.success,
      url: response.data.url,
      message: response.data.success ? '种子已成功发布！' : '发布失败，请检查相关配置。',
    }
    activeStep.value = 2
  } catch (error) {
    ElNotification.closeAll()
    handleApiError(error, '发布种子时发生网络错误')
    finalResult.value = { success: false, url: '', message: '发布过程中发生未知网络错误。' }
    activeStep.value = 2
  } finally {
    isLoading.value = false
  }
}

const handlePreviousStep = () => {
  activeStep.value = 0
}

const resetMigration = () => {
  activeStep.value = 0
  sourceSite.value = ''
  targetSite.value = ''
  searchTerm.value = ''
  isLoading.value = false
  torrentData.value = getInitialTorrentData()
  taskId.value = null
  finalResult.value = { success: false, url: '', message: '' }
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
  width: 500px;
  margin: 20vh auto;
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
</style>
