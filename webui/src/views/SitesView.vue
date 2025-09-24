<template>
  <div class="sites-view-container">
    <div class="layout-wrapper">
      <!-- 第一个象限：做种站点统计 -->
      <div class="quadrant">
        <h2 class="quadrant-title">做种站点统计</h2>
        <!-- [修改] 添加 table-wrapper 用于在极端情况下提供水平滚动 -->
        <div class="table-wrapper">
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
            <el-table-column prop="site_name" label="站点名称" sortable min-width="120" />
            <el-table-column
              prop="torrent_count"
              label="做种数量"
              sortable
              align="right"
              header-align="right"
            />
            <el-table-column
              prop="total_size"
              label="做种总体积"
              sortable
              align="right"
              header-align="right"
              min-width="120"
            >
              <template #default="scope">
                <span>{{ formatBytes(scope.row.total_size) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- 第二个象限：做种官组统计 -->
      <div class="quadrant">
        <h2 class="quadrant-title" style="display:flex;align-items:center;gap:10px;">
          <span>做种官组统计</span>
          <el-select
            v-model="selectedSite"
            placeholder="全部站点"
            clearable
            filterable
            size="small"
            style="width: 240px"
            @change="handleSiteChange"
          >
            <el-option
              v-for="s in siteStatsData"
              :key="s.site_name"
              :label="s.site_name"
              :value="s.site_name"
            />
          </el-select>
        </h2>
        <!-- [修改] 添加 table-wrapper 用于在极端情况下提供水平滚动 -->
        <div class="table-wrapper">
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
            <el-table-column
              prop="site_name"
              label="所属站点"
              sortable
              min-width="80"
            />
            <el-table-column
              :label="selectedSite ? '官组' : '官组'"
              prop="group_suffix"
              sortable
              min-width="120"
            />
            <el-table-column
              prop="torrent_count"
              label="数量"
              sortable
              align="right"
              header-align="right"
              width="65"
            />
            <el-table-column
              prop="total_size"
              label="体积"
              sortable
              align="right"
              header-align="right"
              min-width="55"
            >
              <template #default="scope">
                <span>{{ formatBytes(scope.row.total_size) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- 第三个象限：待定内容 -->
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
const selectedSite = ref('')

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
    const url = selectedSite.value ? `/api/group_stats?site=${encodeURIComponent(selectedSite.value)}` : '/api/group_stats'
    const response = await fetch(url)
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

const handleSiteChange = () => {
  fetchGroupStats()
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
  /* 在小屏幕上，高度需要自适应，而不是固定为 100vh */
  min-height: 100vh;
  padding: 10px 10px 50px 10px;
  box-sizing: border-box;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  /* 在大屏幕上隐藏滚动条，但在小屏幕上需要时会显示 */
  overflow: auto;
  background-color: #f4f7f9;
}

.layout-wrapper {
  flex-grow: 1;
  position: relative;
  display: grid;
  /* 默认（大屏幕）状态：三列等宽布局 */
  grid-template-columns: repeat(3, 1fr);
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
  /* 为象限设置一个最小高度，防止在多行布局时高度不一 */
  min-height: 300px;
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

:deep(.cell) {
  padding: 0;
  text-align: center;
}

/* [新增] 表格包装层，用于提供水平滚动 */
.table-wrapper {
  overflow-x: auto;
  flex-grow: 1;
  position: relative;
}

/* --- 响应式布局 --- */

/* 屏幕宽度小于等于 1200px 时 (例如：小尺寸笔记本电脑、大尺寸平板横屏) */
@media (max-width: 1200px) {
  .layout-wrapper {
    /* 布局变为两列 */
    grid-template-columns: repeat(2, 1fr);
    /* 行高自动，允许网格向下扩展 */
    grid-template-rows: auto;
  }
}

/* 屏幕宽度小于等于 768px 时 (例如：平板竖屏、手机) */
@media (max-width: 768px) {
  .sites-view-container {
    /* 允许整个页面垂直滚动 */
    height: auto;
    overflow-y: auto;
    padding: 15px; /* 在小屏幕上可以减小一些边距 */
  }

  .layout-wrapper {
    /* 布局变为单列，所有象限垂直堆叠 */
    grid-template-columns: 1fr;
    gap: 15px;
  }

  .quadrant {
    /* 在单列模式下，可以给一个建议的高度，或者让其内容自适应 */
    height: 400px;
  }
}
</style>
