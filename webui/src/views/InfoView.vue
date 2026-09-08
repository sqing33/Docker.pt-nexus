<template>
  <div class="info-view-container" v-loading="areSettingsLoading">
    <!-- 速率图表 -->
    <div class="chart-card glass-card glass-rounded">
      <div class="chart-header">
        <!-- 左侧：时间段筛选 -->
        <div class="header-left-controls">
          <div class="button-group date-range-group">
            <!-- [修改] 为“近1分钟”按钮添加禁用状态和提示 -->
            <el-tooltip content="请在设置页面开启“实时速率”以使用此功能" :disabled="isRealtimeSpeedEnabled" placement="top">
              <div class="button-wrapper">
                <button @click="changeSpeedMode('last_1_min')" :class="{ active: speedDisplayMode === 'last_1_min' }"
                  :disabled="!isRealtimeSpeedEnabled">
                  近1分钟
                </button>
              </div>
            </el-tooltip>
            <button @click="changeSpeedMode('today')" :class="{ active: speedDisplayMode === 'today' }">
              今日
            </button>
            <button @click="changeSpeedMode('yesterday')" :class="{ active: speedDisplayMode === 'yesterday' }">
              昨日
            </button>
            <button @click="changeSpeedMode('this_week')" :class="{ active: speedDisplayMode === 'this_week' }">
              本周
            </button>
            <button @click="changeSpeedMode('last_week')" :class="{ active: speedDisplayMode === 'last_week' }">
              上周
            </button>
            <button @click="changeSpeedMode('this_month')" :class="{ active: speedDisplayMode === 'this_month' }">
              本月
            </button>
            <button @click="changeSpeedMode('last_month')" :class="{ active: speedDisplayMode === 'last_month' }">
              上月
            </button>
            <button @click="changeSpeedMode('all')" :class="{ active: speedDisplayMode === 'all' }">
              全部
            </button>
          </div>
        </div>

        <!-- 中间：标题 -->
        <div class="chart-title">速率 {{ speedDisplayModeButtonText }}</div>

        <!-- 右侧：显示切换按钮 -->
        <div class="header-right-controls">
          <div class="button-group visibility-group">
            <button @click="changeSpeedVisibility('all')" :class="{ active: speedChartVisibilityMode === 'all' }">
              全部
            </button>
            <button @click="changeSpeedVisibility('upload')" :class="{ active: speedChartVisibilityMode === 'upload' }">
              仅上传
            </button>
            <button @click="changeSpeedVisibility('download')"
              :class="{ active: speedChartVisibilityMode === 'download' }">
              仅下载
            </button>
          </div>
        </div>
      </div>

      <!-- 自定义的可换行图例容器 -->
      <div class="custom-legend-container">
        <span v-for="item in speedChartLegendItems" :key="item.fullName" class="legend-item"
          :class="{ disabled: item.disabled }" @click="toggleSeries(item.fullName)">
          <span class="legend-color-box" :style="{ backgroundColor: item.color }"></span>
          <span class="legend-item-content">
            <span class="legend-base-name" :title="item.baseName">{{ item.baseName }}{{ item.arrow }}</span>
            <span class="legend-speed-info"> {{ item.speed }}</span>
          </span>
        </span>
      </div>

      <div class="chart-scroll-container">
        <div ref="speedChart" class="chart-body chart-body-inner"></div>
      </div>
    </div>

    <!-- 数据量图表 -->
    <div class="chart-card glass-card glass-rounded">
      <div class="chart-header">
        <!-- 左侧：时间段筛选 -->
        <div class="header-left-controls">
          <div class="button-group date-range-group">
            <button @click="changeTrafficMode('today')" :class="{ active: trafficDisplayMode === 'today' }">
              今日
            </button>
            <button @click="changeTrafficMode('yesterday')" :class="{ active: trafficDisplayMode === 'yesterday' }">
              昨日
            </button>
            <button @click="changeTrafficMode('this_week')" :class="{ active: trafficDisplayMode === 'this_week' }">
              本周
            </button>
            <button @click="changeTrafficMode('last_week')" :class="{ active: trafficDisplayMode === 'last_week' }">
              上周
            </button>
            <button @click="changeTrafficMode('this_month')" :class="{ active: trafficDisplayMode === 'this_month' }">
              本月
            </button>
            <button @click="changeTrafficMode('last_month')" :class="{ active: trafficDisplayMode === 'last_month' }">
              上月
            </button>
            <button @click="changeTrafficMode('this_year')" :class="{ active: trafficDisplayMode === 'this_year' }">
              今年
            </button>
            <button @click="changeTrafficMode('all')" :class="{ active: trafficDisplayMode === 'all' }">
              全部
            </button>
          </div>
        </div>

        <!-- 中间：标题 -->
        <div class="chart-title">数据量 {{ trafficDisplayModeButtonText }}</div>

        <!-- 右侧：显示切换按钮 -->
        <div class="header-right-controls">
          <div class="button-group visibility-group">
            <button @click="changeTrafficVisibility('all')" :class="{ active: trafficChartVisibilityMode === 'all' }">
              全部
            </button>
            <button @click="changeTrafficVisibility('upload')"
              :class="{ active: trafficChartVisibilityMode === 'upload' }">
              仅上传
            </button>
            <button @click="changeTrafficVisibility('download')"
              :class="{ active: trafficChartVisibilityMode === 'download' }">
              仅下载
            </button>
          </div>
        </div>
      </div>
      <div class="traffic-legend-container">
        <span
          v-for="item in trafficChartLegendItems"
          :key="item.name"
          class="traffic-legend-item"
          :class="{ disabled: item.disabled }"
          @click="toggleTrafficSeries(item.name)"
        >
          <span class="traffic-legend-dot" :style="{ backgroundColor: item.color }"></span>
          <span class="traffic-legend-name" :title="item.name">{{ item.name }}</span>
        </span>
      </div>

      <div class="chart-scroll-container">
        <div ref="trafficChart" class="chart-body chart-body-inner"></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import * as echarts from 'echarts'
