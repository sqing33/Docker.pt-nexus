<!-- src/views/InfoView.vue -->
<template>
  <div class="info-view">
    <!-- 速度图表 -->
    <el-card class="chart-container" v-loading="speedChartLoading">
      <div class="chart-header">
        <div class="chart-controls">
          <el-button-group>
            <el-button
              :type="activeSpeedTimeRange === 'last_1_minute' ? 'primary' : ''"
              @click="setSpeedTimeRange('last_1_minute')"
              >近1分钟</el-button
            >
            <el-button
              :type="activeSpeedTimeRange === 'last_1_hour' ? 'primary' : ''"
              @click="setSpeedTimeRange('last_1_hour')"
              >近1小时</el-button
            >
            <el-button
              :type="activeSpeedTimeRange === 'last_12_hours' ? 'primary' : ''"
              @click="setSpeedTimeRange('last_12_hours')"
              >近12小时</el-button
            >
            <el-button
              :type="activeSpeedTimeRange === 'last_24_hours' ? 'primary' : ''"
              @click="setSpeedTimeRange('last_24_hours')"
              >近24小时</el-button
            >
            <el-button
              :type="activeSpeedTimeRange === 'today' ? 'primary' : ''"
              @click="setSpeedTimeRange('today')"
              >今日</el-button
            >
            <el-button
              :type="activeSpeedTimeRange === 'yesterday' ? 'primary' : ''"
              @click="setSpeedTimeRange('yesterday')"
              >昨日</el-button
            >
          </el-button-group>
          <h2 class="chart-title">速率</h2>
        </div>
        <div class="chart-actions">
          <el-button @click="toggleSpeedDisplayMode()" size="small">{{
            speedDisplayModeButtonText
          }}</el-button>
        </div>
      </div>
      <div class="card" ref="speedChartRef"></div>
    </el-card>

    <!-- 数据量图表 -->
    <el-card class="chart-container" v-loading="chartLoading">
      <div class="chart-header">
        <div class="chart-controls">
          <el-button-group>
            <el-button
              :type="activeTimeRange === 'today' ? 'primary' : ''"
              @click="setTimeRange('today')"
              >今日</el-button
            >
            <el-button
              :type="activeTimeRange === 'yesterday' ? 'primary' : ''"
              @click="setTimeRange('yesterday')"
              >昨日</el-button
            >
            <el-button
              :type="activeTimeRange === 'this_week' ? 'primary' : ''"
              @click="setTimeRange('this_week')"
              >本周</el-button
            >
            <el-button
              :type="activeTimeRange === 'last_week' ? 'primary' : ''"
              @click="setTimeRange('last_week')"
              >上周</el-button
            >
            <el-button
              :type="activeTimeRange === 'this_month' ? 'primary' : ''"
              @click="setTimeRange('this_month')"
              >本月</el-button
            >
            <el-button
              :type="activeTimeRange === 'last_month' ? 'primary' : ''"
              @click="setTimeRange('last_month')"
              >上月</el-button
            >
            <el-button
              :type="activeTimeRange === 'last_6_months' ? 'primary' : ''"
              @click="setTimeRange('last_6_months')"
              >近半年</el-button
            >
            <el-button
              :type="activeTimeRange === 'this_year' ? 'primary' : ''"
              @click="setTimeRange('this_year')"
              >今年</el-button
            >
            <el-button
              :type="activeTimeRange === 'all' ? 'primary' : ''"
              @click="setTimeRange('all')"
              >全部</el-button
            >
          </el-button-group>
          <h2 class="chart-title">数据量</h2>
        </div>
        <div class="chart-actions">
          <el-button @click="toggleTrafficDisplayMode()" size="small">{{
            trafficDisplayModeButtonText
          }}</el-button>
        </div>
      </div>
      <div class="card" ref="chartRef">
        <div class="total-traffic-info">
          <div>
            总上传: <strong>{{ totalChartUpload }}</strong>
          </div>
          <div>
            总下载: <strong>{{ totalChartDownload }}</strong>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts/core'
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  ToolboxComponent,
  DataZoomComponent,
  type TooltipComponentOption,
  type GridComponentOption,
  type LegendComponentOption,
  type TitleComponentOption,
  type ToolboxComponentOption,
  type DataZoomComponentOption,
} from 'echarts/components'
import { LineChart, BarChart, type LineSeriesOption, type BarSeriesOption } from 'echarts/charts'
import { UniversalTransition } from 'echarts/features'
import { SVGRenderer } from 'echarts/renderers'

