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
          <div class="expand-content"
            :class="{ 'with-special-sites': (props.row.sites['财神'] && props.row.sites['财神'].state !== '不存在') || (props.row.sites['星陨阁'] && props.row.sites['星陨阁'].state !== '不存在') }">
            <!-- 所有站点容器 -->
            <div class="all-sites-container">
              <!-- 特殊站点容器 -->
              <div class="special-sites-container">

                <!-- 财神站点 -->
                <div class="caishen-container">
                  <!-- [修改] 使用 v-if/v-else 切换显示 -->
                  <template v-if="props.row.sites['财神'] && props.row.sites['财神'].state !== '不存在'">
                    <!-- 当财神站点存在且状态不为"不存在"时，显示特效标签 (原有逻辑) -->
                    <a v-if="hasLink(props.row.sites['财神'], '财神') && props.row.sites['财神'].state !== '未做种'"
                      :href="getLink(props.row.sites['财神'], '财神')!" target="_blank" style="text-decoration: none">
                      <div class="caishen-tag animated-tag">
                        <div class="site-name">财神</div>
                        <div class="site-upload-data">({{ formatBytes(props.row.sites['财神'].uploaded) }})</div>
                      </div>
                    </a>
                    <div v-else class="caishen-tag animated-tag"
                      @click.stop="handleSpecialSiteClick(props.row.name, '财神', props.row.sites['财神'])">
                      <div class="site-name">财神</div>
                      <div class="site-upload-data">({{ formatBytes(props.row.sites['财神'].uploaded) }})</div>
                    </div>
                  </template>
                  <template v-else>
                    <!-- 当财神站点不存在或状态为"不存在"时，显示占位标签 -->
                    <div class="special-site-placeholder">
                      <div class="site-name">财神</div>
                      <div class="site-upload-data">(0B)</div>
                    </div>
                  </template>
                </div>

                <!-- 星陨阁站点 -->
                <div class="xingyunge-container">
                  <!-- [修改] 使用 v-if/v-else 切换显示 -->
                  <template v-if="props.row.sites['星陨阁'] && props.row.sites['星陨阁'].state !== '不存在'">
                    <!-- 当星陨阁站点存在且状态不为"不存在"时，显示特效标签 (原有逻辑) -->
                    <a v-if="hasLink(props.row.sites['星陨阁'], '星陨阁') && props.row.sites['星陨阁'].state !== '未做种'"
                      :href="getLink(props.row.sites['星陨阁'], '星陨阁')!" target="_blank" style="text-decoration: none">
                      <div class="xingyunge-tag animated-tag-flame">
                        <div class="site-name">星陨阁</div>
                        <div class="site-upload-data">({{ formatBytes(props.row.sites['星陨阁'].uploaded) }})</div>
                      </div>
                    </a>
                    <div v-else class="xingyunge-tag animated-tag-flame"
                      @click.stop="handleSpecialSiteClick(props.row.name, '星陨阁', props.row.sites['星陨阁'])">
                      <div class="site-name">星陨阁</div>
                      <div class="site-upload-data">({{ formatBytes(props.row.sites['星陨阁'].uploaded) }})</div>
                    </div>
                  </template>
                  <template v-else>
                    <!-- 当星陨阁站点不存在或状态为"不存在"时，显示占位标签 -->
                    <div class="special-site-placeholder">
                      <div class="site-name">星陨阁</div>
                      <div class="site-upload-data">(0B)</div>
                    </div>
                  </template>
                </div>

              </div>

              <!-- 其他站点 -->
              <template v-for="(site, index) in getOtherSites(props.row.sites, all_sites)" :key="site.name">
                <div class="other-site-item" :style="getSitePosition(index)">
                  <!-- 对于未做种状态的站点，使用可点击的div而不是链接 -->
                  <a v-if="hasLink(site.data, site.name) && site.data.state !== '未做种'"
                    :href="getLink(site.data, site.name)!" target="_blank" style="text-decoration: none;width: 80px;">
                    <div class="site-wrapper">
                      <el-tag effect="dark" :type="getTagType(site.data)" class="other-site-tag"
                        style="text-align: center">
                        {{ site.name }}
                        <div>({{ formatBytes(site.data.uploaded) }})</div>
                      </el-tag>
                    </div>
                  </a>
                  <div v-else class="site-wrapper">
                    <el-tag :effect="site.data.state !== '未做种' ? 'plain' : 'dark'" :type="getTagType(site.data)"
                      class="other-site-tag" style="text-align: center;width: 80px; cursor: pointer;"
                      @click.stop="handleSiteClick(props.row.name, site)">
                      {{ site.name }}
                      <div>({{ formatBytes(site.data.uploaded) }})</div>
                    </el-tag>
                  </div>
                </div>
              </template>
            </div>
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

    <el-pagination v-if="totalTorrents > 0" style="margin-top: 15px; justify-content: flex-end"
      v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[20, 50, 100, 200, 500]"
      :total="totalTorrents" layout="total, sizes, prev, pager, next, jumper" @size-change="handleSizeChange"
      @current-change="handleCurrentChange" background />

    <!-- 转种弹窗 -->
    <div v-if="crossSeedDialogVisible" class="modal-overlay" @click.self="closeCrossSeedDialog">
      <el-card class="cross-seed-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>转种 - {{ selectedTorrentForMigration?.name }}</span>
            <el-button type="danger" circle @click="closeCrossSeedDialog" plain>X</el-button>
          </div>
        </template>
        <div class="cross-seed-content" v-if="selectedTorrentForMigration">
          <CrossSeedPanel :torrent="selectedTorrentForMigration" :source-site="selectedSourceSite"
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
          <div class="site-list-box">
            <el-tag v-for="site in allSourceSitesStatus" :key="site.name"
              :type="getSiteTagType(site, isSourceSiteSelectable(site.name))"
              :class="{ 'is-selectable': isSourceSiteSelectable(site.name) }" class="site-tag"
              @click="isSourceSiteSelectable(site.name) && confirmSourceSiteAndProceed(getSiteDetails(site.name))">
              {{ site.name }}
            </el-tag>
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
import { ElMessage } from 'element-plus';
import type { TableInstance, Sort } from 'element-plus'
import type { ElTree } from 'element-plus'
import CrossSeedPanel from '../components/CrossSeedPanel.vue'

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
  has_passkey: boolean;
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
const selectedTorrentForMigration = ref<Torrent | null>(null);
const crossSeedDialogVisible = ref<boolean>(false);
const selectedSourceSite = ref<string>('');

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
  const availableSources = Object.entries(row.sites)
    .map(([siteName, siteDetails]) => ({ siteName, ...siteDetails }))
    .filter(site => {
      // 检查站点是否配置为源站点
      const isSourceSite = site.migration === 1 || site.migration === 3;
      if (!isSourceSite) return false;

      // 检查是否有有效的种子ID或链接
      // 1. 完整的详情页链接
      const hasDetailsLink = site.comment && site.comment.includes('details.php?id=');
      // 2. 只有种子ID的情况（纯数字）
      const hasTorrentId = site.comment && /^\d+$/.test(site.comment.trim());

      return hasDetailsLink || hasTorrentId;
    });

  if (availableSources.length === 0) {
    ElMessage.error('该种子没有找到可用的、已配置为源站点的做种站点。');
    return;
  }

  selectedTorrentForMigration.value = row;
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

  // 首先检查是否能从链接中提取到ID
  const idMatch = siteDetails?.comment?.match(/id=(\d+)/);
  if (idMatch && idMatch[1]) {
    torrentId = idMatch[1];
  }
  // 检查注释是否只包含纯数字（种子ID）
  else if (siteDetails?.comment && /^\d+$/.test(siteDetails.comment.trim())) {
    torrentId = siteDetails.comment.trim();
  }
  // 如果以上都无法提取到ID，则使用种子名称进行搜索
  else {
    try {
      const response = await fetch('/api/migrate/search_torrent_id', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          sourceSite: sourceSite.siteName,
          torrentName: row.name
        })
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
    } catch (error) {
      ElMessage.error(`搜索种子ID时发生网络错误：${error.message}`);
      sourceSelectionDialogVisible.value = false;
      return;
    }
  }

  // 将获取到的种子ID存储起来，供后续使用
  if (siteDetails) {
    siteDetails.torrentId = torrentId;
  }

  const sourceSiteName = sourceSite.siteName;

  ElMessage.success(`准备从站点 [${sourceSiteName}] 开始迁移种子...`);

  // 设置选中的源站点并打开转种弹窗
  selectedSourceSite.value = sourceSiteName;
  sourceSelectionDialogVisible.value = false;
  crossSeedDialogVisible.value = true;
};