import type {
  EChartsOption,
  EChartsType,
  TooltipComponentFormatterCallbackParams,
  TooltipComponentPositionCallbackParams,
} from 'echarts'
import axios from 'axios'
import { ElTooltip } from 'element-plus'
import { ElMessage } from '@/utils/uiNotify'

const displayModeTextMap = {
  last_1_min: '近1分钟',
  today: '今日',
  yesterday: '昨日',
  this_week: '本周',
  last_week: '上周',
  this_month: '本月',
  last_month: '上月',
  this_year: '今年',
  all: '全部',
} as const

type SpeedDisplayMode = Exclude<keyof typeof displayModeTextMap, 'this_year'>
type TrafficDisplayMode = Exclude<keyof typeof displayModeTextMap, 'last_1_min'>
type VisibilityMode = 'all' | 'upload' | 'download'

type DownloaderMeta = { id: string; name: string }
type SpeedLegendArrow = '↑' | '↓'

type SpeedLegendItem = {
  fullName: string
  baseName: string
  arrow: SpeedLegendArrow
  speed: string
  color: string
  disabled: boolean
}

type TrafficLegendItem = {
  name: string
  color: string
  disabled: boolean
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const getLegendSelectedMap = (chartInstance: EChartsType | null): Record<string, boolean> => {
  const option = chartInstance?.getOption() as unknown
  if (!isRecord(option)) return {}

  const legendOption = option.legend
  const legend = Array.isArray(legendOption) ? legendOption[0] : legendOption
  if (!isRecord(legend)) return {}

  const selectedValue = legend.selected
  if (!isRecord(selectedValue)) return {}

  const selected: Record<string, boolean> = {}
  for (const [key, value] of Object.entries(selectedValue)) {
    if (typeof value === 'boolean') {
      selected[key] = value
    }
  }
  return selected
}

const getLegendData = (chartInstance: EChartsType | null): string[] => {
  const option = chartInstance?.getOption() as unknown
  if (!isRecord(option)) return []

  const legendOption = option.legend
  const legend = Array.isArray(legendOption) ? legendOption[0] : legendOption
  if (!isRecord(legend)) return []

  const dataValue = legend.data
  if (!Array.isArray(dataValue)) return []
  return dataValue.filter((item): item is string => typeof item === 'string')
}

// --- Refs and State ---
const speedChart = ref<HTMLElement | null>(null)
const trafficChart = ref<HTMLElement | null>(null)
let speedChartInstance: EChartsType | null = null
let trafficChartInstance: EChartsType | null = null
let speedUpdateTimer: ReturnType<typeof setInterval> | null = null
let isMouseOverChart = false
let lastTooltipDataIndex: number | null = null

const speedDisplayMode = ref<SpeedDisplayMode>('last_1_min')
const trafficDisplayMode = ref<TrafficDisplayMode>('today')

const speedChartVisibilityMode = ref<VisibilityMode>('all')
const trafficChartVisibilityMode = ref<VisibilityMode>('all')

const speedChartDownloaders = ref<DownloaderMeta[]>([])
const speedChartLegendItems = ref<SpeedLegendItem[]>([])
const trafficChartLegendItems = ref<TrafficLegendItem[]>([])

const isRealtimeSpeedEnabled = ref(false)
const areSettingsLoading = ref(true)

const speedDisplayModeButtonText = computed(() => `(${displayModeTextMap[speedDisplayMode.value]})`)
const trafficDisplayModeButtonText = computed(
  () => `(${displayModeTextMap[trafficDisplayMode.value]})`,
)

// --- Helper Functions ---
const formatBytes = (bytes: unknown) => {
  const value = typeof bytes === 'number' ? bytes : Number(bytes)
  if (!Number.isFinite(value) || value < 0) return '0 B'
  if (value === 0) return '0 B'
  const s = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(value) / Math.log(1024))
  return `${parseFloat((value / Math.pow(1024, i)).toFixed(2))} ${s[i]}`
}
const formatSpeed = (speed: unknown) => `${formatBytes(speed)}/s`

const MOBILE_BREAKPOINT = 768
const isMobileViewport = () => window.innerWidth <= MOBILE_BREAKPOINT
const getTooltipTriggerOn = () => (isMobileViewport() ? 'click' : 'mousemove|click')
const SPEED_MOBILE_VISIBLE_POINTS = 12
const TRAFFIC_MOBILE_VISIBLE_POINTS = 7

const getChartGrid = (chartType: 'speed' | 'traffic') => {
  const isMobile = isMobileViewport()
  if (chartType === 'speed') {
    return isMobile
      ? { top: 85, left: 0, right: 8, bottom: 2, containLabel: true }
      : { top: 85, left: '3%', right: '4%', bottom: '3%', containLabel: true }
  }

  return isMobile
    ? { top: 80, left: 0, right: 8, bottom: 2, containLabel: true }
    : { top: 80, left: '3%', right: '4%', bottom: '3%', containLabel: true }
}