// ECharts 类型组合
type ECOption = echarts.ComposeOption<
  | TitleComponentOption
  | TooltipComponentOption
  | GridComponentOption
  | LegendComponentOption
  | ToolboxComponentOption
  | DataZoomComponentOption
  | LineSeriesOption
  | BarSeriesOption
>

// 注册 ECharts 组件
echarts.use([
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  ToolboxComponent,
  DataZoomComponent,
  LineChart,
  BarChart,
  SVGRenderer,
  UniversalTransition,
])

// --- 类型定义 ---
interface SpeedData {
  qb_ul: number
  qb_dl: number
  tr_ul: number
  tr_dl: number
}
interface SpeedHistoryPoint {
  time: string
  qb_ul_speed: number
  qb_dl_speed: number
  tr_ul_speed: number
  tr_dl_speed: number
}
interface TrafficDataPoint {
  time: string
  qb_ul: number
  qb_dl: number
  tr_ul: number
  tr_dl: number
}
interface DownloaderStatus {
  qb: boolean
  tr: boolean
}

// --- 状态与引用 ---
const speedChartRef = ref<HTMLElement | null>(null)
const chartRef = ref<HTMLElement | null>(null)
let speedChart: echarts.ECharts | null = null
let trafficChart: echarts.ECharts | null = null

const speedChartLoading = ref<boolean>(true)
const chartLoading = ref<boolean>(true)

const activeSpeedTimeRange = ref<string>('last_1_minute')
const activeTimeRange = ref<string>('this_month')

const speedDisplayMode = ref<'all' | 'upload' | 'download'>('all')
const trafficDisplayMode = ref<'all' | 'upload' | 'download'>('all')

const currentSpeeds = ref<SpeedData>({ qb_ul: 0, qb_dl: 0, tr_ul: 0, tr_dl: 0 })
const downloaderEnabledStatus = ref<DownloaderStatus>({ qb: false, tr: false })
const speedHistory = ref<SpeedHistoryPoint[]>([])

const totalChartUpload = ref<string>('0 B')
const totalChartDownload = ref<string>('0 B')

// 定时器 ID
let liveSpeedTimerId: number | null = null
let realtimeChartTimerId: number | null = null
let trafficChartTimerId: number | null = null

// 格式化单位
const formatBytesForSpeed = (b: number | null): string => {
  if (b == null || b < 0) return '0 B/s'
  const s = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
  if (b === 0) return '0 B/s'
  const i = Math.floor(Math.log(b) / Math.log(1024))
  return (b / Math.pow(1024, i)).toFixed(2) + ' ' + s[i]
}

const formatBytes = (b: number | null, unit: string = ''): string => {
  if (b == null || b < 0) return `0 ${unit.replace('/s', 'B')}`
  if (b === 0) return `0 ${unit}`
  const s = unit ? [unit] : ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = unit ? 0 : Math.floor(Math.log(b) / Math.log(1024))
  return `${(b / Math.pow(1024, i)).toFixed(2)} ${s[i]}`
}

// --- ECharts 逻辑 ---
const initCharts = () => {
  if (speedChartRef.value && !speedChart) {
    speedChart = echarts.init(speedChartRef.value, 'light', { renderer: 'svg' })
  }
  if (chartRef.value && !trafficChart) {
    trafficChart = echarts.init(chartRef.value, 'light', { renderer: 'svg' })
  }
}

const manageTimers = (start: boolean) => {
  if (start) {
    fetchTrafficChartData()
    trafficChartTimerId = window.setInterval(() => fetchTrafficChartData(true), 60000)

    updateLiveSpeedDisplay()
    liveSpeedTimerId = window.setInterval(updateLiveSpeedDisplay, 1000)

    if (activeSpeedTimeRange.value === 'last_1_minute') {
      startRealtimeSpeedChart()
    } else {
      fetchHistoricalSpeedChart()
    }
  } else {
    if (liveSpeedTimerId) clearInterval(liveSpeedTimerId)
    if (realtimeChartTimerId) clearInterval(realtimeChartTimerId)
    if (trafficChartTimerId) clearInterval(trafficChartTimerId)
    liveSpeedTimerId = realtimeChartTimerId = trafficChartTimerId = null
  }
}

