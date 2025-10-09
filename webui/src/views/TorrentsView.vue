<template>
  <div class="torrents-view">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" center
      style="margin-bottom: 15px"></el-alert>

    <!-- [修改] 使用 v-if 确保在加载设置后再渲染表格 -->
    <el-table v-if="settingsLoaded" :data="allData" v-loading="loading" border height="100%" ref="tableRef"
      row-key="unique_id" :row-class-name="tableRowClassName" @row-click="handleRowClick" @expand-change="handleExpandChange"
      @sort-change="handleSortChange" :default-sort="currentSort" empty-text="无数据或当前筛选条件下无结果"
      class="glass-table">
      <!-- ... (其他列保持不变) ... -->
      <el-table-column type="expand" width="1">
        <template #default="props">
          <div class="expand-content">
            <template v-for="siteName in sorted_all_sites" :key="siteName">
              <template v-if="props.row.sites[siteName]">
                <!-- 对于未做种状态的站点，使用可点击的div而不是链接 -->
                <div v-if="props.row.sites[siteName].state === '未做种'"
                  style="cursor: pointer; display: inline-block; width: 100%; text-align: center;"
                  @click.stop="handleSiteClick(props.row.name, { name: siteName, data: props.row.sites[siteName] })">
                  <el-tag effect="dark" :type="getTagType(props.row.sites[siteName])"
                    style="text-align: center; width: 100%;">
                    {{ siteName }}
                    <div>({{ formatBytes(props.row.sites[siteName].uploaded) }})</div>
                  </el-tag>
                </div>
                <!-- 对于有链接的站点，使用链接 -->
                <a v-else-if="hasLink(props.row.sites[siteName], siteName)"
                  :href="getLink(props.row.sites[siteName], siteName)!" target="_blank" style="text-decoration: none">
                  <el-tag effect="dark" :type="getTagType(props.row.sites[siteName])" style="text-align: center">
                    {{ siteName }}
                    <div>({{ formatBytes(props.row.sites[siteName].uploaded) }})</div>
                  </el-tag>
                </a>
                <!-- 对于其他站点，使用可点击的div -->
                <div v-else style="cursor: pointer; display: inline-block; width: 100%; text-align: center;"
                  @click.stop="handleSiteClick(props.row.name, { name: siteName, data: props.row.sites[siteName] })">
                  <el-tag effect="dark" :type="getTagType(props.row.sites[siteName])"
                    style="text-align: center; width: 100%;">
                    {{ siteName }}
                    <div>({{ formatBytes(props.row.sites[siteName].uploaded) }})</div>
                  </el-tag>
                </div>
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
            <span @click.stop style="display: flex; align-items: center;">
              <div v-if="hasActiveFilters" class="current-filters" style="margin-right: 15px; display: flex; align-items: center;">
                <el-tag type="info" size="default" effect="plain">{{ currentFilterText }}</el-tag>
                <el-button type="danger" link style="padding: 0; margin-left: 8px;" @click="clearAllFilters">清除</el-button>
              </div>
              <el-button type="primary" @click="openFilterDialog" plain>筛选</el-button>
            </span>
          </div>
        </template>
        <template #default="scope">
          <span style="white-space: normal">{{ scope.row.name }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="site_count" label="做种数" sortable="custom" width="95" align="center" header-align="center">
        <template #default="scope">
          <span style="display: inline-block; width: 100%; text-align: center">
            {{ scope.row.site_count }} / {{ scope.row.total_site_count }}
          </span>
        </template>
      </el-table-column>

      <el-table-column prop="save_path" label="保存路径" width="220" header-align="center">
        <template #default="scope">
          <div :title="scope.row.save_path"
            style="width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {{ shortenPath(scope.row.save_path, 30) }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="下载器" width="120" align="center" header-align="center">
        <template #default="scope">
          <div style="display: flex; justify-content: center; align-items: center; width: 100%; height: 100%;">
            <div v-if="scope.row.downloaderIds && scope.row.downloaderIds.length > 0">
              <el-tag v-for="downloaderId in sortedDownloaderIds(scope.row.downloaderIds)" :key="downloaderId"
                size="small" :type="getDownloaderTagType(downloaderId)" style="margin: 2px;">
                {{ getDownloaderName(downloaderId) }}
              </el-tag>
            </div>
            <el-tag v-else type="info" size="small">
              未知下载器
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="大小" prop="size_formatted" width="100" align="center" sortable="custom" />

      <el-table-column label="总上传量" prop="total_uploaded_formatted" width="110" align="center" sortable="custom" />
      <el-table-column label="进度" prop="progress" width="120" align="center" sortable="custom">
        <template #default="scope">
          <div style="padding: 1px 0; width: 100%;">
            <el-progress :percentage="scope.row.progress" :stroke-width="10" :color="progressColors" :show-text="false"
              style="width: 100%;" />
            <div style="text-align: center; font-size: 12px; margin-top: 5px; line-height: 1;">
              {{ scope.row.progress }}%
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="状态" prop="state" width="120" align="center" header-align="center">
        <template #default="scope">
          <div style="display: flex; justify-content: center; align-items: center; width: 100%; height: 100%;">
            <el-tag :type="getStateTagType(scope.row.state)" size="large">{{
              scope.row.state
              }}</el-tag>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="可转种" width="100" align="center" header-align="center" prop="target_sites_count"
        sortable="custom">
        <template #default="scope">
          <div style="display: flex; justify-content: center; align-items: center; width: 100%; height: 100%;">
            <span v-if="scope.row.target_sites_count !== undefined">{{ scope.row.target_sites_count }}</span>
            <span v-else>-</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="100" align="center" header-align="center">
        <template #default="scope">
          <div style="display: flex; justify-content: center; align-items: center; width: 100%; height: 100%;">
            <el-button type="primary" size="small" @click.stop="startCrossSeed(scope.row)">
              转种
            </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination v-if="totalTorrents > 0"  class="glass-pagination" style="justify-content: flex-end"
      v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]"
      :total="totalTorrents" layout="total, sizes, prev, pager, next, jumper" @size-change="handleSizeChange"
      @current-change="handleCurrentChange" background />

    <!-- 转种弹窗 -->
    <div v-if="crossSeedDialogVisible" class="modal-overlay">
      <el-card class="cross-seed-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>转种 - {{ selectedTorrentForMigration?.name }}</span>
            <el-button type="danger" circle @click="closeCrossSeedDialog" plain>X</el-button>
          </div>
        </template>
        <div class="cross-seed-content" v-if="selectedTorrentForMigration">
          <CrossSeedPanel
            @complete="handleCrossSeedComplete" @cancel="closeCrossSeedDialog" />
        </div>
      </el-card>
    </div>

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
            <div style="display:flex; align-items:center; gap:15px; margin-bottom:5px;">
              <el-radio-group v-model="siteFilterMode" size="default">
                <el-radio-button label="exist" class="compact-radio-button">存在于</el-radio-button>
                <el-radio-button label="not-exist" class="compact-radio-button">不存在于</el-radio-button>
              </el-radio-group>
              <el-input v-model="siteSearch" placeholder="搜索站点" clearable style="width:280px; font-size: 14px;"
                size="default" />
              <div style="display: flex; align-items: center; gap: 10px;">
                <div v-if="tempFilters.existSiteNames.length > 0" style="display: flex; align-items: center;">
                  <el-tag type="info" size="default" effect="plain">存在于: {{ tempFilters.existSiteNames.length }}</el-tag>
                  <el-button type="danger" link style="padding: 0; margin-left: 5px;" @click="clearExistSiteFilter">清除</el-button>
                </div>
                <div v-if="tempFilters.notExistSiteNames.length > 0" style="display: flex; align-items: center;">
                  <el-tag type="info" size="default" effect="plain">不存在于: {{ tempFilters.notExistSiteNames.length }}</el-tag>
                  <el-button type="danger" link style="padding: 0; margin-left: 5px;" @click="clearNotExistSiteFilter">清除</el-button>
                </div>
              </div>
            </div>
            <div class="site-checkbox-container">
              <el-checkbox-group v-model="currentSiteNames">
                <el-checkbox v-for="site in filteredSiteOptions" :key="site" :label="site"
                  :disabled="!isSiteAvailable(site)" :class="{ 'disabled-site': !isSiteAvailable(site) }">{{
                    site
                  }}</el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
          <el-divider content-position="left">下载器</el-divider>
          <div style="margin-bottom: 10px;">
            <div v-if="tempFilters.downloaderIds.length > 0" style="display: flex; align-items: center;">
              <el-tag type="info" size="default" effect="plain">下载器: {{ tempFilters.downloaderIds.length }}</el-tag>
              <el-button type="danger" link style="padding: 0; margin-left: 5px;" @click="clearDownloaderFilter">清除</el-button>
            </div>
          </div>
          <el-checkbox-group v-model="tempFilters.downloaderIds">
            <el-checkbox v-for="downloader in downloadersList" :key="downloader.id" :label="downloader.id">
              {{ downloader.name }}
            </el-checkbox>
          </el-checkbox-group>
          <el-divider content-position="left">保存路径</el-divider>
          <div style="margin-bottom: 10px;">
            <div v-if="tempFilters.paths.length > 0" style="display: flex; align-items: center;">
              <el-tag type="info" size="default" effect="plain">路径: {{ tempFilters.paths.length }}</el-tag>
              <el-button type="danger" link style="padding: 0; margin-left: 5px;" @click="clearPathFilter">清除</el-button>
            </div>
          </div>
          <div class="path-tree-container">
            <el-tree ref="pathTreeRef" :data="pathTreeData" show-checkbox node-key="path" default-expand-all
              check-on-click-node :props="{ class: 'path-tree-node' }" />
          </div>
          <el-divider content-position="left">状态</el-divider>
          <div style="margin-bottom: 10px;">
            <div v-if="tempFilters.states.length > 0" style="display: flex; align-items: center;">
              <el-tag type="info" size="default" effect="plain">状态: {{ tempFilters.states.length }}</el-tag>
              <el-button type="danger" link style="padding: 0; margin-left: 5px;" @click="clearStateFilter">清除</el-button>
            </div>
          </div>
          <el-checkbox-group v-model="tempFilters.states">
            <el-checkbox v-for="state in unique_states" :key="state" :label="state">{{
              state
              }}</el-checkbox>
          </el-checkbox-group>
        </div>
        <div class="filter-card-footer">
          <el-button @click="clearFilters">清除筛选</el-button>
          <el-button @click="filterDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="applyFilters">确认</el-button>
        </div>
      </el-card>
    </div>

    <!-- 站点操作弹窗 -->
    <div v-if="siteOperationDialogVisible" class="filter-overlay" @click.self="siteOperationDialogVisible = false">
      <el-card class="filter-card" style="max-width: 400px;">
        <template #header>
          <div class="filter-card-header">
            <span>站点操作</span>
            <el-button type="danger" circle @click="siteOperationDialogVisible = false" plain>X</el-button>
          </div>
        </template>
        <div class="site-operation-body">
          <div class="torrent-name-container">
            <p class="label">种子名称:</p>
            <p class="torrent-name">{{ selectedTorrentName }}</p>
          </div>
          <p>站点名称: {{ selectedSite?.name }}</p>
          <p>当前状态: {{ selectedSite?.data.state }}</p>
          <div v-if="hasLink(selectedSite?.data, selectedSite?.name)" class="site-operation-link">
            <p class="label">详情页链接:</p>
            <el-link :href="getLink(selectedSite?.data, selectedSite?.name)" target="_blank" type="primary"
              :underline="false">
              {{ getLink(selectedSite?.data, selectedSite?.name) }}
            </el-link>
          </div>
          <div class="site-operation-buttons">
            <el-button @click="siteOperationDialogVisible = false">取消</el-button>
            <el-button type="primary" @click="setSiteNotExist">设为不存在</el-button>
          </div>
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
          <div class="site-list-box glass-site-box">
            <el-tag v-for="site in allSourceSitesStatus" :key="site.name"
              :type="getSiteTagType(site, isSourceSiteSelectable(site.name))"
              :class="{ 'is-selectable': isSourceSiteSelectable(site.name) }" class="site-tag"
              @click="isSourceSiteSelectable(site.name) && confirmSourceSiteAndProceed(getSiteDetails(site.name))">
              {{ site.name }}
            </el-tag>
          </div>
        </div>
        <div class="filter-card-footer">
          <el-button type="warning" @click="triggerIYUUQuery" :loading="iyuuQueryLoading" plain>IYUU查询</el-button>
          <el-button @click="sourceSelectionDialogVisible = false">取消</el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, watch, defineEmits, nextTick, computed } from 'vue'
