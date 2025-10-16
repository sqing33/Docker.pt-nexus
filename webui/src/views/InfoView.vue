<template>
  <div class="info-view-container" v-loading="areSettingsLoading">
    <!-- 速率图表 -->
    <div class="chart-card glass-card glass-rounded">
      <div class="chart-header">
        <!-- 左侧：时间段筛选 -->
        <div class="header-left-controls">
          <div class="button-group">
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
          <div class="button-group">
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

      <div ref="speedChart" class="chart-body"></div>
    </div>

    <!-- 数据量图表 -->
    <div class="chart-card glass-card glass-rounded">
      <div class="chart-header">
        <!-- 左侧：时间段筛选 -->
        <div class="header-left-controls">
          <div class="button-group">
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
          <div class="button-group">
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
      <div ref="trafficChart" class="chart-body"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import * as echarts from 'echarts'
import axios from 'axios'
import { ElMessage, ElTooltip } from 'element-plus'

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

const speedChartVisibilityMode = ref('all')
const trafficChartVisibilityMode = ref('all')

const speedChartDownloaders = ref([])
const speedChartLegendItems = ref([])

const isRealtimeSpeedEnabled = ref(true)
const areSettingsLoading = ref(true)

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

// --- App Settings Fetching ---
const fetchAppSettings = async () => {
  try {
    const { data } = await axios.get('/api/settings')
    isRealtimeSpeedEnabled.value = data.realtime_speed_enabled
  } catch (error) {
    console.error('获取应用设置失败:', error)
    ElMessage.error('获取应用设置失败，部分功能可能不正常。')
    isRealtimeSpeedEnabled.value = true
  }
}

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
            const series = speedChartInstance.getOption().series[param.seriesIndex]
            const seriesName = series.name
            const isUpload = seriesName.includes('↑')
            const arrowIndex = isUpload ? seriesName.indexOf('↑') : seriesName.indexOf('↓')
            const baseName = seriesName.substring(0, seriesName.lastIndexOf(' ', arrowIndex)).trim()
            const downloader = speedChartDownloaders.value.find((d) => d.name === baseName)
            if (!downloader) return
            if (!dataByDownloaderId[downloader.id]) dataByDownloaderId[downloader.id] = {}
            if (isUpload) {
              dataByDownloaderId[downloader.id]['上传'] = { value: param.value, color: param.color }
            } else {
              dataByDownloaderId[downloader.id]['下载'] = { value: param.value, color: param.color }
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
      grid: { top: 85, left: '3%', right: '4%', bottom: '3%', containLabel: true },
      legend: { show: false },
      dataZoom: [{ type: 'inside' }],
    })
    speedChartInstance.on('legendselectchanged', (params) => {
      const selected = params.selected
      speedChartLegendItems.value = speedChartLegendItems.value.map((item) => ({
        ...item,
        disabled: !selected[item.fullName],
      }))
    })
    speedChartInstance.on('mouseover', () => (isMouseOverChart = true))
    speedChartInstance.on('mouseout', () => {
      isMouseOverChart = false
      lastTooltipDataIndex = null
    })
    speedChartInstance.on('mousemove', (params) => {
      if (params.dataIndex !== undefined) lastTooltipDataIndex = params.dataIndex
    })
  }
}