const getYAxisLabel = (formatter: (value: number) => string) => ({
  formatter,
  margin: isMobileViewport() ? 2 : 8,
})

const getInsideDataZoom = (labelCount: number, visiblePoints: number) => {
  const baseOptions = {
    type: 'inside',
    xAxisIndex: 0,
    filterMode: 'none',
    zoomOnMouseWheel: false,
    moveOnMouseMove: true,
    moveOnMouseWheel: true,
    zoomLock: true,
    preventDefaultMouseMove: false,
  }

  if (labelCount > visiblePoints) {
    return [{ ...baseOptions, startValue: labelCount - visiblePoints, endValue: labelCount - 1 }]
  }

  return [{ ...baseOptions, start: 0, end: 100 }]
}

const applyChartDataZoom = (
  chartInstance: EChartsType | null,
  labelCount: number,
  visiblePoints: number,
) => {
  if (!chartInstance) return

  if (isMobileViewport()) {
    chartInstance.setOption(
      {
        dataZoom: getInsideDataZoom(labelCount, visiblePoints),
      },
      { replaceMerge: ['dataZoom'] },
    )
    return
  }

  chartInstance.setOption(
    {
      dataZoom: [],
    },
    { replaceMerge: ['dataZoom'] },
  )
}

const getLabelCountByChart = (chartInstance: EChartsType | null) => {
  const option = chartInstance?.getOption() as EChartsOption | undefined
  const xAxisOption = option?.xAxis
  const axis = Array.isArray(xAxisOption) ? xAxisOption[0] : xAxisOption
  const labels = (axis as { data?: unknown } | undefined)?.data
  return Array.isArray(labels) ? labels.length : 0
}

const syncChartViewportOptions = () => {
  speedChartInstance?.setOption({
    grid: getChartGrid('speed'),
    yAxis: {
      type: 'value',
      axisLabel: getYAxisLabel((value) => formatSpeed(value)),
    },
  })
  applyChartDataZoom(speedChartInstance, getLabelCountByChart(speedChartInstance), SPEED_MOBILE_VISIBLE_POINTS)

  trafficChartInstance?.setOption({
    grid: getChartGrid('traffic'),
    yAxis: {
      type: 'value',
      axisLabel: getYAxisLabel((value) => formatBytes(value)),
    },
  })
  applyChartDataZoom(
    trafficChartInstance,
    getLabelCountByChart(trafficChartInstance),
    TRAFFIC_MOBILE_VISIBLE_POINTS,
  )
}

// --- App Settings Fetching ---
const fetchAppSettings = async () => {
  try {
    const { data } = await axios.get<{ realtime_speed_enabled?: boolean }>('/api/settings')
    isRealtimeSpeedEnabled.value = data.realtime_speed_enabled === true
  } catch (caught: unknown) {
    console.error('获取应用设置失败:', caught)
    ElMessage.error('获取应用设置失败，部分功能可能不正常。')
    isRealtimeSpeedEnabled.value = false
  }
}

// --- ECharts Initialization ---
const initSpeedChart = () => {
  if (speedChart.value) {
    speedChartInstance = echarts.init(speedChart.value)
    speedChartInstance.setOption({
      tooltip: {
        trigger: 'axis',
        triggerOn: getTooltipTriggerOn(),
        position: (
          point: [number, number],
          _params: TooltipComponentPositionCallbackParams,
          _el: HTMLDivElement | null,
          _rect: unknown,
          size: { contentSize: [number, number]; viewSize: [number, number] },
        ) => {
          const tooltipWidth = size.contentSize[0]
          let newX = point[0] - tooltipWidth - 10
          if (newX < 0) {
            newX = point[0] + 20
          }
          return [newX, point[1] - 20]
        },
        formatter: (params: TooltipComponentFormatterCallbackParams) => {
          const list = Array.isArray(params) ? params : [params]
          if (list.length === 0) return ''
          const downloadersMap = new Map(speedChartDownloaders.value.map((d) => [d.id, d.name]))
          const axisValueLabel = String((list[0] as { axisValueLabel?: unknown }).axisValueLabel ?? '')
          let tooltipContent = `${axisValueLabel}<br/>`

          type TooltipSeriesEntry = { value: unknown; color: string }
          type TooltipByDownloader = Record<string, { 上传?: TooltipSeriesEntry; 下载?: TooltipSeriesEntry }>
          const dataByDownloaderId: TooltipByDownloader = {}

          list.forEach((param) => {
            const seriesName = String((param as { seriesName?: unknown }).seriesName ?? '')
            const isUpload = seriesName.includes('↑')
            const arrowIndex = isUpload ? seriesName.indexOf('↑') : seriesName.indexOf('↓')
            const baseName = seriesName.substring(0, seriesName.lastIndexOf(' ', arrowIndex)).trim()
            const downloader = speedChartDownloaders.value.find((d) => d.name === baseName)
            if (!downloader) return
            if (!dataByDownloaderId[downloader.id]) dataByDownloaderId[downloader.id] = {}
            const color =
              typeof (param as { color?: unknown }).color === 'string'
                ? ((param as { color?: unknown }).color as string)
                : String((param as { color?: unknown }).color ?? '')

            if (isUpload) {
              dataByDownloaderId[downloader.id]['上传'] = {
                value: (param as { value?: unknown }).value,
                color,
              }
            } else {
              dataByDownloaderId[downloader.id]['下载'] = {
                value: (param as { value?: unknown }).value,
                color,
              }
            }
          })
          for (const id in dataByDownloaderId) {
            const data = dataByDownloaderId[id]
            const name = downloadersMap.get(id) || '未知下载器'
            tooltipContent += `<div style="margin-top: 8px; font-weight: bold;">${name}</div>`
            if (data['上传'])
              tooltipContent += `<div><span style="display:inline-block;margin-right:5px;border-radius:10px;width:10px;height:10px;background-color:${data['上传'].color};"></span>上传: ${formatSpeed(data['上传'].value)}</div>`
            if (data['下载'])
              tooltipContent += `<div><span style="display:inline-block;margin-right:5px;border-radius:10px;width:10px;height:10px;background-color:${data['下载'].color};"></span>下载: ${formatSpeed(data['下载'].value)}</div>`
          }
          return tooltipContent
        },
      },
      xAxis: { type: 'category', data: [], boundaryGap: false },
      yAxis: { type: 'value', axisLabel: getYAxisLabel((value) => formatSpeed(value)) },
      series: [],
      grid: getChartGrid('speed'),
      legend: { show: false },
    })
    applyChartDataZoom(speedChartInstance, 0, SPEED_MOBILE_VISIBLE_POINTS)
    speedChartInstance.on('legendselectchanged', (params: unknown) => {
      const selected =
        isRecord(params) && isRecord(params.selected)
          ? (params.selected as Record<string, boolean>)
          : {}
      speedChartLegendItems.value = speedChartLegendItems.value.map((item) => ({
        ...item,
        disabled: selected[item.fullName] === false,
      }))
    })
    speedChartInstance.on('mouseover', () => (isMouseOverChart = true))
    speedChartInstance.on('mouseout', () => {
      isMouseOverChart = false
      lastTooltipDataIndex = null
    })
    speedChartInstance.on('mousemove', (params: unknown) => {
      if (isRecord(params) && typeof params.dataIndex === 'number') {
        lastTooltipDataIndex = params.dataIndex
      }
    })
  }
}

