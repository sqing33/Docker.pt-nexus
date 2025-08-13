<!-- src/views/SitesView.vue -->
<template>
  <div class="sites-view-container">
    <h2>站点信息 - 按总大小分布</h2>

    <!-- Loading State -->
    <div v-if="loading" class="message-box">正在加载数据...</div>

    <!-- No Data State -->
    <div v-if="!loading && chartData.length === 0" class="message-box">
      没有找到站点数据，或所有种子体积为零。
    </div>

    <!-- Chart Container -->
    <div ref="chartRef" class="chart-container"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watchEffect } from 'vue'

// 1. Import ECharts core and required components
import * as echarts from 'echarts/core'
import { PieChart, PieSeriesOption } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponentOption,
  TooltipComponentOption,
  LegendComponentOption,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// Define the type for ECharts options for better TypeScript support
type EChartsOption = echarts.ComposeOption<
  PieSeriesOption | TitleComponentOption | TooltipComponentOption | LegendComponentOption
>

// 2. Register the necessary components with ECharts
echarts.use([TitleComponent, TooltipComponent, LegendComponent, PieChart, CanvasRenderer])

// --- Component State ---

const loading = ref(true)
const chartRef = ref<HTMLDivElement>() // Ref to the DOM element for the chart
let myChart: echarts.ECharts | null = null // Variable to hold the chart instance

// Type for our fetched and processed data
interface SiteDataPoint {
  name: string
  value: number
}
const chartData = ref<SiteDataPoint[]>([])

// --- Helper Functions ---

function formatBytes(bytes: number, decimals = 2): string {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
}

// --- API Fetching ---

async function fetchSiteStats() {
  loading.value = true
  try {
    const response = await fetch('http://192.168.1.100:15001/api/site_stats')
    if (!response.ok) {
      throw new Error(`Network response was not ok: ${response.statusText}`)
    }
    const apiResult = await response.json()

    // Transform backend data {labels: [], datasets: [...]} into ECharts format [{name, value}, ...]
    if (apiResult.labels && apiResult.datasets && apiResult.datasets[0]) {
      chartData.value = apiResult.labels.map((label: string, index: number) => ({
        name: label,
        value: apiResult.datasets[0].data[index] || 0,
      }))
    }
  } catch (error) {
    console.error('Failed to fetch site statistics:', error)
    chartData.value = [] // Clear data on error
  } finally {
    loading.value = false
  }
}

// --- ECharts Logic ---

function initOrUpdateChart() {
  if (chartRef.value && chartData.value.length > 0) {
    if (!myChart) {
      myChart = echarts.init(chartRef.value)
    }

    const option: EChartsOption = {
      title: {
        text: '各站点体积总和',
        subtext: '数据来自所有种子',
        left: 'center',
      },
      tooltip: {
        trigger: 'item',
        formatter: (params: any) => {
          const data = params.data as SiteDataPoint
          return `${data.name}<br/>${formatBytes(data.value)} (${params.percent}%)`
        },
      },
      series: [
        {
          name: '站点体积',
          type: 'pie',
          radius: ['40%', '70%'],
          center: ['50%', '50%'],
          data: chartData.value,
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowOffsetX: 0,
              shadowColor: 'rgba(0, 0, 0, 0.5)',
            },
          },

          // --- 核心修改部分：借鉴官方示例 ---

          label: {
            // 将标签的对齐方式设置为 'edge'，这样标签会紧贴引导线的末端
            alignTo: 'edge',
            // 使用 rich 文本格式化标签内容
            formatter: (params: any) => {
              const siteName = params.name
              const formattedSize = formatBytes(params.value)
              // {name|...} 和 {size|...} 对应下面 rich 对象中的样式
              return `{name|${siteName}}\n{size|${formattedSize}}`
            },
            // 标签和引导线末端的最小间距
            minMargin: 5,
            // 标签离容器边缘的距离
            edgeDistance: 10,
            // 文本的行高
            lineHeight: 15,
            // 定义富文本样式
            rich: {
              name: {
                // 站点名称的样式
                fontSize: 14,
                color: '#333', // 可以根据您的主题调整颜色
              },
              size: {
                // 体积大小的样式
                fontSize: 11,
                color: '#999',
              },
            },
          },
          labelLine: {
            // 第一段引导线的长度
            length: 15,
            // 第二段引导线的长度，设置为 0 使其成为一条直线
            length2: 0,
            // 平滑引导线的最大角度，防止过于尖锐的折角
            maxSurfaceAngle: 80,
          },
          // 使用函数动态调整标签布局，实现“文字在线条上方”的效果
          labelLayout: (params: any) => {
            // 判断标签在图表的左侧还是右侧
            const isLeft = params.labelRect.x < myChart!.getWidth() / 2
            // 获取 ECharts 计算出的引导线路径点
            const points = params.labelLinePoints
            // 关键：更新引导线终点（第二段的结束点）的 x 坐标
            // 如果在左侧，终点 x 就是标签矩形的左边界
            // 如果在右侧，终点 x 就是标签矩形的右边界（x + width）
            points[2][0] = isLeft ? params.labelRect.x : params.labelRect.x + params.labelRect.width

            // 返回更新后的引导线路径，ECharts 会根据这个新路径来绘制
            return {
              labelLinePoints: points,
            }
          },
        },
      ],
    }

    myChart.setOption(option)
  }
}

// Function to handle window resize
function resizeChart() {
  myChart?.resize()
}

// --- Lifecycle Hooks ---

onMounted(() => {
  fetchSiteStats() // Fetch data when component mounts
  window.addEventListener('resize', resizeChart)
})

onBeforeUnmount(() => {
  // IMPORTANT: Clean up the chart instance and event listener to prevent memory leaks
  window.removeEventListener('resize', resizeChart)
  myChart?.dispose()
})

// Use watchEffect to reactively update the chart whenever the data or the ref changes.
// This is the modern Vue 3 way to handle this.
watchEffect(() => {
  initOrUpdateChart()
})
</script>

<style scoped>
.sites-view-container {
  padding: 20px;
  max-width: 1200px;
  margin: 20px auto;
}

h2 {
  text-align: center;
  margin-bottom: 20px;
}

.chart-container {
  /* IMPORTANT: ECharts needs a container with a defined height to render */
  width: 1000px;
  height: 70vh; /* Adjust height as needed */
  min-height: 400px;
}

.message-box {
  text-align: center;
  font-size: 1.2em;
  color: #888;
  padding: 50px 0;
}
</style>
