<template>
  <div class="info-view-container">
    <!-- 速率图表 -->
    <div class="chart-card">
      <div class="chart-header">
        <div class="button-group">
          <button
            @click="changeSpeedMode('last_1_min')"
            :class="{ active: speedDisplayMode === 'last_1_min' }"
          >
            近1分钟
          </button>
          <button
            @click="changeSpeedMode('last_12_hours')"
            :class="{ active: speedDisplayMode === 'last_12_hours' }"
          >
            近12小时
          </button>
          <button
            @click="changeSpeedMode('last_24_hours')"
            :class="{ active: speedDisplayMode === 'last_24_hours' }"
          >
            近24小时
          </button>
          <button
            @click="changeSpeedMode('today')"
            :class="{ active: speedDisplayMode === 'today' }"
          >
            今日
          </button>
          <button
            @click="changeSpeedMode('yesterday')"
            :class="{ active: speedDisplayMode === 'yesterday' }"
          >
            昨日
          </button>
        </div>
        <div class="chart-title">速率 {{ speedDisplayModeButtonText }}</div>
      </div>

      <!-- 自定义的可换行图例容器 -->
      <div class="custom-legend-container">
        <span
          v-for="item in speedChartLegendItems"
          :key="item.name"
          class="legend-item"
          :class="{ disabled: item.disabled }"
          @click="toggleSeries(item.name)"
        >
          <span class="legend-color-box" :style="{ backgroundColor: item.color }"></span>
          <span class="legend-text">{{ item.name }}</span>
        </span>
      </div>

      <div ref="speedChart" class="chart-body"></div>
    </div>

    <!-- 数据量图表 -->
    <div class="chart-card">
      <div class="chart-header">
        <div class="button-group">
          <button
            @click="changeTrafficMode('today')"
            :class="{ active: trafficDisplayMode === 'today' }"
          >
            今日
          </button>
          <button
            @click="changeTrafficMode('yesterday')"
            :class="{ active: trafficDisplayMode === 'yesterday' }"
          >
            昨日
          </button>
          <button
            @click="changeTrafficMode('this_week')"
            :class="{ active: trafficDisplayMode === 'this_week' }"
          >
            本周
          </button>
          <button
            @click="changeTrafficMode('last_week')"
            :class="{ active: trafficDisplayMode === 'last_week' }"
          >
            上周
          </button>
          <button
            @click="changeTrafficMode('this_month')"
            :class="{ active: trafficDisplayMode === 'this_month' }"
          >
            本月
          </button>
          <button
            @click="changeTrafficMode('last_month')"
            :class="{ active: trafficDisplayMode === 'last_month' }"
          >
            上月
          </button>
          <button
            @click="changeTrafficMode('last_6_months')"
            :class="{ active: trafficDisplayMode === 'last_6_months' }"
          >
            近半年
          </button>
          <button
            @click="changeTrafficMode('this_year')"
            :class="{ active: trafficDisplayMode === 'this_year' }"
          >
            今年
          </button>
          <button
            @click="changeTrafficMode('all')"
            :class="{ active: trafficDisplayMode === 'all' }"
          >
            全部
          </button>
        </div>
        <div class="chart-title">数据量 {{ trafficDisplayModeButtonText }}</div>
      </div>
      <div ref="trafficChart" class="chart-body"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import * as echarts from 'echarts'
import axios from 'axios'

// --- Refs and State ---
const speedChart = ref(null)
const trafficChart = ref(null)
let speedChartInstance = null
let trafficChartInstance = null
let speedUpdateTimer = null
let isMouseOverChart = false
let lastTooltipDataIndex = null

const speedDisplayMode = ref('last_1_min')
const trafficDisplayMode = ref('today')

const speedChartDownloaders = ref([])
const speedChartLegendItems = ref([])