const initTrafficChart = () => {
  if (trafficChart.value) {
    trafficChartInstance = echarts.init(trafficChart.value)
    trafficChartInstance.setOption({
      tooltip: {
        trigger: 'axis',
        triggerOn: getTooltipTriggerOn(),
        axisPointer: { type: 'shadow' },
        formatter: (params: TooltipComponentFormatterCallbackParams) => {
          const list = Array.isArray(params) ? params : [params]
          if (list.length === 0) return ''
          const axisValueLabel = String((list[0] as { axisValueLabel?: unknown }).axisValueLabel ?? '')
          let content = `${axisValueLabel}<br/>`

          type TrafficSeriesEntry = { value: unknown; marker: string }
          type TrafficByDownloaderName = Record<string, { 上传?: TrafficSeriesEntry; 下载?: TrafficSeriesEntry }>
          const dataByDownloaderName: TrafficByDownloaderName = {}

          list.forEach((param) => {
            const seriesName = String((param as { seriesName?: unknown }).seriesName ?? '')
            const baseName = seriesName.split(' - ')[0]

            if (!dataByDownloaderName[baseName]) {
              dataByDownloaderName[baseName] = {}
            }

            if (seriesName.includes('上传量')) {
              dataByDownloaderName[baseName]['上传'] = {
                value: (param as { value?: unknown }).value,
                marker: String((param as { marker?: unknown }).marker ?? ''),
              }
            } else if (seriesName.includes('下载量')) {
              dataByDownloaderName[baseName]['下载'] = {
                value: (param as { value?: unknown }).value,
                marker: String((param as { marker?: unknown }).marker ?? ''),
              }
            }
          })

          for (const name in dataByDownloaderName) {
            const data = dataByDownloaderName[name]
            content += `<div style="margin-top: 8px; font-weight: bold;">${name}</div>`
            if (data['上传'])
              content += `${data['上传'].marker} 上传: ${formatBytes(data['上传'].value)}<br/>`
            if (data['下载'])
              content += `${data['下载'].marker} 下载: ${formatBytes(data['下载'].value)}<br/>`
          }
          return content
        },
      },
      xAxis: { type: 'category', data: [] },
      yAxis: { type: 'value', axisLabel: getYAxisLabel((value) => formatBytes(value)) },
      series: [],
      grid: getChartGrid('traffic'),
      legend: { show: false, type: 'scroll', top: 'top' },
    })
    applyChartDataZoom(trafficChartInstance, 0, TRAFFIC_MOBILE_VISIBLE_POINTS)

    trafficChartInstance.on('legendselectchanged', (params: unknown) => {
      const selected =
        isRecord(params) && isRecord(params.selected)
          ? (params.selected as Record<string, boolean>)
          : {}
      trafficChartLegendItems.value = trafficChartLegendItems.value.map((item) => ({
        ...item,
        disabled: selected[item.name] === false,
      }))
    })
  }
}

// --- Data Fetching ---
type SpeedApiSpeedEntry = { ul_speed?: number; dl_speed?: number }
type SpeedApiDataPoint = { speeds: Record<string, SpeedApiSpeedEntry | undefined> }
type SpeedApiResponse = {
  labels: string[]
  datasets: SpeedApiDataPoint[]
  downloaders: DownloaderMeta[]
}