import { ElMessage } from 'element-plus';
import type { TableInstance, Sort } from 'element-plus'
import type { ElTree } from 'element-plus'
import CrossSeedPanel from '../components/CrossSeedPanel.vue'
import { useCrossSeedStore } from '@/stores/crossSeed'
import type { ISourceInfo } from '@/types'

const emits = defineEmits(['ready'])

interface SiteData {
  uploaded: number
  comment: string
  migration: number
  state: string
}

interface OtherSite {
  name: string
  data: SiteData
}

interface Torrent {
  unique_id: string
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
  downloaderIds?: string[]
  target_sites_count?: number
}
interface SiteStatus {
  name: string;
  has_cookie: boolean;
  is_source: boolean;
  is_target: boolean;
}
interface ActiveFilters {
  paths: string[]
  states: string[]
  existSiteNames: string[]
  notExistSiteNames: string[]
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
  enabled?: boolean;
}

// const router = useRouter();

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
  existSiteNames: [],
  notExistSiteNames: [],
  downloaderIds: [],
})
const tempFilters = reactive<ActiveFilters>({ ...activeFilters })

// 站点筛选模式相关
const siteFilterMode = ref<'exist' | 'not-exist'>('exist')

// 计算当前显示的站点名称（根据筛选模式）
const currentSiteNames = computed({
  get: () => {
    return siteFilterMode.value === 'exist'
      ? tempFilters.existSiteNames
      : tempFilters.notExistSiteNames
  },
  set: (val) => {
    if (siteFilterMode.value === 'exist') {
      tempFilters.existSiteNames = val
    } else {
      tempFilters.notExistSiteNames = val
    }
  }
})
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
const allDownloadersList = ref<Downloader[]>([]);