// --- 速度图表逻辑 ---
const fetchHistoricalSpeedChart = async () => {
  if (realtimeChartTimerId) clearInterval(realtimeChartTimerId)
  realtimeChartTimerId = null
  speedChartLoading.value = true
  try {
    const response = await fetch(`/api/speed_chart_data?range=${activeSpeedTimeRange.value}`)
    if (!response.ok) throw new Error('获取历史速度数据失败')
    const result: { labels: string[]; datasets: any[] } = await response.json()

    if (!speedChart) initCharts()

    const option: ECOption = {
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          let tooltipHtml = `${params[0].axisValue}<br/>`
          params.forEach((p) => {
            tooltipHtml += `${p.marker} ${p.seriesName}: ${formatBytesForSpeed(p.value)}<br/>`
          })
          return tooltipHtml
        },
      },
      animation: true,
      animationDuration: 1000,
      animationDurationUpdate: 300,
      animationEasingUpdate: 'cubicInOut',
      legend: { data: ['qB上传', 'qB下载', 'Tr上传', 'Tr下载'], top: 0 },
      grid: { top: 70, left: 10, right: 0, bottom: 0, containLabel: true },
      xAxis: { type: 'category', boundaryGap: false, data: result.labels },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: (value: number) => formatBytesForSpeed(value) },
      },
      series: [
        {
          name: 'qB上传',
          type: 'line',
          smooth: true,
          symbol: 'none',
          data: result.datasets.map((d) => d.qb_ul_speed),
          itemStyle: { color: '#67C23A' },
        },
        {
          name: 'qB下载',
          type: 'line',
          smooth: true,
          symbol: 'none',
          data: result.datasets.map((d) => d.qb_dl_speed),
          itemStyle: { color: '#409EFF' },
        },
        {
          name: 'Tr上传',
          type: 'line',
          smooth: true,
          symbol: 'none',
          data: result.datasets.map((d) => d.tr_ul_speed),
          itemStyle: { color: '#F56C6C' },
        },
        {
          name: 'Tr下载',
          type: 'line',
          smooth: true,
          symbol: 'none',
          data: result.datasets.map((d) => d.tr_dl_speed),
          itemStyle: { color: '#E6A23C' },
        },
      ],
      dataZoom: [{ type: 'inside', start: 0, end: 100, zoomLock: true }],
      toolbox: { feature: { saveAsImage: { title: '保存' } } },
    }
    speedChart?.setOption(option, true)
    toggleSpeedDisplayMode(true)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    speedChartLoading.value = false
    nextTick(() => {
      speedChart?.resize()
    })
  }
}

const startRealtimeSpeedChart = async () => {
  speedChartLoading.value = true
  try {
    const response = await fetch('/api/recent_speed_data?seconds=60')
    if (!response.ok) throw new Error('获取近期速度数据失败')
    const initialData: SpeedHistoryPoint[] = await response.json()
    speedHistory.value = initialData

    updateRealtimeSpeedChart(true)
    if (realtimeChartTimerId) clearInterval(realtimeChartTimerId)
    realtimeChartTimerId = window.setInterval(updateRealtimeSpeedChart, 1000)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    speedChartLoading.value = false
  }
}