type TrafficApiDatasetEntry = { uploaded: number[]; downloaded: number[] }
type TrafficApiResponse = {
  labels: string[]
  datasets: Record<string, TrafficApiDatasetEntry | undefined>
  downloaders: DownloaderMeta[]
}

type SpeedLineSeriesOption = {
  name: string
  type: 'line'
  smooth: boolean
  showSymbol: boolean
  data: number[]
  color: string
}

type TrafficBarSeriesOption = {
  name: string
  type: 'bar'
  stack: 'upload' | 'download'
  emphasis: { focus: 'series' }
  data: number[]
  color: string
}

type TrafficLabelFormatterParam = { dataIndex: number }

type TrafficLabelSeriesOption = {
  name: string
  type: 'bar'
  stack: 'upload' | 'download'
  data: number[]
  itemStyle: { borderColor: string; color: string }
  emphasis: { itemStyle: { borderColor: string; color: string } }
  tooltip: { show: boolean }
  label: {
    show: boolean
    position: 'top'
    formatter: (p: TrafficLabelFormatterParam) => string
    color: string
    fontSize: number
    fontWeight: 'normal'
  }
}

type TrafficSeriesOption = TrafficBarSeriesOption | TrafficLabelSeriesOption

const fetchSpeedData = async (mode: SpeedDisplayMode, isPeriodicUpdate: boolean = false) => {
  if (!speedChartInstance) return
  if (!isPeriodicUpdate) speedChartInstance.showLoading()
  try {
    const endpoint = mode === 'last_1_min' ? '/api/recent_speed_data' : '/api/speed_chart_data'
    const params = mode === 'last_1_min' ? { seconds: 60 } : { range: mode }
    const { data } = await axios.get<SpeedApiResponse>(endpoint, { params })

    speedChartDownloaders.value = Array.isArray(data.downloaders) ? data.downloaders : []
    const series: SpeedLineSeriesOption[] = []
    const newLegendItems: SpeedLegendItem[] = []
    const uploadColors = ['#F56C6C', '#E6A23C', '#D98A6F', '#FAB6B6', '#F7D0A3']
    const downloadColors = ['#409EFF', '#67C23A', '#8A2BE2', '#A0CFFF', '#B3E19D']
    const lastDataPoint = data.datasets.length > 0 ? data.datasets[data.datasets.length - 1] : null

    const allUploadData: number[] = []
    const allDownloadData: number[] = []

    speedChartDownloaders.value.forEach((downloader, index) => {
      const currentSpeeds = lastDataPoint?.speeds?.[downloader.id]
      const ulSpeed = typeof currentSpeeds?.ul_speed === 'number' ? currentSpeeds.ul_speed : 0
      const dlSpeed = typeof currentSpeeds?.dl_speed === 'number' ? currentSpeeds.dl_speed : 0

      const ulSpeedText = formatSpeed(ulSpeed)
      const uploadLegendFullName = `${downloader.name} ↑ ${ulSpeedText}`
      newLegendItems.push({
        fullName: uploadLegendFullName,
        baseName: downloader.name,
        arrow: '↑',
        speed: ulSpeedText,
        color: uploadColors[index % uploadColors.length],
        disabled: false,
      })

      const uploadData = data.datasets.map(
        (point) => point.speeds[downloader.id]?.ul_speed ?? 0,
      )
      allUploadData.push(...uploadData)

      series.push({
        name: uploadLegendFullName,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: uploadData,
        color: uploadColors[index % uploadColors.length],
      })

      const dlSpeedText = formatSpeed(dlSpeed)
      const downloadLegendFullName = `${downloader.name} ↓ ${dlSpeedText}`
      newLegendItems.push({
        fullName: downloadLegendFullName,
        baseName: downloader.name,
        arrow: '↓',
        speed: dlSpeedText,
        color: downloadColors[index % downloadColors.length],
        disabled: false,
      })

      const downloadData = data.datasets.map(
        (point) => point.speeds[downloader.id]?.dl_speed ?? 0,
      )
      allDownloadData.push(...downloadData)

      series.push({
        name: downloadLegendFullName,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: downloadData,
        color: downloadColors[index % downloadColors.length],
      })
    })

    const maxOf = (values: number[]) => (values.length ? Math.max(...values) : 0)
    const uploadMax = maxOf(allUploadData)
    const downloadMax = maxOf(allDownloadData)

    let yAxisMax =
      speedChartVisibilityMode.value === 'upload'
        ? uploadMax
        : speedChartVisibilityMode.value === 'download'
          ? downloadMax
          : Math.max(uploadMax, downloadMax)

    if (yAxisMax <= 0) {
      yAxisMax = 1024
    }

    yAxisMax *= 1.2

    const oldSelectedState = speedChartLegendItems.value.reduce<Record<string, boolean>>((acc, item) => {
      if (item.disabled) acc[`${item.baseName} ${item.arrow}`] = true
      return acc
    }, {})
    newLegendItems.forEach((item) => {
      if (oldSelectedState[`${item.baseName} ${item.arrow}`]) item.disabled = true
    })
    speedChartLegendItems.value = newLegendItems

    const currentSelected = getLegendSelectedMap(speedChartInstance)
    newLegendItems.forEach((item) => {
      currentSelected[item.fullName] = item.disabled !== true
    })

    speedChartInstance.setOption({
      xAxis: { data: data.labels },
      yAxis: {
        type: 'value',
        axisLabel: getYAxisLabel((value) => formatSpeed(value)),
        max: yAxisMax,
      },
      series: series,
      grid: getChartGrid('speed'),
      legend: {
        show: false,
        data: newLegendItems.map((i) => i.fullName),
        selected: currentSelected,
      },
    })
    applyChartDataZoom(speedChartInstance, data.labels.length, SPEED_MOBILE_VISIBLE_POINTS)

    changeSpeedVisibility(speedChartVisibilityMode.value, true)
    if (!isPeriodicUpdate) {
      nextTick(() => {
        speedChartInstance?.resize()
      })
    }

    if (isPeriodicUpdate && isMouseOverChart && lastTooltipDataIndex !== null) {
      speedChartInstance.dispatchAction({
        type: 'showTip',
        seriesIndex: 0,
        dataIndex: lastTooltipDataIndex,
      })
    }
  } catch (caught: unknown) {
    console.error('获取速率数据失败:', caught)
  } finally {
    if (!isPeriodicUpdate) speedChartInstance.hideLoading()
  }
}

