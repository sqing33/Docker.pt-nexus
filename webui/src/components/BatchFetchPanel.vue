<template>
  <div class="batch-fetch-panel">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" center
      style="margin-bottom: 15px"></el-alert>

    <!-- 搜索和控制栏 -->
    <div class="search-and-controls">
      <el-input v-model="nameSearch" placeholder="搜索名称..." clearable class="search-input"
        style="width: 300px; margin-right: 15px;" />

      <!-- 筛选按钮 -->
      <el-button type="primary" @click="openFilterDialog" plain style="margin-right: 15px;">
        筛选
      </el-button>
      <div v-if="hasActiveFilters" class="current-filters"
        style="margin-right: 15px; display: flex; align-items: center;">
        <el-tag type="info" size="default" effect="plain">{{ currentFilterText }}</el-tag>
        <el-button type="danger" link style="padding: 0; margin-left: 8px;" @click="clearFilters">清除</el-button>
      </div>

      <!-- 设置优先级按钮 -->
      <el-button type="warning" @click="openPrioritySettingsDialog" plain style="margin-right: 15px;">
        <el-icon style="margin-right: 5px;">
          <Setting />
        </el-icon>
        设置优先级
      </el-button>

      <!-- 批量获取按钮 -->
      <el-button type="success" @click="openBatchFetchDialog" plain style="margin-right: 15px;"
        :disabled="selectedRows.length === 0">
        批量获取数据 ({{ selectedRows.length }})
      </el-button>

      <!-- 查看进度按钮 -->
      <el-button v-if="currentTaskId" type="info" @click="openProgressDialog" plain style="margin-right: 15px;">
        查看进度
      </el-button>

      <div class="pagination-controls" v-if="tableData.length > 0">
        <el-pagination v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]"
          :total="total" layout="total, sizes, prev, pager, next, jumper" @size-change="handleSizeChange"
          @current-change="handleCurrentChange" background>
        </el-pagination>
      </div>
    </div>

    <!-- 种子列表表格 -->
    <div class="table-container">
      <el-table :data="tableData" v-loading="loading" border style="width: 100%" empty-text="暂无种子数据" height="100%"
        @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="55" align="center"></el-table-column>
        <el-table-column prop="name" label="种子名称" min-width="450" show-overflow-tooltip></el-table-column>
        <el-table-column prop="save_path" label="保存路径" width="220" show-overflow-tooltip></el-table-column>
        <el-table-column prop="site_count" label="站点数" width="100" align="center">
          <template #default="scope">
            {{ Object.keys(scope.row.sites || {}).length }}
          </template>
        </el-table-column>
        <el-table-column prop="state" label="状态" width="150" align="center"></el-table-column>
        <el-table-column label="已有源站点" min-width="200">
          <template #default="scope">
            <el-tag v-for="(siteData, siteName) in getSourceSites(scope.row.sites)" :key="siteName" size="small"
              type="success" style="margin: 2px;">
              {{ siteName }}
            </el-tag>
            <span v-if="Object.keys(getSourceSites(scope.row.sites)).length === 0" style="color: #909399;">
              无可用源站点
            </span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 筛选器弹窗 -->
    <div v-if="filterDialogVisible" class="filter-overlay" @click.self="filterDialogVisible = false">
      <el-card class="filter-card">
        <template #header>
          <div class="filter-card-header">
            <span>筛选选项</span>
            <el-button type="danger" circle @click="filterDialogVisible = false" plain>X</el-button>
          </div>
        </template>
        <div class="filter-card-body">
          <el-divider content-position="left">保存路径</el-divider>
          <div class="path-tree-container">
            <el-tree ref="pathTreeRef" :data="pathTreeData" show-checkbox node-key="path" default-expand-all
              check-on-click-node :props="{ class: 'path-tree-node' }" />
          </div>

          <el-divider content-position="left">状态</el-divider>
          <el-checkbox-group v-model="tempFilters.states">
            <el-checkbox v-for="state in uniqueStates" :key="state" :label="state">{{ state }}</el-checkbox>
          </el-checkbox-group>

          <el-divider content-position="left">下载器</el-divider>
          <el-checkbox-group v-model="tempFilters.downloaderIds">
            <el-checkbox v-for="downloader in downloadersList" :key="downloader.id" :label="downloader.id">
              {{ downloader.name }}
            </el-checkbox>
          </el-checkbox-group>
        </div>
        <div class="filter-card-footer">
          <el-button @click="filterDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="applyFilters">确认</el-button>
        </div>
      </el-card>
    </div>

    <!-- 批量获取配置弹窗 -->
    <div v-if="batchFetchDialogVisible" class="modal-overlay">
      <el-card class="batch-fetch-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>批量获取种子数据</span>
            <el-button type="danger" circle @click="closeBatchFetchDialog" plain>X</el-button>
          </div>
        </template>
        <div class="batch-fetch-content">
          <div class="config-section">
            <h3>已选择 {{ selectedRows.length }} 个种子</h3>
            <p style="color: #909399; font-size: 13px; margin-top: 5px;">
              系统将按名称聚合，逐个从源站点获取种子数据并存储到数据库
            </p>
          </div>
        </div>
        <div class="batch-fetch-footer">
          <el-button @click="closeBatchFetchDialog">取消</el-button>
          <el-button type="primary" @click="startBatchFetch">
            开始批量获取
          </el-button>
        </div>
      </el-card>
    </div>

    <!-- 源站点优先级设置弹窗 -->
    <div v-if="prioritySettingsDialogVisible" class="modal-overlay">
      <el-card class="priority-settings-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>源站点优先级设置</span>
            <el-button type="danger" circle @click="closePrioritySettingsDialog" plain>X</el-button>
          </div>
        </template>
        <div class="priority-settings-content">
          <el-alert type="info" show-icon :closable="false" style="margin-bottom: 20px;">
            <template #title>
              设置批量获取种子数据时的源站点优先级顺序，系统将按顺序查找第一个可用的源站点
            </template>
          </el-alert>

          <div class="priority-section">
            <p style="color: #606266; font-size: 14px; margin-bottom: 10px; font-weight: 600;">
              优先级顺序（拖拽调整）：
            </p>
            <div class="priority-list" v-loading="priorityLoading">
              <el-tag v-for="(site, index) in sourceSitesPriority" :key="site" :type="getSitePriorityType(index)"
                size="large" closable @close="removeSiteFromPriority(site)" draggable="true"
                @dragstart="handleDragStart(index)" @dragover.prevent @drop="handleDrop(index)"
                style="margin: 5px; cursor: move; user-select: none;">
                {{ index + 1 }}. {{ site }}
              </el-tag>
              <span v-if="sourceSitesPriority.length === 0" style="color: #909399; margin-left: 10px;">
                暂无源站点，请从下方添加
              </span>
            </div>

            <el-divider />

            <p style="color: #606266; font-size: 14px; margin-bottom: 10px; font-weight: 600;">
              可用源站点列表（点击添加）：
            </p>
            <div class="available-sites" v-loading="priorityLoading">
              <el-tag v-for="site in availableSourceSites" :key="site" type="info" size="default"
                @click="addSiteToPriority(site)" style="margin: 5px; cursor: pointer;">
                {{ site }}
              </el-tag>
              <span v-if="availableSourceSites.length === 0" style="color: #909399; margin-left: 10px;">
                所有源站点已添加
              </span>
            </div>
          </div>
        </div>
        <div class="priority-settings-footer">
          <el-button @click="closePrioritySettingsDialog">取消</el-button>
          <el-button type="primary" @click="savePrioritySettings" :loading="prioritySaving">
            保存设置
          </el-button>
        </div>
      </el-card>
    </div>

    <!-- 进度查看弹窗 -->
    <div v-if="progressDialogVisible" class="modal-overlay">
      <el-card class="progress-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>批量获取进度 {{ progress.isRunning ? '(进行中...)' : '(已完成)' }}</span>
            <div class="progress-header-controls">
              <el-button v-if="progress.isRunning" type="warning" size="small" @click="stopAutoRefresh">
                停止自动刷新
              </el-button>
              <el-button v-else type="primary" size="small" @click="refreshProgress">
                刷新
              </el-button>
              <el-button type="danger" circle @click="closeProgressDialog" plain>X</el-button>
            </div>
          </div>
        </template>
        <div class="progress-content">
          <!-- 进度概览 -->
          <div class="progress-summary">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="总数">{{ progress.total }}</el-descriptions-item>
              <el-descriptions-item label="已处理">{{ progress.processed }}</el-descriptions-item>
              <el-descriptions-item label="成功">
                <el-tag type="success" size="small">{{ progress.success }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="失败">
                <el-tag type="danger" size="small">{{ progress.failed }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="跳过">
                <el-tag type="info" size="small">{{ progress.skipped }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="progress.isRunning ? 'warning' : 'success'" size="small">
                  {{ progress.isRunning ? '进行中' : '已完成' }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>

            <el-progress :percentage="progressPercentage" :status="progressStatus" style="margin-top: 15px;" />
          </div>

          <!-- 详细结果列表 -->
          <el-divider content-position="left">处理详情</el-divider>
          <div class="results-table-container">
            <el-table :data="progress.results" style="width: 100%" size="small" stripe max-height="400">
              <el-table-column prop="name" label="种子名称" min-width="300" show-overflow-tooltip />
              <el-table-column prop="status" label="状态" width="100" align="center">
                <template #default="scope">
                  <el-tag :type="getResultStatusType(scope.row.status)" size="small">
                    {{ getResultStatusText(scope.row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="source_site" label="源站点" width="120" align="center" />
              <el-table-column prop="reason" label="失败原因" min-width="200" show-overflow-tooltip />
            </el-table>
          </div>
        </div>
        <div class="progress-footer">
          <el-button @click="closeProgressDialog">关闭</el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import type { ElTree } from 'element-plus'

const emit = defineEmits<{
  (e: 'cancel'): void
}>()

interface PathNode {
  path: string
  label: string
  children?: PathNode[]
}

interface Downloader {
  id: string;
  name: string;
  enabled?: boolean;
}

interface SiteData {
  comment: string
  state: string
  migration: number
}

interface Torrent {
  name: string
  save_path: string
  size: number
  progress: number
  state: string
  sites: Record<string, SiteData>
  downloader_ids: string[]
}

interface SiteStatus {
  name: string
  has_cookie: boolean
  is_source: boolean
  is_target: boolean
}

interface BatchProgress {
  total: number
  processed: number
  success: number
  failed: number
  skipped: number
  isRunning: boolean
  results: Array<{
    name: string
    status: string
    source_site?: string
    reason?: string
  }>
}

const tableData = ref<Torrent[]>([])
const loading = ref<boolean>(true)
const error = ref<string | null>(null)

const selectedRows = ref<Torrent[]>([])
const batchFetchDialogVisible = ref<boolean>(false)
const progressDialogVisible = ref<boolean>(false)

// 源站点优先级设置相关
const prioritySettingsDialogVisible = ref<boolean>(false)
const priorityLoading = ref<boolean>(false)
const prioritySaving = ref<boolean>(false)
const allSourceSites = ref<SiteStatus[]>([])
const sourceSitesPriority = ref<string[]>([])
const draggedIndex = ref<number | null>(null)

const pathTreeRef = ref<InstanceType<typeof ElTree> | null>(null)
const pathTreeData = ref<PathNode[]>([])
const uniquePaths = ref<string[]>([])
const uniqueStates = ref<string[]>([])
const downloadersList = ref<Downloader[]>([])

const currentPage = ref<number>(1)
const pageSize = ref<number>(20)
const total = ref<number>(0)

const nameSearch = ref<string>('')

const filterDialogVisible = ref<boolean>(false)
const activeFilters = ref({
  paths: [] as string[],
  states: [] as string[],
  downloaderIds: [] as string[]
})
const tempFilters = ref({ ...activeFilters.value })

// 任务进度相关
const currentTaskId = ref<string | null>(null)
const progress = ref<BatchProgress>({
  total: 0,
  processed: 0,
  success: 0,
  failed: 0,
  skipped: 0,
  isRunning: false,
  results: []
})
const refreshTimer = ref<ReturnType<typeof setInterval> | null>(null)
const REFRESH_INTERVAL = 3000 // 3秒刷新一次

const currentFilterText = computed(() => {
  const filters = activeFilters.value
  const filterTexts = []

  if (filters.paths && filters.paths.length > 0) {
    filterTexts.push(`路径: ${filters.paths.length}`)
  }

  if (filters.states && filters.states.length > 0) {
    filterTexts.push(`状态: ${filters.states.length}`)
  }

  if (filters.downloaderIds && filters.downloaderIds.length > 0) {
    filterTexts.push(`下载器: ${filters.downloaderIds.length}`)
  }

  return filterTexts.join(', ')
})

const hasActiveFilters = computed(() => {
  const filters = activeFilters.value
  return (
    (filters.paths && filters.paths.length > 0) ||
    (filters.states && filters.states.length > 0) ||
    (filters.downloaderIds && filters.downloaderIds.length > 0)
  )
})

const availableSourceSites = computed(() => {
  return allSourceSites.value
    .filter(s => s.is_source && s.has_cookie)
    .map(s => s.name)
    .filter(name => !sourceSitesPriority.value.includes(name))
})

const progressPercentage = computed(() => {
  if (progress.value.total === 0) return 0
  return Math.round((progress.value.processed / progress.value.total) * 100)
})

const progressStatus = computed(() => {
  if (progress.value.isRunning) return undefined
  if (progress.value.failed > 0) return 'exception'
  return 'success'
})

const buildPathTree = (paths: string[]): PathNode[] => {
  const root: PathNode[] = []
  const nodeMap = new Map<string, PathNode>()
  paths.sort().forEach((fullPath) => {
    const parts = fullPath.replace(/^\/|\/$/g, '').split('/')
    let currentPath = ''
    let parentChildren = root
    parts.forEach((part, index) => {
      currentPath = index === 0 ? `/${part}` : `${currentPath}/${part}`
      if (!nodeMap.has(currentPath)) {
        const newNode: PathNode = {
          path: index === parts.length - 1 ? fullPath : currentPath,
          label: part,
          children: [],
        }
        nodeMap.set(currentPath, newNode)
        parentChildren.push(newNode)
      }
      const currentNode = nodeMap.get(currentPath)!
      parentChildren = currentNode.children!
    })
  })
  nodeMap.forEach((node) => {
    if (node.children && node.children.length === 0) {
      delete node.children
    }
  })
  return root
}

const fetchData = async () => {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      page_size: pageSize.value.toString(),
      search: nameSearch.value,
      path_filters: JSON.stringify(activeFilters.value.paths),
      state_filters: JSON.stringify(activeFilters.value.states),
      downloader_filters: JSON.stringify(activeFilters.value.downloaderIds)
    })

    const response = await fetch(`/api/data?${params.toString()}`)

    if (!response.ok) throw new Error(`网络错误: ${response.status}`)
    const result = await response.json()

    if (!result.error) {
      // 转换数据格式以匹配现有的 Torrent 接口
      tableData.value = result.data.map((item: any) => ({
        name: item.name,
        save_path: item.save_path,
        size: item.size,
        progress: item.progress,
        state: item.state,
        sites: item.sites || {},
        downloader_ids: item.downloader_ids || []
      }))
      total.value = result.total

      // 提取唯一状态（路径现在通过专门的API获取）
      if (uniqueStates.value.length === 0 || !activeFilters.value.states.length) {
        uniqueStates.value = [...new Set(tableData.value.map((t: Torrent) => t.state))] as string[]
      }
    } else {
      error.value = result.error || '获取数据失败'
      ElMessage.error(result.error || '获取数据失败')
    }
  } catch (e: any) {
    error.value = e.message || '网络错误'
    ElMessage.error(e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

const fetchDownloadersList = async () => {
  try {
    const response = await fetch('/api/all_downloaders');
    if (!response.ok) throw new Error('无法获取下载器列表');
    const allDownloaders = await response.json();
    downloadersList.value = allDownloaders.filter((d: any) => d.enabled);
  } catch (e: any) {
    error.value = e.message;
  }
}

const fetchAllPaths = async () => {
  try {
    const params = new URLSearchParams({
      page: '1',
      page_size: '1', // 只需要获取路径信息，不需要实际数据
      path_filters: JSON.stringify([]), // 清空路径筛选以获取所有路径
      state_filters: JSON.stringify([]), // 清空状态筛选
      downloader_filters: JSON.stringify([]) // 清空下载器筛选
    });

    const response = await fetch(`/api/data?${params.toString()}`);

    if (!response.ok) throw new Error('无法获取路径列表');
    const result = await response.json();

    if (result.unique_paths) {
      uniquePaths.value = result.unique_paths;
      pathTreeData.value = buildPathTree(uniquePaths.value);
    }
  } catch (e: any) {
    console.error('获取路径列表失败:', e);
  }
}

const handleSizeChange = (val: number) => {
  pageSize.value = val
  currentPage.value = 1
  fetchData()
}

const handleCurrentChange = (val: number) => {
  currentPage.value = val
  fetchData()
}

const clearFilters = () => {
  activeFilters.value = {
    paths: [],
    states: [],
    downloaderIds: []
  }
  currentPage.value = 1

  // 保存清空的筛选条件到配置
  saveFiltersToConfig()

  fetchData()
}

const openFilterDialog = () => {
  tempFilters.value = { ...activeFilters.value }
  filterDialogVisible.value = true
  nextTick(() => {
    if (pathTreeRef.value && activeFilters.value.paths) {
      pathTreeRef.value.setCheckedKeys(activeFilters.value.paths, false)
    }
  })
}

const applyFilters = () => {
  if (pathTreeRef.value) {
    const selectedPaths = pathTreeRef.value.getCheckedKeys(true) as string[]
    tempFilters.value.paths = selectedPaths
  }

  activeFilters.value = { ...tempFilters.value }
  filterDialogVisible.value = false
  currentPage.value = 1

  // 保存筛选条件到配置
  saveFiltersToConfig()

  fetchData()
}

const saveFiltersToConfig = async () => {
  try {
    await fetch('/api/config/batch_fetch_filters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        batch_fetch_filters: activeFilters.value
      })
    })
  } catch (e: any) {
    console.error('保存筛选条件失败:', e)
  }
}

const loadFiltersFromConfig = async () => {
  try {
    const response = await fetch('/api/config/batch_fetch_filters')
    if (response.ok) {
      const result = await response.json()
      if (result.success && result.data) {
        activeFilters.value = result.data
      }
    }
  } catch (e: any) {
    console.error('加载筛选条件失败:', e)
  }
}

const handleSelectionChange = (selection: Torrent[]) => {
  selectedRows.value = selection
}

const getSourceSites = (sites: Record<string, SiteData>) => {
  const sourceSites: Record<string, SiteData> = {}
  for (const [siteName, siteData] of Object.entries(sites || {})) {
    if (siteData.migration === 1 || siteData.migration === 3) {
      sourceSites[siteName] = siteData
    }
  }
  return sourceSites
}

const openBatchFetchDialog = () => {
  if (selectedRows.value.length === 0) {
    ElMessage.warning('请先选择要获取数据的种子')
    return
  }
  batchFetchDialogVisible.value = true
}

const closeBatchFetchDialog = () => {
  batchFetchDialogVisible.value = false
}

const openPrioritySettingsDialog = async () => {
  prioritySettingsDialogVisible.value = true
  await loadPrioritySettings()
}

const closePrioritySettingsDialog = () => {
  prioritySettingsDialogVisible.value = false
}

const loadPrioritySettings = async () => {
  priorityLoading.value = true
  try {
    // 加载所有源站点
    const sitesResponse = await fetch('/api/sites/status')
    if (!sitesResponse.ok) throw new Error('无法获取站点状态列表')
    allSourceSites.value = await sitesResponse.json()

    // 加载已保存的优先级配置
    const configResponse = await fetch('/api/config/source_priority')
    if (!configResponse.ok) throw new Error('无法获取配置')
    const configResult = await configResponse.json()
    if (configResult.success) {
      sourceSitesPriority.value = configResult.data || []
    }
  } catch (e: any) {
    ElMessage.error(e.message || '加载配置失败')
  } finally {
    priorityLoading.value = false
  }
}

const savePrioritySettings = async () => {
  prioritySaving.value = true
  try {
    const response = await fetch('/api/config/source_priority', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_priority: sourceSitesPriority.value
      })
    })

    if (!response.ok) throw new Error('保存失败')
    const result = await response.json()
    if (result.success) {
      ElMessage.success('源站点优先级配置已保存')
      closePrioritySettingsDialog()
    } else {
      throw new Error(result.message || '保存失败')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '保存配置失败')
  } finally {
    prioritySaving.value = false
  }
}

const getSitePriorityType = (index: number) => {
  if (index === 0) return 'success'
  if (index === 1) return 'primary'
  if (index === 2) return 'warning'
  return 'info'
}

const addSiteToPriority = (site: string) => {
  if (!sourceSitesPriority.value.includes(site)) {
    sourceSitesPriority.value.push(site)
  }
}

const removeSiteFromPriority = (site: string) => {
  const index = sourceSitesPriority.value.indexOf(site)
  if (index > -1) {
    sourceSitesPriority.value.splice(index, 1)
  }
}

const handleDragStart = (index: number) => {
  draggedIndex.value = index
}

const handleDrop = (dropIndex: number) => {
  if (draggedIndex.value === null) return

  const draggedItem = sourceSitesPriority.value[draggedIndex.value]
  sourceSitesPriority.value.splice(draggedIndex.value, 1)
  sourceSitesPriority.value.splice(dropIndex, 0, draggedItem)

  draggedIndex.value = null
}

const startBatchFetch = async () => {
  try {
    const torrentNames = selectedRows.value.map(row => row.name)

    const response = await fetch('/api/migrate/batch_fetch_seed_data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        torrentNames
      })
    })

    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

    const result = await response.json()
    if (result.success) {
      currentTaskId.value = result.task_id
      ElMessage.success('批量获取任务已启动')
      closeBatchFetchDialog()
      openProgressDialog()
    } else {
      ElMessage.error(result.message || '批量获取任务启动失败')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '网络错误')
  }
}