const updateRealtimeSpeedChart = (isInitial = false) => {
  if (!isInitial) {
    speedHistory.value.push({
      time: new Date().toLocaleTimeString(),
      qb_ul_speed: currentSpeeds.value.qb_ul,
      qb_dl_speed: currentSpeeds.value.qb_dl,
      tr_ul_speed: currentSpeeds.value.tr_ul,
      tr_dl_speed: currentSpeeds.value.tr_dl,
    })
    if (speedHistory.value.length > 60) speedHistory.value.shift()
  }

  const option: ECOption = {
    tooltip: {
      trigger: 'axis',
      // ★★★ 修正点 1：Tooltip Formatter 改回最简单的形式 ★★★
      // 因为 series.name 将变回静态的 "qB上传" 等
      formatter: (params: any) => {
        let tooltipHtml = `${params[0].axisValue}<br/>`
        params.forEach((p) => {
          tooltipHtml += `${p.marker} ${p.seriesName}: ${formatBytesForSpeed(p.value)}<br/>`
        })
        return tooltipHtml
      },
    },
    // ★★★ 核心改动：使用 legend.formatter ★★★
    legend: {
      // 1. data 使用静态、不变的名称
      data: ['qB上传', 'qB下载', 'Tr上传', 'Tr下载'],
      top: 0,
      // 2. formatter 函数根据静态名称返回动态文本
      formatter: (name) => {
        if (name === 'qB上传') {
          return `qB上传: ${formatBytesForSpeed(currentSpeeds.value.qb_ul)}`
        }
        if (name === 'qB下载') {
          return `qB下载: ${formatBytesForSpeed(currentSpeeds.value.qb_dl)}`
        }
        if (name === 'Tr上传') {
          return `Tr上传: ${formatBytesForSpeed(currentSpeeds.value.tr_ul)}`
        }
        if (name === 'Tr下载') {
          return `Tr下载: ${formatBytesForSpeed(currentSpeeds.value.tr_dl)}`
        }
        return name
      },
      textStyle: {
        width: 150,
        overflow: 'truncate',
      },
    },
    grid: { top: 50, left: 10, right: 0, bottom: 0, containLabel: true },
    animation: true,
    animationDuration: 1000,
    animationDurationUpdate: 300,
    animationEasingUpdate: 'cubicInOut',
    xAxis: { data: speedHistory.value.map((p) => p.time) },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => formatBytesForSpeed(v) } },
    // ★★★ 修正点 2：series 的 name 也必须改回静态名称 ★★★
    series: [
      {
        name: 'qB上传', // 使用静态名称
        type: 'line',
        smooth: true,
        symbol: 'none',
        data: speedHistory.value.map((p) => p.qb_ul_speed),
        itemStyle: { color: '#67C23A' },
      },
      {
        name: 'qB下载', // 使用静态名称
        type: 'line',
        smooth: true,
        symbol: 'none',
        data: speedHistory.value.map((p) => p.qb_dl_speed),
        itemStyle: { color: '#409EFF' },
      },
      {
        name: 'Tr上传', // 使用静态名称
        type: 'line',
        smooth: true,
        symbol: 'none',
        data: speedHistory.value.map((p) => p.tr_ul_speed),
        itemStyle: { color: '#F56C6C' },
      },
      {
        name: 'Tr下载', // 使用静态名称
        type: 'line',
        smooth: true,
        symbol: 'none',
        data: speedHistory.value.map((p) => p.tr_dl_speed),
        itemStyle: { color: '#E6A23C' },
      },
    ],
  }

  if (isInitial) {
    if (!speedChart) initCharts()
    speedChart?.setOption(option, true)
    toggleSpeedDisplayMode(true)
  } else {
    // ★★★ 修正点 3：改回默认的 setOption 调用方式 ★★★
    // ECharts 会智能地只更新变化的部分（数据和图例文本），并保持 tooltip 状态
    speedChart?.setOption(option)
  }

  nextTick(() => {
    speedChart?.resize()
  })
}

const updateLiveSpeedDisplay = async () => {
  try {
    const response = await fetch('/api/speed_data')
    if (!response.ok) return
    const data = await response.json()
    currentSpeeds.value = {
      qb_ul: data.qbittorrent.upload_speed,
      qb_dl: data.qbittorrent.download_speed,
      tr_ul: data.transmission.upload_speed,
      tr_dl: data.transmission.download_speed,
    }
    downloaderEnabledStatus.value = {
      qb: data.qbittorrent.enabled,
      tr: data.transmission.enabled,
    }
  } catch (e) {
    console.error('Live speed update failed:', e)
  }
}

