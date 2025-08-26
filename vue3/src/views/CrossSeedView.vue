<template>
  <div class="migration-container">
    <!-- ========================== -->
    <!--          左侧面板          -->
    <!-- ========================== -->
    <div class="left-panel">
      <!-- 左上角: 操作表单 -->
      <div class="form-card">
        <div class="form-grid">
          <div class="form-item">
            <label for="source-site">源站点 (需配置Cookie)</label>
            <select id="source-site" v-model="sourceSite" :disabled="isLoading">
              <option disabled value="">请选择源站点</option>
              <option v-for="site in sourceSitesList" :key="site" :value="site">{{ site }}</option>
            </select>
          </div>
          <div class="form-item">
            <label for="target-site">目标站点 (需配置Passkey)</label>
            <select id="target-site" v-model="targetSite" :disabled="isLoading">
              <option disabled value="">请选择目标站点</option>
              <option v-for="site in targetSitesList" :key="site" :value="site">{{ site }}</option>
            </select>
          </div>
          <div class="form-item full-width">
            <label for="search-term">种子名称 或 源站ID</label>
            <input
              type="text"
              id="search-term"
              v-model="searchTerm"
              placeholder="输入完整的种子名称或其在源站的ID"
              :disabled="isLoading"
            />
          </div>
        </div>
        <div class="actions">
          <button @click="fetchTorrentInfo" :disabled="isLoading" class="migrate-button">
            {{ isLoading && migrationStep === 'form' ? '正在获取...' : '获取种子信息' }}
          </button>
          <button
            @click="publishTorrent"
            :disabled="migrationStep !== 'review' || isLoading"
            class="migrate-button publish-button"
          >
            {{ isLoading && migrationStep === 'review' ? '正在发布...' : '确认并发布' }}
          </button>
        </div>
      </div>

      <!-- 左下角: 日志输出 -->
      <div class="log-card">
        <h2 class="log-title">迁移日志</h2>
        <pre class="log-output" ref="logContainer">{{ logOutput || '此处将显示操作日志...' }}</pre>
      </div>
    </div>

    <!-- ========================== -->
    <!--          右侧面板          -->
    <!-- ========================== -->
    <div class="right-panel">
      <!-- 种子信息预览/编辑 -->
      <div v-if="migrationStep !== 'result'" class="review-card">
        <h2 class="review-title">种子发布信息预览</h2>
        <div class="review-grid">
          <div class="review-item full-span">
            <label>主标题</label>
            <input type="text" v-model="torrentData.main_title" />
          </div>
          <div class="review-item full-span">
            <label>副标题</label>
            <input type="text" v-model="torrentData.subtitle" />
          </div>
          <div class="review-item full-span">
            <label>IMDb链接</label>
            <input type="text" v-model="torrentData.imdb_link" />
          </div>
          <div class="review-item full-span">
            <label>简介 - 声明</label>
            <textarea rows="4" v-model="torrentData.intro.statement"></textarea>
          </div>
          <div class="review-item">
            <label>简介 - 海报</label>
            <textarea rows="4" v-model="torrentData.intro.poster"></textarea>
          </div>
          <div class="review-item">
            <label>简介 - 截图</label>
            <textarea rows="4" v-model="torrentData.intro.screenshots"></textarea>
          </div>
          <div class="review-item full-span">
            <label>简介 - 正文</label>
            <textarea rows="6" v-model="torrentData.intro.body"></textarea>
          </div>
          <div class="review-item full-span">
            <label>Mediainfo</label>
            <textarea class="code-font" rows="10" v-model="torrentData.mediainfo"></textarea>
          </div>
        </div>
      </div>

      <!-- 最终结果显示 -->
      <div v-if="migrationStep === 'result'" class="result-card">
        <h2 v-if="finalTorrentUrl" class="success-title">🎉 发布成功！</h2>
        <h2 v-else class="error-title">发布失败</h2>
        <p v-if="finalTorrentUrl">
          已成功将种子发布到目标站点，点击下方链接查看：<br />
          <a :href="finalTorrentUrl" target="_blank" rel="noopener noreferrer">{{
            finalTorrentUrl
          }}</a>
        </p>
        <p v-else>种子发布失败，请检查左侧日志获取详细信息。</p>
        <div class="actions">
          <button @click="resetMigration" class="migrate-button">开始新的迁移</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import axios from 'axios'

// --- Helper Functions ---
const getInitialTorrentData = () => ({
  main_title: '',
  subtitle: '',
  imdb_link: '',
  intro: {
    statement: '',
    poster: '',
    body: '',
    screenshots: '',
  },
  mediainfo: '',
  source_params: {},
})

// --- Component State ---
const sourceSitesList = ref([])
const targetSitesList = ref([])
const sourceSite = ref('')
const targetSite = ref('')
const searchTerm = ref('')
const isLoading = ref(false)
const logOutput = ref('')
const migrationStep = ref('form') // 'form', 'review', 'result'
const torrentData = ref(getInitialTorrentData())
const taskId = ref(null)
const finalTorrentUrl = ref(null)
const logContainer = ref(null)

// --- Watchers ---
watch(logOutput, async () => {
  await nextTick()
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
})

// --- API Functions ---
const fetchSitesList = async () => {
  try {
    const response = await axios.get('/api/sites_list')
    sourceSitesList.value = response.data.source_sites
    targetSitesList.value = response.data.target_sites
  } catch (error) {
    logOutput.value = '错误：无法从服务器获取站点列表。'
  }
}

