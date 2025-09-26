<template>
  <div class="cross-seed-data-view">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"
      style="margin: 0; border-radius: 0;"></el-alert>

    <!-- 搜索和控制栏 -->
    <div class="search-and-controls">
      <el-button type="primary" @click="fetchData" :loading="loading" size="small"
        style="margin-right: 15px;">刷新</el-button>
      <el-input v-model="searchQuery" placeholder="搜索标题或种子ID..." clearable class="search-input"
        style="width: 300px; margin-right: 15px;" />

      <div class="pagination-controls" v-if="tableData.length > 0">
        <el-pagination v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[10, 20, 50, 100]"
          :total="total" layout="total, sizes, prev, pager, next, jumper" @size-change="handleSizeChange"
          @current-change="handleCurrentChange" background>
        </el-pagination>
      </div>
    </div>

    <div class="table-container">
      <el-table :data="tableData" v-loading="loading" border style="width: 100%" empty-text="暂无转种数据"
        :max-height="tableMaxHeight" height="100%">
        <el-table-column type="selection" width="55" align="center"></el-table-column>
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
            <div class="mapped-cell datetime-cell">{{ formatDateTime(scope.row.updated_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center" fixed="right">
          <template #default="scope">
            <el-button size="small" type="primary" @click="handleEdit(scope.row)">编辑</el-button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import CrossSeedPanel from '../components/CrossSeedPanel.vue'
import { useCrossSeedStore } from '@/stores/crossSeed'
import type { ISourceInfo } from '@/types'


interface SeedParameter {
  id: number
  torrent_id: string
  site_name: string
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

// 表格高度
const tableMaxHeight = ref<number>(window.innerHeight - 80)

// 分页相关
const currentPage = ref<number>(1)
const pageSize = ref<number>(20)
const total = ref<number>(0)

// 搜索相关
const searchQuery = ref<string>('')

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

const fetchData = async () => {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams({
      page: currentPage.value.toString(),
      page_size: pageSize.value.toString(),
      search: searchQuery.value
    })

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

const handleSizeChange = (val: number) => {
  pageSize.value = val
  currentPage.value = 1
  fetchData()
}

const handleCurrentChange = (val: number) => {
  currentPage.value = val
  fetchData()
}

const crossSeedStore = useCrossSeedStore();

// 监听搜索查询的变化，自动触发搜索
watch(searchQuery, () => {
  currentPage.value = 1
  fetchData()
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
        // 添加缺失的 Torrent 接口必需字段（使用默认值）
        save_path: '',
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

onMounted(() => {
  fetchData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
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
  color: #000000;
  font-size: 12px;
  margin-bottom: 2px;
}

.main-title-line {
  font-weight: 500;
}

.invalid-tag {
  background-color: #fef0f0 !important;
  border-color: #fbc4c4 !important;
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
</style>