const fetchTrafficData = async (range: TrafficDisplayMode) => {
  if (!trafficChartInstance) return
  trafficChartInstance.showLoading()
  try {
    const { data } = await axios.get<TrafficApiResponse>('/api/chart_data', { params: { range } })

    const { labels, datasets, downloaders } = data
    const series: TrafficSeriesOption[] = []
    const legendData: string[] = []
    const newTrafficLegendItems: TrafficLegendItem[] = []
    const uploadColors = ['#F56C6C', '#E6A23C', '#D98A6F', '#FAB6B6', '#F7D0A3']
    const downloadColors = ['#409EFF', '#67C23A', '#8A2BE2', '#A0CFFF', '#B3E19D']

    // 1. [保持不变] 创建用于存储每项总和的数组
    const uploadTotals = Array.from({ length: labels.length }, () => 0)
    const downloadTotals = Array.from({ length: labels.length }, () => 0)

    // 2. [保持不变] 遍历下载器，创建真实的柱状图系列，并累计总和
    downloaders.forEach((downloader, index) => {
      const downloaderData = datasets[downloader.id]
      if (!downloaderData) return

      const totalUpload = downloaderData.uploaded.reduce((acc, val) => acc + val, 0)
      const formattedTotalUpload = formatBytes(totalUpload)
      const uploadSeriesName = `${downloader.name} - 上传量 (${formattedTotalUpload})`

      const totalDownload = downloaderData.downloaded.reduce((acc, val) => acc + val, 0)
      const formattedTotalDownload = formatBytes(totalDownload)
      const downloadSeriesName = `${downloader.name} - 下载量 (${formattedTotalDownload})`

      // 累计到总和数组中
      downloaderData.uploaded.forEach((value, i) => {
        uploadTotals[i] += value
      })
      downloaderData.downloaded.forEach((value, i) => {
        downloadTotals[i] += value
      })

      // 添加上传系列
      legendData.push(uploadSeriesName)
      newTrafficLegendItems.push({
        name: uploadSeriesName,
        color: uploadColors[index % uploadColors.length],
        disabled: false,
      })
      series.push({
        name: uploadSeriesName,
        type: 'bar',
        stack: 'upload', // 放入 'upload' 堆叠组
        emphasis: { focus: 'series' },
        data: downloaderData.uploaded,
        color: uploadColors[index % uploadColors.length],
      })

      // 添加下载系列
      legendData.push(downloadSeriesName)
      newTrafficLegendItems.push({
        name: downloadSeriesName,
        color: downloadColors[index % downloadColors.length],
        disabled: false,
      })
      series.push({
        name: downloadSeriesName,
        type: 'bar',
        stack: 'download', // 放入 'download' 堆叠组
        emphasis: { focus: 'series' },
        data: downloaderData.downloaded,
        color: downloadColors[index % downloadColors.length],
      })
    })

    // 3. [核心修正] 添加用于显示“上传总量”的透明系列
    series.push({
      name: '上传总量标签', // 给予一个不重复的名字
      type: 'bar',
      stack: 'upload', // 和上传系列在同一个stack
      data: Array.from({ length: labels.length }, () => 0), // **关键：数据必须是0，因为它只占位，不增加高度**
      itemStyle: {
        borderColor: 'transparent',
        color: 'transparent'
      },
      emphasis: {
        itemStyle: {
          borderColor: 'transparent',
          color: 'transparent'
        }
      },
      tooltip: {
        show: false // 不在tooltip中显示
      },
      label: {
        show: true,
        position: 'top', // 显示在堆叠柱的顶部
        formatter: (p: TrafficLabelFormatterParam) => {
          // **关键：从预先计算好的 totals 数组中根据索引获取值**
          const total = uploadTotals[p.dataIndex] ?? 0
          return total > 0 ? formatBytes(total) : '' // 仅当总和大于0时显示标签
        },
        color: '#333',
        fontSize: 10,
        fontWeight: 'normal', // 修改为 normal，不那么粗壮
      }
    })

    // 4. [核心修正] 添加用于显示“下载总量”的透明系列
    series.push({
      name: '下载总量标签', // 给予一个不重复的名字
      type: 'bar',
      stack: 'download', // 和下载系列在同一个stack
      data: Array.from({ length: labels.length }, () => 0), // **关键：数据必须是0**
      itemStyle: {
        borderColor: 'transparent',
        color: 'transparent'
      },
      emphasis: {
        itemStyle: {
          borderColor: 'transparent',
          color: 'transparent'
        }
      },
      tooltip: {
        show: false
      },
      label: {
        show: true,
        position: 'top',
        formatter: (p: TrafficLabelFormatterParam) => {
          // **关键：从预先计算好的 totals 数组中根据索引获取值**
          const total = downloadTotals[p.dataIndex] ?? 0
          return total > 0 ? formatBytes(total) : ''
        },
        color: '#333',
        fontSize: 10,
        fontWeight: 'normal', // 修改为 normal，不那么粗壮
      }
    })

    const currentSelected = getLegendSelectedMap(trafficChartInstance)
    legendData.forEach((name) => {
      if (typeof currentSelected[name] !== 'boolean') {
        currentSelected[name] = true
      }
    })

    trafficChartInstance.setOption({
      xAxis: { data: labels },
      yAxis: {
        type: 'value',
        axisLabel: getYAxisLabel((value) => formatBytes(value)),
      },
      series: series,
      grid: getChartGrid('traffic'),
      legend: { show: false, data: legendData, top: 'top', selected: currentSelected },
    })
    applyChartDataZoom(trafficChartInstance, labels.length, TRAFFIC_MOBILE_VISIBLE_POINTS)

    trafficChartLegendItems.value = newTrafficLegendItems.map((item) => ({
      ...item,
      disabled: currentSelected[item.name] === false,
    }))

    changeTrafficVisibility(trafficChartVisibilityMode.value, true)
    nextTick(() => {
      trafficChartInstance?.resize()
    })
  } catch (caught: unknown) {
    console.error('获取数据量数据失败:', caught)
  } finally {
    trafficChartInstance.hideLoading()
  }
}


