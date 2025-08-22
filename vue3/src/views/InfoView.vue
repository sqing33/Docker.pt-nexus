<template>
  <div class="info-view">
    <!-- 速率图表 -->
    <div class="chart-container">
      <div class="chart-header">
        <div class="button-group">
          <button
            @click="setSpeedRange('last_1_min')"
            :class="{ active: speedDisplayMode === 'last_1_min' }"
          >
            近1分钟
          </button>
          <button
            @click="setSpeedRange('last_12_hours')"
            :class="{ active: speedDisplayMode === 'last_12_hours' }"
          >
            近12小时
          </button>
          <button
            @click="setSpeedRange('last_24_hours')"
            :class="{ active: speedDisplayMode === 'last_24_hours' }"
          >
            近24小时
          </button>
          <button @click="setSpeedRange('today')" :class="{ active: speedDisplayMode === 'today' }">
            今日
          </button>
          <button
            @click="setSpeedRange('yesterday')"
            :class="{ active: speedDisplayMode === 'yesterday' }"
          >
            昨日
          </button>
        </div>
        <div class="chart-title">
          速率
          <span class="display-mode-text">{{ speedDisplayModeButtonText }}</span>
        </div>
      </div>
      <div ref="speedChart" class="chart"></div>
    </div>

    <!-- 数据量图表 -->
    <div class="chart-container">
      <div class="chart-header">
        <div class="button-group">
          <button
            @click="setTrafficRange('today')"
            :class="{ active: trafficDisplayMode === 'today' }"
          >
            今日
          </button>
          <button
            @click="setTrafficRange('yesterday')"
            :class="{ active: trafficDisplayMode === 'yesterday' }"
          >
            昨日
          </button>
          <button
            @click="setTrafficRange('this_week')"
            :class="{ active: trafficDisplayMode === 'this_week' }"
          >
            本周
          </button>
          <button
            @click="setTrafficRange('last_week')"
            :class="{ active: trafficDisplayMode === 'last_week' }"
          >
            上周
          </button>
          <button
            @click="setTrafficRange('this_month')"
            :class="{ active: trafficDisplayMode === 'this_month' }"
          >
            本月
          </button>
          <button
            @click="setTrafficRange('last_month')"
            :class="{ active: trafficDisplayMode === 'last_month' }"
          >
            上月
          </button>
          <button
            @click="setTrafficRange('last_6_months')"
            :class="{ active: trafficDisplayMode === 'last_6_months' }"
          >
            近半年
          </button>
          <button
            @click="setTrafficRange('this_year')"
            :class="{ active: trafficDisplayMode === 'this_year' }"
          >
            今年
          </button>
          <button @click="setTrafficRange('all')" :class="{ active: trafficDisplayMode === 'all' }">
            全部
          </button>
        </div>
        <div class="chart-title">
          数据量
          <span class="display-mode-text">{{ trafficDisplayModeButtonText }}</span>
        </div>
      </div>
      <div ref="trafficChart" class="chart"></div>
      <div class="chart-totals">
        <span>总上传: {{ totalChartUpload }}</span>
        <span>总下载: {{ totalChartDownload }}</span>
      </div>
    </div>
  </div>
</template>

<script>
import { nextTick } from 'vue'
import * as echarts from 'echarts'
import axios from 'axios'

function formatBytes(bytes, isSpeed = false) {
  if (typeof bytes !== 'number' || bytes < 0 || isNaN(bytes)) {
    return isSpeed ? '0 B/s' : '0 B'
  }
  if (bytes === 0) {
    return isSpeed ? '0 B/s' : '0 B'
  }

  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  let value = parseFloat((bytes / Math.pow(k, i)).toFixed(2))
  let unit = sizes[i]

  if (isSpeed) {
    unit += '/s'
  }
  return `${value} ${unit}`
}

const DOWNLOADER_COLORS = [
  '#5470c6',
  '#91cc75',
  '#fac858',
  '#ee6666',
  '#73c0de',
  '#3ba272',
  '#fc8452',
  '#9a60b4',
  '#ea7ccc',
]