const initTrafficChart = () => {
  if (trafficChart.value) {
    trafficChartInstance = echarts.init(trafficChart.value)
    trafficChartInstance.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params) => {
          if (!params || params.length === 0) return ''
          let content = `${params[0].axisValueLabel}<br/>`

          const dataByDownloaderName = {}

          params.forEach((param) => {
            const baseName = param.seriesName.split(' - ')[0]

            if (!dataByDownloaderName[baseName]) {
              dataByDownloaderName[baseName] = {}
            }

            if (param.seriesName.includes('上传量')) {
              dataByDownloaderName[baseName]['上传'] = {
                value: param.value,
                marker: param.marker,
              }
            } else if (param.seriesName.includes('下载量')) {
              dataByDownloaderName[baseName]['下载'] = {
                value: param.value,
                marker: param.marker,
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
      yAxis: { type: 'value', axisLabel: { formatter: (value) => formatBytes(value) } },
      series: [],
      grid: { top: 80, left: '3%', right: '4%', bottom: '3%', containLabel: true },
      legend: { type: 'scroll', top: 'top' },
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
    const series = []
    const newLegendItems = []
    const uploadColors = ['#F56C6C', '#E6A23C', '#D98A6F', '#FAB6B6', '#F7D0A3']
    const downloadColors = ['#409EFF', '#67C23A', '#8A2BE2', '#A0CFFF', '#B3E19D']
    const lastDataPoint = data.datasets.length > 0 ? data.datasets[data.datasets.length - 1] : null

    const allUploadData = []
    const allDownloadData = []

    speedChartDownloaders.value.forEach((downloader, index) => {
      const currentSpeeds = lastDataPoint?.speeds?.[downloader.id] || { ul_speed: 0, dl_speed: 0 }
      const ulSpeedText = formatSpeed(currentSpeeds.ul_speed || 0)
      const uploadLegendFullName = `${downloader.name} ↑ ${ulSpeedText}`
      newLegendItems.push({
        fullName: uploadLegendFullName,
        baseName: downloader.name,
        arrow: '↑',
        speed: ulSpeedText,
        color: uploadColors[index % uploadColors.length],
        disabled: false,
      })

      const uploadData = data.datasets.map((d) => d.speeds[downloader.id]?.ul_speed || 0);
      allUploadData.push(...uploadData);

      series.push({
        name: uploadLegendFullName,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: uploadData,
        color: uploadColors[index % uploadColors.length],
      })

      const dlSpeedText = formatSpeed(currentSpeeds.dl_speed || 0)
      const downloadLegendFullName = `${downloader.name} ↓ ${dlSpeedText}`
      newLegendItems.push({
        fullName: downloadLegendFullName,
        baseName: downloader.name,
        arrow: '↓',
        speed: dlSpeedText,
        color: downloadColors[index % downloadColors.length],
        disabled: false,
      })

      const downloadData = data.datasets.map((d) => d.speeds[downloader.id]?.dl_speed || 0);
      allDownloadData.push(...downloadData);

      series.push({
        name: downloadLegendFullName,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: downloadData,
        color: downloadColors[index % downloadColors.length],
      })
    })

    let yAxisMax = null;

    if (speedChartVisibilityMode.value === 'upload') {
      yAxisMax = Math.max(...allUploadData);
    } else if (speedChartVisibilityMode.value === 'download') {
      yAxisMax = Math.max(...allDownloadData);
    } else {
      yAxisMax = Math.max(...allUploadData, ...allDownloadData);
    }

    if (yAxisMax === 0) {
      yAxisMax = 1024;
    }

    yAxisMax = yAxisMax * 1.2;

    const oldSelectedState = speedChartLegendItems.value.reduce((acc, item) => {
      if (item.disabled) acc[`${item.baseName} ${item.arrow}`] = true
      return acc
    }, {})
    newLegendItems.forEach((item) => {
      if (oldSelectedState[`${item.baseName} ${item.arrow}`]) item.disabled = true
    })
    speedChartLegendItems.value = newLegendItems
    const currentSelected = speedChartInstance.getOption().legend?.[0]?.selected || {}
    newLegendItems.forEach((item) => {
      currentSelected[item.fullName] = !item.disabled
    })

    speedChartInstance.setOption({
      xAxis: { data: data.labels },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: (value) => formatSpeed(value) },
        max: yAxisMax
      },
      series: series,
      legend: {
        show: false,
        data: newLegendItems.map((i) => i.fullName),
        selected: currentSelected,
      },
    })

    changeSpeedVisibility(speedChartVisibilityMode.value, true)
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

    const { labels, datasets, downloaders } = data
    const series = []
    const legendData = []
    const uploadColors = ['#F56C6C', '#E6A23C', '#D98A6F', '#FAB6B6', '#F7D0A3']
    const downloadColors = ['#409EFF', '#67C23A', '#8A2BE2', '#A0CFFF', '#B3E19D']

    // 1. [保持不变] 创建用于存储每项总和的数组
    const uploadTotals = new Array(labels.length).fill(0)
    const downloadTotals = new Array(labels.length).fill(0)

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
      data: new Array(labels.length).fill(0), // **关键：数据必须是0，因为它只占位，不增加高度**
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
        formatter: (p) => {
          // **关键：从预先计算好的 totals 数组中根据索引获取值**
          const total = uploadTotals[p.dataIndex]
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
      data: new Array(labels.length).fill(0), // **关键：数据必须是0**
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
        formatter: (p) => {
          // **关键：从预先计算好的 totals 数组中根据索引获取值**
          const total = downloadTotals[p.dataIndex]
          return total > 0 ? formatBytes(total) : ''
        },
        color: '#333',
        fontSize: 10,
        fontWeight: 'normal', // 修改为 normal，不那么粗壮
      }
    })

    trafficChartInstance.setOption({
      xAxis: { data: labels },
      series: series,
      legend: { data: legendData, top: 'top' },
    })

    changeTrafficVisibility(trafficChartVisibilityMode.value, true)
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

  if (mode === 'last_1_min' && isRealtimeSpeedEnabled.value) {
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
    speedChartInstance.dispatchAction({ type: 'legendToggleSelect', name: name })
  }
}
const changeSpeedVisibility = (mode, isInternalCall = false) => {
  if (!isInternalCall) speedChartVisibilityMode.value = mode
  if (!speedChartInstance || !speedChartLegendItems.value.length) return
  const selected = {}
  speedChartLegendItems.value.forEach((item) => {
    if (mode === 'all') selected[item.fullName] = true
    else if (mode === 'upload') selected[item.fullName] = item.arrow === '↑'
    else if (mode === 'download') selected[item.fullName] = item.arrow === '↓'
  })
  speedChartInstance.setOption({ legend: { selected: selected } })
}
const changeTrafficVisibility = (mode, isInternalCall = false) => {
  if (!isInternalCall) trafficChartVisibilityMode.value = mode
  if (!trafficChartInstance) return

  const option = trafficChartInstance.getOption()
  if (!option || !option.legend || !option.legend[0] || !option.legend[0].data) return

  const legendData = option.legend[0].data
  const selected = {}

  legendData.forEach(name => {
    if (mode === 'all') {
      selected[name] = true
    } else if (mode === 'upload') {
      selected[name] = name.includes('上传量')
    } else if (mode === 'download') {
      selected[name] = name.includes('下载量')
    }
  })

  trafficChartInstance.setOption({ legend: { selected: selected } })
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
  window.addEventListener('resize', () => {
    speedChartInstance?.resize()
    trafficChartInstance?.resize()
  })

  areSettingsLoading.value = false
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
</style>