const pathTreeRef = ref<InstanceType<typeof ElTree> | null>(null)
const pathTreeData = ref<PathNode[]>([])

const sourceSelectionDialogVisible = ref<boolean>(false);
const allSourceSitesStatus = ref<SiteStatus[]>([]);
const iyuuQueryLoading = ref<boolean>(false);

const crossSeedStore = useCrossSeedStore();

// 控制转种弹窗的显示，当 taskId 存在时显示
const crossSeedDialogVisible = computed(() => !!crossSeedStore.taskId);
// 从 store 获取选中的种子信息
const selectedTorrentForMigration = computed(() => crossSeedStore.workingParams as Torrent | null);
// 从 store 获取源站点名称
const selectedSourceSite = computed(() => crossSeedStore.sourceInfo?.name || '');

// 站点操作弹窗相关
const siteOperationDialogVisible = ref<boolean>(false);
const selectedTorrentName = ref<string>('');
const selectedSite = ref<OtherSite | null>(null);

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

// 计算当前筛选条件的显示文本
const currentFilterText = computed(() => {
  const filters = activeFilters
  const filterTexts = []

  // 处理保存路径筛选
  if (filters.paths && filters.paths.length > 0) {
    filterTexts.push(`路径: ${filters.paths.length}`)
  }

  // 处理状态筛选
  if (filters.states && filters.states.length > 0) {
    filterTexts.push(`状态: ${filters.states.length}`)
  }

  // 处理站点筛选
  if (filters.existSiteNames && filters.existSiteNames.length > 0) {
    filterTexts.push(`存在于: ${filters.existSiteNames.length}`)
  }
  if (filters.notExistSiteNames && filters.notExistSiteNames.length > 0) {
    filterTexts.push(`不存在于: ${filters.notExistSiteNames.length}`)
  }

  // 处理下载器筛选
  if (filters.downloaderIds && filters.downloaderIds.length > 0) {
    filterTexts.push(`下载器: ${filters.downloaderIds.length}`)
  }

  return filterTexts.join(', ')
})

