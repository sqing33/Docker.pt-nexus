<!-- src/views/TorrentsView.vue -->
<template>
  <div class="torrents-view">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      center
      style="margin-bottom: 15px"
    ></el-alert>

    <el-table
      :data="allData"
      v-loading="loading"
      border
      height="100%"
      ref="tableRef"
      row-key="name"
      :row-class-name="tableRowClassName"
      @row-click="handleRowClick"
      @expand-change="handleExpandChange"
      @sort-change="handleSortChange"
      :default-sort="currentSort"
      empty-text="无数据或当前筛选条件下无结果"
    >
      <el-table-column type="expand" width="1">
        <template #default="props">
          <div class="expand-content">
            <template v-for="siteName in all_sites" :key="siteName">
              <template v-if="props.row.sites[siteName]">
                <a
                  v-if="hasLink(props.row.sites[siteName], siteName)"
                  :href="getLink(props.row.sites[siteName], siteName)!"
                  target="_blank"
                  style="text-decoration: none;"
                >
                  <el-tag effect="dark" :type="getTagType(props.row.sites[siteName])">
                    {{ siteName }} ({{
                      formatBytes(
                        props.row.sites[siteName].qb_ul + props.row.sites[siteName].tr_ul,
                      )
                    }})
                  </el-tag>
                </a>
                <el-tag v-else effect="dark" :type="getTagType(props.row.sites[siteName])">
                  {{ siteName }} ({{
                    formatBytes(props.row.sites[siteName].qb_ul + props.row.sites[siteName].tr_ul)
                  }})
                </el-tag>
              </template>
              <template v-else>
                <el-tag type="info" effect="plain" >{{ siteName }}</el-tag>
              </template>
            </template>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="name" min-width="350" sortable="custom">
        <template #header>
          <div class="name-header-container">
            <div>种子名称</div>
            <el-input
              v-model="nameSearch"
              placeholder="搜索名称..."
              clearable
              class="search-input"
            />
            <span>
              <el-button type="primary" @click="openFilterDialog" plain>筛选</el-button>
              <el-button type="success" @click="forceRefresh" :loading="isRefreshing" plain
                >刷新</el-button
              >
            </span>
          </div>
        </template>
        <template #default="scope">
          <span style="white-space: normal">{{ scope.row.name }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="save_path" label="保存路径" width="250" show-overflow-tooltip />
      <el-table-column
        label="大小"
        prop="size_formatted"
        width="110"
        align="center"
        sortable="custom"
      />
      <el-table-column
        label="qB 上传量"
        prop="qb_uploaded_formatted"
        width="130"
        align="center"
        sortable="custom"
      />
      <el-table-column
        label="Tr 上传量"
        prop="tr_uploaded_formatted"
        width="130"
        align="center"
        sortable="custom"
      />
      <el-table-column
        label="总上传量"
        prop="total_uploaded_formatted"
        width="130"
        align="center"
        sortable="custom"
      />
      <el-table-column label="进度" prop="progress" width="140" align="center" sortable="custom">
        <template #default="scope">
          <el-progress
            :percentage="scope.row.progress"
            :stroke-width="10"
            :color="progressColors"
          />
        </template>
      </el-table-column>
      <el-table-column label="状态" prop="state" width="110" align="center">
        <template #default="scope">
          <el-tag :type="getStateTagType(scope.row.state)" size="large">{{
            scope.row.state
          }}</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="totalTorrents > 0"
      style="margin-top: 15px; justify-content: flex-end"
      v-model:current-page="currentPage"
      v-model:page-size="pageSize"
      :page-sizes="[20, 50, 100, 200, 500]"
      :total="totalTorrents"
      layout="total, sizes, prev, pager, next, jumper"
      @size-change="handleSizeChange"
      @current-change="handleCurrentChange"
      background
    />

    <el-dialog v-model="filterDialogVisible" title="筛选选项" width="800px" class="filter-dialog">
      <el-divider content-position="left">站点筛选</el-divider>
      <div class="site-filter-container">
        <el-radio-group v-model="tempFilters.siteExistence">
          <el-radio label="all">不过滤</el-radio>
          <el-radio label="exists">存在于</el-radio>
          <el-radio label="not-exists">不存在于</el-radio>
        </el-radio-group>
        <el-select
          v-model="tempFilters.siteName"
          :disabled="tempFilters.siteExistence === 'all'"
          clearable
          filterable
          placeholder="请选择站点"
          style="width: 200px"
        >
          <el-option v-for="site in all_sites" :key="site" :label="site" :value="site" />
        </el-select>
      </div>
      <el-divider content-position="left">保存路径</el-divider>
      <el-checkbox-group v-model="tempFilters.paths">
        <el-tooltip
          v-for="path in unique_paths"
          :key="path"
          :content="path"
          placement="top"
          class="path-tooltip"
        >
          <el-checkbox :label="path">{{ truncatePath(path, 50) }}</el-checkbox>
        </el-tooltip>
      </el-checkbox-group>
      <el-divider content-position="left">状态</el-divider>
      <el-checkbox-group v-model="tempFilters.states">
        <el-checkbox v-for="state in unique_states" :key="state" :label="state">{{
          state
        }}</el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="filterDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="applyFilters">确认</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { TableInstance, Sort } from 'element-plus'

// --- 类型定义 ---
interface SiteData {
  qb_ul: number
  tr_ul: number
  comment: string
}
interface Torrent {
  name: string
  save_path: string
  size: number
  size_formatted: string
  progress: number
  state: string
  sites: Record<string, SiteData>
  qb_uploaded: number
  qb_uploaded_formatted: string
  tr_uploaded: number
  tr_uploaded_formatted: string
  total_uploaded: number
  total_uploaded_formatted: string
}
interface ActiveFilters {
  paths: string[]
  states: string[]
  siteExistence: 'all' | 'exists' | 'not-exists'
  siteName: string | null
}

// --- 表格与数据状态 ---
const tableRef = ref<TableInstance | null>(null)
const loading = ref<boolean>(true)
const isRefreshing = ref<boolean>(false)
const allData = ref<Torrent[]>([])
const error = ref<string | null>(null)

// --- 筛选与排序状态 ---
const nameSearch = ref<string>('')
const currentSort = ref<Sort>({ prop: 'name', order: 'ascending' })
const activeFilters = reactive<ActiveFilters>({
  paths: [],
  states: [],
  siteExistence: 'all',
  siteName: null,
})
const tempFilters = reactive<ActiveFilters>({ ...activeFilters })
const filterDialogVisible = ref<boolean>(false)

// --- 分页状态 ---
const currentPage = ref<number>(1)
const pageSize = ref<number>(50)
const totalTorrents = ref<number>(0)

// --- 静态数据与UI ---
const unique_paths = ref<string[]>([])
const unique_states = ref<string[]>([])
const all_sites = ref<string[]>([])
const site_link_rules = ref<Record<string, { base_url: string }>>({})
const expandedRows = ref<string[]>([])
const progressColors = [
  { color: '#f56c6c', percentage: 80 },
  { color: '#e6a23c', percentage: 99 },
  { color: '#67c23a', percentage: 100 },
]

// --- 核心方法：数据获取 ---
const fetchData = async (isRefresh = false) => {
  if (!isRefresh) loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      pageSize: pageSize.value.toString(),
      nameSearch: nameSearch.value,
      sortProp: currentSort.value.prop || 'name',
      sortOrder: currentSort.value.order || 'ascending',
      siteFilterExistence: activeFilters.siteExistence,
      siteFilterName: activeFilters.siteName || '',
      path_filters: JSON.stringify(activeFilters.paths),
      state_filters: JSON.stringify(activeFilters.states),
    })

    const response = await fetch(`/api/data?${params.toString()}`)
    if (!response.ok) throw new Error(`网络错误: ${response.status}`)
    const result = await response.json()
    if (result.error) throw new Error(result.error)

    allData.value = result.data
    totalTorrents.value = result.total
    if (pageSize.value !== result.pageSize) pageSize.value = result.pageSize

    // 首次加载或强制刷新时，更新筛选选项
    if (unique_paths.value.length === 0 || isRefresh) {
      unique_paths.value = result.unique_paths
      unique_states.value = result.unique_states
      all_sites.value = result.all_discovered_sites
      site_link_rules.value = result.site_link_rules
      activeFilters.paths = result.active_path_filters
    }
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
    if (isRefresh) isRefreshing.value = false
  }
}