const openProgressDialog = () => {
  progressDialogVisible.value = true
  startAutoRefresh()
}

const closeProgressDialog = () => {
  progressDialogVisible.value = false
  stopAutoRefresh()
}

const startAutoRefresh = () => {
  stopAutoRefresh()
  refreshProgress()

  refreshTimer.value = setInterval(async () => {
    if (progressDialogVisible.value && currentTaskId.value) {
      await refreshProgress()

      if (progress.value && !progress.value.isRunning) {
        setTimeout(() => {
          if (!progress.value.isRunning) {
            stopAutoRefresh()
          }
        }, 3000)
      }
    } else {
      stopAutoRefresh()
    }
  }, REFRESH_INTERVAL)
}

const stopAutoRefresh = () => {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

const refreshProgress = async () => {
  if (!currentTaskId.value) return

  try {
    const response = await fetch(`/api/migrate/batch_fetch_progress?task_id=${currentTaskId.value}`)

    if (response.ok) {
      const result = await response.json()
      if (result.success) {
        progress.value = result.progress
      } else {
        ElMessage.error(result.message || '获取进度失败')
      }
    }
  } catch (error: any) {
    console.error('获取进度时出错:', error)
  }
}

const getResultStatusType = (status: string) => {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'danger'
    case 'skipped': return 'info'
    default: return 'info'
  }
}