// 检查是否有任何筛选条件被应用
const hasActiveFilters = computed(() => {
  const filters = activeFilters
  return (
    (filters.paths && filters.paths.length > 0) ||
    (filters.states && filters.states.length > 0) ||
    (filters.existSiteNames && filters.existSiteNames.length > 0) ||
    (filters.notExistSiteNames && filters.notExistSiteNames.length > 0) ||
    (filters.downloaderIds && filters.downloaderIds.length > 0)
  )
})

// 计算在当前模式下可选的站点（排除已在另一种模式下选择的站点）
const availableSiteOptions = computed(() => {
  const allSites = filteredSiteOptions.value
  if (siteFilterMode.value === 'exist') {
    // 在"存在于"模式下，排除已在"不存在于"中选择的站点
    return allSites.filter(site => !tempFilters.notExistSiteNames.includes(site))
  } else {
    // 在"不存在于"模式下，排除已在"存在于"中选择的站点
    return allSites.filter(site => !tempFilters.existSiteNames.includes(site))
  }
})

// 检查特定站点在当前模式下是否可用
const isSiteAvailable = (site: string) => {
  if (siteFilterMode.value === 'exist') {
    // 在"存在于"模式下，检查是否未在"不存在于"中选择
    return !tempFilters.notExistSiteNames.includes(site)
  } else {
    // 在"不存在于"模式下，检查是否未在"存在于"中选择
    return !tempFilters.existSiteNames.includes(site)
  }
}

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
      // 确保新的站点筛选字段存在
      if (!activeFilters.existSiteNames) {
        activeFilters.existSiteNames = [];
      }
      if (!activeFilters.notExistSiteNames) {
        activeFilters.notExistSiteNames = [];
      }
      // 兼容旧的数据结构
      // 注意：TypeScript类型检查会报错，因为这些属性已不存在于接口定义中
      // 但在运行时可能仍然存在旧数据，所以需要处理
      const filters: any = activeFilters;
      if (filters.siteExistence) {
        // 旧的siteExistence字段不再使用
        delete filters.siteExistence;
      }
      if (filters.siteNames) {
        // 旧的siteNames字段不再使用
        delete filters.siteNames;
      }
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
    const response = await fetch('/api/all_downloaders');
    if (!response.ok) throw new Error('无法获取下载器列表');
    const allDownloaders = await response.json();
    // 只显示启用的下载器在筛选器中
    downloadersList.value = allDownloaders.filter((d: any) => d.enabled);
    // 保存所有下载器信息用于显示
    allDownloadersList.value = allDownloaders;
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
      existSiteNames: JSON.stringify(activeFilters.existSiteNames),
      notExistSiteNames: JSON.stringify(activeFilters.notExistSiteNames),
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
  // 在开始转种流程前，先重置 store，防止旧数据污染
  crossSeedStore.reset();

  const availableSources = Object.entries(row.sites)
    .map(([siteName, siteDetails]) => ({ siteName, ...siteDetails }))
    .filter(site => {
      const isSourceSite = site.migration === 1 || site.migration === 3;
      if (!isSourceSite) return false;
      const hasDetailsLink = site.comment && site.comment.includes('details.php?id=');
      const hasTorrentId = site.comment && /^\d+$/.test(site.comment.trim());
      return hasDetailsLink || hasTorrentId;
    });

  // 将当前要操作的种子信息存入 store
  crossSeedStore.setParams(row);
  
  // 即使没有可用的源站点，也打开弹窗，让用户可以使用 IYUU 查询
  if (availableSources.length === 0) {
    ElMessage.warning('该种子暂无可用的源站点，您可以使用 IYUU 查询来发现更多站点。');
  }
  
  sourceSelectionDialogVisible.value = true;
};