const forceRefresh = async () => {
  isRefreshing.value = true
  ElMessage.info('后台正在刷新缓存...')
  try {
    const response = await fetch('/api/refresh_data', { method: 'POST' })
    if (!response.ok) throw new Error('触发刷新失败')
    // 等待一小段时间让后端处理
    setTimeout(() => {
      ElMessage.success('数据已刷新！')
      currentPage.value = 1
      fetchData(true)
    }, 2500)
  } catch (e: any) {
    ElMessage.error(e.message)
    isRefreshing.value = false
  }
}

// --- 事件处理器 ---
const handleSizeChange = (val: number) => {
  pageSize.value = val
  currentPage.value = 1
  fetchData()
}
const handleCurrentChange = (val: number) => {
  currentPage.value = val
  fetchData()
}
const handleSortChange = (sort: Sort) => {
  currentSort.value = sort
  currentPage.value = 1
  fetchData()
}

// --- 筛选逻辑 ---
const openFilterDialog = () => {
  Object.assign(tempFilters, activeFilters)
  filterDialogVisible.value = true
}
const applyFilters = async () => {
  Object.assign(activeFilters, tempFilters)
  filterDialogVisible.value = false
  currentPage.value = 1
  await fetchData()
  try {
    await fetch('/api/save_filters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: activeFilters.paths }),
    })
  } catch (e: any) {
    ElMessage.error(`保存路径筛选器设置失败: ${e.message}`)
  }
}

