<template>
  <div class="torrents-view">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" center
      style="margin-bottom: 15px"></el-alert>

    <!-- [修改] 使用 v-if 确保在加载设置后再渲染表格 -->
    <el-table v-if="settingsLoaded" :data="allData" v-loading="loading" border height="100%" ref="tableRef"
      row-key="name" :row-class-name="tableRowClassName" @row-click="handleRowClick" @expand-change="handleExpandChange"
      @sort-change="handleSortChange" :default-sort="currentSort" empty-text="无数据或当前筛选条件下无结果">
      <!-- ... (其他列保持不变) ... -->
      <el-table-column type="expand" width="1">
        <template #default="props">
          <div class="expand-content">
            <template v-for="siteName in sorted_all_sites" :key="siteName">
              <template v-if="props.row.sites[siteName]">
                <a v-if="hasLink(props.row.sites[siteName], siteName)"
                  :href="getLink(props.row.sites[siteName], siteName)!" target="_blank" style="text-decoration: none">
                  <el-tag effect="dark" :type="getTagType(props.row.sites[siteName])" style="text-align: center">
                    {{ siteName }}
                    <div>({{ formatBytes(props.row.sites[siteName].uploaded) }})</div>
                  </el-tag>
                </a>
                <el-tag v-else effect="dark" :type="getTagType(props.row.sites[siteName])" style="text-align: center">
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
            <el-input v-model="nameSearch" placeholder="搜索名称..." clearable class="search-input" @click.stop />
            <span @click.stop>
              <el-button type="primary" @click="openFilterDialog" plain>筛选</el-button>
            </span>
          </div>
        </template>
        <template #default="scope">
          <span style="white-space: normal">{{ scope.row.name }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="site_count" label="做种站点数" sortable="custom" width="120" align="center"
        header-align="center">
        <template #default="scope">
          <span style="display: inline-block; width: 100%; text-align: center">
            {{ scope.row.site_count }} / {{ scope.row.total_site_count }}
          </span>
        </template>
      </el-table-column>

      <el-table-column prop="save_path" label="保存路径" width="250" show-overflow-tooltip />
      <el-table-column label="大小" prop="size_formatted" width="110" align="center" sortable="custom" />

      <el-table-column label="总上传量" prop="total_uploaded_formatted" width="130" align="center" sortable="custom" />
      <el-table-column label="进度" prop="progress" width="90" align="center" sortable="custom">
        <template #default="scope">
          <el-progress :percentage="scope.row.progress" :stroke-width="10" :color="progressColors" />
        </template>
      </el-table-column>
      <el-table-column label="状态" prop="state" width="90" align="center">
        <template #default="scope">
          <el-tag :type="getStateTagType(scope.row.state)" size="large">{{
            scope.row.state
            }}</el-tag>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="100" align="center">
        <template #default="scope">
          <el-button type="primary" size="small" @click.stop="startCrossSeed(scope.row)">
            转种
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination v-if="totalTorrents > 0" style="margin-top: 15px; justify-content: flex-end"
      v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[20, 50, 100, 200, 500]"
      :total="totalTorrents" layout="total, sizes, prev, pager, next, jumper" @size-change="handleSizeChange"
      @current-change="handleCurrentChange" background />

    <!-- 筛选器弹窗 (无改动) -->
    <div v-if="filterDialogVisible" class="filter-overlay" @click.self="filterDialogVisible = false">
      <el-card class="filter-card">
        <template #header>
          <div class="filter-card-header">
            <span>筛选选项</span>
            <el-button type="danger" circle @click="filterDialogVisible = false" plain>X</el-button>
          </div>
        </template>
        <div class="filter-card-body">
          <el-divider content-position="left">站点筛选</el-divider>
          <div class="site-filter-container">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px;">
              <el-radio-group v-model="tempFilters.siteExistence">
                <el-radio label="all">不过滤</el-radio>
                <el-radio label="exists">存在于</el-radio>
                <el-radio label="not-exists">不存在于</el-radio>
              </el-radio-group>
              <el-input
                v-model="siteSearch"
                size="small"
                placeholder="搜索站点"
                clearable
                style="width:220px;"
              />
            </div>
            <div class="site-checkbox-container">
              <el-checkbox-group v-model="tempFilters.siteNames" :disabled="tempFilters.siteExistence === 'all'">
                <el-checkbox v-for="site in filteredSiteOptions" :key="site" :label="site">{{
                  site
                  }}</el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
          <el-divider content-position="left">下载器</el-divider>
          <el-checkbox-group v-model="tempFilters.downloaderIds">
            <el-checkbox v-for="downloader in downloadersList" :key="downloader.id" :label="downloader.id">
              {{ downloader.name }}
            </el-checkbox>
          </el-checkbox-group>
          <el-divider content-position="left">保存路径</el-divider>
          <div class="path-tree-container">
            <el-tree ref="pathTreeRef" :data="pathTreeData" show-checkbox node-key="path" default-expand-all
              check-on-click-node :props="{ class: 'path-tree-node' }" />
          </div>
          <el-divider content-position="left">状态</el-divider>
          <el-checkbox-group v-model="tempFilters.states">
            <el-checkbox v-for="state in unique_states" :key="state" :label="state">{{
              state
              }}</el-checkbox>
          </el-checkbox-group>
        </div>
        <div class="filter-card-footer">
          <el-button @click="filterDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="applyFilters">确认</el-button>
        </div>
      </el-card>
    </div>

    <!-- 源站点选择弹窗 -->
    <div v-if="sourceSelectionDialogVisible" class="filter-overlay">
      <el-card class="filter-card" style="max-width: 600px;">
        <template #header>
          <div class="filter-card-header">
            <span>请选择转种的源站点</span>
            <el-button type="danger" circle @click="sourceSelectionDialogVisible = false" plain>X</el-button>
          </div>
        </template>
        <div class="source-site-selection-body">
          <p class="source-site-tip">
            <el-tag type="success" size="small" effect="dark" style="margin-right: 5px;">绿色</el-tag> 表示已配置Cookie，
            <el-tag type="primary" size="small" effect="dark" style="margin-right: 5px;">蓝色</el-tag> 表示未配置Cookie。
            只有当前种子所在的站点才可点击。
          </p>
          <div class="site-list-box">
            <el-tooltip v-for="site in allSourceSitesStatus" :key="site.name"
              :content="isSourceSiteSelectable(site.name) ? `从 ${site.name} 转种` : `当前种子不在 ${site.name}`"
              placement="top">
              <el-tag :type="site.has_cookie ? 'success' : 'primary'"
                :class="{ 'is-selectable': isSourceSiteSelectable(site.name) }" class="site-tag"
                @click="isSourceSiteSelectable(site.name) && confirmSourceSiteAndProceed(getSiteDetails(site.name))">
                {{ site.name }}
              </el-tag>
            </el-tooltip>
          </div>
        </div>
        <div class="filter-card-footer">
          <el-button @click="sourceSelectionDialogVisible = false">取消</el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, watch, defineEmits, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import type { TableInstance, Sort } from 'element-plus'
import type { ElTree } from 'element-plus'

const emits = defineEmits(['ready'])

interface SiteData {
  uploaded: number
  comment: string
  migration: number
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
  downloaderId?: string
}
interface SiteStatus {
  name: string;
  has_cookie: boolean;
  has_passkey: boolean;
  is_source: boolean;
  is_target: boolean;
}
interface ActiveFilters {
  paths: string[]
  states: string[]
  siteExistence: 'all' | 'exists' | 'not-exists'
  siteNames: string[]
  downloaderIds: string[]
}
interface PathNode {
  path: string
  label: string
  children?: PathNode[]
}
interface Downloader {
  id: string;
  name: string;
}

const router = useRouter();

const tableRef = ref<TableInstance | null>(null)
const loading = ref<boolean>(true)
const allData = ref<Torrent[]>([])
const error = ref<string | null>(null)

// --- [新增] 控制表格渲染的状态 ---
const settingsLoaded = ref<boolean>(false)

const nameSearch = ref<string>('')
const currentSort = ref<Sort>({ prop: 'name', order: 'ascending' })

const activeFilters = reactive<ActiveFilters>({
  paths: [],
  states: [],
  siteExistence: 'all',
  siteNames: [],
  downloaderIds: [],
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
const downloadersList = ref<Downloader[]>([]);

const pathTreeRef = ref<InstanceType<typeof ElTree> | null>(null)
const pathTreeData = ref<PathNode[]>([])

const sourceSelectionDialogVisible = ref<boolean>(false);
const allSourceSitesStatus = ref<SiteStatus[]>([]);
const selectedTorrentForMigration = ref<Torrent | null>(null);

const sorted_all_sites = computed(() => {
  const collator = new Intl.Collator('zh-CN', { numeric: true })
  return [...all_sites.value].sort(collator.compare)
})

const siteSearch = ref('')
const filteredSiteOptions = computed(() => {
  if (!siteSearch.value) return sorted_all_sites.value
  const kw = siteSearch.value.toLowerCase()
  return sorted_all_sites.value.filter((s) => s.toLowerCase().includes(kw))
})

const progressColors = [
  { color: '#f56c6c', percentage: 80 },
  { color: '#e6a23c', percentage: 99 },
  { color: '#67c23a', percentage: 100 },
]

const saveUiSettings = async () => {
  try {
    const settingsToSave = {
      page_size: pageSize.value,
      sort_prop: currentSort.value.prop,
      sort_order: currentSort.value.order,
      name_search: nameSearch.value,
      active_filters: activeFilters,
    };
    await fetch('/api/ui_settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settingsToSave)
    });
  } catch (e: any) {
    console.error('无法保存UI设置:', e.message);
  }
};

const loadUiSettings = async () => {
  try {
    const response = await fetch('/api/ui_settings');
    if (!response.ok) {
      console.warn('无法加载UI设置，将使用默认值。');
      return;
    }
    const settings = await response.json();
    pageSize.value = settings.page_size ?? 50;
    currentSort.value = {
      prop: settings.sort_prop || 'name',
      // --- [修改] 正确处理 null (取消排序) 状态 ---
      order: 'sort_order' in settings ? settings.sort_order : 'ascending'
    };
    nameSearch.value = settings.name_search ?? '';
    if (settings.active_filters) {
      Object.assign(activeFilters, settings.active_filters);
    }
  } catch (e) {
    console.error('加载UI设置时出错:', e);
  } finally {
    // --- [修改] 无论加载成功与否，都设置此值为 true，以渲染表格 ---
    settingsLoaded.value = true;
  }
}


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

const fetchDownloadersList = async () => {
  try {
    const response = await fetch('/api/downloaders_list');
    if (!response.ok) throw new Error('无法获取下载器列表');
    downloadersList.value = await response.json();
  } catch (e: any) {
    error.value = e.message;
  }
}

const fetchAllSitesStatus = async () => {
  try {
    const response = await fetch('/api/sites/status');
    if (!response.ok) throw new Error('无法获取站点状态列表');
    const allSites = await response.json();
    allSourceSitesStatus.value = allSites.filter((s: SiteStatus) => s.is_source);
  } catch (e: any) {
    error.value = (e as Error).message;
  }
};


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
      downloader_filters: JSON.stringify(activeFilters.downloaderIds),
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

const startCrossSeed = (row: Torrent) => {
  const availableSources = Object.entries(row.sites)
    .map(([siteName, siteDetails]) => ({ siteName, ...siteDetails }))
    .filter(site => {
      const hasDetailsLink = site.comment && site.comment.includes('details.php?id=');
      const isSourceSite = site.migration === 1 || site.migration === 3;
      return hasDetailsLink && isSourceSite;
    });

  if (availableSources.length === 0) {
    ElMessage.error('该种子没有找到可用的、已配置为源站点的做种站点。');
    return;
  }

  selectedTorrentForMigration.value = row;
  sourceSelectionDialogVisible.value = true;
};

const confirmSourceSiteAndProceed = (sourceSite: any) => {
  const row = selectedTorrentForMigration.value;
  if (!row) {
    ElMessage.error('发生内部错误：未找到选中的种子信息。');
    sourceSelectionDialogVisible.value = false;
    return;
  }

  const siteDetails = row.sites[sourceSite.siteName];
  const idMatch = siteDetails.comment.match(/id=(\d+)/);
  if (!idMatch || !idMatch[1]) {
    ElMessage.error(`无法从源站点 ${sourceSite.siteName} 的链接中提取种子ID。`);
    sourceSelectionDialogVisible.value = false;
    return;
  }
  const torrentId = idMatch[1];
  const sourceSiteName = sourceSite.siteName;

  ElMessage.success(`准备从站点 [${sourceSiteName}] 开始迁移种子...`);
  const finalSavePath = `${row.save_path.replace(/[/\\]$/, '')}/${row.name}`;

  router.push({
    path: '/cross_seed',
    query: {
      sourceSite: sourceSiteName,
      searchTerm: torrentId,
      savePath: finalSavePath,
      downloaderPath: row.save_path,
      downloaderId: row.downloaderId,
    },
  });

  sourceSelectionDialogVisible.value = false;
};

const isSourceSiteSelectable = (siteName: string): boolean => {
  return !!(selectedTorrentForMigration.value && selectedTorrentForMigration.value.sites[siteName]);
};

const getSiteDetails = (siteName: string) => {
  if (!selectedTorrentForMigration.value) return null;
  const siteData = selectedTorrentForMigration.value.sites[siteName];
  if (!siteData) return null;
  return { siteName, ...siteData };
};


const handleSizeChange = (val: number) => {
  pageSize.value = val
  currentPage.value = 1
  fetchData()
  saveUiSettings()
}
const handleCurrentChange = (val: number) => {
  currentPage.value = val
  fetchData()
}
const handleSortChange = (sort: Sort) => {
  currentSort.value = sort
  currentPage.value = 1
  fetchData()
  saveUiSettings()
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
    tempFilters.paths = selectedPaths as string[]
  }

  Object.assign(activeFilters, tempFilters)
  filterDialogVisible.value = false
  currentPage.value = 1
  await fetchData()
  saveUiSettings()
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

// --- [修改] onMounted 启动逻辑 ---
onMounted(async () => {
  // 1. 先加载保存的UI设置
  await loadUiSettings();
  // 2. loadUiSettings 会设置 settingsLoaded=true，此时表格才会被渲染
  // 3. 使用加载好的设置去获取数据
  fetchData();
  // 4. 执行其他初始化
  fetchDownloadersList();
  fetchAllSitesStatus();
  emits('ready', fetchData);
})

watch(nameSearch, () => {
  currentPage.value = 1
  fetchData()
  saveUiSettings()
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
/* ... (所有样式保持不变) ... */
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

:deep(.expanded-row>td) {
  background-color: #ecf5ff !important;
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
  z-index: 2000;
}

.filter-card {
  width: 800px;
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

:deep(.el-card__header) {
  padding: 5px 10px;
}

:deep(.el-divider--horizontal) {
  margin: 18px 0;
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

.filter-card .el-checkbox-group,
.filter-card .el-radio-group {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 0;
}

.filter-card .el-checkbox,
.filter-card .el-radio {
  margin-right: 15px !important;
}

.path-tree-container {
  max-height: 200px;
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
  height: 160px; /* 固定高度，避免筛选结果变少时区域高度跳变 */
  overflow-y: auto;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 10px;
  margin-top: 10px;
  box-sizing: border-box;
}

:deep(.site-checkbox-container .el-checkbox-group) {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
}

:deep(.site-checkbox-container .el-checkbox) {
  margin-right: 0 !important;
}

:deep(.el-pagination) {
  margin: 8px 0 !important;
  padding-right: 10px;
}

.source-site-selection-body {
  padding: 5px 20px 20px 20px;
}

.source-site-tip {
  font-size: 13px;
  color: #909399;
  margin-bottom: 15px;
  text-align: center;
}

.site-list-box {
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  padding: 16px;
  background-color: #fafafa;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-content: flex-start;
}

.site-list-box .site-tag {
  font-size: 14px;
  height: 28px;
  line-height: 26px;
  opacity: 0.5;
}

.site-list-box .site-tag.is-selectable {
  cursor: pointer;
  opacity: 1;
}

.site-list-box .site-tag.is-selectable:hover {
  filter: brightness(1.1);
}
</style>
