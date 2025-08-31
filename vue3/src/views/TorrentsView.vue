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
            <!-- [修改] 使用按中文拼音排序的 sorted_all_sites -->
            <template v-for="siteName in sorted_all_sites" :key="siteName">
              <template v-if="props.row.sites[siteName]">
                <a
                  v-if="hasLink(props.row.sites[siteName], siteName)"
                  :href="getLink(props.row.sites[siteName], siteName)!"
                  target="_blank"
                  style="text-decoration: none"
                >
                  <el-tag
                    effect="dark"
                    :type="getTagType(props.row.sites[siteName])"
                    style="text-align: center"
                  >
                    {{ siteName }}
                    <div>({{ formatBytes(props.row.sites[siteName].uploaded) }})</div>
                  </el-tag>
                </a>
                <el-tag
                  v-else
                  effect="dark"
                  :type="getTagType(props.row.sites[siteName])"
                  style="text-align: center"
                >
                  {{ siteName }}
                  <div>({{ formatBytes(props.row.sites[siteName].uploaded) }})</div>
                </el-tag>
              </template>
              <template v-else>
                <el-tag type="info" effect="plain">{{ siteName }}</el-tag>
              </template>
            </template>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="name" min-width="450" sortable="custom">
        <template #header>
          <div class="name-header-container">
            <div>种子名称</div>
            <el-input
              v-model="nameSearch"
              placeholder="搜索名称..."
              clearable
              class="search-input"
              @click.stop
            />
            <span @click.stop>
              <el-button type="primary" @click="openFilterDialog" plain>筛选</el-button>
            </span>
          </div>
        </template>
        <template #default="scope">
          <span style="white-space: normal">{{ scope.row.name }}</span>
        </template>
      </el-table-column>

      <el-table-column
        prop="site_count"
        label="做种站点数"
        sortable="custom"
        width="120"
        align="center"
        header-align="center"
      >
        <template #default="scope">
          <span style="display: inline-block; width: 100%; text-align: center">
            {{ scope.row.site_count }} / {{ scope.row.total_site_count }}
          </span>
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
        label="总上传量"
        prop="total_uploaded_formatted"
        width="130"
        align="center"
        sortable="custom"
      />
      <el-table-column label="进度" prop="progress" width="90" align="center" sortable="custom">
        <template #default="scope">
          <el-progress
            :percentage="scope.row.progress"
            :stroke-width="10"
            :color="progressColors"
          />
        </template>
      </el-table-column>
      <el-table-column label="状态" prop="state" width="90" align="center">
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
        <el-radio-group v-model="tempFilters.siteExistence" style="margin-bottom: 10px">
          <el-radio label="all">不过滤</el-radio>
          <el-radio label="exists">存在于</el-radio>
          <el-radio label="not-exists">不存在于</el-radio>
        </el-radio-group>

        <div class="site-checkbox-container">
          <el-checkbox-group
            v-model="tempFilters.siteNames"
            :disabled="tempFilters.siteExistence === 'all'"
          >
            <!-- [修改] 使用按中文拼音排序的 sorted_all_sites -->
            <el-checkbox v-for="site in sorted_all_sites" :key="site" :label="site">{{
              site
            }}</el-checkbox>
          </el-checkbox-group>
        </div>
      </div>

      <el-divider content-position="left">保存路径</el-divider>
      <div class="path-tree-container">
        <el-tree
          ref="pathTreeRef"
          :data="pathTreeData"
          show-checkbox
          node-key="path"
          default-expand-all
          check-on-click-node
          :props="{ class: 'path-tree-node' }"
        />
      </div>

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
// [新增] 引入 computed
import { ref, onMounted, reactive, watch, defineEmits, nextTick, computed } from 'vue'
import type { TableInstance, Sort } from 'element-plus'
import type { ElTree } from 'element-plus'

const emits = defineEmits(['ready'])

interface SiteData {
  uploaded: number
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
  total_uploaded: number
  total_uploaded_formatted: string
}

interface ActiveFilters {
  paths: string[]
  states: string[]
  siteExistence: 'all' | 'exists' | 'not-exists'
  siteNames: string[]
}
interface PathNode {
  path: string
  label: string
  children?: PathNode[]
}

const tableRef = ref<TableInstance | null>(null)
const loading = ref<boolean>(true)
const allData = ref<Torrent[]>([])
const error = ref<string | null>(null)

const nameSearch = ref<string>('')
const currentSort = ref<Sort>({ prop: 'name', order: 'ascending' })