// --- UI 辅助函数 ---
const formatBytes = (b: number | null): string => {
  if (b == null || b <= 0) return '0 B'
  const s = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(b) / Math.log(1024))
  return `${(b / Math.pow(1024, i)).toFixed(2)} ${s[i]}`
}
const hasLink = (siteData: SiteData, siteName: string): boolean => {
  const { comment } = siteData
  return !!(
    comment &&
    (comment.startsWith('http') || (/^\d+$/.test(comment) && site_link_rules.value[siteName]))
  )
}
const getLink = (siteData: SiteData, siteName: string): string | null => {
  const { comment } = siteData
  if (comment.startsWith('http')) return comment
  const rule = site_link_rules.value[siteName]
  if (rule && /^\d+$/.test(comment)) {
    const baseUrl = rule.base_url.startsWith('http') ? rule.base_url : `https://${rule.base_url}`
    return `${baseUrl.replace(/\/$/, '')}/details.php?id=${comment}`
  }
  return null
}
const getTagType = (siteData: SiteData) => (siteData.comment ? 'success' : 'primary')
const getStateTagType = (state: string) => {
  if (state.includes('下载')) return 'primary'
  if (state.includes('做种')) return 'success'
  if (state.includes('暂停')) return 'warning'
  if (state.includes('错误') || state.includes('丢失')) return 'danger'
  return 'info'
}
const truncatePath = (text: string, maxLength: number): string => {
  if (text.length <= maxLength) return text
  const segLen = Math.floor((maxLength - 3) / 2)
  return `${text.substring(0, segLen)}...${text.substring(text.length - segLen)}`
}
const handleRowClick = (row: Torrent) => tableRef.value?.toggleRowExpansion(row)
const handleExpandChange = (row: Torrent, expanded: Torrent[]) => {
  expandedRows.value = expanded.map((r) => r.name)
}
const tableRowClassName = ({ row }: { row: Torrent }) => {
  return expandedRows.value.includes(row.name) ? 'expanded-row' : ''
}

// --- 生命周期与侦听器 ---
onMounted(() => {
  fetchData()
})

watch(nameSearch, () => {
  currentPage.value = 1
  fetchData()
})
watch(
  () => tempFilters.siteExistence,
  (val) => {
    if (val === 'all') tempFilters.siteName = null
  },
)
</script>

<style scoped>
.torrents-view {
  height: 100%;
  display: flex;
  flex-direction: column;

  box-sizing: border-box;
}

:deep(.cell) {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.name-header-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
  flex: 1;
}

.name-header-container .search-input {
  width: 200px;
  margin: 0 15px;
}

.expand-content {
  padding: 10px 20px;
  background-color: #fafcff;
}

.expand-content .el-tag {
  margin: 0 5px 5px 0;
}

.el-table__row,
.el-table .sortable-header .cell {
  cursor: pointer;
}

:deep(.el-table__expand-icon) {
  display: none;
}

:deep(.expanded-row > td) {
  background-color: #ecf5ff !important;
}

.filter-dialog .el-checkbox-group,
.filter-dialog .el-radio-group {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 0;
}

.filter-dialog .el-checkbox,
.filter-dialog .el-radio {
  margin-right: 15px !important;
}

.path-tooltip {
  display: inline-block;
  margin-bottom: 10px;
}

.site-filter-container {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