const isSourceSiteSelectable = (siteName: string): boolean => {
  return !!(selectedTorrentForMigration.value && selectedTorrentForMigration.value.sites[siteName]);
};

const closeCrossSeedDialog = () => {
  crossSeedDialogVisible.value = false;
  selectedTorrentForMigration.value = null;
  selectedSourceSite.value = '';
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

// 处理特殊站点点击事件
const handleSpecialSiteClick = (torrentName: string, siteName: string, siteData: SiteData) => {
  // 只有当站点状态为"未做种"时才显示操作弹窗
  if (siteData.state === '未做种') {
    selectedTorrentName.value = torrentName;
    selectedSite.value = {
      name: siteName,
      data: siteData
    };
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
  closeCrossSeedDialog();
  // 可选：刷新数据以显示最新状态
  fetchData();
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
  expandedRows.value = expanded.map((r) => r.name)
}
const tableRowClassName = ({ row }: { row: Torrent }) => {
  return expandedRows.value.includes(row.name) ? 'expanded-row' : ''
}

// 获取除了特殊站点外的其他站点，包括未做种的站点，但排除状态为"不存在"的站点
const getOtherSites = (sites: Record<string, SiteData>, allSiteNames: string[]): OtherSite[] => {
  const specialSites = ['财神', '星陨阁'];
  const otherSites: OtherSite[] = [];

  // 添加所有在数据库中存在的站点，但排除状态为"不存在"的站点
  allSiteNames.forEach(siteName => {
    if (!specialSites.includes(siteName)) {
      // 如果站点在当前种子中存在，则使用实际数据
      const siteData = sites[siteName];

      // 如果站点数据存在且状态为"不存在"，则跳过该站点
      if (siteData && siteData.state === '不存在') {
        return;
      }

      // 否则，创建一个表示"未添加"的占位站点
      const finalSiteData = siteData || {
        uploaded: 0,
        comment: '',
        migration: 0,
        state: '未添加' // <--- [修改] 使用一个明确的状态来表示占位
      };

      otherSites.push({
        name: siteName,
        data: finalSiteData
      });
    }
  });

  return otherSites;
}

// 计算站点位置样式
// 计算站点位置样式
const getSitePosition = (index: number): { 'grid-row': number; 'grid-column': number } => {
  let availablePositionCount = 0;
  const maxRows = 20; // 您可以根据需要调整最大行数，以容纳更多站点

  for (let row = 1; row <= maxRows; row++) {
    for (let col = 1; col <= 20; col++) {
      // 检查当前单元格是否位于为特殊站点保留的区域
      // 根据您的CSS，特殊站点容器占据 grid-column: 9 / span 4 (即 9, 10, 11, 12列)
      // 和 grid-row: 2 / span 2 (即 2, 3行)
      const isReserved = col >= 9 && col <= 12 && row >= 2 && row <= 3;

      if (!isReserved) {
        // 如果不是保留区域，则这是一个可用的位置
        if (availablePositionCount === index) {
          // 当可用位置的计数等于当前站点的索引时，
          // 我们就找到了这个站点应该放置的位置
          return {
            'grid-row': row,
            'grid-column': col
          };
        }
        availablePositionCount++;
      }
    }
  }

  // 如果循环结束还没找到位置（例如索引过大），提供一个默认的回退位置
  return { 'grid-row': 1, 'grid-column': 1 };
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
  grid-template-columns: repeat(20, 1fr);
  grid-auto-rows: minmax(40px, auto);
  gap: 5px;
}

.expand-content.with-special-sites {
  display: grid;
  grid-template-columns: repeat(20, 1fr);
  grid-auto-rows: minmax(40px, auto);
  gap: 5px;
  align-items: start;
  justify-content: start;
}

/* 所有站点容器 */
.all-sites-container {
  display: contents;
}


/* 普通站点项 */
.other-site-item {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 80px;
}

/* 特殊站点容器 */
.special-sites-container {
  grid-column: 9 / span 4;
  grid-row: 2 / span 2;
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  min-height: 80px;
  font-size: 14px;
  position: relative;
  z-index: 1;
}

.caishen-container {
  display: flex;
  justify-content: center;
  align-items: center;
  margin: 0;
  width: 180px;
  height: 80px;
  flex-shrink: 0;
  box-sizing: border-box;
}

.caishen-tag {
  width: 100%;
  height: 100%;
  font-size: 20px;
  font-weight: bold;
  background: linear-gradient(45deg, #ffd700, #ffed4e, #ffd700);
  color: #8b4513;
  border: 3px solid #ffd700;
  box-shadow: 0 0 15px #ffd700, 0 0 30px #ff8c00, 0 0 45px #ff4500;
  position: relative;
  overflow: hidden;
  transform: scale(1);
  transition: transform 0.3s ease;
  text-shadow: 0 0 5px #fff, 0 0 10px #ffd700;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  flex-shrink: 0;
  box-sizing: border-box;
  white-space: nowrap;
  text-align: center;
  padding: 5px;
}

.caishen-tag:hover {
  transform: scale(1.05);
  box-shadow: 0 0 20px #ffd700, 0 0 40px #ff8c00, 0 0 60px #ff4500;
}

.caishen-tag div {
  font-size: 14px;
  font-weight: normal;
  color: #daa520;
  text-shadow: none;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
  box-sizing: border-box;
  white-space: nowrap;
  flex-shrink: 0;
}

.site-name {
  font-size: 16px;
  margin-bottom: 5px;
}

.special-site-placeholder {
  width: 95px;
  height: 60px;
  border: 1px solid #C8C9CC;
  color: #909399;
  background-color: #ffffff;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  box-sizing: border-box;
  white-space: nowrap;
  text-align: center;
  padding: 5px;
  border-radius: 4px;
  /* 轻微的圆角 */
  transition: all 0.3s ease;
}

.special-site-placeholder .site-upload-data {
  font-size: 14px;
  font-weight: normal;
}

.caishen-tag .site-upload-data {
  width: 80px;
  flex-shrink: 0;
  font-size: 14px;
  font-weight: normal;
  color: #daa520;
}

.caishen-tag::before {
  content: "";
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(45deg, transparent, rgba(255, 255, 255, 0.5), transparent);
  transform: rotate(45deg);
  animation: shine 2s infinite;
}

.animated-tag {
  animation: glow 1.5s ease-in-out infinite alternate, float 3s ease-in-out infinite;
}

.animated-tag-flame {
  animation: glow-flame 1.5s ease-in-out infinite alternate, float 3s ease-in-out infinite;
}


@keyframes float {
  0% {
    transform: translateY(0) scale(1);
  }

  50% {
    transform: translateY(-5px) scale(1.05);
  }

  100% {
    transform: translateY(0) scale(1);
  }
}

@keyframes glow {
  0% {
    box-shadow: 0 0 15px #ffd700, 0 0 30px #ff8c00, 0 0 45px #ff4500;
  }

  100% {
    box-shadow: 0 0 25px #ffd700, 0 0 50px #ff8c00, 0 0 75px #ff4500;
  }
}

@keyframes glow-flame {
  0% {
    box-shadow: 0 0 15px #ff4500, 0 0 30px #ff6347, 0 0 45px #ff0000;
  }

  100% {
    box-shadow: 0 0 25px #ff4500, 0 0 50px #ff6347, 0 0 75px #ff0000;
  }
}


@keyframes shine {
  0% {
    transform: translateX(-100%) translateY(-100%) rotate(45deg);
  }

  100% {
    transform: translateX(100%) translateY(100%) rotate(45deg);
  }
}

@keyframes flame-shine {
  0% {
    transform: translateX(-100%) translateY(-100%) rotate(45deg);
    opacity: 0.5;
  }

  50% {
    opacity: 0.8;
  }

  100% {
    transform: translateX(100%) translateY(100%) rotate(45deg);
    opacity: 0.5;
  }
}

.expand-content :deep(.el-tag) {
  height: 40px;
  width: 100%;
  white-space: normal;
  text-align: center;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  line-height: 1.2;
  padding: 0;
  font-size: 12px;
}

.expand-content.with-special-sites :deep(.other-site-tag) {
  height: 40px;
  font-size: 12px;
}

/* 站点包装器样式 */
.expand-content.with-special-sites .site-wrapper {
  /* 动态样式通过JavaScript设置 */
  display: flex;
  justify-content: center;
  align-items: center;
}

.expand-content :deep(.caishen-container .el-tag) {
  height: 100%;
  font-size: 20px;
  font-weight: bold;
}

/* 星陨阁站点样式 */
.xingyunge-container {
  display: flex;
  justify-content: center;
  align-items: center;
  margin: 0;
  width: 180px;
  height: 80px;
  flex-shrink: 0;
  box-sizing: border-box;
}

.xingyunge-tag {
  width: 100%;
  height: 100%;
  font-size: 20px;
  font-weight: bold;
  background: linear-gradient(45deg, #ff4500, #ff6347, #ff4500);
  color: #ffffff;
  border: 3px solid #ff4500;
  box-shadow: 0 0 15px #ff4500, 0 0 30px #ff6347, 0 0 45px #ff0000;
  position: relative;
  overflow: hidden;
  transform: scale(1);
  transition: transform 0.3s ease;
  text-shadow: 0 0 5px #fff, 0 0 10px #ff4500;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  flex-shrink: 0;
  box-sizing: border-box;
  white-space: nowrap;
  text-align: center;
  padding: 5px;
}

.xingyunge-tag:hover {
  transform: scale(1.05);
  box-shadow: 0 0 20px #ff4500, 0 0 40px #ff6347, 0 0 60px #ff0000;
}

.xingyunge-tag::before {
  content: "";
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: linear-gradient(45deg, transparent, rgba(255, 100, 0, 0.6), transparent);
  transform: rotate(45deg);
  animation: flame-shine 1.5s infinite;
}

.xingyunge-tag div {
  font-size: 14px;
  font-weight: normal;
  color: #ffd700;
  text-shadow: none;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
  box-sizing: border-box;
  white-space: nowrap;
  flex-shrink: 0;
}

.xingyunge-tag .site-upload-data {
  width: 80px;
  flex-shrink: 0;
  font-size: 14px;
  font-weight: normal;
  color: #ffd700;
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