const confirmSourceSiteAndProceed = async (sourceSite: any) => {
  const row = selectedTorrentForMigration.value;
  if (!row) {
    ElMessage.error('发生内部错误：未找到选中的种子信息。');
    sourceSelectionDialogVisible.value = false;
    return;
  }

  const siteDetails = row.sites[sourceSite.siteName];
  let torrentId = null;

  const idMatch = siteDetails?.comment?.match(/id=(\d+)/);
  if (idMatch && idMatch[1]) {
    torrentId = idMatch[1];
  } else if (siteDetails?.comment && /^\d+$/.test(siteDetails.comment.trim())) {
    torrentId = siteDetails.comment.trim();
  } else {
    try {
      const response = await fetch('/api/migrate/search_torrent_id', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sourceSite: sourceSite.siteName, torrentName: row.name })
      });
      const result = await response.json();
      if (result.success && result.torrent_id) {
        torrentId = result.torrent_id;
        ElMessage.success(`通过种子名称搜索成功获取到ID: ${torrentId}`);
      } else {
        ElMessage.error(`无法从源站点 ${sourceSite.siteName} 获取种子ID：${result.message || '搜索失败'}`);
        sourceSelectionDialogVisible.value = false;
        return;
      }
    } catch (error: any) {
      ElMessage.error(`搜索种子ID时发生网络错误：${error.message}`);
      sourceSelectionDialogVisible.value = false;
      return;
    }
  }

  if (siteDetails) {
    // @ts-ignore
    siteDetails.torrentId = torrentId;
  }

  const sourceSiteName = sourceSite.siteName;
  const sourceSiteIdentifier = allSourceSitesStatus.value.find(s => s.name === sourceSiteName)?.site || sourceSiteName.toLowerCase();

  ElMessage.success(`准备从站点 [${sourceSiteName}] 开始迁移种子...`);

  // 设置 store，触发转种弹窗
  const sourceInfo: ISourceInfo = {
    name: sourceSiteName,
    site: sourceSiteIdentifier,
    torrentId,
  };
  crossSeedStore.setSourceInfo(sourceInfo);
  crossSeedStore.setTaskId(row.name + '_' + Date.now()); // 使用时间戳确保唯一性

  sourceSelectionDialogVisible.value = false;
  // crossSeedDialogVisible 会通过 computed 属性自动变为 true
};