// --- 数据量图表逻辑 ---
const fetchTrafficChartData = async (isAutoRefresh = false) => {
  if (!isAutoRefresh) chartLoading.value = true
  try {
    const response = await fetch(`/api/chart_data?range=${activeTimeRange.value}`)
    if (!response.ok) throw new Error('获取数据量图表失败')
    const result: { labels: string[]; datasets: TrafficDataPoint[] } = await response.json()

    if (!trafficChart) initCharts()

    totalChartUpload.value = formatBytes(
      result.datasets.reduce((acc, cur) => acc + cur.qb_ul + cur.tr_ul, 0),
    )
    totalChartDownload.value = formatBytes(
      result.datasets.reduce((acc, cur) => acc + cur.qb_dl + cur.tr_dl, 0),
    )

    // 1. 预先计算好每个堆叠的总量数据 (此步骤保持不变)
    const uploadTotals = result.datasets.map((d) => d.qb_ul + d.tr_ul)
    const downloadTotals = result.datasets.map((d) => d.qb_dl + d.tr_dl)

    const option: ECOption = {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params) => {
          let tooltipHtml = `${params[0].name}<br/>`
          const sums = {}
          const visibleParams = params.filter((p) => p.seriesName && !p.seriesName.includes('总和'))

          visibleParams.forEach((p) => {
            const stackName = p.seriesName.includes('上传') ? '上传总和' : '下载总和'
            if (!sums[stackName]) sums[stackName] = 0
            sums[stackName] += Number(p.value || 0)
            tooltipHtml += `${p.marker} ${p.seriesName}: ${formatBytes(p.value)}<br/>`
          })
          if (sums['上传总和'] !== undefined) {
            tooltipHtml += `<strong>上传总和: ${formatBytes(sums['上传总和'])}</strong><br/>`
          }
          if (sums['下载总和'] !== undefined) {
            tooltipHtml += `<strong>下载总和: ${formatBytes(sums['下载总和'])}</strong>`
          }
          return tooltipHtml
        },
      },

      legend: { data: ['qB上传', 'qB下载', 'Tr上传', 'Tr下载'], top: 0 },
      grid: { top: 50, left: 10, right: 10, bottom: 0, containLabel: true },
      xAxis: { type: 'category', data: result.labels },
      yAxis: { type: 'value', axisLabel: { formatter: (v: number) => formatBytes(v) } },
      series: [
        // --- 可见的数据系列 (保持不变) ---
        {
          name: 'qB上传',
          type: 'bar',
          stack: '上传',
          emphasis: { focus: 'series' },
          data: result.datasets.map((d) => d.qb_ul),
          itemStyle: { color: '#67C23A' },
        },
        {
          name: 'Tr上传',
          type: 'bar',
          stack: '上传',
          emphasis: { focus: 'series' },
          data: result.datasets.map((d) => d.tr_ul),
          itemStyle: { color: '#F56C6C' },
        },
        {
          name: 'qB下载',
          type: 'bar',
          stack: '下载',
          emphasis: { focus: 'series' },
          data: result.datasets.map((d) => d.qb_dl),
          itemStyle: { color: '#409EFF' },
        },
        {
          name: 'Tr下载',
          type: 'bar',
          stack: '下载',
          emphasis: { focus: 'series' },
          data: result.datasets.map((d) => d.tr_dl),
          itemStyle: { color: '#E6A23C' },
        },

        // --- 修正后的辅助系列 ---
        {
          name: '上传总和',
          type: 'bar',
          stack: '上传',
          label: {
            show: true,
            position: 'top',
            // 关键改动： formatter 利用 dataIndex 从外部数组获取真正的总和
            formatter: (params: any) => {
              const total = uploadTotals[params.dataIndex]
              return total > 0 ? formatBytes(total) : ''
            },
            color: '#303133',
            fontSize: 12,
            fontWeight: 'bold',
          },
          // 关键改动：数据应为 0，这样它才不会占用堆叠的高度
          data: result.labels.map(() => 0),
          itemStyle: { color: 'transparent' },
          tooltip: { show: false },
        },
        {
          name: '下载总和',
          type: 'bar',
          stack: '下载',
          label: {
            show: true,
            position: 'top',
            formatter: (params: any) => {
              const total = downloadTotals[params.dataIndex]
              return total > 0 ? formatBytes(total) : ''
            },
            color: '#303133',
            fontSize: 12,
            fontWeight: 'bold',
          },
          data: result.labels.map(() => 0),
          itemStyle: { color: 'transparent' },
          tooltip: { show: false },
        },
      ],
      toolbox: { feature: { saveAsImage: { title: '保存' } } },
    }
    trafficChart?.setOption(option, true)
    toggleTrafficDisplayMode(true)
  } catch (e: any) {
    if (!isAutoRefresh) ElMessage.error(e.message)
  } finally {
    if (!isAutoRefresh) chartLoading.value = false
    nextTick(() => {
      trafficChart?.resize()
    })
  }
}

