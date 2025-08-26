<template>
  <div class="cross-seed-container">
    <h1 class="title">种子迁移工具</h1>

    <div class="form-card">
      <div class="form-grid">
        <!-- 源站点选择 -->
        <div class="form-item">
          <label for="source-site">源站点 (需配置Cookie)</label>
          <select id="source-site" v-model="sourceSite">
            <option disabled value="">请选择源站点</option>
            <option v-for="site in sourceSitesList" :key="site" :value="site">{{ site }}</option>
          </select>
        </div>

        <!-- 目标站点选择 -->
        <div class="form-item">
          <label for="target-site">目标站点 (需配置Passkey)</label>
          <select id="target-site" v-model="targetSite">
            <option disabled value="">请选择目标站点</option>
            <option v-for="site in targetSitesList" :key="site" :value="site">{{ site }}</option>
          </select>
        </div>

        <!-- 种子名称/ID输入 -->
        <div class="form-item full-width">
          <label for="search-term">种子名称 或 源站ID</label>
          <input
            type="text"
            id="search-term"
            v-model="searchTerm"
            placeholder="输入完整的种子名称或其在源站的ID"
          />
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="actions">
        <button @click="startMigration" :disabled="isLoading" class="migrate-button">
          {{ isLoading ? '正在迁移中...' : '开始迁移' }}
        </button>
      </div>
    </div>

    <!-- 日志输出区域 -->
    <div v-if="logOutput" class="log-card">
      <h2 class="log-title">迁移日志</h2>
      <pre class="log-output">{{ logOutput }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios' // 确保你项目中安装了axios

// --- 响应式状态定义 ---
const sourceSitesList = ref([])
const targetSitesList = ref([])
const sourceSite = ref('')
const targetSite = ref('')
const searchTerm = ref('')
const isLoading = ref(false)
const logOutput = ref('')

// --- API 函数 ---

/**
 * 从后端获取已配置的站点列表
 */
const fetchSitesList = async () => {
  try {
    const response = await axios.get('/api/sites_list')
    sourceSitesList.value = response.data.source_sites
    targetSitesList.value = response.data.target_sites
  } catch (error) {
    console.error('获取站点列表失败:', error)
    logOutput.value = '错误：无法从服务器获取站点列表。请检查后端服务是否正常运行。'
  }
}

/**
 * 开始迁移任务
 */
const startMigration = async () => {
  // 基本校验
  if (!sourceSite.value || !targetSite.value || !searchTerm.value.trim()) {
    logOutput.value = '请填写所有必填项：源站点、目标站点和种子名称/ID。'
    return
  }
  if (sourceSite.value === targetSite.value) {
    logOutput.value = '源站点和目标站点不能相同。'
    return
  }

  isLoading.value = true
  logOutput.value = '正在初始化迁移任务，请稍候...'

  try {
    const response = await axios.post('/api/migrate_torrent', {
      sourceSite: sourceSite.value,
      targetSite: targetSite.value,
      searchTerm: searchTerm.value.trim(),
    })
    // 将后端的日志直接显示出来
    logOutput.value = response.data.logs
  } catch (error) {
    console.error('迁移任务失败:', error)
    if (error.response && error.response.data && error.response.data.logs) {
      logOutput.value = `请求失败:\n${error.response.data.logs}`
    } else {
      logOutput.value = `发生未知网络错误: ${error.message}`
    }
  } finally {
    isLoading.value = false
  }
}

// --- 生命周期钩子 ---

// 组件挂载后，自动获取站点列表
onMounted(() => {
  fetchSitesList()
})
</script>

<style scoped>
.cross-seed-container {
  padding: 24px;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  max-width: 900px;
  margin: 0 auto;
}

.title {
  text-align: center;
  color: #333;
  margin-bottom: 24px;
}

.form-card,
.log-card {
  background-color: #ffffff;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  padding: 24px;
  margin-bottom: 24px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.form-item {
  display: flex;
  flex-direction: column;
}

.form-item.full-width {
  grid-column: 1 / -1;
}

.form-item label {
  margin-bottom: 8px;
  font-weight: 600;
  color: #555;
}

.form-item select,
.form-item input {
  padding: 10px 12px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 16px;
  width: 100%;
}

.form-item input:focus,
.form-item select:focus {
  outline: none;
  border-color: #007bff;
  box-shadow: 0 0 0 2px rgba(0, 123, 255, 0.25);
}

.actions {
  margin-top: 24px;
  text-align: center;
}

.migrate-button {
  background-color: #007bff;
  color: white;
  border: none;
  padding: 12px 24px;
  font-size: 16px;
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
}

.log-title {
  color: #333;
  border-bottom: 1px solid #eee;
  padding-bottom: 12px;
  margin-bottom: 12px;
}

.log-output {
  background-color: #f5f5f5;
  color: #333;
  padding: 16px;
  border-radius: 6px;
  white-space: pre-wrap; /* 自动换行 */
  word-wrap: break-word;
  max-height: 400px;
  overflow-y: auto;
  font-family: 'Courier New', Courier, monospace;
}
</style>