// --- Event Handlers ---
const changeSpeedMode = (mode: SpeedDisplayMode) => {
  if (speedUpdateTimer) {
    clearInterval(speedUpdateTimer)
    speedUpdateTimer = null
  }
  speedDisplayMode.value = mode
  fetchSpeedData(mode)

  if (mode === 'last_1_min' && isRealtimeSpeedEnabled.value) {
    speedUpdateTimer = setInterval(() => {
      fetchSpeedData(mode, true)
    }, 1000)
  }
}
const changeTrafficMode = (range: TrafficDisplayMode) => {
  trafficDisplayMode.value = range
  fetchTrafficData(range)
}
const toggleSeries = (name: string) => {
  if (speedChartInstance) {
    speedChartInstance.dispatchAction({ type: 'legendToggleSelect', name })
  }
}

const toggleTrafficSeries = (name: string) => {
  if (!trafficChartInstance) return
  trafficChartInstance.dispatchAction({ type: 'legendToggleSelect', name })
  const selected = getLegendSelectedMap(trafficChartInstance)
  trafficChartLegendItems.value = trafficChartLegendItems.value.map((item) => ({
    ...item,
    disabled: selected[item.name] === false,
  }))
}

const changeSpeedVisibility = (mode: VisibilityMode, isInternalCall = false) => {
  if (!isInternalCall) speedChartVisibilityMode.value = mode
  if (!speedChartInstance || !speedChartLegendItems.value.length) return
  const selected: Record<string, boolean> = {}
  speedChartLegendItems.value.forEach((item) => {
    if (mode === 'all') selected[item.fullName] = true
    else if (mode === 'upload') selected[item.fullName] = item.arrow === '↑'
    else if (mode === 'download') selected[item.fullName] = item.arrow === '↓'
  })
  speedChartInstance.setOption({ legend: { selected: selected } })
}
const changeTrafficVisibility = (mode: VisibilityMode, isInternalCall = false) => {
  if (!isInternalCall) trafficChartVisibilityMode.value = mode
  if (!trafficChartInstance) return

  const legendData = getLegendData(trafficChartInstance)
  if (!legendData.length) return
  const selected: Record<string, boolean> = {}

  legendData.forEach((name) => {
    if (mode === 'all') {
      selected[name] = true
    } else if (mode === 'upload') {
      selected[name] = name.includes('上传量')
    } else if (mode === 'download') {
      selected[name] = name.includes('下载量')
    }
  })

  trafficChartInstance.setOption({ legend: { selected: selected } })
  trafficChartLegendItems.value = trafficChartLegendItems.value.map((item) => ({
    ...item,
    disabled: selected[item.name] === false,
  }))
}

const handleWindowResize = () => {
  const tooltipTriggerOn = getTooltipTriggerOn()

  speedChartInstance?.setOption({
    tooltip: { triggerOn: tooltipTriggerOn },
  })
  trafficChartInstance?.setOption({
    tooltip: { triggerOn: tooltipTriggerOn },
  })

  syncChartViewportOptions()

  speedChartInstance?.resize()
  trafficChartInstance?.resize()
}

// --- Lifecycle ---
onMounted(async () => {
  areSettingsLoading.value = true
  await fetchAppSettings()

  if (!isRealtimeSpeedEnabled.value && speedDisplayMode.value === 'last_1_min') {
    speedDisplayMode.value = 'today'
  }

  await nextTick()

  initSpeedChart()
  initTrafficChart()
  changeSpeedMode(speedDisplayMode.value)
  changeTrafficMode(trafficDisplayMode.value)
  window.addEventListener('resize', handleWindowResize)

  areSettingsLoading.value = false
})

onUnmounted(() => {
  if (speedUpdateTimer) {
    clearInterval(speedUpdateTimer)
  }
  window.removeEventListener('resize', handleWindowResize)
})
</script>