const isSourceSiteSelectable = (siteName: string): boolean => {
  return !!(selectedTorrentForMigration.value && selectedTorrentForMigration.value.sites[siteName]);
};

const closeCrossSeedDialog = () => {
  crossSeedStore.reset();
};

// 处理站点点击事件
const handleSiteClick = (torrentName: string, site: OtherSite) => {
  // 只有当站点状态为"未做种"时才显示操作弹窗
  if (site.data.state === '未做种') {
    selectedTorrentName.value = torrentName;
    selectedSite.value = site;
    siteOperationDialogVisible.value = true;
  }
};


// 设置站点为不存在
const setSiteNotExist = async () => {
  if (!selectedTorrentName.value || !selectedSite.value) {
    ElMessage.error('缺少必要的参数');
    return;
  }

  try {
    const response = await fetch('/api/sites/set_not_exist', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        torrent_name: selectedTorrentName.value,
        site_name: selectedSite.value.name
      })
    });

    if (response.ok) {
      ElMessage.success('站点状态已成功设置为不存在');
      siteOperationDialogVisible.value = false;
      // 重新加载数据以反映更改
      fetchData();
    } else {
      const result = await response.json();
      ElMessage.error(result.error || '设置站点状态失败');
    }
  } catch (error) {
    console.error('设置站点状态时出错:', error);
    ElMessage.error('设置站点状态时发生错误');
  }
};

const handleCrossSeedComplete = () => {
  ElMessage.success('转种操作已完成！');
  crossSeedStore.reset();
  // 可选：刷新数据以显示最新状态
  fetchData();
};

const getSiteDetails = (siteName: string) => {
  if (!selectedTorrentForMigration.value) return null;
  const siteData = selectedTorrentForMigration.value.sites[siteName];
  if (!siteData) return null;
  return { siteName, ...siteData };
};

// IYUU 查询功能
const triggerIYUUQuery = async () => {
  const row = selectedTorrentForMigration.value;
  if (!row) {
    ElMessage.error('未找到选中的种子信息');
    return;
  }

  iyuuQueryLoading.value = true;

  try {
    const response = await fetch('/api/iyuu_query', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name: row.name,
        size: row.size
      })
    });

    const result = await response.json();

    if (response.ok && result.success) {
      ElMessage.success(result.message || 'IYUU查询已完成');
      // 刷新数据
      await fetchData();
      
      // 更新 store 中的种子信息为最新数据
      const updatedRow = allData.value.find(t => t.name === row.name && t.size === row.size);
      if (updatedRow) {
        crossSeedStore.setParams(updatedRow);
      }
    } else {
      ElMessage.error(result.error || 'IYUU查询失败');
    }
  } catch (error: any) {
    console.error('触发IYUU查询时出错:', error);
    ElMessage.error('触发IYUU查询时发生网络错误');
  } finally {
    iyuuQueryLoading.value = false;
  }
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