const displayModeTextMap = {
  last_1_min: '近1分钟',
  last_12_hours: '近12小时',
  last_24_hours: '近24小时',
  today: '今日',
  yesterday: '昨日',
  this_week: '本周',
  last_week: '上周',
  this_month: '本月',
  last_month: '上月',
  last_6_months: '近半年',
  this_year: '今年',
  all: '全部',
}

const speedDisplayModeButtonText = computed(() => `(${displayModeTextMap[speedDisplayMode.value]})`)
const trafficDisplayModeButtonText = computed(
  () => `(${displayModeTextMap[trafficDisplayMode.value]})`,
)

// --- Helper Functions ---
const formatBytes = (b) => {
  if (b === null || b === undefined || isNaN(b) || b < 0) return '0 B'
  if (b === 0) return '0 B'
  const s = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(b) / Math.log(1024))
  return `${parseFloat((b / Math.pow(1024, i)).toFixed(2))} ${s[i]}`
}
const formatSpeed = (speed) => formatBytes(speed) + '/s'

// --- ECharts Initialization ---
const initSpeedChart = () => {
  if (speedChart.value) {
    speedChartInstance = echarts.init(speedChart.value)
    speedChartInstance.setOption({
      tooltip: {
        trigger: 'axis',
        position: function (point, params, dom, rect, size) {
          const chartWidth = size.viewSize[0]
          const tooltipWidth = size.contentSize[0]
          let newX = point[0] - tooltipWidth - 10
          if (newX < 0) {
            newX = point[0] + 20
          }
          return [newX, point[1] - 20]
        },
        formatter: (params) => {
          if (!params || params.length === 0) return ''

          const downloadersMap = new Map(speedChartDownloaders.value.map((d) => [d.id, d.name]))
          let tooltipContent = `${params[0].axisValueLabel}<br/>`
          const dataByDownloaderId = {}

          params.forEach((param) => {
            const { seriesIndex } = param
            const series = speedChartInstance.getOption().series[seriesIndex]

            const seriesName = series.name
            const isUpload = seriesName.includes('↑')
            const isDownload = seriesName.includes('↓')
            if (!isUpload && !isDownload) return

            const arrowIndex = isUpload ? seriesName.indexOf('↑') : seriesName.indexOf('↓')
            const baseName = seriesName.substring(0, arrowIndex).trim()

            const downloader = speedChartDownloaders.value.find((d) => d.name === baseName)
            if (!downloader) return

            const downloaderId = downloader.id
            if (!dataByDownloaderId[downloaderId]) {
              dataByDownloaderId[downloaderId] = {}
            }

            if (isUpload) {
              dataByDownloaderId[downloaderId]['上传'] = {
                value: param.value,
                color: param.color,
              }
            } else if (isDownload) {
              dataByDownloaderId[downloaderId]['下载'] = {
                value: param.value,
                color: param.color,
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
      yAxis: { type: 'value', axisLabel: { formatter: (value) => formatSpeed(value) } },
      series: [],
      grid: {
        top: 85,
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true,
      },
      legend: { show: false },
      dataZoom: [{ type: 'inside' }],
    })

    speedChartInstance.on('legendselectchanged', (params) => {
      const selected = params.selected
      speedChartLegendItems.value = speedChartLegendItems.value.map((item) => ({
        ...item,
        disabled: !selected[item.name],
      }))
    })
    speedChartInstance.on('mouseover', () => {
      isMouseOverChart = true
    })
    speedChartInstance.on('mouseout', () => {
      isMouseOverChart = false
      lastTooltipDataIndex = null
    })
    speedChartInstance.on('mousemove', (params) => {
      if (params.dataIndex !== undefined) {
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
        formatter: (params) => {
          if (!params || params.length === 0) return ''
          let tooltipContent = `${params[0].axisValueLabel}<br/>`
          let total = 0
          params.forEach((param) => {
            const value = param.value || 0
            total += value
            // 提示框内依然显示完整的 series.name，例如 "上传量 (12.5 GB)"
            tooltipContent += `<div><span style="display:inline-block;margin-right:5px;border-radius:10px;width:10px;height:10px;background-color:${param.color};"></span>${param.seriesName}: ${formatBytes(value)}</div>`
          })
          tooltipContent += `<div style="margin-top: 8px; font-weight: bold;">总计: ${formatBytes(total)}</div>`
          return tooltipContent
        },
      },
      xAxis: { type: 'category', data: [] },
      yAxis: { type: 'value', axisLabel: { formatter: (value) => formatBytes(value) } },
      series: [
        {
          name: '上传量',
          type: 'bar',
          emphasis: { focus: 'series' },
          data: [],
          label: {
            show: true,
            position: 'top',
            formatter: (params) => (params.value > 0 ? formatBytes(params.value) : ''),
            color: '#464646',
            fontSize: 10,
          },
        },
        {
          name: '下载量',
          type: 'bar',
          emphasis: { focus: 'series' },
          data: [],
          label: {
            show: true,
            position: 'top',
            formatter: (params) => (params.value > 0 ? formatBytes(params.value) : ''),
            color: '#464646',
            fontSize: 10,
          },
        },
      ],
      grid: {
        top: 60,
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true,
      },
      legend: { data: ['上传量', '下载量'], top: 'top' },
      dataZoom: [{ type: 'inside' }],
    })
  }
}

// --- Data Fetching ---
const fetchSpeedData = async (mode, isPeriodicUpdate = false) => {
  if (!speedChartInstance) return
  if (!isPeriodicUpdate) speedChartInstance.showLoading()
  try {
    const endpoint = mode === 'last_1_min' ? '/api/recent_speed_data' : '/api/speed_chart_data'
    const params = mode === 'last_1_min' ? { seconds: 60 } : { range: mode }
    const { data } = await axios.get(endpoint, { params })
    speedChartDownloaders.value = data.downloaders || []
    const labels = data.labels || []
    const datasets = data.datasets || []
    const series = []
    const newLegendItems = []
    const uploadColors = ['#F56C6C', '#E6A23C', '#D98A6F', '#FAB6B6', '#F7D0A3']
    const downloadColors = ['#409EFF', '#67C23A', '#8A2BE2', '#A0CFFF', '#B3E19D']
    const lastDataPoint =
      mode === 'last_1_min' && datasets.length > 0 ? datasets[datasets.length - 1] : null
    speedChartDownloaders.value.forEach((downloader, index) => {
      const baseName = downloader.name
      let uploadLegendName = `${baseName} ↑`
      let downloadLegendName = `${baseName} ↓`
      if (lastDataPoint && lastDataPoint.speeds) {
        const currentSpeeds = lastDataPoint.speeds[downloader.id]
        if (currentSpeeds) {
          const ulSpeed = formatSpeed(currentSpeeds.ul_speed || 0)
          const dlSpeed = formatSpeed(currentSpeeds.dl_speed || 0)
          uploadLegendName = `${baseName} ↑ ${ulSpeed}`
          downloadLegendName = `${baseName} ↓ ${dlSpeed}`
        }
      }
      const uploadColor = uploadColors[index % uploadColors.length]
      const downloadColor = downloadColors[index % downloadColors.length]
      newLegendItems.push({ name: uploadLegendName, color: uploadColor, disabled: false })
      newLegendItems.push({ name: downloadLegendName, color: downloadColor, disabled: false })
      series.push({
        name: uploadLegendName,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: datasets.map((d) => d.speeds[downloader.id]?.ul_speed || 0),
        color: uploadColor,
      })
      series.push({
        name: downloadLegendName,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: datasets.map((d) => d.speeds[downloader.id]?.dl_speed || 0),
        color: downloadColor,
      })
    })
    speedChartLegendItems.value = newLegendItems
    speedChartInstance.setOption({
      xAxis: { data: labels },
      series: series,
    })
    if (isPeriodicUpdate && isMouseOverChart && lastTooltipDataIndex !== null) {
      speedChartInstance.dispatchAction({
        type: 'showTip',
        seriesIndex: 0,
        dataIndex: lastTooltipDataIndex,
      })
    }
  } catch (error) {
    console.error('获取速率数据失败:', error)
  } finally {
    if (!isPeriodicUpdate) speedChartInstance.hideLoading()
  }
}

const fetchTrafficData = async (range) => {
  if (!trafficChartInstance) return
  trafficChartInstance.showLoading()
  try {
    const { data } = await axios.get('/api/chart_data', { params: { range } })
    const labels = data.labels || []
    const datasets = data.datasets || []
    const uploadData = datasets.map((item) => item.uploaded)
    const downloadData = datasets.map((item) => item.downloaded)

    const totalUpload = uploadData.reduce((acc, val) => acc + val, 0)
    const totalDownload = downloadData.reduce((acc, val) => acc + val, 0)

    const uploadLegendName = `上传量 (${formatBytes(totalUpload)})`
    const downloadLegendName = `下载量 (${formatBytes(totalDownload)})`

    trafficChartInstance.setOption({
      xAxis: { data: labels },
      series: [
        {
          name: uploadLegendName,
          data: uploadData,
          type: 'bar',
          emphasis: { focus: 'series' },
          label: {
            show: true,
            position: 'top',
            formatter: (params) => (params.value > 0 ? formatBytes(params.value) : ''),
            color: '#464646',
            fontSize: 10,
          },
        },
        {
          name: downloadLegendName,
          data: downloadData,
          type: 'bar',
          emphasis: { focus: 'series' },
          label: {
            show: true,
            position: 'top',
            formatter: (params) => (params.value > 0 ? formatBytes(params.value) : ''),
            color: '#464646',
            fontSize: 10,
          },
        },
      ],
      legend: {
        data: [uploadLegendName, downloadLegendName],
        top: 'top',
      },
    })
  } catch (error) {
    console.error('获取数据量数据失败:', error)
  } finally {
    trafficChartInstance.hideLoading()
  }
}

// --- Event Handlers ---
const changeSpeedMode = (mode) => {
  if (speedUpdateTimer) {
    clearInterval(speedUpdateTimer)
    speedUpdateTimer = null
  }
  speedDisplayMode.value = mode
  fetchSpeedData(mode)
  if (mode === 'last_1_min') {
    speedUpdateTimer = setInterval(() => {
      fetchSpeedData(mode, true)
    }, 1000)
  }
}

const changeTrafficMode = (range) => {
  trafficDisplayMode.value = range
  fetchTrafficData(range)
}

const toggleSeries = (name) => {
  if (speedChartInstance) {
    speedChartInstance.dispatchAction({
      type: 'legendToggleSelect',
      name: name,
    })
  }
}

// --- Lifecycle ---
onMounted(() => {
  nextTick(() => {
    initSpeedChart()
    initTrafficChart()
    changeSpeedMode(speedDisplayMode.value)
    changeTrafficMode(trafficDisplayMode.value)
    window.addEventListener('resize', () => {
      speedChartInstance?.resize()
      trafficChartInstance?.resize()
    })
  })
})

onUnmounted(() => {
  if (speedUpdateTimer) {
    clearInterval(speedUpdateTimer)
  }
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
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  background-color: #fff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}

.chart-body {
  flex: 1;
  width: 100%;
  min-height: 0;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 20px;
}
.chart-title {
  font-size: 16px;
  font-weight: bold;
  color: #333;
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
.button-group button.active {
  background-color: #007bff;
  color: white;
  border-color: #007bff;
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
  transition: color 0.2s;
}
.legend-item.disabled .legend-text {
  color: #ccc;
  text-decoration: line-through;
}
.legend-item.disabled .legend-color-box {
  background-color: #ccc !important;
}
.legend-color-box {
  width: 25px;
  height: 14px;
  margin-right: 8px;
  border-radius: 3px;
}
.legend-text {
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 120px;
}
</style>