const getResultStatusText = (status: string) => {
  switch (status) {
    case 'success': return '成功'
    case 'failed': return '失败'
    case 'skipped': return '跳过'
    default: return '未知'
  }
}

onMounted(async () => {
  await fetchDownloadersList()
  await loadFiltersFromConfig()
  await fetchAllPaths() // 获取所有路径
  fetchData()
})

onUnmounted(() => {
  stopAutoRefresh()
})

watch(nameSearch, () => {
  currentPage.value = 1
  fetchData()
})
</script>

<style scoped>
.batch-fetch-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0;
  box-sizing: border-box;
}

.search-and-controls {
  display: flex;
  align-items: center;
  padding: 10px 15px;
  background-color: #ffffff;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
}

.pagination-controls {
  flex: 1;
  display: flex;
  justify-content: flex-end;
}

.table-container {
  flex: 1;
  overflow: hidden;
  min-height: 300px;
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 3000;
}

.filter-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 3000;
}

.filter-card {
  width: 600px;
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.filter-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

:deep(.filter-card .el-card__body) {
  padding: 0;
  flex: 1;
  overflow-y: auto;
}

.filter-card-body {
  overflow-y: auto;
  padding: 10px 15px;
}

.filter-card-footer {
  padding: 5px 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: flex-end;
}

.path-tree-container {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 5px;
  margin-bottom: 20px;
}

.batch-fetch-card {
  padding: 10px;
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

:deep(.batch-fetch-card .el-card__body) {
  padding: 20px;
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.batch-fetch-content {
  flex: 1;
  overflow-y: auto;
}

.batch-fetch-footer {
  padding: 10px 0 0 0;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: flex-end;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.config-section {
  margin-bottom: 20px;
  padding: 15px;
  background-color: #f8f9fa;
  border-radius: 8px;
  border-left: 4px solid #409eff;
}

.config-section h3 {
  margin: 0 0 5px 0;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.priority-settings-card {
  width: 700px;
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  padding: 0 10px 10px;
}

:deep(.priority-settings-card .el-card__body) {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.priority-settings-content {
  flex: 1;
  overflow-y: auto;
}

.priority-settings-footer {
  padding: 10px 0 0 0;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.priority-section {
  margin-top: 15px;
}

.priority-list {
  min-height: 80px;
  padding: 15px;
  border: 2px dashed #dcdfe6;
  border-radius: 6px;
  background-color: #f5f7fa;
  transition: all 0.3s;
}

.priority-list:hover {
  border-color: #409eff;
  background-color: #ecf5ff;
}

.available-sites {
  min-height: 60px;
  padding: 15px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background-color: #fafafa;
}

.progress-card {
  width: 90vw;
  max-width: 1000px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  padding: 0 10px 10px;
}

:deep(.progress-card .el-card__body) {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.progress-content {
  flex: 1;
  overflow-y: auto;
}

.progress-footer {
  padding: 10px 0 0 0;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: flex-end;
}

.progress-header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-summary {
  margin-bottom: 20px;
}

.results-table-container {
  margin-top: 15px;
}
</style>
