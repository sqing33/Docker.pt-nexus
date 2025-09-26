<template>
  <div class="cross-seed-data-view">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"
      style="margin: 0; border-radius: 0;"></el-alert>

    <div class="table-container">
      <el-table :data="tableData" v-loading="loading" border style="width: 100%" empty-text="暂无转种数据"
        :max-height="tableMaxHeight" height="100%">
        <el-table-column prop="id" label="ID" width="65" align="center" sortable></el-table-column>
        <el-table-column prop="torrent_id" label="种子ID" align="center" width="80"
          show-overflow-tooltip></el-table-column>
        <el-table-column prop="site_name" label="站点名称" width="100" align="center">
          <template #default="scope">
            <div class="mapped-cell">{{ getMappedValue('site_name', scope.row.site_name) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="200">
          <template #default="scope">
            <div class="title-cell">
              <div class="subtitle-line" :title="scope.row.subtitle">
                {{ scope.row.subtitle || 'N/A' }}
              </div>
              <div class="main-title-line" :title="scope.row.title">
                {{ scope.row.title || 'N/A' }}
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
        <el-table-column prop="audio_codec" label="音频编码" width="120" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.audio_codec) || !isMapped('audio_codec', scope.row.audio_codec) }">
              {{ getMappedValue('audio_codec', scope.row.audio_codec) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="resolution" label="分辨率" width="100" align="center">
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
        <el-table-column prop="source" label="产地" width="110" align="center">
          <template #default="scope">
            <div class="mapped-cell"
              :class="{ 'invalid-value': !isValidFormat(scope.row.source) || !isMapped('source', scope.row.source) }">
              {{ getMappedValue('source', scope.row.source) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="tags" label="标签" min-width="150">
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
        <el-table-column prop="created_at" label="创建时间" width="140" align="center" sortable>
          <template #default="scope">
            <div class="mapped-cell datetime-cell">{{ formatDateTime(scope.row.created_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="140" align="center" sortable>
          <template #default="scope">
            <div class="mapped-cell datetime-cell">{{ formatDateTime(scope.row.updated_at) }}</div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="pagination-container" v-if="tableData.length > 0">
      <el-button type="primary" @click="fetchData" :loading="loading" size="small"
        style="margin-right: 15px;">刷新</el-button>
      <el-pagination v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[10, 20, 50, 100]"
        :total="total" layout="total, sizes, prev, pager, next, jumper" @size-change="handleSizeChange"
        @current-change="handleCurrentChange" background>
      </el-pagination>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'

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

// 辅助函数：获取映射后的中文值
const getMappedValue = (category: keyof ReverseMappings, standardValue: string) => {
  if (!standardValue) return 'N/A'

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
  if (!dateString) return 'N/A'

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
      page_size: pageSize.value.toString()
    })

    const response = await fetch(`/api/cross-seed-data?${params.toString()}`)
    const result = await response.json()

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
.cross-seed-data-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0;
  box-sizing: border-box;
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

.pagination-container {
  display: flex;
  align-items: center;
  padding: 10px 15px;
  background-color: #ffffff;
  border-top: 1px solid #ebeef5;
}

.pagination-container :deep(.el-pagination) {
  flex: 1;
  display: flex;
  justify-content: flex-end;
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

:deep(.el-table_1_column_12) {
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
