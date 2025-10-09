<template>
  <div class="sites-view-container">
    <div class="layout-wrapper">
      <!-- 第一个象限：做种站点统计 -->
      <div class="quadrant glass-card glass-rounded">
        <h2 class="quadrant-title">做种站点统计</h2>
        <!-- [修改] 添加 table-wrapper 用于在极端情况下提供水平滚动 -->
        <div class="table-wrapper">
          <el-table v-loading="siteStatsLoading" :data="siteStatsData" class="stats-table glass-table"  border height="100%"
            :default-sort="{ prop: 'total_size', order: 'descending' }">
            <template #empty>
              <el-empty description="无站点数据" />
            </template>
            <el-table-column prop="site_name" label="站点名称" align="center" sortable min-width="120" />
            <el-table-column prop="torrent_count" label="做种数量" sortable align="center" />
            <el-table-column prop="total_size" label="做种总体积" sortable align="center" min-width="100">
              <template #default="scope">
                <span>{{ formatBytes(scope.row.total_size) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- 第二个象限：做种官组统计 -->
      <div class="quadrant glass-card glass-rounded">
        <h2 class="quadrant-title" style="display:flex;align-items:center;gap:10px;">
          <span>做种官组统计</span>
          <el-select v-model="selectedSite" placeholder="全部站点" clearable filterable size="small" style="width: 240px"
            @change="handleSiteChange">
            <el-option v-for="s in siteStatsData" :key="s.site_name" :label="s.site_name" :value="s.site_name" />
          </el-select>
        </h2>
        <!-- [修改] 添加 table-wrapper 用于在极端情况下提供水平滚动 -->
        <div class="table-wrapper">
          <el-table v-loading="groupStatsLoading" :data="groupStatsData" class="stats-table glass-table" border height="100%"
            :default-sort="{ prop: 'total_size', order: 'descending' }">
            <template #empty>
              <el-empty description="无官组数据" />
            </template>
            <el-table-column prop="site_name" label="所属站点" align="center" sortable width="110" />
            <el-table-column :label="selectedSite ? '官组' : '官组'" prop="group_suffix" sortable align="center" />
            <el-table-column prop="torrent_count" label="数量" sortable align="center" width="80" />
            <el-table-column prop="total_size" label="体积" sortable align="center" width="90">
              <template #default="scope">
                <span>{{ formatBytes(scope.row.total_size) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- 第三个象限：本地文件扫描 -->
      <div class="quadrant local-scan-quadrant glass-card glass-rounded">
        <div class="scan-header">
          <div class="scan-header-left">
            <h2 class="quadrant-title">本地文件扫描</h2>
            <p class="scan-description">扫描数据库中所有种子的保存路径，找出本地已删除的文件或未被任务引用的孤立文件。为防止误删除种子，所以不提供一键删除功能。</p>
          </div>
          <div class="scan-controls">
            <el-select v-model="selectedPath" clearable placeholder="选择路径(可选)" filterable size="default"
              style="width: 280px; margin-right: 10px">
              <el-option-group v-for="downloader in downloadersWithPaths" :key="downloader.id" :label="downloader.name">
                <el-option v-for="pathItem in downloader.paths" :key="pathItem.path" :label="pathItem.path"
                  :value="pathItem.path">
                  <span>{{ pathItem.path }}</span>
                  <span style="float: right; color: #8492a6; font-size: 13px">({{ pathItem.count }})</span>
                </el-option>
              </el-option-group>
            </el-select>
            <el-button type="primary" @click="startScan" :loading="scanning" :icon="Search">
              {{ selectedPath ? '扫描选定路径' : '扫描全部路径' }}
            </el-button>
          </div>
        </div>

        <!-- 扫描结果统计 -->
        <div v-if="scanResult" class="scan-summary glass-card glass-rounded">
          <el-row :gutter="16">
            <el-col :span="4">
              <div class="stat-item">
                <div class="stat-value">{{ scanResult.scan_summary.total_torrents }}</div>
                <div class="stat-label">总种子数</div>
              </div>
            </el-col>
            <el-col :span="5">
              <div class="stat-item">
                <div class="stat-value">{{ scanResult.scan_summary.total_local_items }}</div>
                <div class="stat-label">本地文件数</div>
              </div>
            </el-col>
            <el-col :span="5">
              <div class="stat-item stat-danger">
                <div class="stat-value">{{ scanResult.scan_summary.missing_count }}</div>
                <div class="stat-label">缺失文件</div>
              </div>
            </el-col>
            <el-col :span="5">
              <div class="stat-item stat-warning">
                <div class="stat-value">{{ scanResult.scan_summary.orphaned_count }}</div>
                <div class="stat-label">孤立文件</div>
              </div>
            </el-col>
            <el-col :span="5">
              <div class="stat-item stat-success">
                <div class="stat-value">{{ scanResult.scan_summary.synced_count }}</div>
                <div class="stat-label">正常做种</div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 结果详情 -->
        <div v-if="scanResult" class="scan-results glass-card glass-rounded">
          <div style="display: flex; align-items: center; gap: 12px; ">
            <el-tabs v-model="activeTab" style="flex: 0 0 auto;">
              <el-tab-pane name="missing">
                <template #label>
                  <span class="tab-label">
                    缺失文件
                    <el-badge v-if="scanResult.scan_summary.missing_count > 0"
                      :value="scanResult.scan_summary.missing_count" type="danger" :max="999999" />
                  </span>
                </template>
              </el-tab-pane>
              <el-tab-pane name="orphaned">
                <template #label>
                  <span class="tab-label">
                    孤立文件
                    <el-badge v-if="scanResult.scan_summary.orphaned_count > 0"
                      :value="scanResult.scan_summary.orphaned_count" type="warning" :max="999999" />
                  </span>
                </template>
              </el-tab-pane>
              <el-tab-pane name="synced">
                <template #label>
                  <span class="tab-label">
                    正常做种
                    <el-badge v-if="scanResult.scan_summary.synced_count > 0"
                      :value="scanResult.scan_summary.synced_count" type="success" :max="999999" />
                  </span>
                </template>
              </el-tab-pane>
            </el-tabs>
            <el-select v-model="pathFilter" placeholder="筛选路径" clearable filterable style="width: 240px;">
              <el-option v-for="path in allPaths" :key="path" :label="path" :value="path" />
            </el-select>
          </div>

          <div class="tab-content-area">
            <div v-if="activeTab === 'missing'" class="tab-content">
              <el-table :data="filteredMissingFiles" class="glass-table glass-transition" height="100%"
                :default-sort="{ prop: 'size', order: 'descending' }">
                <el-table-column prop="name" label="种子名称" show-overflow-tooltip align="left" header-align="center" />
                <el-table-column prop="save_path" label="保存路径"  align="center" width="250" show-overflow-tooltip
                  header-align="center" />
                <el-table-column prop="size" label="大小" width="110" sortable align="center">
                  <template #default="{ row }">
                    {{ formatBytes(row.size) }}
                  </template>
                </el-table-column>
                <el-table-column prop="downloader_name" label="下载器" width="120" align="center" />
              </el-table>
            </div>

            <div v-if="activeTab === 'orphaned'" class="tab-content">
              <el-table :data="filteredOrphanedFiles" class="glass-table glass-transition" height="100%"
                :default-sort="{ prop: 'size', order: 'descending' }">
                <el-table-column prop="name" label="文件/文件夹名称" show-overflow-tooltip align="left"
                  header-align="center" />
                <el-table-column prop="path" label="所在路径" width="250" align="center" show-overflow-tooltip 
                  header-align="center" />
                <el-table-column prop="size" label="大小" width="120" sortable align="center">
                  <template #default="{ row }">
                    {{ row.size ? formatBytes(row.size) : '未知' }}
                  </template>
                </el-table-column>
                <el-table-column prop="is_file" label="类型" width="120" align="center" header-align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.is_file ? 'success' : 'info'" size="small">
                      {{ row.is_file ? '文件' : '文件夹' }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div v-if="activeTab === 'synced'" class="tab-content">
              <el-table :data="filteredSyncedTorrents" class="glass-table glass-transition" height="100%">
                <el-table-column prop="name" label="名称" show-overflow-tooltip align="left" header-align="center" />
                <el-table-column prop="path" label="路径" width="250" show-overflow-tooltip align="center"
                  header-align="center" />
                <el-table-column prop="torrents_count" label="任务数" width="120" align="center" header-align="center">
                  <template #default="{ row }">
                    <el-tag v-if="row.torrents_count > 0" type="warning" size="small">
                      {{ row.torrents_count }}
                    </el-tag>
                    <span v-else>{{ row.torrents_count }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="下载器" width="120" align="center" header-align="center">
                  <template #default="{ row }">
                    <el-tag v-for="(name, index) in row.downloader_names" :key="index" size="small"
                      style="margin-right: 4px">
                      {{ name }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>

        <!-- 加载中状态 -->
        <div v-if="scanning" v-loading="scanning" element-loading-text="正在扫描本地文件..."
          element-loading-background="transparent" class="loading-container">
        </div>

        <!-- 空状态 -->
        <div v-if="!scanResult && !scanning"
          style="display: flex; align-items: center; justify-content: center; flex: 1">
          <el-empty description="点击扫描按钮进行本地文件检查" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, defineEmits, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import axios from 'axios'

interface SiteStat {
  site_name: string
  torrent_count: number
  total_size: number
}

interface GroupStat {
  site_name: string
  group_suffix: string
  torrent_count: number
  total_size: number
}

interface PathItem {
  path: string
  count: number
}

interface Downloader {
  id: string | number
  name: string
  paths: PathItem[]
}

interface ScanSummary {
  total_torrents: number
  total_local_items: number
  missing_count: number
  orphaned_count: number
  synced_count: number
}

interface MissingFile {
  name: string
  save_path: string
  size: number
  downloader_name: string
}

interface OrphanedFile {
  name: string
  path: string
  size?: number
  is_file: boolean
  full_path: string
}

interface SyncedTorrent {
  name: string
  path: string
  torrents_count: number
  downloader_names: string[]
}

interface ScanResult {
  scan_summary: ScanSummary
  missing_files: MissingFile[]
  orphaned_files: OrphanedFile[]
  synced_torrents: SyncedTorrent[]
}

const emits = defineEmits<{
  ready: [refreshFn: () => Promise<void>]
}>()

const siteStatsLoading = ref(true)
const groupStatsLoading = ref(true)
const siteStatsData = ref<SiteStat[]>([])
const groupStatsData = ref<GroupStat[]>([])
const selectedSite = ref('')

// 本地扫描相关
const scanning = ref(false)
const activeTab = ref('missing')
const scanResult = ref<ScanResult | null>(null)
const selectedPath = ref<string>('')
const downloadersWithPaths = ref<Downloader[]>([])

// 路径筛选（共用一个）
const pathFilter = ref<string>('')

// 计算属性：获取所有路径的并集
const allPaths = computed(() => {
  if (!scanResult.value) return []

  const paths = new Set<string>()

  // 收集缺失文件的路径
  if (scanResult.value.missing_files) {
    scanResult.value.missing_files.forEach(f => paths.add(f.save_path))
  }

  // 收集孤立文件的路径
  if (scanResult.value.orphaned_files) {
    scanResult.value.orphaned_files.forEach(f => paths.add(f.path))
  }

  // 收集正常做种的路径
  if (scanResult.value.synced_torrents) {
    scanResult.value.synced_torrents.forEach(t => paths.add(t.path))
  }

  return Array.from(paths).sort()
})

// 计算属性：根据筛选条件过滤数据
const filteredMissingFiles = computed(() => {
  if (!scanResult.value?.missing_files) return []
  if (!pathFilter.value) return scanResult.value.missing_files
  return scanResult.value.missing_files.filter(f => f.save_path === pathFilter.value)
})

const filteredOrphanedFiles = computed(() => {
  if (!scanResult.value?.orphaned_files) return []
  if (!pathFilter.value) return scanResult.value.orphaned_files
  return scanResult.value.orphaned_files.filter(f => f.path === pathFilter.value)
})

const filteredSyncedTorrents = computed(() => {
  if (!scanResult.value?.synced_torrents) return []
  if (!pathFilter.value) return scanResult.value.synced_torrents
  return scanResult.value.synced_torrents.filter(t => t.path === pathFilter.value)
})

const formatBytes = (bytes: number, decimals = 2): string => {
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

// 获取下载器路径列表
const fetchDownloadersWithPaths = async () => {
  try {
    const res = await axios.get<{ downloaders: Downloader[] }>('/api/local_query/downloaders_with_paths')
    downloadersWithPaths.value = res.data.downloaders || []
  } catch (error) {
    console.error('获取路径列表失败:', error)
  }
}

// 获取缓存的扫描结果
const fetchCachedScanResult = async () => {
  try {
    const res = await axios.get<ScanResult>('/api/local_query/scan/cache')
    scanResult.value = res.data
    console.log('已加载缓存的扫描结果')
  } catch (error) {
    // 404表示没有缓存，这是正常的，不需要报错
    if (axios.isAxiosError(error) && error.response?.status !== 404) {
      console.error('获取缓存扫描结果失败:', error)
    }
  }
}

// 开始扫描
const startScan = async () => {
  scanning.value = true
  scanResult.value = null
  try {
    const url = selectedPath.value
      ? `/api/local_query/scan?path=${encodeURIComponent(selectedPath.value)}`
      : '/api/local_query/scan'
    const res = await axios.post<ScanResult>(url)
    scanResult.value = res.data
    ElMessage.success('扫描完成！')
  } catch (error) {
    console.error('扫描失败:', error)
    ElMessage.error('扫描失败，请查看控制台获取详情')
  } finally {
    scanning.value = false
  }
}

const refreshAllData = async () => {
  await Promise.all([fetchSiteStats(), fetchGroupStats(), fetchDownloadersWithPaths(), fetchCachedScanResult()])
}

onMounted(() => {
  refreshAllData()
  emits('ready', refreshAllData)
})
</script>

<style scoped lang="scss">
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
}

.layout-wrapper {
  flex-grow: 1;
  position: relative;
  display: grid;
  /* 默认（大屏幕）状态：左侧宽度等于单行高度，使左侧区域看起来像正方形 */
  grid-template-columns: minmax(300px, calc((100vh - 90px) / 2)) 1fr;
  grid-template-rows: 1fr 1fr;
  gap: 20px;
  min-height: 0;
}

.quadrant {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 15px;
  overflow: hidden;
  min-height: 300px;
}

/* 第一、二个象限（做种站点、做种官组）在左侧上下排列 */
.quadrant:nth-child(1),
.quadrant:nth-child(2) {
  grid-column: 1;
}

/* 第三个象限（待定内容）在右侧，跨越两行 */
.quadrant:nth-child(3) {
  grid-column: 2;
  grid-row: 1 / 3;
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
  background-color: rgba(255, 255, 255, 0.3) !important;
}

:deep(.el-table) {
  height: 100% !important;
}

/* [新增] 表格包装层，用于提供水平滚动 */
.table-wrapper {
  overflow-x: auto;
  position: relative;
}

/* 本地扫描区块特殊样式 */
.local-scan-quadrant {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.scan-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-shrink: 0;
  gap: 20px;
}

.scan-header-left {
  flex: 1;
  min-width: 0;
}

.scan-header-left .quadrant-title {
  margin-bottom: 6px;
}

.scan-description {
  margin: 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
}

.scan-controls {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.scan-summary {
  padding: 10px;
  flex-shrink: 0;
}

.stat-item {
  text-align: center;
  padding: 12px;
  border-radius: 6px;
  transition: all 0.3s;
}

.stat-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  margin-bottom: 6px;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  font-weight: 500;
}

.stat-danger .stat-value {
  color: #f56c6c;
}

.stat-warning .stat-value {
  color: #e6a23c;
}

.stat-success .stat-value {
  color: #67c23a;
}

.scan-results {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 12px;
}

.tab-content-area {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.tab-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.glass-transition {
  background-color: rgba(255, 255, 255, 0.3) !important;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.loading-container {
  flex: 1;
  min-height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
}

:deep(.el-tabs__header) {
  margin: 0;
}

:deep(.el-tabs__item) {
  padding: 0 15px!important;
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
    padding: 15px;
    /* 在小屏幕上可以减小一些边距 */
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