// --- UI 事件处理 ---
const setSpeedTimeRange = (range: string) => (activeSpeedTimeRange.value = range)
const setTimeRange = (range: string) => (activeTimeRange.value = range)

const toggleDisplayMode = (chart: echarts.ECharts | null, mode: 'all' | 'upload' | 'download') => {
  if (!chart) return
  const newSelected: Record<string, boolean> = {}
  const allSeries = ['qB上传', 'qB下载', 'Tr上传', 'Tr下载']
  allSeries.forEach((name) => {
    if (mode === 'upload') newSelected[name] = name.includes('上传')
    else if (mode === 'download') newSelected[name] = name.includes('下载')
    else newSelected[name] = true
  })
  chart.setOption({ legend: { selected: newSelected } })
}

const toggleSpeedDisplayMode = (isUpdate = false) => {
  if (!isUpdate) {
    speedDisplayMode.value =
      speedDisplayMode.value === 'all'
        ? 'upload'
        : speedDisplayMode.value === 'upload'
          ? 'download'
          : 'all'
  }
  toggleDisplayMode(speedChart, speedDisplayMode.value)
}
const toggleTrafficDisplayMode = (isUpdate = false) => {
  if (!isUpdate) {
    trafficDisplayMode.value =
      trafficDisplayMode.value === 'all'
        ? 'upload'
        : trafficDisplayMode.value === 'upload'
          ? 'download'
          : 'all'
  }
  toggleDisplayMode(trafficChart, trafficDisplayMode.value)
}

const speedDisplayModeButtonText = computed(() =>
  speedDisplayMode.value === 'all'
    ? '全部'
    : speedDisplayMode.value === 'upload'
      ? '仅上传'
      : '仅下载',
)
const trafficDisplayModeButtonText = computed(() =>
  trafficDisplayMode.value === 'all'
    ? '全部'
    : trafficDisplayMode.value === 'upload'
      ? '仅上传'
      : '仅下载',
)

// --- 生命周期 ---
onMounted(() => {
  const resizeHandler = () => {
    speedChart?.resize()
    trafficChart?.resize()
  }
  window.addEventListener('resize', resizeHandler)

  onUnmounted(() => {
    window.removeEventListener('resize', resizeHandler)
    manageTimers(false)
    speedChart?.dispose()
    trafficChart?.dispose()
  })

  manageTimers(true)
})

watch(activeSpeedTimeRange, (newRange) => {
  if (newRange === 'last_1_minute') {
    if (realtimeChartTimerId) clearInterval(realtimeChartTimerId)
    realtimeChartTimerId = null
    startRealtimeSpeedChart()
  } else {
    fetchHistoricalSpeedChart()
  }
})

watch(activeTimeRange, () => fetchTrafficChartData())
</script>

<style scoped>
:deep(.el-card) {
  --el-card-padding: 10px;
}

.info-view {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 15px;
  height: 100%;
  box-sizing: border-box;
}
.chart-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 300px;
  height: 40vh;
}
.chart-container .el-card__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.chart-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  align-items: center;
}
.chart-actions {
  display: flex;
  align-items: center;
  gap: 15px;
  font-size: 12px;
  color: #606266;
}
.total-traffic-info {
  display: flex;
  gap: 10px;
  position: absolute;
  font-size: 13px;
  left: calc(50% + 175px);
  transform: translateY(2px);
}
.card {
  width: 100%;
  flex: 1;
  min-height: 0;
  height: calc((100vh - 40px - 20px - 15px) / 2 - 55px);
}
.chart-title {
  position: absolute;
  left: 50%;
  transform: translate(-50%, -10px);
}
</style>
