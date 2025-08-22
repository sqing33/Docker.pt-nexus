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
      <div class="chart-summary">
        总上传: {{ totalChartUpload }} | 总下载: {{ totalChartDownload }}
      </div>
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

const totalChartUpload = ref('0 B')
const totalChartDownload = ref('0 B')
const speedChartDownloaders = ref([])

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

        // --- MODIFICATION START: 更新 Tooltip 逻辑以适应新的 Series 结构 ---
        formatter: (params) => {
          if (!params || params.length === 0) return ''

          // 创建一个从 downloaderId 到其名称的映射，方便查找
          const downloadersMap = new Map(speedChartDownloaders.value.map((d) => [d.id, d.name]))

          let tooltipContent = `${params[0].axisValueLabel}<br/>`
          const dataByDownloaderId = {}

          params.forEach((param) => {
            const { seriesIndex } = param
            const series = speedChartInstance.getOption().series[seriesIndex]
            const { downloaderId, dataType } = series // 使用我们附加的自定义属性

            if (!dataByDownloaderId[downloaderId]) {
              dataByDownloaderId[downloaderId] = {}
            }
            dataByDownloaderId[downloaderId][dataType] = {
              value: param.value,
              color: param.color,
            }
          })

          for (const id in dataByDownloaderId) {
            const data = dataByDownloaderId[id]
            const name = downloadersMap.get(id) || '未知下载器' // 通过ID查找名称
            tooltipContent += `<div style="margin-top: 8px; font-weight: bold;">${name}</div>`
            if (data.upload)
              tooltipContent += `<div><span style="display:inline-block;margin-right:5px;border-radius:10px;width:10px;height:10px;background-color:${data.upload.color};"></span>上传: ${formatSpeed(data.upload.value)}</div>`
            if (data.download)
              tooltipContent += `<div><span style="display:inline-block;margin-right:5px;border-radius:10px;width:10px;height:10px;background-color:${data.download.color};"></span>下载: ${formatSpeed(data.download.value)}</div>`
          }
          return tooltipContent
        },
        // --- MODIFICATION END ---
      },
      xAxis: { type: 'category', data: [], boundaryGap: false },
      yAxis: { type: 'value', axisLabel: { formatter: (value) => formatSpeed(value) } },
      series: [],
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      legend: { data: [], top: 'top' },
      dataZoom: [{ type: 'inside' }],
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
            formatter: (params) => {
              if (params.value > 0) {
                return formatBytes(params.value)
              }
              return ''
            },
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
            formatter: (params) => {
              if (params.value > 0) {
                return formatBytes(params.value)
              }
              return ''
            },
            color: '#464646',
            fontSize: 10,
          },
        },
      ],
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
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
    const legendData = []

    // --- MODIFICATION START: 定义颜色并为上传下载创建独立的图例 ---
    // 定义颜色方案，您可以根据喜好修改这些颜色
    const uploadColors = ['#F56C6C', '#E6A23C', '#D98A6F', '#FAB6B6', '#F7D0A3']
    const downloadColors = ['#409EFF', '#67C23A', '#8A2BE2', '#A0CFFF', '#B3E19D']

    const lastDataPoint =
      mode === 'last_1_min' && datasets.length > 0 ? datasets[datasets.length - 1] : null

    speedChartDownloaders.value.forEach((downloader, index) => {
      let baseName = downloader.name
      let uploadLegendName = `${baseName} - 上传`
      let downloadLegendName = `${baseName} - 下载`

      if (lastDataPoint && lastDataPoint.speeds) {
        const currentSpeeds = lastDataPoint.speeds[downloader.id]
        if (currentSpeeds) {
          const ulSpeed = formatSpeed(currentSpeeds.ul_speed || 0)
          const dlSpeed = formatSpeed(currentSpeeds.dl_speed || 0)
          // 实时模式下，为图例添加速率信息
          uploadLegendName = `${baseName} - 上传 ↑ ${ulSpeed}`
          downloadLegendName = `${baseName} - 下载 ↓ ${dlSpeed}`
        }
      }

      legendData.push(uploadLegendName, downloadLegendName)

      // 上传 Series
      series.push({
        name: uploadLegendName,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: datasets.map((d) => d.speeds[downloader.id]?.ul_speed || 0),
        downloaderId: downloader.id,
        dataType: 'upload',
        // 分配颜色
        color: uploadColors[index % uploadColors.length],
      })

      // 下载 Series
      series.push({
        name: downloadLegendName,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: datasets.map((d) => d.speeds[downloader.id]?.dl_speed || 0),
        downloaderId: downloader.id,
        dataType: 'download',
        // 分配颜色
        color: downloadColors[index % downloadColors.length],
      })
    })
    // --- MODIFICATION END ---

    speedChartInstance.setOption({
      xAxis: { data: labels },
      series: series,
      legend: { data: legendData },
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
    trafficChartInstance.setOption({
      xAxis: { data: labels },
      series: [
        { name: '上传量', data: uploadData },
        { name: '下载量', data: downloadData },
      ],
    })
    const totalUpload = uploadData.reduce((acc, val) => acc + val, 0)
    const totalDownload = downloadData.reduce((acc, val) => acc + val, 0)
    totalChartUpload.value = formatBytes(totalUpload)
    totalChartDownload.value = formatBytes(totalDownload)
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
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.chart-card {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  background-color: #fff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
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
.chart-body {
  width: 100%;
  height: 350px;
}
.chart-summary {
  text-align: right;
  margin-top: 10px;
  font-size: 14px;
  color: #555;
  font-weight: bold;
}
</style>