const activeFilters = reactive<ActiveFilters>({
  paths: [],
  states: [],
  siteExistence: 'all',
  siteNames: [],
})
const tempFilters = reactive<ActiveFilters>({ ...activeFilters })
const filterDialogVisible = ref<boolean>(false)

const currentPage = ref<number>(1)
const pageSize = ref<number>(50)
const totalTorrents = ref<number>(0)

const unique_paths = ref<string[]>([])
const unique_states = ref<string[]>([])
const all_sites = ref<string[]>([])
const site_link_rules = ref<Record<string, { base_url: string }>>({})
const expandedRows = ref<string[]>([])

const pathTreeRef = ref<InstanceType<typeof ElTree> | null>(null)
const pathTreeData = ref<PathNode[]>([])

// [新增] 创建一个计算属性，它会自动按中文拼音对 all_sites 进行排序
const sorted_all_sites = computed(() => {
  // Intl.Collator 是专门用于处理特定语言排序的 API
  const collator = new Intl.Collator('zh-CN', { numeric: true })
  // 创建一个 all_sites 的副本并进行排序
  return [...all_sites.value].sort(collator.compare)
})

const progressColors = [
  { color: '#f56c6c', percentage: 80 },
  { color: '#e6a23c', percentage: 99 },
  { color: '#67c23a', percentage: 100 },
]

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
      pageSize: pageSize.value.toString(),
      nameSearch: nameSearch.value,
      sortProp: currentSort.value.prop || 'name',
      sortOrder: currentSort.value.order || 'ascending',
      siteFilterExistence: activeFilters.siteExistence,
      siteFilterNames: JSON.stringify(activeFilters.siteNames),
      path_filters: JSON.stringify(activeFilters.paths || []),
      state_filters: JSON.stringify(activeFilters.states),
    })

    const response = await fetch(`/api/data?${params.toString()}`)
    if (!response.ok) throw new Error(`网络错误: ${response.status}`)
    const result = await response.json()
    if (result.error) throw new Error(result.error)

    allData.value = result.data
    totalTorrents.value = result.total
    if (pageSize.value !== result.pageSize) pageSize.value = result.pageSize

    unique_paths.value = result.unique_paths
    unique_states.value = result.unique_states
    all_sites.value = result.all_discovered_sites
    site_link_rules.value = result.site_link_rules
    activeFilters.paths = result.active_path_filters

    pathTreeData.value = buildPathTree(result.unique_paths)
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
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
const handleSortChange = (sort: Sort) => {
  currentSort.value = sort
  currentPage.value = 1
  fetchData()
}

const openFilterDialog = () => {
  Object.assign(tempFilters, activeFilters)
  filterDialogVisible.value = true
  nextTick(() => {
    if (pathTreeRef.value) {
      pathTreeRef.value.setCheckedKeys(activeFilters.paths, false)
    }
  })
}
const applyFilters = async () => {
  if (pathTreeRef.value) {
    const selectedPaths = pathTreeRef.value.getCheckedKeys(true)
    tempFilters.paths = selectedPaths
  }

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
    console.error(`保存路径筛选器设置失败: ${e.message}`)
  }
}

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

const handleRowClick = (row: Torrent) => tableRef.value?.toggleRowExpansion(row)
const handleExpandChange = (row: Torrent, expanded: Torrent[]) => {
  expandedRows.value = expanded.map((r) => r.name)
}
const tableRowClassName = ({ row }: { row: Torrent }) => {
  return expandedRows.value.includes(row.name) ? 'expanded-row' : ''
}

onMounted(() => {
  fetchData()
  emits('ready', fetchData)
})

watch(nameSearch, () => {
  currentPage.value = 1
  fetchData()
})
watch(
  () => tempFilters.siteExistence,
  (val) => {
    if (val === 'all') {
      tempFilters.siteNames = []
    }
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
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
  gap: 5px;
}

.expand-content :deep(.el-tag) {
  height: 35px;
  width: 100%;
  white-space: normal;
  text-align: center;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  line-height: 1.2;
  padding: 0;
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

.path-tree-container {
  max-height: 250px;
  overflow-y: auto;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 5px;
}

:deep(.path-tree-node .el-tree-node__content) {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.site-filter-container {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.site-checkbox-container {
  width: 100%;
  max-height: 160px;
  overflow-y: auto;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 10px;
  margin-top: 10px;
  box-sizing: border-box;
}

:deep(.site-checkbox-container .el-checkbox-group) {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

:deep(.site-checkbox-container .el-checkbox) {
  margin-right: 0 !important;
}

:deep(.el-pagination) {
  margin: 8px 0 !important;
  padding-right: 10px;
}
</style>
