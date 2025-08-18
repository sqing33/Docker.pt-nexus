<template>
  <div class="sites-view-container">
    <!-- 标题部分 -->
    <h1 class="main-title">站点信息 - 按总大小与数量分布</h1>

    <!-- 
      新增的布局包裹层 
      - 它将作为表格定位的相对父容器
      - flex-grow: 1 样式使其填充父容器所有剩余空间
    -->
    <div class="layout-wrapper">
      <!-- 
        Element Plus 表格
        - 新增 class="top-left-table" 用于 CSS 定位
        - 关键改动: :height="'100%'" 属性，让表格内容可滚动
      -->
      <el-table
        v-loading="loading"
        :data="siteStatsData"
        class="top-left-table"
        border
        stripe
        :height="'100%'"
        :default-sort="{ prop: 'total_size', order: 'descending' }"
      >
        <template #empty>
          <el-empty description="没有找到站点数据，或所有种子体积为零。" />
        </template>

        <el-table-column prop="site_name" label="站点名称" sortable min-width="180" />

        <el-table-column
          prop="torrent_count"
          label="种子数量"
          sortable
          align="right"
          header-align="right"
          width="150"
        />

        <el-table-column
          prop="total_size"
          label="种子总体积"
          sortable
          align="right"
          header-align="right"
          min-width="180"
        >
          <template #default="scope">
            <span>{{ formatBytes(scope.row.total_size) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <!-- 您可以在这里为其他象限添加内容 -->
      <!-- <div class="top-right-placeholder">右上角</div> -->
      <!-- <div class="bottom-left-placeholder">左下角</div> -->
      <!-- <div class="bottom-right-placeholder">右下角</div> -->
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

// --- 响应式状态定义 ---
const loading = ref(true)
const siteStatsData = ref([])

// --- 工具函数 ---
const formatBytes = (bytes, decimals = 2) => {
  if (!+bytes) return '0 Bytes'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}

// --- 数据获取逻辑 ---
const fetchSiteStats = async () => {
  loading.value = true
  try {
    const response = await fetch('/api/site_stats')
    if (!response.ok) {
      throw new Error(`网络响应错误，状态码: ${response.status}`)
    }
    const data = await response.json()
    if (Array.isArray(data)) {
      siteStatsData.value = data
    } else {
      console.error('API 返回的数据格式不正确，期望得到一个数组，但收到了:', data)
      siteStatsData.value = []
    }
  } catch (error) {
    console.error('获取站点统计数据失败:', error)
    siteStatsData.value = []
  } finally {
    loading.value = false
  }
}

// --- Vue 生命周期钩子 ---
onMounted(() => {
  fetchSiteStats()
})
</script>

<style scoped>
/* --- 关键布局样式 --- */

/* 1. 主容器设置为 flex 布局，垂直排列，并撑满整个视口高度 */
.sites-view-container {
  display: flex;
  flex-direction: column;
  height: 100vh; /* 占满视口高度 */
  padding: 25px;
  box-sizing: border-box; /* 让 padding 不会撑大容器 */
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  overflow: hidden; /* 防止子元素溢出导致整个页面滚动 */
}

/* 2. 标题样式，不拉伸 */
.main-title {
  font-size: 1.8em;
  color: #333;
  margin: 0 0 20px 0; /* 调整外边距 */
  flex-shrink: 0; /* 防止容器缩小时标题被压缩 */
}

/* 3. 布局包裹层，它将自动填充标题下方的所有剩余空间 */
.layout-wrapper {
  flex-grow: 1; /* 核心：占据所有可用的垂直空间 */
  position: relative; /* 关键：为内部绝对定位的元素提供定位上下文 */
  min-height: 0; /* flex 布局中的一个 hack，防止内容溢出 */
}

/* 4. 将表格绝对定位在包裹层的左上角四分之一区域 */
.top-left-table {
  position: absolute;
  top: 0;
  left: 0;
  width: 50%;
  height: 50%;
}

/* --- (可选) 为其他象限添加占位符样式，方便未来扩展 --- */

.top-right-placeholder,
.bottom-left-placeholder,
.bottom-right-placeholder {
  position: absolute;
  border: 2px dashed #ccc;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #aaa;
  font-size: 1.5em;
  box-sizing: border-box;
}

.top-right-placeholder {
  top: 0;
  left: 50%;
  width: 50%;
  height: 50%;
}
.bottom-left-placeholder {
  top: 50%;
  left: 0;
  width: 50%;
  height: 50%;
}
.bottom-right-placeholder {
  top: 50%;
  left: 50%;
  width: 50%;
  height: 50%;
}
</style>
