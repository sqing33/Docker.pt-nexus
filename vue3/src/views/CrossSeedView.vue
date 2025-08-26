<template>
  <div class="migration-container">
    <!-- 步骤条 (带图标) -->
    <el-steps :active="activeStep" finish-status="success" align-center>
      <el-step title="填写基本信息" :icon="Edit" />
      <el-step title="核对种子详情" :icon="DocumentChecked" />
      <el-step title="完成发布" :icon="UploadFilled" />
    </el-steps>

    <!-- 内容区域 -->
    <div class="content-card">
      <!-- ========================== -->
      <!--      第一步: 填写表单      -->
      <!-- ========================== -->
      <div v-if="activeStep === 0">
        <el-form label-position="top" label-width="100px">
          <el-row :gutter="20">
            <el-col :span="12">
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
            <el-col :span="12">
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

      <!-- ========================== -->
      <!--      第二步: 核对信息      -->
      <!-- ========================== -->
      <div v-if="activeStep === 1">
        <el-tabs v-model="activeTab" type="border-card">
          <el-tab-pane label="主要信息" name="main">
            <el-form label-position="top">
              <el-form-item label="主标题"
                ><el-input v-model="torrentData.main_title"
              /></el-form-item>
              <el-form-item label="副标题"
                ><el-input v-model="torrentData.subtitle"
              /></el-form-item>
              <el-form-item label="IMDb链接"
                ><el-input v-model="torrentData.imdb_link"
              /></el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="简介详情" name="intro">
            <el-form label-position="top">
              <el-form-item label="声明"
                ><el-input type="textarea" :rows="4" v-model="torrentData.intro.statement"
              /></el-form-item>
              <el-form-item label="海报"
                ><el-input type="textarea" :rows="4" v-model="torrentData.intro.poster"
              /></el-form-item>
              <el-form-item label="截图"
                ><el-input type="textarea" :rows="4" v-model="torrentData.intro.screenshots"
              /></el-form-item>
              <el-form-item label="正文"
                ><el-input type="textarea" :rows="6" v-model="torrentData.intro.body"
              /></el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="媒体信息" name="mediainfo">
            <el-form-item label="Mediainfo">
              <el-input
                type="textarea"
                class="code-font"
                :rows="15"
                v-model="torrentData.mediainfo"
              ></el-input>
            </el-form-item>
          </el-tab-pane>
          <el-tab-pane label="源站参数" name="params">
            <pre class="code-block">{{ JSON.stringify(torrentData.source_params, null, 2) }}</pre>
          </el-tab-pane>
        </el-tabs>
        <div class="button-group">
          <el-button @click="handlePreviousStep" :disabled="isLoading">上一步</el-button>
          <el-button type="success" @click="handlePublish" :loading="isLoading">
            确认并发布种子
          </el-button>
        </div>
      </div>

      <!-- ========================== -->
      <!--       第三步: 完成         -->
      <!-- ========================== -->
      <div v-if="activeStep === 2">
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElNotification } from 'element-plus'
import axios from 'axios'
// [新增] 导入 Element Plus 图标
import { Edit, DocumentChecked, UploadFilled } from '@element-plus/icons-vue'

// --- Helper Functions ---
const getInitialTorrentData = () => ({
  main_title: '',
  subtitle: '',
  imdb_link: '',
  intro: { statement: '', poster: '', body: '', screenshots: '' },
  mediainfo: '',
  source_params: {},
})

// --- Component State ---
const activeStep = ref(0)
const activeTab = ref('main')
const sourceSitesList = ref([])
const targetSitesList = ref([])
const sourceSite = ref('')
const targetSite = ref('')
const searchTerm = ref('')
const isLoading = ref(false)
const torrentData = ref(getInitialTorrentData())
const taskId = ref(null)
const finalResult = ref({ success: false, url: '', message: '' })

// --- Core Logic Functions ---
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

    ElNotification.closeAll() // Close the loading notification

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
  fetchSitesList()
}

const handleApiError = (error, defaultMessage) => {
  const message = error.response?.data?.logs || error.message || defaultMessage
  ElNotification.error({ title: '操作失败', message, duration: 0, showClose: true })
}

onMounted(fetchSitesList)
</script>

<style scoped>
.migration-container {
  padding: 24px;
  max-width: 1000px;
  margin: 20px auto;
}

.el-steps {
  max-width: 800px;
  margin: 0 auto 24px auto;
}

.content-card {
  margin-top: 24px;
  padding: 24px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  min-height: 500px;
}

.button-group {
  margin-top: 24px;
  display: flex;
  justify-content: center;
  gap: 16px;
}

.code-font .el-textarea__inner {
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  background-color: #f8f9fa;
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
.el-result {
  padding-bottom: 0;
}
</style>