export default {
  name: 'InfoView',
  data() {
    return {
      speedChart: null,
      trafficChart: null,
      speedDisplayMode: 'last_12_hours',
      trafficDisplayMode: 'this_week',
      totalChartUpload: '0 B',
      totalChartDownload: '0 B',
      speedInterval: null,
    }
  },
  computed: {
    speedDisplayModeButtonText() {
      const texts = {
        last_1_min: '近1分钟',
        last_12_hours: '近12小时',
        last_24_hours: '近24小时',
        today: '今日',
        yesterday: '昨日',
      }
      return texts[this.speedDisplayMode] || ''
    },
    trafficDisplayModeButtonText() {
      const texts = {
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
      return texts[this.trafficDisplayMode] || ''
    },
  },
  mounted() {
    // 使用 nextTick 确保 DOM 完全渲染完毕后再初始化图表
    nextTick(() => {
      this.initCharts()
      this.setSpeedRange('last_1_min')
      this.fetchTrafficData()
    })
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    clearInterval(this.speedInterval)
    window.removeEventListener('resize', this.handleResize)
    if (this.speedChart) {
      this.speedChart.dispose()
    }
    if (this.trafficChart) {
      this.trafficChart.dispose()
    }
  },
  methods: {
    handleResize() {
      if (this.speedChart) {
        this.speedChart.resize()
      }
      if (this.trafficChart) {
        this.trafficChart.resize()
      }
    },
    // --- MODIFICATION START: 修复初始化逻辑 ---
    initCharts() {
      if (this.$refs.speedChart && !this.speedChart) {
        this.speedChart = echarts.init(this.$refs.speedChart)
        this.speedChart.setOption({
          tooltip: { trigger: 'axis' },
          grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
          xAxis: { type: 'category', boundaryGap: false, data: [] },
          yAxis: { type: 'value', axisLabel: { formatter: (value) => formatBytes(value, true) } },
          series: [],
          legend: { data: [], top: 10 },
        })
      }
      if (this.$refs.trafficChart && !this.trafficChart) {
        this.trafficChart = echarts.init(this.$refs.trafficChart)
        this.trafficChart.setOption({
          tooltip: { trigger: 'axis' },
          grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
          xAxis: { type: 'category', boundaryGap: false, data: [] },
          yAxis: { type: 'value', axisLabel: { formatter: (value) => formatBytes(value, false) } },
          series: [],
          legend: { data: [], top: 10 },
        })
      }
    },
    // --- MODIFICATION END ---
    setSpeedRange(range) {
      this.speedDisplayMode = range
      clearInterval(this.speedInterval)
      if (range === 'last_1_min') {
        this.fetchRecentSpeedData()
        this.speedInterval = setInterval(this.fetchRecentSpeedData, 2000)
      } else {
        this.fetchSpeedChartData()
      }
    },
    setTrafficRange(range) {
      this.trafficDisplayMode = range
      this.fetchTrafficData()
    },
    async fetchRecentSpeedData() {
      try {
        const response = await axios.get('/api/recent_speed_data', { params: { seconds: 60 } })
        this.updateSpeedChart(response.data)
      } catch (error) {
        console.error('获取近期速度数据失败:', error)
      }
    },
    async fetchSpeedChartData() {
      try {
        const response = await axios.get('/api/speed_chart_data', {
          params: { range: this.speedDisplayMode },
        })
        this.updateSpeedChart(response.data)
      } catch (error) {
        console.error('获取速度图表数据失败:', error)
      }
    },
    updateSpeedChart(data) {
      if (!this.speedChart || !data) return

      const { labels, datasets, downloaders } = data
      const series = []
      const legendData = []

      if (!downloaders || downloaders.length === 0) {
        this.speedChart.setOption({
          legend: { data: [] },
          xAxis: { data: [] },
          series: [],
        })
        return
      }

      downloaders.forEach((downloader, index) => {
        const color = DOWNLOADER_COLORS[index % DOWNLOADER_COLORS.length]
        const uploadSeriesName = `${downloader.name} 上传`
        const downloadSeriesName = `${downloader.name} 下载`
        legendData.push(uploadSeriesName, downloadSeriesName)

        series.push({
          name: uploadSeriesName,
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { color: color, width: 2 },
          itemStyle: { color: color },
          data: datasets.map((d) => d.speeds[downloader.id]?.ul_speed || 0),
        })
        series.push({
          name: downloadSeriesName,
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { color: color, width: 2, type: 'dashed' },
          itemStyle: { color: color },
          data: datasets.map((d) => d.speeds[downloader.id]?.dl_speed || 0),
        })
      })

      this.speedChart.setOption({
        legend: {
          data: legendData,
          top: 10,
          type: 'scroll',
        },
        xAxis: {
          data: labels,
        },
        series: series,
        tooltip: {
          trigger: 'axis',
          formatter: (params) => {
            if (!params || params.length === 0) return ''
            let tooltip = `${params[0].axisValue}<br/>`
            params.forEach((param) => {
              tooltip += `${param.marker} ${param.seriesName}: ${formatBytes(param.value, true)}<br/>`
            })
            return tooltip
          },
        },
      })
    },
    async fetchTrafficData() {
      try {
        const response = await axios.get('/api/chart_data', {
          params: { range: this.trafficDisplayMode },
        })
        const { labels, datasets } = response.data
        if (!this.trafficChart) return

        let totalUl = 0
        let totalDl = 0

        const uploadData = datasets.map((item) => {
          totalUl += item.uploaded
          return item.uploaded
        })

        const downloadData = datasets.map((item) => {
          totalDl += item.downloaded
          return item.downloaded
        })

        this.totalChartUpload = formatBytes(totalUl)
        this.totalChartDownload = formatBytes(totalDl)

        const legendData = ['总上传量', '总下载量']
        const series = [
          {
            name: '总上传量',
            type: 'line',
            smooth: true,
            showSymbol: false,
            data: uploadData,
            areaStyle: { opacity: 0.3 },
          },
          {
            name: '总下载量',
            type: 'line',
            smooth: true,
            showSymbol: false,
            data: downloadData,
            areaStyle: { opacity: 0.3 },
          },
        ]

        this.trafficChart.setOption({
          legend: { data: legendData, top: 10 },
          xAxis: { data: labels },
          series: series,
          tooltip: {
            trigger: 'axis',
            formatter: (params) => {
              if (!params || params.length === 0) return ''
              let tooltip = `${params[0].axisValue}<br/>`
              params.forEach((param) => {
                tooltip += `${param.marker} ${param.seriesName}: ${formatBytes(param.value)}<br/>`
              })
              return tooltip
            },
          },
        })
      } catch (error) {
        console.error('获取数据量图表数据失败:', error)
      }
    },
  },
}
</script>

<style scoped>
.info-view {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  background-color: #f0f2f5;
  height: 100%;
  box-sizing: border-box;
}
.chart-container {
  background-color: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  flex-wrap: wrap;
}
.chart-title {
  font-size: 18px;
  font-weight: bold;
  color: #333;
  margin-left: auto;
  padding-left: 20px;
}
.display-mode-text {
  font-size: 14px;
  font-weight: normal;
  color: #666;
  margin-left: 8px;
  background-color: #f0f2f5;
  padding: 2px 8px;
  border-radius: 4px;
}
.button-group {
  display: flex;
  gap: 10px;
}
.button-group button {
  padding: 6px 12px;
  border: 1px solid #dcdfe6;
  background-color: #fff;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}
.button-group button:hover {
  border-color: #409eff;
  color: #409eff;
}
.button-group button.active {
  background-color: #409eff;
  color: #fff;
  border-color: #409eff;
}
.chart {
  width: 100%;
  height: 350px;
}
.chart-totals {
  margin-top: 15px;
  text-align: right;
  font-size: 14px;
  color: #555;
}
.chart-totals span {
  margin-left: 20px;
}
</style>