<style scoped>
.info-view-container {
  height: 100%;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  box-sizing: border-box;
}

.chart-card {
  /* 背景样式已移至 glass-morphism.css (使用 glass-card 和 glass-rounded 类) */
  padding: 16px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
  /* 默认z-index，让所有卡片在同一层级 */
  z-index: 1; 
}

/* [核心修改] 移除 :first-child 规则，并添加 :hover 规则 */
/* 当鼠标悬浮在任意图表卡片上时，都将其 z-index 提升到最高 */
.chart-card:hover {
  z-index: 10;
}

.chart-body {
  flex: 1;
  width: 100%;
  height: 100%;
  min-height: 0;
}

.chart-scroll-container {
  flex: 1;
  min-height: 0;
  width: 100%;
  overflow: hidden;
  display: flex;
}

.chart-body-inner {
  flex: 1;
  width: 100%;
  min-height: 0;
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.header-left-controls,
.header-right-controls {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-left-controls {
  justify-content: flex-start;
}

.header-right-controls {
  justify-content: flex-end;
}

.chart-title {
  flex-shrink: 0;
  font-size: 16px;
  font-weight: bold;
  color: #333;
  text-align: center;
}

.button-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.button-group button {
  padding: 6px 12px;
  border: 1px solid #ccc;
  background-color: #f7f7f7;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition:
    background-color 0.2s,
    color 0.2s,
    border-color 0.2s;
}

.button-group button:hover {
  background-color: #e9e9e9;
  border-color: #bbb;
}

.button-group button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.button-group button.active {
  background-color: #007bff;
  color: white;
  border-color: #007bff;
}

/* [新增] 禁用按钮提示的包裹层样式 */
.button-wrapper {
  display: inline-block;
}

.custom-legend-container {
  position: absolute;
  top: 55px;
  left: 16px;
  right: 16px;
  z-index: 10;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px 16px;
}

.legend-item {
  display: flex;
  align-items: center;
  cursor: pointer;
  font-size: 13px;
  transition: opacity 0.2s;
}

.legend-item.disabled {
  opacity: 0.5;
  text-decoration: line-through;
}

.legend-color-box {
  width: 25px;
  height: 14px;
  margin-right: 8px;
  border-radius: 3px;
  flex-shrink: 0;
}

.legend-item-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 50px;
  max-width: 150px;
  overflow: hidden;
}

.legend-base-name {
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-right: 4px;
  flex: 1 1 auto;
  min-width: 0;
}

.legend-speed-info {
  color: #666;
  white-space: nowrap;
  flex-shrink: 0;
  width: 75px;
  text-align: right;
}

.legend-item.disabled .legend-base-name,
.legend-item.disabled .legend-speed-info {
  color: #999;
}

.traffic-legend-container {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px 14px;
}

.traffic-legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #333;
  min-width: 0;
  max-width: 280px;
}

.traffic-legend-item.disabled {
  opacity: 0.5;
  text-decoration: line-through;
}

.traffic-legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  flex-shrink: 0;
}

.traffic-legend-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 768px) {
  .info-view-container {
    padding: 8px;
    gap: 10px;
    overflow-x: hidden;
  }

  .chart-card {
    padding: 10px 8px;
    flex: none;
  }

  .chart-header {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }

  .header-left-controls {
    order: 2;
    flex: 1;
    min-width: 0;
    width: auto;
    justify-content: flex-start;
    gap: 6px;
  }

  .header-right-controls {
    order: 3;
    flex: 0 0 auto;
    width: auto;
    justify-content: flex-end;
    gap: 6px;
  }

  .chart-title {
    order: 1;
    width: 100%;
    font-size: 14px;
    text-align: left;
  }

  .button-group {
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }

  .button-group::-webkit-scrollbar {
    display: none;
  }

  .date-range-group {
    width: 100%;
    overflow-x: auto;
    overflow-y: hidden;
    flex-wrap: nowrap;
    padding-bottom: 2px;
    touch-action: pan-x;
  }

  .visibility-group {
    width: auto;
    overflow: visible;
    flex-wrap: nowrap;
    gap: 6px;
    padding-bottom: 0;
  }

  .button-group button {
    flex-shrink: 0;
    padding: 6px 10px;
    font-size: 12px;
    white-space: nowrap;
  }

  .visibility-group button {
    padding: 6px 8px;
  }

  .button-wrapper {
    flex-shrink: 0;
  }

  .custom-legend-container {
    position: static;
    margin-top: 2px;
    justify-content: flex-start;
    gap: 6px 10px;
    overflow-x: auto;
    overflow-y: hidden;
    flex-wrap: nowrap;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }

  .custom-legend-container::-webkit-scrollbar {
    display: none;
  }

  .legend-item {
    max-width: none;
    flex-shrink: 0;
  }

  .legend-item-content {
    max-width: 190px;
  }

  .legend-speed-info {
    width: auto;
    min-width: 58px;
    margin-left: 6px;
  }

  .traffic-legend-container {
    margin-top: 6px;
    overflow-x: auto;
    overflow-y: hidden;
    flex-wrap: nowrap;
    justify-content: flex-start;
    gap: 8px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    touch-action: pan-x;
  }

  .traffic-legend-container::-webkit-scrollbar {
    display: none;
  }

  .traffic-legend-item {
    flex-shrink: 0;
    max-width: none;
  }

  .chart-body,
  .chart-body-inner {
    min-height: 300px;
  }
}
</style>
