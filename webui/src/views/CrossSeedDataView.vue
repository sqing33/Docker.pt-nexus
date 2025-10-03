<template>
  <div class="cross-seed-data-view">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"
      style="margin: 0; border-radius: 0;"></el-alert>

    <!-- 搜索和控制栏 -->
    <div class="search-and-controls">
      <el-input v-model="searchQuery" placeholder="搜索标题或种子ID..." clearable class="search-input"
        style="width: 300px; margin-right: 15px;" />

      <!-- 批量转种按钮 -->
      <el-button type="success" @click="openBatchCrossSeedDialog" plain style="margin-right: 15px;"
        :disabled="!canBatchCrossSeed">
        {{ batchCrossSeedButtonText }}
      </el-button>

      <!-- 查看记录按钮 -->
      <el-button type="info" @click="openRecordViewDialog" plain style="margin-right: 15px;">
        查看处理记录
      </el-button>

      <!-- 批量获取数据按钮 -->
      <el-button type="warning" @click="openBatchFetchDialog" plain style="margin-right: 15px;">
        批量获取数据
      </el-button>

      <!-- 筛选按钮 -->
      <el-button type="primary" @click="openFilterDialog" plain style="margin-right: 15px;">
        筛选
      </el-button>

      <!-- 批量删除按钮 - 仅在筛选出已删除项目时显示，删除已勾选项目 -->
      <el-button v-if="activeFilters.isDeleted === '1'" type="danger" @click="handleDisplayBatchDelete" plain
        style="margin-right: 15px;" :disabled="selectedRows.length === 0">
        批量删除已勾选项 ({{ selectedRows.length }})
      </el-button>

      <div v-if="hasActiveFilters" class="current-filters"
        style="margin-right: 15px; display: flex; align-items: center;">
        <el-tag type="info" size="default" effect="plain">{{ currentFilterText }}</el-tag>
        <el-button type="danger" link style="padding: 0; margin-left: 8px;" @click="clearFilters">清除</el-button>
      </div>

      <div class="pagination-controls" v-if="tableData.length > 0">
        <el-pagination v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]"
          :total="total" layout="total, sizes, prev, pager, next, jumper" @size-change="handleSizeChange"
          @current-change="handleCurrentChange" background>
        </el-pagination>
      </div>
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

          <el-divider content-position="left">删除状态</el-divider>
          <el-radio-group v-model="tempFilters.isDeleted" style="width: 100%;">
            <el-radio :label="''">全部</el-radio>
            <el-radio :label="'0'">未删除</el-radio>
            <el-radio :label="'1'">已删除</el-radio>
          </el-radio-group>

          <el-divider content-position="left">不存在种子筛选</el-divider>
          <div class="target-sites-container">
            <div class="selected-site-display">
              <div v-if="selectedTargetSite" class="selected-site-info">
                <el-tag type="info" size="default" effect="plain">已选择: {{ selectedTargetSite }}</el-tag>
                <el-button type="danger" link style="padding: 0; margin-left: 8px;"
                  @click="clearSelectedTargetSite">清除</el-button>
              </div>
              <div v-else class="selected-site-info">
                <el-tag type="info" size="default" effect="plain">未选择</el-tag>
              </div>
            </div>
            <div class="target-sites-radio-container">
              <el-radio-group v-model="selectedTargetSite" class="target-sites-radio-group">
                <el-radio v-for="site in targetSitesList" :key="site" :label="site" class="target-site-radio">
                  {{ site }}
                </el-radio>
              </el-radio-group>
            </div>
          </div>
        </div>
        <div class="filter-card-footer">
          <el-button @click="filterDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="applyFilters">确认</el-button>
        </div>
      </el-card>
    </div>

    <div class="table-container">
      <el-table :data="tableData" v-loading="loading" border style="width: 100%" empty-text="暂无转种数据"
        :max-height="tableMaxHeight" height="100%" :row-class-name="tableRowClassName"
        @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="55" align="center" :selectable="checkSelectable"></el-table-column>
        <el-table-column prop="torrent_id" label="种子ID" align="center" width="80"
          show-overflow-tooltip></el-table-column>
        <el-table-column prop="nickname" label="站点名称" width="100" align="center">
          <template #default="scope">
            <div class="mapped-cell">{{ scope.row.nickname }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" align="center">
          <template #default="scope">
            <div class="title-cell">
              <div class="subtitle-line" :title="scope.row.subtitle">
                {{ scope.row.subtitle || '' }}
              </div>
              <div class="main-title-line" :title="scope.row.title">
                {{ scope.row.title || '' }}
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="type" label="类型" width="100" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.type) || !isMapped('type', scope.row.type) }">
              {{ getMappedValue('type', scope.row.type) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="medium" label="媒介" width="100" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.medium) || !isMapped('medium', scope.row.medium) }">
              {{ getMappedValue('medium', scope.row.medium) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="video_codec" label="视频编码" width="120" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.video_codec) || !isMapped('video_codec', scope.row.video_codec) }">
              {{ getMappedValue('video_codec', scope.row.video_codec) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="audio_codec" label="音频编码" width="90" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.audio_codec) || !isMapped('audio_codec', scope.row.audio_codec) }">
              {{ getMappedValue('audio_codec', scope.row.audio_codec) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="resolution" label="分辨率" width="90" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.resolution) || !isMapped('resolution', scope.row.resolution) }">
              {{ getMappedValue('resolution', scope.row.resolution) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="team" label="制作组" width="120" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.team) || !isMapped('team', scope.row.team) }">
              {{ getMappedValue('team', scope.row.team) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="产地" width="100" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.source) || !isMapped('source', scope.row.source) }">
              {{ getMappedValue('source', scope.row.source) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="tags" label="标签" align="center" width="170">
          <template #default="scope">
            <div class="tags-cell">
              <el-tag v-for="(tag, index) in getMappedTags(scope.row.tags)" :key="tag" size="small"
                :type="getTagType(scope.row.tags, index)" :class="getTagClass(scope.row.tags, index)"
                style="margin: 2px;">
                {{ tag }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="unrecognized" label="无法识别" width="120" align="center">
          <template #default="scope">
            <div class="mapped-cell" :class="{ 'invalid-value': scope.row.unrecognized }">
              {{ scope.row.unrecognized || '' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="140" align="center" sortable>
          <template #default="scope">
            <div class="mapped-cell datetime-cell">
              {{ scope.row.is_deleted ? '已删除/禁转' : formatDateTime(scope.row.updated_at) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center" fixed="right">
          <template #default="scope">
            <el-button size="small" type="primary" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(scope.row)"
              style="margin-left: 5px;">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 转种弹窗 -->
    <div v-if="crossSeedDialogVisible" class="modal-overlay">
      <el-card class="cross-seed-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>转种 - {{ selectedTorrentName }}</span>
            <el-button type="danger" circle @click="closeCrossSeedDialog" plain>X</el-button>
          </div>
        </template>
        <div class="cross-seed-content">
          <CrossSeedPanel :show-complete-button="true" @complete="handleCrossSeedComplete"
            @cancel="closeCrossSeedDialog" />
        </div>
      </el-card>
    </div>

    <!-- 批量转种弹窗 -->
    <div v-if="batchCrossSeedDialogVisible" class="modal-overlay">
      <el-card class="batch-cross-seed-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>批量转种</span>
            <el-button type="danger" circle @click="closeBatchCrossSeedDialog" plain>X</el-button>
          </div>
        </template>
        <div class="batch-cross-seed-content">
          <div class="target-site-selection-body">
            <div class="batch-info">
              <p><strong>目标站点：</strong>{{ activeFilters.excludeTargetSites }}</p>
              <p><strong>选中种子数量：</strong>{{ selectedRows.length }} 个</p>
              <p style="color: #909399; font-size: 13px; margin-top: 10px;">
                将把选中的种子转种到上述目标站点，请确认无误后点击确定。
              </p>
            </div>
          </div>
        </div>
        <div class="batch-cross-seed-footer">
          <el-button @click="closeBatchCrossSeedDialog">取消</el-button>
          <el-button type="primary" @click="handleBatchCrossSeed">确定</el-button>
        </div>
      </el-card>
    </div>

    <!-- 处理记录查看弹窗 -->
    <div v-if="recordDialogVisible" class="modal-overlay">
      <el-card class="record-view-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>批量转种记录 {{ refreshTimer ? '(自动刷新中...)' : '' }}</span>
            <div class="record-header-controls">
              <el-button type="primary" size="small" @click="refreshRecords" :loading="recordsLoading">
                刷新
              </el-button>
              <el-button v-if="refreshTimer" type="warning" size="small" @click="stopAutoRefresh">
                停止自动刷新
              </el-button>
              <el-button v-else-if="batchProgress && batchProgress.isRunning" type="success" size="small"
                @click="startAutoRefresh">
                开启自动刷新
              </el-button>
              <el-button type="danger" circle @click="closeRecordViewDialog" plain>X</el-button>
            </div>
          </div>
        </template>
        <div class="record-view-content">
          <!-- 种子处理记录表格 -->
          <div class="records-table-container" v-if="records.length > 0">
            <el-table :data="records" style="width: 100%" size="small" v-loading="recordsLoading"
              element-loading-text="加载记录中..." stripe>
              <el-table-column prop="batch_id" label="批次ID" width="150" show-overflow-tooltip>
                <template #default="scope">
                  <el-tag size="small" type="info">{{ scope.row.batch_id }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="torrent_id" label="种子ID" width="100" show-overflow-tooltip />
              <el-table-column prop="source_site" label="源站点" width="100" />
              <el-table-column prop="target_site" label="目标站点" width="100" />
              <el-table-column prop="video_size_gb" label="视频大小" width="100" align="center">
                <template #default="scope">
                  <span v-if="scope.row.video_size_gb">{{ scope.row.video_size_gb }}GB</span>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column prop="status" label="状态" width="100" align="center">
                <template #default="scope">
                  <el-tag :type="getRecordStatusTypeLocal(scope.row.status)" size="small">
                    {{ getRecordStatusTextLocal(scope.row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="error_detail" label="详情" show-overflow-tooltip>
                <template #default="scope">
                  <span v-if="scope.row.status === 'success' && scope.row.success_url">
                    <el-link type="primary" :href="scope.row.success_url" target="_blank">查看转种页面</el-link>
                  </span>
                  <span v-else-if="scope.row.error_detail">{{ scope.row.error_detail }}</span>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column prop="downloader_add_result" label="下载器添加状态" width="140" align="center"
                show-overflow-tooltip>
                <template #default="scope">
                  <el-tag v-if="scope.row.downloader_add_result"
                    :type="getDownloaderAddStatusType(scope.row.downloader_add_result)" size="small">
                    {{ formatDownloaderAddResult(scope.row.downloader_add_result) }}
                  </el-tag>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column prop="processed_at" label="处理时间" width="160" align="center">
                <template #default="scope">
                  {{ formatRecordTimeLocal(scope.row.processed_at) }}
                </template>
              </el-table-column>
            </el-table>
          </div>

          <!-- 无记录时的显示 -->
          <div v-if="records.length === 0 && !recordsLoading" class="no-records">
            <el-empty description="暂无批量转种记录" />
          </div>
        </div>
        <div class="record-view-footer">
          <el-button @click="clearRecordsLocal" type="warning">清空记录</el-button>
          <el-button @click="closeRecordViewDialog">关闭</el-button>
        </div>
      </el-card>
    </div>

    <!-- 批量获取数据弹窗 -->
    <div v-if="batchFetchDialogVisible" class="modal-overlay">
      <el-card class="batch-fetch-main-card" shadow="always">
        <template #header>
          <div class="modal-header">
            <span>批量获取种子数据</span>
            <el-button type="danger" circle @click="closeBatchFetchDialog" plain>X</el-button>
          </div>
        </template>
        <div class="batch-fetch-main-content">
          <BatchFetchPanel @cancel="closeBatchFetchDialog" />
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ElTree } from 'element-plus'
import CrossSeedPanel from '../components/CrossSeedPanel.vue'
import BatchFetchPanel from '../components/BatchFetchPanel.vue'
import { useCrossSeedStore } from '@/stores/crossSeed'
import type { ISourceInfo } from '@/types'

// 定义emit事件
const emit = defineEmits<{
  (e: 'ready', refreshMethod: () => Promise<void>): void
}>()

// 在组件挂载时发送ready事件
onMounted(() => {
  emit('ready', fetchData)
})


interface SeedParameter {
  id: number
  hash: string
  torrent_id: string
  site_name: string
  nickname: string
  title: string
  subtitle: string
  imdb_link: string
  douban_link: string
  type: string
  medium: string
  video_codec: string
  audio_codec: string
  resolution: string
  team: string
  source: string
  tags: string[] | string
  poster: string
  screenshots: string
  statement: string
  body: string
  mediainfo: string
  title_components: string
  unrecognized: string
  created_at: string
  updated_at: string
  is_deleted: boolean
}

interface PathNode {
  path: string
  label: string
  children?: PathNode[]
}

interface ReverseMappings {
  type: Record<string, string>
  medium: Record<string, string>
  video_codec: Record<string, string>
  audio_codec: Record<string, string>
  resolution: Record<string, string>
  source: Record<string, string>
  team: Record<string, string>
  tags: Record<string, string>
  site_name: Record<string, string>
}

// 反向映射表，用于将标准值映射到中文显示名称
const reverseMappings = ref<ReverseMappings>({
  type: {},
  medium: {},
  video_codec: {},
  audio_codec: {},
  resolution: {},
  source: {},
  team: {},
  tags: {},
  site_name: {}
})

const tableData = ref<SeedParameter[]>([])
const loading = ref<boolean>(true)
const error = ref<string | null>(null)

// 批量转种相关
const selectedRows = ref<SeedParameter[]>([])
const batchCrossSeedDialogVisible = ref<boolean>(false)

// 批量获取数据相关
const batchFetchDialogVisible = ref<boolean>(false)

// 记录查看相关
const recordDialogVisible = ref<boolean>(false)
const records = ref<SeedRecord[]>([])
const recordsLoading = ref<boolean>(false)
const batchProgress = ref<BatchProgress | null>(null)

// 定时刷新相关
const refreshTimer = ref<ReturnType<typeof setInterval> | null>(null)
const REFRESH_INTERVAL = 5000 // 5秒刷新一次

interface SeedRecord {
  id: number
  batch_id: string
  torrent_id: string
  source_site: string
  target_site: string
  video_size_gb?: number
  status: string
  success_url?: string
  error_detail?: string
  downloader_add_result?: string
  processed_at: string
}

interface SeedProgress {
  torrentId: string
  siteName: string
  targetSite: string
  status: 'pending' | 'checking' | 'processing' | 'success' | 'failed' | 'filtered'
  statusText: string
  videoSize?: string
  filterReason?: string
  url?: string
  error?: string
  processingTime?: string
}

interface BatchProgress {
  totalSeeds: number
  processedSeeds: number
  isRunning: boolean
  startTime?: string
  endTime?: string
  summary?: string
  seeds: SeedProgress[]
}

// 路径树相关
const pathTreeRef = ref<InstanceType<typeof ElTree> | null>(null)
const pathTreeData = ref<PathNode[]>([])
const uniquePaths = ref<string[]>([])

// 表格高度
const tableMaxHeight = ref<number>(window.innerHeight - 80)

// 分页相关
const currentPage = ref<number>(1)
const pageSize = ref<number>(20)
const total = ref<number>(0)

// 搜索相关
const searchQuery = ref<string>('')

// 计算当前筛选条件的显示文本
const currentFilterText = computed(() => {
  const filters = activeFilters.value
  const filterTexts = []

  // 处理保存路径筛选
  if (filters.savePath) {
    const paths = filters.savePath.split(',').filter(path => path.trim() !== '')
    if (paths.length > 0) {
      filterTexts.push(`路径: ${paths.length}个`)
    }
  }

  // 处理删除状态筛选
  if (filters.isDeleted === '0') {
    filterTexts.push('未删除')
  } else if (filters.isDeleted === '1') {
    filterTexts.push('已删除')
  }

  // 处理不存在种子筛选
  if (filters.excludeTargetSites && filters.excludeTargetSites.trim() !== '') {
    filterTexts.push(`不存在于: ${filters.excludeTargetSites}`)
  }

  return filterTexts.join(', ')
})

// 检查是否可以进行批量转种
const canBatchCrossSeed = computed(() => {
  return selectedRows.value.length > 0 &&
    activeFilters.value.excludeTargetSites &&
    activeFilters.value.excludeTargetSites.trim() !== ''
})

// 批量转种按钮的文字
const batchCrossSeedButtonText = computed(() => {
  const selectedCount = selectedRows.value.length
  const targetSite = activeFilters.value.excludeTargetSites

  if (!targetSite || targetSite.trim() === '') {
    return `批量转种 (${selectedCount}) - 请先选择目标站点`
  }

  return `批量转种到 ${targetSite} (${selectedCount})`
})

// 检查是否有任何筛选条件被应用
const hasActiveFilters = computed(() => {
  const filters = activeFilters.value
  return (
    (filters.savePath && filters.savePath.split(',').filter(path => path.trim() !== '').length > 0) ||
    filters.isDeleted !== '' ||
    (filters.excludeTargetSites && filters.excludeTargetSites.trim() !== '')
  )
})

// 筛选相关
const filterDialogVisible = ref<boolean>(false)
const activeFilters = ref({
  savePath: '',
  isDeleted: '',
  excludeTargetSites: ''  // 新增：排除目标站点筛选
})
const tempFilters = ref({ ...activeFilters.value })
const targetSitesList = ref<string[]>([])  // 新增：目标站点列表

// 计算属性：选中的目标站点（单选）
const selectedTargetSite = computed({
  get: () => {
    return tempFilters.value.excludeTargetSites || ''
  },
  set: (site) => {
    tempFilters.value.excludeTargetSites = site
  }
})

// 清除选中的目标站点
const clearSelectedTargetSite = () => {
  tempFilters.value.excludeTargetSites = ''
}

// 辅助函数：获取映射后的中文值
const getMappedValue = (category: keyof ReverseMappings, standardValue: string) => {
  if (!standardValue) return ''

  const mappings = reverseMappings.value[category]
  if (!mappings) return standardValue

  return mappings[standardValue] || standardValue
}

// 检查值是否符合 *.* 格式
const isValidFormat = (value: string) => {
  if (!value) return true // 空值认为是有效的
  const regex = /^[^.]+[.][^.]+$/ // 匹配 *.* 格式
  return regex.test(value)
}

// 检查值是否已正确映射
const isMapped = (category: keyof ReverseMappings, standardValue: string) => {
  if (!standardValue) return true // 空值认为是有效的

  const mappings = reverseMappings.value[category]
  if (!mappings) return false // 没有映射表则认为未映射

  return !!mappings[standardValue] // 检查是否有对应的映射
}

// 辅助函数：获取映射后的标签列表
const getMappedTags = (tags: string[] | string) => {
  // 处理字符串或数组格式的标签
  let tagList: string[] = []
  if (typeof tags === 'string') {
    try {
      // 尝试解析为JSON数组
      tagList = JSON.parse(tags)
    } catch {
      // 如果解析失败，按逗号分割
      tagList = tags.split(',').map(tag => tag.trim()).filter(tag => tag)
    }
  } else if (Array.isArray(tags)) {
    tagList = tags
  }

  if (tagList.length === 0) return []

  // 映射标签到中文名称
  return tagList.map((tag: string) => {
    return reverseMappings.value.tags[tag] || tag
  })
}

// 获取标签的类型（用于显示不同颜色）
const getTagType = (tags: string[] | string, index: number) => {
  // 获取原始标签值
  let tagList: string[] = []
  if (typeof tags === 'string') {
    try {
      tagList = JSON.parse(tags)
    } catch {
      tagList = tags.split(',').map(tag => tag.trim()).filter(tag => tag)
    }
  } else if (Array.isArray(tags)) {
    tagList = tags
  }

  if (tagList.length === 0 || index >= tagList.length) return 'info'

  const originalTag = tagList[index]

  // 检查标签是否符合 *.* 格式且已映射
  if (!isValidFormat(originalTag) || !isMapped('tags', originalTag)) {
    return 'danger' // 红色
  }

  return 'info' // 默认蓝色
}

// 获取标签的自定义CSS类（用于背景色）
const getTagClass = (tags: string[] | string, index: number) => {
  // 获取原始标签值
  let tagList: string[] = []
  if (typeof tags === 'string') {
    try {
      tagList = JSON.parse(tags)
    } catch {
      tagList = tags.split(',').map(tag => tag.trim()).filter(tag => tag)
    }
  } else if (Array.isArray(tags)) {
    tagList = tags
  }

  if (tagList.length === 0 || index >= tagList.length) return ''

  const originalTag = tagList[index]

  // 检查标签是否符合 *.* 格式且已映射
  if (!isValidFormat(originalTag) || !isMapped('tags', originalTag)) {
    return 'invalid-tag' // 返回自定义类名
  }

  return '' // 返回空字符串表示使用默认样式
}

// 格式化日期时间为完整的年月日时分秒格式，并支持换行显示
const formatDateTime = (dateString: string) => {
  if (!dateString) return ''

  try {
    const date = new Date(dateString)
    if (isNaN(date.getTime())) return dateString // 如果日期无效，返回原始字符串

    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    const seconds = String(date.getSeconds()).padStart(2, '0')
    return `${year}-${month}-${day}\n${hours}:${minutes}:${seconds}`
  } catch (error) {
    return dateString // 如果解析失败，返回原始字符串
  }
}

// 检查行是否有无效参数
const hasInvalidParams = (row: SeedParameter): boolean => {
  const categories: (keyof Omit<ReverseMappings, 'tags' | 'site_name'>)[] = ['type', 'medium', 'video_codec', 'audio_codec', 'resolution', 'team', 'source'];

  for (const category of categories) {
    const value = row[category as keyof SeedParameter] as string;
    if (value && (!isValidFormat(value) || !isMapped(category, value))) {
      return true;
    }
  }

  let tagList: string[] = []
  if (typeof row.tags === 'string') {
    try {
      tagList = JSON.parse(row.tags)
    } catch {
      tagList = row.tags.split(',').map(tag => tag.trim()).filter(tag => tag)
    }
  } else if (Array.isArray(row.tags)) {
    tagList = row.tags
  }

  for (const tag of tagList) {
    if (!isValidFormat(tag) || !isMapped('tags', tag)) {
      return true
    }
  }

  if (row.unrecognized) {
    return true
  }

  return false
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

const fetchData = async () => {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      page_size: pageSize.value.toString(),
      search: searchQuery.value,
      save_path: activeFilters.value.savePath,
      is_deleted: activeFilters.value.isDeleted,
      exclude_target_sites: activeFilters.value.excludeTargetSites  // 新增：目标站点排除参数
    })

    // 调试日志：检查筛选参数
    if (activeFilters.value.excludeTargetSites) {
      console.log('发送目标站点排除参数:', activeFilters.value.excludeTargetSites)
    }

    const response = await fetch(`/api/cross-seed-data?${params.toString()}`)

    // 检查响应状态
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const responseText = await response.text();

    // 检查响应是否为JSON格式
    if (!responseText.startsWith('{') && !responseText.startsWith('[')) {
      throw new Error('服务器响应不是有效的JSON格式');
    }

    const result = JSON.parse(responseText)

    if (result.success) {
      tableData.value = result.data
      total.value = result.total

      // 更新反向映射表
      if (result.reverse_mappings) {
        reverseMappings.value = result.reverse_mappings
      }

      // 更新唯一路径数据并构建路径树
      if (result.unique_paths) {
        uniquePaths.value = result.unique_paths
        pathTreeData.value = buildPathTree(result.unique_paths)
      }

      // 更新目标站点列表
      if (result.target_sites) {
        targetSitesList.value = result.target_sites
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

const saveUiSettings = async () => {
  try {
    const settingsToSave = {
      page_size: pageSize.value,
      search_query: searchQuery.value,
      active_filters: activeFilters.value,
    };
    await fetch('/api/ui_settings/cross_seed', {
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
    const response = await fetch('/api/ui_settings/cross_seed');
    if (!response.ok) {
      console.warn('无法加载UI设置，将使用默认值。');
      return;
    }
    const settings = await response.json();
    pageSize.value = settings.page_size ?? 20;
    searchQuery.value = settings.search_query ?? '';
    if (settings.active_filters) {
      Object.assign(activeFilters.value, settings.active_filters);
    }
  } catch (e) {
    console.error('加载UI设置时出错:', e);
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

// 清除筛选条件
const clearFilters = () => {
  activeFilters.value = {
    savePath: '',
    isDeleted: '',
    excludeTargetSites: ''  // 新增：清除目标站点排除筛选
  }
  currentPage.value = 1
  fetchData()
  saveUiSettings()
}

// 打开筛选对话框
const openFilterDialog = () => {
  // 将当前活动的筛选条件复制到临时筛选条件
  tempFilters.value = { ...activeFilters.value }
  filterDialogVisible.value = true
  nextTick(() => {
    // 如果已有选中的路径，设置树的选中状态
    if (pathTreeRef.value && activeFilters.value.savePath) {
      // 将逗号分隔的路径字符串转换为数组
      const selectedPaths = activeFilters.value.savePath.split(',').filter(path => path.trim() !== '')
      // 设置树的选中状态，只设置叶子节点
      pathTreeRef.value.setCheckedKeys(selectedPaths, true)
    }
  })
}

// 应用筛选条件
const applyFilters = () => {
  // 从路径树中获取选中的路径
  if (pathTreeRef.value) {
    const selectedPaths = pathTreeRef.value.getCheckedKeys(true) as string[]
    // 将选中的路径以逗号分隔的形式保存到筛选条件中
    tempFilters.value.savePath = selectedPaths.join(',')
  }

  // 将临时筛选条件应用为活动筛选条件
  activeFilters.value = { ...tempFilters.value }
  filterDialogVisible.value = false
  // 重置到第一页并获取数据
  currentPage.value = 1
  fetchData()
  saveUiSettings()
}

const crossSeedStore = useCrossSeedStore();

// 监听搜索查询的变化，自动触发搜索
watch(searchQuery, () => {
  currentPage.value = 1
  fetchData()
  saveUiSettings()
})

// 控制转种弹窗的显示
const crossSeedDialogVisible = computed(() => !!crossSeedStore.taskId);
const selectedTorrentName = computed(() => crossSeedStore.workingParams?.title || '');

// 处理编辑按钮点击
const handleEdit = async (row: SeedParameter) => {
  try {
    // 重置 store
    crossSeedStore.reset();

    // 从后端API获取详细的种子参数
    const response = await fetch(`/api/migrate/get_db_seed_info?torrent_id=${row.torrent_id}&site_name=${row.site_name}`);

    // 检查响应状态
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const responseText = await response.text();

    // 检查响应是否为JSON格式
    if (!responseText.startsWith('{') && !responseText.startsWith('[')) {
      throw new Error('服务器响应不是有效的JSON格式');
    }

    const result = JSON.parse(responseText);

    if (result.success) {
      // 将获取到的数据设置到 store 中
      // 构造一个基本的 Torrent 对象结构
      const torrentData = {
        ...result.data,
        name: result.data.title,
        // 使用从数据库获取的实际保存路径，如果没有则为空字符串
        save_path: result.data.save_path || '',
        size: 0,
        size_formatted: '0 B',
        progress: 100,
        state: 'completed',
        total_uploaded: 0,
        total_uploaded_formatted: '0 B',
        sites: {
          [result.data.site_name]: {
            torrentId: result.data.torrent_id,
            comment: `id=${result.data.torrent_id}` // 为了向后兼容，也提供comment格式
          }
        }
      };

      crossSeedStore.setParams(torrentData);

      // 设置源站点信息
      const sourceInfo: ISourceInfo = {
        name: result.data.site_name,
        site: result.data.site_name.toLowerCase(), // 假设站点标识符是站点名称的小写形式
        torrentId: result.data.torrent_id
      };
      crossSeedStore.setSourceInfo(sourceInfo);

      // 设置一个任务ID以显示弹窗
      crossSeedStore.setTaskId(`cross_seed_${row.id}_${Date.now()}`);
    } else {
      ElMessage.error(result.error || '获取种子参数失败');
    }
  } catch (error: any) {
    ElMessage.error(error.message || '网络错误');
  }
};

// 处理删除按钮点击
const handleDelete = async (row: SeedParameter) => {
  try {
    // 确认是否删除
    await ElMessageBox.confirm(
      `确定要永久删除种子数据 "${row.title}" 吗？此操作无法恢复！`,
      '确认永久删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    );

    // 向后端发送删除请求 - 使用统一的 delete API
    const deleteData = {
      torrent_id: row.torrent_id,
      site_name: row.site_name
    };
    const response = await fetch('/api/cross-seed-data/delete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(deleteData)
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();

    if (result.success) {
      ElMessage.success(result.message || `删除成功`);
      // 重新获取数据，以更新表格
      fetchData();
    } else {
      ElMessage.error(result.error || '删除失败');
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      // 只有在不是用户取消的情况下才显示错误
      ElMessage.error(error.message || '网络错误');
    }
  }
};

// 处理选中项目的批量删除
const handleBulkDelete = async () => {
  if (selectedRows.value.length === 0) {
    ElMessage.warning('请先选择要删除的行');
    return;
  }

  try {
    // 确认是否删除
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedRows.value.length} 条种子数据吗？`,
      '确认批量删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    );

    // 构造请求体
    const deleteData = {
      items: selectedRows.value.map(row => ({
        torrent_id: row.torrent_id,
        site_name: row.site_name
      }))
    };

    // 调用批量删除API - 使用统一的 delete API
    const response = await fetch('/api/cross-seed-data/delete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(deleteData)
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();

    if (result.success) {
      ElMessage.success(result.message || `成功删除 ${result.deleted_count} 条数据`);
      // 清空已选行
      selectedRows.value = [];
      // 重新获取数据，以更新表格
      fetchData();
    } else {
      ElMessage.error(result.error || '批量删除失败');
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      // 只有在不是用户取消的情况下才显示错误
      ElMessage.error(error.message || '网络错误');
    }
  }
};

// 批量永久删除当前选中的已删除项目（确认删除已选择的项目）
const handleDisplayBatchDelete = async () => {
  // 当筛选出已删除项目且进行了勾选时，批量删除已选择的项，而不是全部显示的项
  if (selectedRows.value.length === 0) {
    ElMessage.warning('请先选择要删除的项目');
    return;
  }

  try {
    // 确认是否彻底删除
    await ElMessageBox.confirm(
      `确定要永久删除选中的 ${selectedRows.value.length} 条种子数据吗？此操作无法恢复！`,
      '确认永久删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    );

    // 构造请求体 - 包含当前选中的项目
    const deleteData = {
      items: selectedRows.value.map(row => ({
        torrent_id: row.torrent_id,
        site_name: row.site_name
      }))
    };

    // 调用批量删除API - 使用统一的 delete API
    const response = await fetch('/api/cross-seed-data/delete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(deleteData)
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const result = await response.json();

    if (result.success) {
      ElMessage.success(result.message || `已永久删除 ${result.deleted_count} 条数据`);
      // 清空选中行
      selectedRows.value = [];
      // 重新获取数据，以更新表格
      fetchData();
    } else {
      ElMessage.error(result.error || '批量删除失败');
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      // 只有在不是用户取消的情况下才显示错误
      ElMessage.error(error.message || '网络错误');
    }
  }
};

// 关闭转种弹窗
const closeCrossSeedDialog = () => {
  crossSeedStore.reset();
};

// 处理转种完成
const handleCrossSeedComplete = () => {
  ElMessage.success('转种操作已完成！');
  crossSeedStore.reset();
  // 可选：刷新数据以显示最新状态
  fetchData();
};

// 处理窗口大小变化
const handleResize = () => {
  tableMaxHeight.value = window.innerHeight - 80
}

onMounted(async () => {
  // 加载UI设置
  await loadUiSettings();
  // 获取数据
  fetchData()
  window.addEventListener('resize', handleResize)
})

// 为表格行设置CSS类名
const tableRowClassName = ({ row }: { row: SeedParameter }) => {
  if (row.is_deleted) {
    return 'deleted-row'
  }
  // 如果行不可选择，添加selected-row-disabled类
  if (!checkSelectable(row)) {
    return 'selected-row-disabled'
  }
  return ''
}

// 控制表格行是否可选择
const checkSelectable = (row: SeedParameter) => {
  // 如果已删除筛选处于活动状态，则允许选择已删除的行 - 便于批量操作
  if (activeFilters.value.isDeleted === '1') {
    // 但仍需检查是否有无效参数
    return !hasInvalidParams(row)
  } else {
    // 在正常模式下，已删除的行不可选择；有无效参数的行也不可选择
    if (row.is_deleted) {
      return false
    }
    // 如果有无效参数，则不可选择
    return !hasInvalidParams(row)
  }
}

// 处理表格选中行变化
const handleSelectionChange = (selection: SeedParameter[]) => {
  selectedRows.value = selection
}

// 打开批量转种对话框
const openBatchCrossSeedDialog = () => {
  // 直接打开对话框，不需要获取站点列表
  batchCrossSeedDialogVisible.value = true
}

// 处理批量转种
const handleBatchCrossSeed = async () => {
  // 直接使用筛选中的站点
  const targetSiteName = activeFilters.value.excludeTargetSites

  if (!targetSiteName || targetSiteName.trim() === '') {
    ElMessage.warning('请先在筛选中选择目标站点')
    return
  }

  try {
    // 关闭批量转种对话框
    closeBatchCrossSeedDialog()

    // 立即打开记录窗口
    openRecordViewDialog()

    // 构造要传递给后端的数据
    const batchData = {
      target_site_name: targetSiteName,
      seeds: selectedRows.value.map(row => ({
        hash: row.hash,
        torrent_id: row.torrent_id,
        site_name: row.site_name,
        nickname: row.nickname
      }))
    }

    console.log('批量转种数据:', batchData)

    // 通过vite代理调用Go服务的API
    const response = await fetch('/go-api/batch-enhance', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(batchData)
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const result = await response.json()
    if (result.success) {
      ElMessage.success(`批量转种请求已发送，成功 ${result.data.seeds_processed} 个，失败 ${result.data.seeds_failed} 个`)
      // 可选：刷新数据
      // fetchData()
    } else {
      ElMessage.error(result.error || '批量转种失败')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '网络错误')
  }
}

// 关闭批量转种对话框
const closeBatchCrossSeedDialog = () => {
  batchCrossSeedDialogVisible.value = false
}

// 打开批量获取数据对话框
const openBatchFetchDialog = () => {
  batchFetchDialogVisible.value = true
}

// 关闭批量获取数据对话框
const closeBatchFetchDialog = () => {
  batchFetchDialogVisible.value = false
}

// 启动定时刷新
const startAutoRefresh = () => {
  // 先清除任何现有的定时器
  stopAutoRefresh()

  // 立即刷新一次
  refreshRecords()

  // 启动定时器
  refreshTimer.value = setInterval(async () => {
    if (recordDialogVisible.value) {
      await refreshRecords()

      // 检查是否还有正在处理的种子
      if (batchProgress.value && !batchProgress.value.isRunning) {
        // 批量处理已完成，延迟3秒后停止自动刷新
        setTimeout(() => {
          if (!batchProgress.value?.isRunning) {
            stopAutoRefresh()
          }
        }, 3000)
      }
    } else {
      // 如果记录窗口已关闭，停止定时器
      stopAutoRefresh()
    }
  }, REFRESH_INTERVAL)
}

// 停止定时刷新
const stopAutoRefresh = () => {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

// 打开记录查看对话框
const openRecordViewDialog = () => {
  recordDialogVisible.value = true
  startAutoRefresh()
}

// 关闭记录查看对话框
const closeRecordViewDialog = () => {
  recordDialogVisible.value = false
  stopAutoRefresh()
}

// 刷新记录
const refreshRecords = async () => {
  recordsLoading.value = true
  try {
    // 通过vite代理调用Go服务的记录API
    const response = await fetch('/go-api/records', {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    })

    if (response.ok) {
      const result = await response.json()
      if (result.success) {
        records.value = result.records || []

        // 自动滚动到表格顶部（显示最新记录）
        await nextTick()
        const tableContainer = document.querySelector('.records-table-container .el-table__body-wrapper')
        if (tableContainer) {
          tableContainer.scrollTop = 0
        }
      } else {
        ElMessage.error(result.error || '获取记录失败')
      }
    } else if (response.status === 404) {
      // 如果接口不存在，显示提示信息
      records.value = []
      ElMessage.warning('记录接口暂未实现，请等待后续更新')
    } else {
      ElMessage.error('获取记录失败')
    }
  } catch (error: any) {
    console.error('获取记录时出错:', error)
    ElMessage.error('获取记录失败: ' + (error.message || '网络错误'))
  } finally {
    recordsLoading.value = false
  }
}

// 清空记录
const clearRecordsLocal = async () => {
  try {
    // 调用清空记录的API
    const response = await fetch('/go-api/records', {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json'
      }
    })

    if (response.ok) {
      records.value = []
      ElMessage.success('记录已清空')
    } else {
      // 如果API不存在，只是清空本地显示
      records.value = []
      ElMessage.success('本地记录已清空')
    }
  } catch (error) {
    // 如果请求失败，只是清空本地显示
    records.value = []
    ElMessage.success('本地记录已清空')
  }
}

// 获取记录状态对应的Element Plus标签类型
const getRecordStatusTypeLocal = (status: string) => {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'danger'
    case 'filtered': return 'warning'
    case 'processing': return 'primary'
    case 'pending': return 'info'
    default: return 'info'
  }
}

// 获取记录状态文本
const getRecordStatusTextLocal = (status: string) => {
  switch (status) {
    case 'success': return '成功'
    case 'failed': return '失败'
    case 'filtered': return '已过滤'
    case 'processing': return '处理中'
    case 'pending': return '等待中'
    default: return '未知'
  }
}

// 获取下载器添加状态的标签类型
const getDownloaderAddStatusType = (result: string) => {
  if (result.startsWith('成功')) return 'success'
  if (result.startsWith('失败')) return 'danger'
  return 'info'
}

// 格式化下载器添加结果显示
const formatDownloaderAddResult = (result: string) => {
  if (result.startsWith('成功:')) {
    return result.substring(3) // 移除 "成功:" 前缀
  }
  if (result.startsWith('失败:')) {
    return result.substring(3) // 移除 "失败:" 前缀
  }
  return result
}

// 格式化记录时间
const formatRecordTimeLocal = (timestamp: string) => {
  try {
    const date = new Date(timestamp)
    if (isNaN(date.getTime())) return timestamp // 如果日期无效，返回原始字符串

    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    const seconds = String(date.getSeconds()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
  } catch (error) {
    return timestamp
  }
}

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  stopAutoRefresh() // 清理定时器
})
</script>

<style scoped>
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
  width: 500px;
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

.path-tree-container {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 5px;
  margin-bottom: 20px;
}

:deep(.path-tree-node .el-tree-node__content) {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.target-sites-container {
  margin-bottom: 20px;
}

.selected-site-display {
  margin-bottom: 10px;
}

.selected-site-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px;
}

.target-sites-radio-container {
  width: 100%;
  min-height: 100px;
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 10px;
  margin-bottom: 10px;
  box-sizing: border-box;
}

.target-sites-radio-group {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  width: 100%;
}

:deep(.target-sites-radio-group .el-radio) {
  margin-right: 0 !important;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
}

:deep(.target-sites-radio-group .el-radio .el-radio__label) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.target-site-radio {
  margin-bottom: 8px;
}

.filter-card-footer {
  padding: 5px 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: flex-end;
}

.cross-seed-card {
  width: 90vw;
  max-width: 1200px;
  height: 90vh;
  max-height: 800px;
  display: flex;
  flex-direction: column;
}

.batch-cross-seed-card {
  width: 500px;
  max-width: 95vw;
  display: flex;
  flex-direction: column;
}

:deep(.batch-cross-seed-card .el-card__body) {
  padding: 20px;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.batch-cross-seed-content {
  flex: 1;
  overflow-y: auto;
}

.batch-cross-seed-footer {
  padding: 10px 0 0 0;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: flex-end;
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

.cross-seed-data-view {
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

.table-container :deep(.el-table) {
  height: 100%;
}

.table-container :deep(.el-table__body-wrapper) {
  overflow-y: auto;
}

.table-container :deep(.el-table__header-wrapper) {
  overflow-x: hidden;
}


.mapped-cell {
  text-align: center;
  line-height: 1.4;
}

.mapped-cell.invalid-value {
  color: #f56c6c;
  background-color: #fef0f0;
  font-weight: bold;
  padding: 8px 12px;
  height: calc(100% + 16px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.datetime-cell {
  white-space: pre-line;
  line-height: 1.2;
}

:deep(.el-table_1_column_13) {
  padding: 0;
}

.tags-cell {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 2px;
  margin: -8px -12px;
  padding: 8px 12px;
  height: calc(100% + 16px);
  align-items: center;
}

.invalid-tag {
  background-color: #fef0f0 !important;
  border-color: #fbc4c4 !important;
}

:deep(.deleted-row) {
  background-color: #fef0f0 !important;
  color: #f56c6c !important;
}

:deep(.deleted-row:hover) {
  background-color: #fde2e2 !important;
}

.title-cell {
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
  line-height: 1.4;
  text-align: left;
}

.subtitle-line,
.main-title-line {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
}

.subtitle-line {
  font-size: 12px;
  margin-bottom: 2px;
}

.main-title-line {
  font-weight: 500;
}

.tags-cell {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 2px;
  margin: -8px -12px;
  padding: 8px 12px;
  height: calc(100% + 16px);
  align-items: center;
}

/* 不可选择行的复选框变红 */
:deep(.el-table__body tr.selected-row-disabled td.el-table-column--selection .cell .el-checkbox__input.is-disabled .el-checkbox__inner) {
  border-color: #f56c6c !important;
  background-color: #fef0f0 !important;
}

:deep(.el-table__body tr.selected-row-disabled td.el-table-column--selection .cell .el-checkbox__input.is-disabled .el-checkbox__inner::after) {
  border-color: #f56c6c !important;
}

/* 批量转种弹窗样式 */
.target-site-selection-body {
  padding: 5px 20px 20px 20px;
}

.batch-info {
  margin-top: 20px;
  padding: 12px;
  background-color: #f8f9fa;
  border-radius: 4px;
  border-left: 4px solid #409eff;
}

.batch-info p {
  margin: 8px 0;
  font-size: 14px;
  color: #606266;
}

.batch-info p strong {
  color: #303133;
}

/* 批量获取数据弹窗样式 */
.batch-fetch-main-card {
  width: 95vw;
  max-width: 1400px;
  height: 85vh;
  max-height: 900px;
  display: flex;
  flex-direction: column;
}

:deep(.batch-fetch-main-card .el-card__body) {
  padding: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.batch-fetch-main-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* 记录查看弹窗样式 */
.record-view-card {
  width: 90vw;
  max-width: 1200px;
  height: 80vh;
  max-height: 800px;
  display: flex;
  flex-direction: column;
}

:deep(.record-view-card .el-card__body) {
  padding: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.record-header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.record-view-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* 记录表格样式 */
.records-table-container {
  flex: 1;
  overflow: hidden;
  padding: 10px;
}

.no-records {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.record-view-footer {
  padding: 10px 20px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: space-between;
}
</style>