// 清除筛选条件
const clearFilters = () => {
  // 重置临时筛选条件
  tempFilters.paths = []
  tempFilters.states = []
  tempFilters.existSiteNames = []
  tempFilters.notExistSiteNames = []
  tempFilters.downloaderIds = []

  // 重置站点筛选模式
  siteFilterMode.value = 'exist'

  // 重置搜索
  siteSearch.value = ''

  // 清除路径树的选中状态
  if (pathTreeRef.value) {
    pathTreeRef.value.setCheckedKeys([], false)
  }
}

// 清除"存在于"站点筛选
const clearExistSiteFilter = () => {
  tempFilters.existSiteNames = []
  // 如果当前是"存在于"模式，更新树的选中状态
  if (siteFilterMode.value === 'exist' && pathTreeRef.value) {
    const selectedPaths = pathTreeRef.value.getCheckedKeys(true)
    tempFilters.paths = selectedPaths as string[]
  }
}

// 清除"不存在于"站点筛选
const clearNotExistSiteFilter = () => {
  tempFilters.notExistSiteNames = []
  // 如果当前是"不存在于"模式，更新树的选中状态
  if (siteFilterMode.value === 'not-exist' && pathTreeRef.value) {
    const selectedPaths = pathTreeRef.value.getCheckedKeys(true)
    tempFilters.paths = selectedPaths as string[]
  }
}

// 清除路径筛选
const clearPathFilter = () => {
  tempFilters.paths = []
  // 清除路径树的选中状态
  if (pathTreeRef.value) {
    pathTreeRef.value.setCheckedKeys([], false)
  }
}

// 清除状态筛选
const clearStateFilter = () => {
  tempFilters.states = []
}

// 清除下载器筛选
const clearDownloaderFilter = () => {
  tempFilters.downloaderIds = []
}