const fetchTorrentInfo = async () => {
  if (!sourceSite.value || !targetSite.value || !searchTerm.value.trim()) {
    logOutput.value = '请填写所有必填项：源站点、目标站点和种子名称/ID。'
    return
  }
  if (sourceSite.value === targetSite.value) {
    logOutput.value = '源站点和目标站点不能相同。'
    return
  }

  isLoading.value = true
  migrationStep.value = 'form'
  logOutput.value = '正在初始化任务，请稍候...'

  try {
    const response = await axios.post('/api/migrate/fetch_info', {
      sourceSite: sourceSite.value,
      targetSite: targetSite.value,
      searchTerm: searchTerm.value.trim(),
    })

    logOutput.value = response.data.logs

    if (response.data.success) {
      torrentData.value = response.data.data
      taskId.value = response.data.task_id
      migrationStep.value = 'review'
    }
  } catch (error) {
    handleApiError(error, '获取种子信息失败')
  } finally {
    isLoading.value = false
  }
}

const publishTorrent = async () => {
  isLoading.value = true
  migrationStep.value = 'review' // Keep step as review while loading
  logOutput.value += '\n\n====================\n\n正在发布种子，请稍候...'

  try {
    const response = await axios.post('/api/migrate/publish', {
      task_id: taskId.value,
      upload_data: torrentData.value,
    })

    logOutput.value = response.data.logs

    if (response.data.success) {
      finalTorrentUrl.value = response.data.url
    }
    migrationStep.value = 'result'
  } catch (error) {
    handleApiError(error, '发布种子失败')
    migrationStep.value = 'result'
  } finally {
    isLoading.value = false
  }
}

const resetMigration = () => {
  sourceSite.value = ''
  targetSite.value = ''
  searchTerm.value = ''
  logOutput.value = ''
  migrationStep.value = 'form'
  torrentData.value = getInitialTorrentData()
  taskId.value = null
  finalTorrentUrl.value = null
  fetchSitesList()
}

const handleApiError = (error, defaultMessage) => {
  console.error(`${defaultMessage}:`, error)
  if (error.response && error.response.data && error.response.data.logs) {
    logOutput.value = error.response.data.logs
  } else {
    logOutput.value = `发生未知网络错误: ${error.message}`
  }
}

onMounted(() => {
  fetchSitesList()
})
</script>

<style scoped>
/* Main Layout */
.migration-container {
  display: grid;
  grid-template-columns: 3fr 7fr; /* 左3右7 */
  gap: 24px;
  padding: 24px;
  height: calc(100vh - 48px); /* 适应视窗高度 */
  box-sizing: border-box;
}

.left-panel,
.right-panel {
  display: flex;
  flex-direction: column;
  gap: 24px;
  overflow-y: auto; /* 超出内容可滚动 */
}

/* Card Styles */
.form-card,
.log-card,
.review-card,
.result-card {
  background-color: #ffffff;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  padding: 24px;
  display: flex;
  flex-direction: column;
}

/* Left Panel Specifics */
.left-panel .form-card {
  flex-shrink: 0; /* 不收缩 */
}
.left-panel .log-card {
  flex-grow: 1; /* 占据剩余空间 */
  min-height: 200px;
}
.log-output {
  flex-grow: 1;
  background-color: #f5f5f5;
  color: #333;
  padding: 16px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-wrap: break-word;
  overflow-y: auto;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}

/* Right Panel Specifics */
.right-panel .review-card,
.right-panel .result-card {
  flex-grow: 1;
}

/* Form Grid */
.form-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}
.form-item.full-width {
  grid-column: 1 / -1;
}
.form-item label,
.review-item label {
  margin-bottom: 8px;
  font-weight: 600;
  color: #555;
  font-size: 14px;
}
.form-item select,
.form-item input {
  padding: 10px 12px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 14px;
  width: 100%;
  box-sizing: border-box;
}
.form-item input:focus,
.form-item select:focus {
  outline: none;
  border-color: #007bff;
  box-shadow: 0 0 0 2px rgba(0, 123, 255, 0.25);
}

/* Review Grid */
.review-card .review-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.review-item {
  display: flex;
  flex-direction: column;
}
.review-item.full-span {
  grid-column: 1 / -1;
}
.review-item input,
.review-item textarea {
  padding: 10px 12px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 14px;
  width: 100%;
  box-sizing: border-box;
}
.review-item textarea {
  font-family: inherit;
  line-height: 1.5;
  resize: vertical;
}
.review-item textarea.code-font {
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  background-color: #f8f9fa;
}

/* Actions & Buttons */
.actions {
  margin-top: 24px;
  display: flex;
  gap: 16px;
  justify-content: center;
}
.migrate-button {
  background-color: #007bff;
  color: white;
  border: none;
  padding: 10px 20px;
  font-size: 15px;
  font-weight: bold;
  border-radius: 6px;
  cursor: pointer;
  transition:
    background-color 0.2s,
    transform 0.1s;
}
.migrate-button:hover:not(:disabled) {
  background-color: #0056b3;
}
.migrate-button:active:not(:disabled) {
  transform: scale(0.98);
}
.migrate-button:disabled {
  background-color: #a0a0a0;
  cursor: not-allowed;
  opacity: 0.7;
}
.publish-button {
  background-color: #28a745;
}
.publish-button:hover:not(:disabled) {
  background-color: #218838;
}

/* Titles and Result */
.log-title,
.review-title,
.success-title,
.error-title {
  color: #333;
  border-bottom: 1px solid #eee;
  padding-bottom: 12px;
  margin-top: 0;
  margin-bottom: 18px;
}
.success-title {
  color: #28a745;
}
.error-title {
  color: #dc3545;
}

.result-card {
  justify-content: center;
  align-items: center;
  text-align: center;
}
.result-card p {
  font-size: 16px;
  line-height: 1.6;
}
.result-card a {
  color: #007bff;
  font-weight: bold;
  word-break: break-all;
}
</style>
