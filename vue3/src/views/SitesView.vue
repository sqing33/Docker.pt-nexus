<template>
  <div class="sites-view-container">
    <div class="layout-wrapper">
      <div class="quadrant">
        <h2 class="quadrant-title">做种站点统计</h2>
        <el-table
          v-loading="siteStatsLoading"
          :data="siteStatsData"
          class="stats-table"
          border
          stripe
          height="100%"
          :default-sort="{ prop: 'total_size', order: 'descending' }"
        >
          <template #empty>
            <el-empty description="无站点数据" />
          </template>
          <el-table-column prop="site_name" label="站点名称" sortable min-width="150" />
          <el-table-column
            prop="torrent_count"
            label="做种数量"
            sortable
            align="right"
            header-align="right"
            width="120"
          />
          <el-table-column
            prop="total_size"
            label="做种总体积"
            sortable
            align="right"
            header-align="right"
            min-width="160"
          >
            <template #default="scope">
              <span>{{ formatBytes(scope.row.total_size) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="quadrant">
        <h2 class="quadrant-title">做种官组统计</h2>
        <el-table
          v-loading="groupStatsLoading"
          :data="groupStatsData"
          class="stats-table"
          border
          stripe
          height="100%"
          :default-sort="{ prop: 'total_size', order: 'descending' }"
        >
          <template #empty>
            <el-empty description="无官组数据" />
          </template>
          <el-table-column prop="site_name" label="所属站点" sortable min-width="150" />
          <el-table-column prop="group_suffix" label="官组" sortable min-width="150" />
          <el-table-column
            prop="torrent_count"
            label="种子数量"
            sortable
            align="right"
            header-align="right"
            width="120"
          />
          <el-table-column
            prop="total_size"
            label="种子体积"
            sortable
            align="right"
            header-align="right"
            min-width="160"
          >
            <template #default="scope">
              <span>{{ formatBytes(scope.row.total_size) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="quadrant">
        <h2 class="quadrant-title">待定内容</h2>
        <div style="display: flex; align-items: center; justify-content: center; height: 100%">
          <el-empty description="此区域内容待定" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, defineEmits } from 'vue'

const emits = defineEmits(['ready'])

const siteStatsLoading = ref(true)
const groupStatsLoading = ref(true)
const siteStatsData = ref([])
const groupStatsData = ref([])

const formatBytes = (bytes, decimals = 2) => {
  if (!+bytes) return '0 Bytes'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}

// 获取站点统计数据
const fetchSiteStats = async () => {
  siteStatsLoading.value = true
  try {
    const response = await fetch('/api/site_stats')
    if (!response.ok) throw new Error(`网络响应错误: ${response.status}`)
    const data = await response.json()
    siteStatsData.value = Array.isArray(data) ? data : []
  } catch (error) {
    console.error('获取站点统计数据失败:', error)
    siteStatsData.value = []
  } finally {
    siteStatsLoading.value = false
  }
}

// 获取官组统计数据
const fetchGroupStats = async () => {
  groupStatsLoading.value = true
  try {
    const response = await fetch('/api/group_stats')
    if (!response.ok) throw new Error(`网络响应错误: ${response.status}`)
    const data = await response.json()
    groupStatsData.value = Array.isArray(data) ? data : []
  } catch (error) {
    console.error('获取官组统计数据失败:', error)
    groupStatsData.value = []
  } finally {
    groupStatsLoading.value = false
  }
}

const refreshAllData = async () => {
  await Promise.all([fetchSiteStats(), fetchGroupStats()])
}

onMounted(() => {
  refreshAllData()
  emits('ready', refreshAllData)
})
</script>

<style scoped>
.sites-view-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: 20px;
  box-sizing: border-box;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  overflow: hidden;
  background-color: #f4f7f9;
}

.main-title {
  font-size: 1.8em;
  color: #333;
  margin: 0 0 15px 0;
  flex-shrink: 0;
}

.layout-wrapper {
  flex-grow: 1;
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  grid-template-rows: 1fr;
  gap: 20px;
  min-height: 0;
}

.quadrant {
  position: relative;
  display: flex;
  flex-direction: column;
  background-color: #ffffff;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.06);
  padding: 15px;
  overflow: hidden;
}

.quadrant-title {
  font-size: 1.1em;
  font-weight: 600;
  color: #444;
  margin: 0 0 10px 0;
  flex-shrink: 0;
}

.stats-table {
  width: 100%;
  flex-grow: 1;
}

:deep(.el-table) {
  height: 100% !important;
}
</style>