// 清除所有筛选和搜索条件
const clearAllFilters = async () => {
  // 重置所有筛选条件
  activeFilters.paths = []
  activeFilters.states = []
  activeFilters.existSiteNames = []
  activeFilters.notExistSiteNames = []
  activeFilters.downloaderIds = []

  // 重置名称搜索
  nameSearch.value = ''

  // 重置站点筛选模式
  siteFilterMode.value = 'exist'

  // 重置站点搜索
  siteSearch.value = ''

  // 清除路径树的选中状态
  if (pathTreeRef.value) {
    pathTreeRef.value.setCheckedKeys([], false)
  }

  // 重置到第一页并获取数据
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
const getTagType = (siteData: SiteData) => {
  if (siteData.state === '未做种') {
    return 'danger';
  }
  else if (siteData.state === '不存在') {
    return 'info';
  }
  else if (siteData.comment) {
    return 'success';
  }
  else if (siteData.state === '做种中') {
    return 'primary';
  }
  else return 'info';
}

const getDownloaderName = (downloaderId: string | null) => {
  if (!downloaderId) return '未知下载器'
  const downloader = allDownloadersList.value.find(d => d.id === downloaderId)
  return downloader ? downloader.name : '未知下载器'
}

const getDownloaderTagType = (downloaderId: string | null) => {
  if (!downloaderId) return 'info'
  // Generate a consistent color based on the downloader ID
  const downloader = allDownloadersList.value.find(d => d.id === downloaderId)
  if (!downloader) return 'info'

  // Simple hash function to generate a consistent color index
  let hash = 0
  for (let i = 0; i < downloaderId.length; i++) {
    hash = downloaderId.charCodeAt(i) + ((hash << 5) - hash)
  }

  // Map hash to Element Plus tag types
  const types = ['primary', 'success', 'warning', 'danger', 'info']
  return types[Math.abs(hash) % types.length]
}

const sortedDownloaderIds = (downloaderIds: string[]) => {
  // Create a copy of the array to avoid modifying the original
  const sortedIds = [...downloaderIds]

  // Sort by downloader name for consistent ordering
  return sortedIds.sort((a, b) => {
    const nameA = getDownloaderName(a)
    const nameB = getDownloaderName(b)
    return nameA.localeCompare(nameB, 'zh-CN')
  })
}

const shortenPath = (path: string, maxLength: number = 50) => {
  if (!path || path.length <= maxLength) {
    return path
  }

  // 对于路径，我们尝试保留开头和结尾的部分
  const halfLength = Math.floor((maxLength - 3) / 2)

  // 确保我们不会在路径分隔符中间截断
  let start = path.substring(0, halfLength)
  let end = path.substring(path.length - halfLength)

  // 如果可能的话，尝试在路径分隔符处截断
  const lastSeparatorInStart = start.lastIndexOf('/')
  const firstSeparatorInEnd = end.indexOf('/')

  if (lastSeparatorInStart > 0 && firstSeparatorInEnd >= 0) {
    start = start.substring(0, lastSeparatorInStart)
    end = end.substring(firstSeparatorInEnd + 1)
  }

  return `${start}...${end}`
}

const getDisabledDownloaderIds = () => {
  return allDownloadersList.value
    .filter(d => d.enabled === false)
    .map(d => d.id);
}

// 根据站点配置和可选性返回标签类型
const getSiteTagType = (site: SiteStatus, isSelectable: boolean) => {
  // 如果站点不可选，显示为灰色
  if (!isSelectable) {
    return 'info';
  }
  // 如果站点已配置Cookie，显示为绿色
  if (site.has_cookie) {
    return 'success';
  }
  // 如果站点未配置Cookie，显示为蓝色
  return 'primary';
}
const getStateTagType = (state: string) => {
  if (state.includes('下载')) return 'primary'
  if (state.includes('做种')) return 'success'
  if (state.includes('暂停')) return 'warning'
  if (state.includes('错误') || state.includes('丢失')) return 'danger'
  return 'info'
}

const handleRowClick = (row: Torrent) => tableRef.value?.toggleRowExpansion(row)
const handleExpandChange = (row: Torrent, expanded: Torrent[]) => {
  expandedRows.value = expanded.map((r) => r.unique_id)
}
const tableRowClassName = ({ row }: { row: Torrent }) => {
  return expandedRows.value.includes(row.unique_id) ? 'expanded-row' : ''
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
// 移除旧的监听器，现在不需要根据siteExistence值清空siteNames
</script>

<style scoped>
.torrents-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* 表格和分页器样式已移至 glass-morphism.scss */

.disabled-site {
  opacity: 0.5;
  text-decoration: line-through;
}

.disabled-site :deep(.el-checkbox__input.is-disabled) {
  opacity: 0.5;
}

.compact-radio-button :deep(.el-radio-button__inner) {
  font-size: 14px;
  padding: 8px 20px;
  border-radius: 0;
}

.compact-radio-button:first-child :deep(.el-radio-button__inner) {
  border-top-left-radius: 4px;
  border-bottom-left-radius: 4px;
}

.compact-radio-button:last-child :deep(.el-radio-button__inner) {
  border-top-right-radius: 4px;
  border-bottom-right-radius: 4px;
  margin-left: -1px;
}

:deep(.el-table__body .cell) {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

:deep(.el-table__header .cell) {
  display: flex;
  align-items: center;
  justify-content: center;
}

.name-header-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
  flex: 1;
}

.name-header-container .search-input {
  width: calc(30vw - 100px);
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
  height: 160px;
  /* 固定高度，避免筛选结果变少时区域高度跳变 */
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

/* 分页器样式已移至 glass-morphism.css */

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

/* 站点操作弹窗样式 */
.site-operation-body {
  padding: 20px;
}

.site-operation-body p {
  margin: 10px 0;
}

.torrent-name-container {
  margin: 10px 0;
}

.torrent-name-container .label {
  font-weight: bold;
  margin-bottom: 5px;
}

.torrent-name {
  word-wrap: break-word;
  word-break: break-all;
  white-space: normal;
  max-height: 100px;
  overflow-y: auto;
  padding: 5px;
  background-color: #f5f7fa;
  border-radius: 4px;
}

.site-operation-link {
  margin: 15px 0;
}

.site-operation-link .label {
  font-weight: bold;
  margin-bottom: 5px;
}

.site-operation-link :deep(.el-link) {
  word-wrap: break-word;
  word-break: break-all;
  white-space: normal;
}

.site-operation-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

/* 转种弹窗样式 */
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
  z-index: 2000;
}

.cross-seed-card {
  width: 90vw;
  max-width: 1200px;
  height: 90vh;
  max-height: 800px;
  display: flex;
  flex-direction: column;
  position: relative; /* 添加相对定位，作为 LogProgress 的定位上下文 */
}

:deep(.cross-seed-card .el-card__body) {
  padding: 10px;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.cross-seed-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
