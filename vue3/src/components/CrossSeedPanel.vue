<template>
  <div class="cross-seed-panel">
    <!-- 1. 顶部步骤条 (固定) -->
    <header class="panel-header">
      <div class="custom-steps">
        <div v-for="(step, index) in steps" :key="index" class="custom-step" :class="{
          'active': index === activeStep,
          'completed': index < activeStep,
          'last': index === steps.length - 1
        }">
          <div class="step-icon">
            <el-icon v-if="index < activeStep">
              <CircleCheckFilled />
            </el-icon>
            <span v-else>{{ index + 1 }}</span>
          </div>
          <div class="step-title">{{ step.title }}</div>
          <div class="step-connector" v-if="index < steps.length - 1"></div>
        </div>
      </div>
    </header>

    <!-- 2. 中间内容区 (自适应高度、可滚动) -->
    <main class="panel-content">
      <!-- 步骤 0: 核对种子详情 -->
      <div v-if="activeStep === 0" class="step-container details-container">
        <el-tabs v-model="activeTab" type="border-card" class="details-tabs">
          <el-tab-pane label="主要信息" name="main">
            <div class="main-info-container">
              <div class="full-width-form-column">
                <el-form label-position="top" class="fill-height-form">
                  <div class="title-section">
                    <el-form-item label="原始/待解析标题">
                      <el-input v-model="torrentData.original_main_title">
                        <template #append>
                          <el-button :icon="Refresh" @click="reparseTitle" :loading="isReparsing">
                            重新解析
                          </el-button>
                        </template>
                      </el-input>
                    </el-form-item>
                    <div class="title-components-grid">
                      <el-form-item v-for="param in torrentData.title_components" :key="param.key" :label="param.key">
                        <el-input v-model="param.value" />
                      </el-form-item>
                    </div>
                  </div>

                  <div class="bottom-info-section">
                    <el-form-item label="副标题">
                      <el-input v-model="torrentData.subtitle" />
                    </el-form-item>
                    <el-form-item label="IMDb链接">
                      <el-input v-model="torrentData.imdb_link" />
                    </el-form-item>
                  </div>
                </el-form>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="海报与声明" name="poster-statement">
            <div class="poster-statement-container">
              <el-form label-position="top" class="fill-height-form">
                <div class="poster-statement-split">
                  <div class="left-panel">
                    <el-form-item label="声明" class="statement-item">
                      <el-input type="textarea" v-model="torrentData.intro.statement" :rows="18" />
                    </el-form-item>
                    <el-form-item label="海报链接">
                      <el-input type="textarea" v-model="torrentData.intro.poster" :rows="2" />
                    </el-form-item>
                  </div>
                  <div class="right-panel">
                    <div class="poster-preview-section">
                      <div class="preview-header">海报预览</div>
                      <div class="image-preview-container">
                        <template v-if="posterImages.length">
                          <img v-for="(url, index) in posterImages" :key="'poster-' + index" :src="url" alt="海报预览"
                            class="preview-image" @error="handleImageError(url, 'poster', index)" />
                        </template>
                        <div v-else class="preview-placeholder">暂无海报预览</div>
                      </div>
                    </div>
                  </div>
                </div>
              </el-form>
            </div>
          </el-tab-pane>

          <el-tab-pane label="视频截图" name="images">
            <div class="screenshot-container">
              <div class="form-column screenshot-text-column">
                <el-form label-position="top" class="fill-height-form">
                  <el-form-item label="截图" class="is-flexible">
                    <el-input type="textarea" v-model="torrentData.intro.screenshots" :rows="20" />
                  </el-form-item>
                </el-form>
              </div>
              <div class="preview-column screenshot-preview-column">
                <div class="carousel-container">
                  <template v-if="screenshotImages.length">
                    <el-carousel :interval="5000" height="500px" indicator-position="outside">
                      <el-carousel-item v-for="(url, index) in screenshotImages" :key="'ss-' + index">
                        <div class="carousel-image-wrapper">
                          <img :src="url" alt="截图预览" class="carousel-image"
                            @error="handleImageError(url, 'screenshot', index)" />
                        </div>
                      </el-carousel-item>
                    </el-carousel>
                  </template>
                  <div v-else class="preview-placeholder">截图预览</div>
                </div>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="简介详情" name="intro">
            <el-form label-position="top" class="fill-height-form">
              <el-form-item label="正文" class="is-flexible">
                <el-input type="textarea" v-model="torrentData.intro.body" :rows="20" />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="媒体信息" name="mediainfo">
            <el-form label-position="top" class="fill-height-form">
              <el-form-item label="Mediainfo" class="is-flexible">
                <el-input type="textarea" class="code-font" v-model="torrentData.mediainfo" :rows="22" />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="已过滤声明" name="filtered-declarations" class="filtered-declarations-pane">
            <div class="filtered-declarations-container">
              <div class="filtered-declarations-header">
                <h3>已自动过滤的声明内容</h3>
                <el-tag type="warning" size="small">共 {{ filteredDeclarationsCount }} 条</el-tag>
              </div>
              <div class="filtered-declarations-content">
                <template v-if="filteredDeclarationsCount > 0">
                  <div v-for="(declaration, index) in filteredDeclarationsList" :key="index" class="declaration-item">
                    <div class="declaration-header">
                      <span class="declaration-number">#{{ index + 1 }}</span>
                      <el-tag type="danger" size="small">已过滤</el-tag>
                    </div>
                    <pre class="declaration-content code-font">{{ declaration }}</pre>
                  </div>
                </template>
                <div v-else class="no-filtered-declarations">
                  <el-empty description="未检测到需要过滤的 ARDTU 声明内容" />
                </div>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>

      <!-- 步骤 1: 发布参数预览 -->
      <div v-if="activeStep === 1" class="step-container publish-preview-container">
        <div class="publish-preview-content">
          <!-- 第一行：主标题 -->
          <div class="preview-row main-title-row">
            <div class="row-label">主标题：</div>
            <div class="row-content main-title-content">
              {{ torrentData.final_publish_parameters?.['主标题 (预览)'] || '暂无数据' }}
            </div>
          </div>

          <!-- 第二行：副标题 -->
          <div class="preview-row subtitle-row">
            <div class="row-label">副标题：</div>
            <div class="row-content subtitle-content">
              {{ torrentData.subtitle || '暂无数据' }}
            </div>
          </div>

          <!-- 第三行：媒介音频等各种参数 -->
          <div class="preview-row params-row">
            <div class="row-label">参数信息：</div>
            <div class="row-content">
              <!-- IMDb链接和标签在同一行 -->
              <div class="param-row">
                <div class="param-item imdb-item half-width">
                  <span class="param-label">IMDb链接：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.imdb_link || torrentData.raw_params_for_preview?.imdb_link === 'N/A' }]">
                    {{ torrentData.raw_params_for_preview?.imdb_link || 'N/A' }}
                  </span>
                </div>
                <div class="param-item tags-item half-width">
                  <span class="param-label">标签：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.tags || torrentData.raw_params_for_preview?.tags?.length === 0 }]">
                    {{ torrentData.raw_params_for_preview?.tags?.join(', ') || 'N/A' }}
                  </span>
                </div>
              </div>

              <!-- 其他参数在第二行开始排列 -->
              <div class="params-content">
                <div class="param-item inline-param">
                  <span class="param-label">类型：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.type || torrentData.raw_params_for_preview?.type === 'N/A' }]">
                    {{ torrentData.raw_params_for_preview?.type || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">媒介：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.medium || torrentData.raw_params_for_preview?.medium === 'N/A' }]">
                    {{ torrentData.raw_params_for_preview?.medium || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">视频编码：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.video_codec || torrentData.raw_params_for_preview?.video_codec === 'N/A' }]">
                    {{ torrentData.raw_params_for_preview?.video_codec || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">音频编码：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.audio_codec || torrentData.raw_params_for_preview?.audio_codec === 'N/A' }]">
                    {{ torrentData.raw_params_for_preview?.audio_codec || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">分辨率：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.resolution || torrentData.raw_params_for_preview?.resolution === 'N/A' }]">
                    {{ torrentData.raw_params_for_preview?.resolution || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">制作组：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.release_group || torrentData.raw_params_for_preview?.release_group === 'N/A' }]">
                    {{ torrentData.raw_params_for_preview?.release_group || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">产地/来源：</span>
                  <span :class="['param-value', { 'empty': !torrentData.raw_params_for_preview?.source || torrentData.raw_params_for_preview?.source === 'N/A' }]">
                    {{ torrentData.raw_params_for_preview?.source || 'N/A' }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 第四行：Mediainfo 可滚动区域 -->
          <div class="preview-row mediainfo-row">
            <div class="row-label">Mediainfo：</div>
            <div class="row-content mediainfo-content scrollable-content">
              <pre class="mediainfo-pre">{{ torrentData.mediainfo || '暂无数据' }}</pre>
            </div>
          </div>

          <!-- 第五行：声明+简介全部内容 -->
          <div class="preview-row description-row">
            <div class="row-label">简介内容：</div>
            <div class="row-content description-content">
              <!-- 声明内容 -->
              <div class="description-section">
                <div class="section-content" v-html="parseBBCode(torrentData.intro?.statement) || '暂无声明'"></div>
              </div>

              <!-- 海报图片 -->
              <div class="description-section" v-if="posterImages.length > 0">
                <div class="image-gallery">
                  <img v-for="(url, index) in posterImages" :key="'poster-preview-' + index" :src="url"
                    :alt="'海报 ' + (index + 1)" class="preview-image-inline" style="width: 200px;"
                    @error="handleImageError(url, 'poster', index)" />
                </div>
              </div>

              <!-- 简介正文 -->
              <div class="description-section">
                <br />
                <div class="section-content" v-html="parseBBCode(torrentData.intro?.body) || '暂无正文'"></div>
              </div>

              <!-- 视频截图 -->
              <div class="description-section" v-if="screenshotImages.length > 0">
                <div class="section-title">视频截图:</div>
                <div class="image-gallery">
                  <img v-for="(url, index) in screenshotImages" :key="'screenshot-preview-' + index" :src="url"
                    :alt="'截图 ' + (index + 1)" class="preview-image-inline"
                    @error="handleImageError(url, 'screenshot', index)" />
                </div>
              </div>
            </div>
          </div>

        </div>
      </div>

      <!-- 步骤 2: 选择发布站点 -->
      <div v-if="activeStep === 2" class="step-container site-selection-container">
        <h3 class="selection-title">请选择要发布的目标站点</h3>
        <p class="selection-subtitle">只有Cookie和Passkey均配置正常的站点才会在此处显示。已存在的站点已被自动禁用。</p>
        <div class="select-all-container">
          <el-button-group>
            <el-button type="primary" @click="selectAllTargetSites">全选</el-button>
            <el-button type="info" @click="clearAllTargetSites">清空</el-button>
          </el-button-group>
        </div>
        <div class="site-buttons-group">
          <el-button v-for="site in allSitesStatus.filter(s => s.is_target)" :key="site.name" class="site-button"
            :type="selectedTargetSites.includes(site.name) ? 'success' : 'default'"
            :disabled="!isTargetSiteSelectable(site.name)" @click="toggleSiteSelection(site.name)">
            {{ site.name }}
          </el-button>
        </div>
      </div>

      <!-- 步骤 3: 完成发布 -->
      <div v-if="activeStep === 3" class="step-container results-container">
        <!-- 进度条显示 -->
        <div class="progress-section" v-if="publishProgress.total > 0 || downloaderProgress.total > 0">
          <div class="progress-item" v-if="publishProgress.total > 0">
            <div class="progress-label">发布进度:</div>
            <el-progress :percentage="Math.round((publishProgress.current / publishProgress.total) * 100)" :show-text="true" />
            <div class="progress-text">{{ publishProgress.current }} / {{ publishProgress.total }}</div>
          </div>
          <div class="progress-item" v-if="downloaderProgress.total > 0">
            <div class="progress-label">下载器添加进度:</div>
            <el-progress :percentage="Math.round((downloaderProgress.current / downloaderProgress.total) * 100)" :show-text="true" />
            <div class="progress-text">{{ downloaderProgress.current }} / {{ downloaderProgress.total }}</div>
          </div>
        </div>

        <div class="results-grid-container">
          <div v-for="result in finalResultsList" :key="result.siteName" class="result-card"
            :class="{ 'is-success': result.success, 'is-error': !result.success }">
            <div class="card-icon">
              <el-icon v-if="result.success" color="#67C23A" :size="32">
                <CircleCheckFilled />
              </el-icon>
              <el-icon v-else color="#F56C6C" :size="32">
                <CircleCloseFilled />
              </el-icon>
            </div>
            <h4 class="card-title">{{ result.siteName }}</h4>
            <div v-if="result.isExisted" class="existed-tag">
              <el-tag type="warning" size="small">种子已存在</el-tag>
            </div>

            <!-- 下载器添加状态 -->
            <div class="downloader-status" v-if="result.downloaderStatus">
              <div class="status-icon">
                <el-icon v-if="result.downloaderStatus.success" color="#67C23A" :size="16">
                  <CircleCheckFilled />
                </el-icon>
                <el-icon v-else color="#F56C6C" :size="16">
                  <CircleCloseFilled />
                </el-icon>
              </div>
              <span class="status-text"
                :class="{ 'success': result.downloaderStatus.success, 'error': !result.downloaderStatus.success }">
                {{ result.downloaderStatus.success ? `成功将种子添加到下载器 '${result.downloaderStatus.downloaderName}'` : '添加失败'
                }}
              </span>
            </div>

            <!-- 操作按钮 -->
            <div class="card-extra">
              <el-button type="primary" size="small" @click="showSiteLog(result.siteName, result.logs)">
                查看日志
              </el-button>
              <a v-if="result.success && result.url" :href="result.url" target="_blank" rel="noopener noreferrer">
                <el-button type="success" size="small">
                  查看种子
                </el-button>
              </a>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- 3. 底部按钮栏 (固定) -->
    <footer class="panel-footer">
      <!-- 步骤 0 的按钮 -->
      <div v-if="activeStep === 0" class="button-group">
        <el-button @click="$emit('cancel')">取消</el-button>
        <el-button type="primary" @click="goToPublishPreviewStep" :disabled="isLoading || !canProceedToNextStep">
          下一步：发布参数预览
        </el-button>
      </div>
      <!-- 步骤 1 的按钮 -->
      <div v-if="activeStep === 1" class="button-group">
        <el-button @click="handlePreviousStep" :disabled="isLoading">上一步</el-button>
        <el-tooltip
          :content="isScrolledToBottom ? '' : '请先滚动到页面底部'"
          :disabled="isScrolledToBottom"
          placement="top">
          <el-button
            type="primary"
            @click="goToSelectSiteStep"
            :disabled="isLoading || !isScrolledToBottom"
            :class="{ 'scrolled-to-bottom': isScrolledToBottom }">
            下一步：选择发布站点
          </el-button>
        </el-tooltip>
      </div>
      <!-- 步骤 2 的按钮 -->
      <div v-if="activeStep === 2" class="button-group">
        <el-button @click="handlePreviousStep" :disabled="isLoading">上一步</el-button>
        <el-button type="primary" @click="handlePublish" :loading="isLoading"
          :disabled="selectedTargetSites.length === 0">
          立即发布
        </el-button>
      </div>
      <!-- 步骤 3 的按钮 -->
      <div v-if="activeStep === 3" class="button-group">
        <el-button type="primary" @click="$emit('complete')">完成</el-button>
      </div>
    </footer>
  </div>

  <!-- 日志弹窗 (保持不变) -->
  <div v-if="showLogCard" class="log-card-overlay" @click="hideLog"></div>
  <el-card v-if="showLogCard" class="log-card" shadow="xl">
    <template #header>
      <div class="card-header">
        <span>操作日志</span>
        <el-button type="danger" :icon="Close" circle @click="hideLog" />
      </div>
    </template>
    <pre class="log-content-pre">{{ logContent }}</pre>
  </el-card>
</template>

<script setup lang="ts">
// ... 你的 <script setup> 部分完全保持不变 ...
import { ref, onMounted, computed, nextTick, watch } from 'vue'
import { ElNotification, ElMessageBox } from 'element-plus'
import { ElTooltip } from 'element-plus'
import axios from 'axios'
import { Refresh, CircleCheckFilled, CircleCloseFilled, Close } from '@element-plus/icons-vue'

// BBCode 解析函数
const parseBBCode = (text) => {
  if (!text) return ''

  // 处理 [quote] 标签
  text = text.replace(/\[quote\]([\s\S]*?)\[\/quote\]/gi, '<blockquote>$1</blockquote>')

  // 处理 [b] 标签
  text = text.replace(/\[b\]([\s\S]*?)\[\/b\]/gi, '<strong>$1</strong>')

  // 处理 [color] 标签
  text = text.replace(/\[color=(\w+|\#[0-9a-fA-F]{3,6})\]([\s\S]*?)\[\/color\]/gi, '<span style="color: $1;">$2</span>')

  // 处理 [size] 标签，映射到具体的像素值
  text = text.replace(/\[size=(\d+)\]([\s\S]*?)\[\/size\]/gi, (match, size, content) => {
    // 根据 size 值映射到具体的像素值
    const sizeMap = {
      '1': '12',
      '2': '14',
      '3': '16',
      '4': '18',
      '5': '24',
      '6': '32',
      '7': '48'
    }
    const pixelSize = sizeMap[size] || (parseInt(size) * 4)
    return `<span style="font-size: ${pixelSize}px;">${content}</span>`
  })

  // 处理换行符
  text = text.replace(/\n/g, '<br>')

  return text
}

interface SiteStatus {
  name: string;
  has_cookie: boolean;
  has_passkey: boolean;
  is_source: boolean;
  is_target: boolean;
}

interface Torrent {
  name: string;
  save_path: string;
  size: number;
  size_formatted: string;
  progress: number;
  state: string;
  sites: Record<string, any>;
  total_uploaded: number;
  total_uploaded_formatted: string;
  downloaderId?: string;
}

const props = defineProps<{
  torrent: Torrent;
  sourceSite: string;
}>();

const emit = defineEmits(['complete', 'cancel']);

const getInitialTorrentData = () => ({
  title_components: [] as { key: string, value: string }[],
  original_main_title: '',
  subtitle: '',
  imdb_link: '',
  douban_link: '',
  intro: { statement: '', poster: '', body: '', screenshots: '', removed_ardtudeclarations: [] },
  mediainfo: '',
  source_params: {},
  final_publish_parameters: {},
})

const parseImageUrls = (text: string) => {
  if (!text || typeof text !== 'string') return []
  const regex = /\[img\](https?:\/\/[^\s[\]]+)\[\/img\]/gi
  const matches = [...text.matchAll(regex)]
  return matches.map((match) => match[1])
}

const activeStep = ref(0)
const activeTab = ref('main')
const isScrolledToBottom = ref(false)

// Progress tracking variables
const publishProgress = ref({ current: 0, total: 0 })
const downloaderProgress = ref({ current: 0, total: 0 })

// 防抖函数
const debounce = (func, wait) => {
  let timeout
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout)
      func(...args)
    }
    clearTimeout(timeout)
    timeout = setTimeout(later, wait)
  }
}

// 检查是否滚动到底部
const checkIfScrolledToBottom = debounce(() => {
  const panelContent = document.querySelector('.panel-content')
  if (panelContent) {
    const { scrollTop, scrollHeight, clientHeight } = panelContent
    isScrolledToBottom.value = scrollTop + clientHeight >= scrollHeight - 5 // 5px的容差
  }
}, 100) // 100ms防抖

// 添加滚动事件监听器
const addScrollListener = () => {
  const panelContent = document.querySelector('.panel-content')
  if (panelContent) {
    panelContent.addEventListener('scroll', checkIfScrolledToBottom)
  }
}

// 移除滚动事件监听器
const removeScrollListener = () => {
  const panelContent = document.querySelector('.panel-content')
  if (panelContent) {
    panelContent.removeEventListener('scroll', checkIfScrolledToBottom)
  }
}

// 在组件挂载时添加监听器
onMounted(() => {
  fetchSitesStatus();
  fetchTorrentInfo();

  // 在下一个tick添加滚动监听器，确保DOM已经渲染
  nextTick(() => {
    if (activeStep.value === 1) {
      addScrollListener()
      checkIfScrolledToBottom() // 初始检查
    }
  })
})

// 监听活动步骤的变化
watch(activeStep, (newStep, oldStep) => {
  if (oldStep === 1) {
    removeScrollListener()
  }
  if (newStep === 1) {
    nextTick(() => {
      addScrollListener()
      checkIfScrolledToBottom() // 初始检查
    })
  }
})

const steps = [
  { title: '核对种子详情' },
  { title: '发布参数预览' },
  { title: '选择发布站点' },
  { title: '完成发布' }
]
const allSitesStatus = ref<SiteStatus[]>([])
const selectedTargetSites = ref<string[]>([])
const isLoading = ref(false)
const torrentData = ref(getInitialTorrentData())
const taskId = ref<string | null>(null)
const finalResultsList = ref<any[]>([])
const isReparsing = ref(false)
const reportedFailedScreenshots = ref(false)
const logContent = ref('')
const showLogCard = ref(false)
const downloaderList = ref<{ id: string, name: string }[]>([])
const posterImages = computed(() => parseImageUrls(torrentData.value.intro.poster))
const screenshotImages = computed(() => parseImageUrls(torrentData.value.intro.screenshots))

const filteredDeclarationsList = computed(() => {
  const removedDeclarations = torrentData.value.intro.removed_ardtudeclarations;
  if (Array.isArray(removedDeclarations)) {
    return removedDeclarations;
  }
  return [];
})
const filteredDeclarationsCount = computed(() => filteredDeclarationsList.value.length)

const isTargetSiteSelectable = (siteName: string): boolean => {
  if (!props.torrent || !props.torrent.sites) {
    return true;
  }
  return !props.torrent.sites[siteName];
};

const canProceedToNextStep = computed(() => {
  if (isLoading.value || isReparsing.value) {
    return false;
  }

  if (reportedFailedScreenshots.value) {
    if (screenshotImages.value.length === 0 && torrentData.value.intro.screenshots) {
      return false;
    }
  }

  const titleComponents = torrentData.value.title_components;
  if (titleComponents && Array.isArray(titleComponents)) {
    const unrecognizedParam = titleComponents.find(
      param => param.key === "无法识别" && param.value && param.value.trim() !== ""
    );
    if (unrecognizedParam) {
      return false;
    }
  }

  if (!torrentData.value.original_main_title || torrentData.value.original_main_title.trim() === "") {
    return false;
  }

  return true;
});

const reparseTitle = async () => {
  if (!torrentData.value.original_main_title) {
    ElNotification.warning('标题为空，无法解析。');
    return;
  }
  isReparsing.value = true;
  try {
    const response = await axios.post('/api/utils/parse_title', { title: torrentData.value.original_main_title });
    if (response.data.success) {
      torrentData.value.title_components = response.data.components;
      ElNotification.success('标题已重新解析！');
    } else {
      ElNotification.error(response.data.message || '解析失败');
    }
  } catch (error) {
    handleApiError(error, '重新解析标题时发生网络错误');
  } finally {
    isReparsing.value = false;
  }
};

const handleImageError = async (url: string, type: 'poster' | 'screenshot', index: number) => {
  if (type === 'screenshot' && reportedFailedScreenshots.value) {
    return
  }
  console.error(`图片加载失败: 类型=${type}, URL=${url}, 索引=${index}`)
  if (type === 'screenshot') {
    reportedFailedScreenshots.value = true
    ElNotification.warning({
      title: '截图失效',
      message: '检测到截图链接失效，正在尝试从视频重新生成...',
    })
  } else if (type === 'poster') {
    ElNotification.warning({
      title: '海报失效',
      message: '检测到海报链接失效，正在尝试重新获取...',
    })
  }

  const payload = {
    type: type,
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: props.sourceSite,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
    },
    savePath: props.torrent.save_path,
    torrentName: props.torrent.name
  }

  try {
    const response = await axios.post('/api/media/validate', payload)
    if (response.data.success) {
      if (type === 'screenshot' && response.data.screenshots) {
        torrentData.value.intro.screenshots = response.data.screenshots;
        reportedFailedScreenshots.value = false;
        ElNotification.success({
          title: '截图已更新',
          message: '已成功生成并加载了新的截图。',
        });
      } else if (type === 'poster' && response.data.posters) {
        torrentData.value.intro.poster = response.data.posters;
        ElNotification.success({
          title: '海报已更新',
          message: '已成功生成并加载了新的海报。',
        });
      }
    } else {
      ElNotification.error({
        title: '更新失败',
        message: response.data.error || `无法从后端获取新的${type === 'poster' ? '海报' : '截图'}。`,
      });
    }
  } catch (error: any) {
    const errorMsg = error.response?.data?.error || `发送失效${type === 'poster' ? '海报' : '截图'}信息请求时发生网络错误`;
    console.error('发送失效图片信息请求时发生网络错误:', error)
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    });
  }
}

const fetchSitesStatus = async () => {
  try {
    const response = await axios.get('/api/sites/status');
    allSitesStatus.value = response.data;
    const downloaderResponse = await axios.get('/api/downloaders_list');
    downloaderList.value = downloaderResponse.data;
  } catch (error) {
    ElNotification.error({ title: '错误', message: '无法从服务器获取站点状态列表或下载器列表' });
  }
}

const fetchTorrentInfo = async () => {
  if (!props.sourceSite || !props.torrent) return;

  const siteDetails = props.torrent.sites[props.sourceSite];
  // 首先检查是否有存储的种子ID
  let torrentId = siteDetails.torrentId || null;

  // 如果没有存储的ID，则尝试从链接中提取
  if (!torrentId) {
    const idMatch = siteDetails.comment?.match(/id=(\d+)/);
    if (!idMatch || !idMatch[1]) {
      ElNotification.error(`无法从源站点 ${props.sourceSite} 的链接中提取种子ID。`);
      emit('cancel');
      return;
    }
    torrentId = idMatch[1];
  }

  isLoading.value = true
  ElNotification({
    title: '正在获取',
    message: '正在从源站点抓取种子信息，请稍候...',
    type: 'info',
    duration: 0,
  })

  try {
    const response = await axios.post('/api/migrate/fetch_info', {
      sourceSite: props.sourceSite,
      searchTerm: torrentId,
      savePath: props.torrent.save_path,
    })

    ElNotification.closeAll()
    if (response.data.success) {
      ElNotification.success({ title: '获取成功', message: '种子信息已成功加载，请核对。' })
      torrentData.value = response.data.data
      taskId.value = response.data.task_id

      if ((!torrentData.value.imdb_link || !torrentData.value.douban_link) && torrentData.value.intro.body) {
        let imdbExtracted = false;
        let doubanExtracted = false;
        if (!torrentData.value.imdb_link) {
          const imdbRegex = /(https?:\/\/www\.imdb\.com\/title\/tt\d+)/;
          const imdbMatch = torrentData.value.intro.body.match(imdbRegex);
          if (imdbMatch && imdbMatch[1]) {
            torrentData.value.imdb_link = imdbMatch[1];
            imdbExtracted = true;
          }
        }
        if (!torrentData.value.douban_link) {
          const doubanRegex = /(https:\/\/movie\.douban\.com\/subject\/\d+)/;
          const doubanMatch = torrentData.value.intro.body.match(doubanRegex);
          if (doubanMatch && doubanMatch[1]) {
            torrentData.value.douban_link = doubanMatch[1];
            doubanExtracted = true;
          }
        }
        if (imdbExtracted || doubanExtracted) {
          const messages = [];
          if (imdbExtracted) messages.push('IMDb链接');
          if (doubanExtracted) messages.push('豆瓣链接');
          ElNotification.info({
            title: '自动填充',
            message: `已从简介正文中自动提取并填充 ${messages.join(' 和 ')}。`
          });
        }
      }
      activeStep.value = 0
    } else {
      ElNotification.error({
        title: '获取失败',
        message: response.data.logs,
        duration: 0,
        showClose: true,
      })
      emit('cancel');
    }
  } catch (error) {
    ElNotification.closeAll()
    handleApiError(error, '获取种子信息时发生网络错误')
    emit('cancel');
  } finally {
    isLoading.value = false
  }
}

const goToPublishPreviewStep = async () => {
  isLoading.value = true;
  try {
    // 将当前修改后的数据发送给后端进行更新
    const response = await axios.post('/api/migrate/update_preview_data', {
      task_id: taskId.value,
      updated_data: torrentData.value
    });

    if (response.data.success) {
      // 更新成功后，获取新的预览数据
      torrentData.value = { ...torrentData.value, ...response.data.data };
      activeStep.value = 1;
    } else {
      ElNotification.error({
        title: '更新预览数据失败',
        message: response.data.message || '未知错误',
        duration: 0,
        showClose: true,
      });
    }
  } catch (error) {
    handleApiError(error, '更新预览数据时发生网络错误');
  } finally {
    isLoading.value = false;
  }
};

const goToSelectSiteStep = () => {
  activeStep.value = 2;
}

const toggleSiteSelection = (siteName: string) => {
  const index = selectedTargetSites.value.indexOf(siteName)
  if (index > -1) {
    selectedTargetSites.value.splice(index, 1)
  } else {
    selectedTargetSites.value.push(siteName)
  }
}

const selectAllTargetSites = () => {
  const selectableSites = allSitesStatus.value
    .filter(s => s.is_target && isTargetSiteSelectable(s.name))
    .map(s => s.name);
  selectedTargetSites.value = selectableSites;
}

const clearAllTargetSites = () => {
  selectedTargetSites.value = [];
}

const handlePublish = async () => {
  activeStep.value = 3
  isLoading.value = true
  finalResultsList.value = []

  // Initialize progress tracking
  publishProgress.value = { current: 0, total: selectedTargetSites.value.length }
  downloaderProgress.value = { current: 0, total: 0 }

  ElNotification({
    title: '正在发布',
    message: `准备向 ${selectedTargetSites.value.length} 个站点发布种子...`,
    type: 'info',
    duration: 0,
  })

  const results = []

  for (const siteName of selectedTargetSites.value) {
    try {
      const response = await axios.post('/api/migrate/publish', {
        task_id: taskId.value,
        upload_data: torrentData.value,
        targetSite: siteName,
      })

      const result = {
        siteName,
        message: getCleanMessage(response.data.logs || '发布成功'),
        ...response.data
      }

      if (response.data.logs && response.data.logs.includes("种子已存在")) {
        result.isExisted = true;
      }
      results.push(result)
      finalResultsList.value = [...results]

      if (result.success) {
        ElNotification.success({
          title: `发布成功 - ${siteName}`,
          message: '种子已成功发布到该站点'
        })
      }
    } catch (error) {
      const result = {
        siteName,
        success: false,
        logs: error.response?.data?.logs || error.message,
        url: null,
        message: `发布到 ${siteName} 时发生网络错误。`
      }
      results.push(result)
      finalResultsList.value = [...results]
      ElNotification.error({
        title: `发布失败 - ${siteName}`,
        message: result.message
      })
    }
    // Update publish progress
    publishProgress.value.current++
    await new Promise(resolve => setTimeout(resolve, 1000))
  }

  ElNotification.closeAll()
  const successCount = results.filter(r => r.success).length
  ElNotification.success({
    title: '发布完成',
    message: `成功发布到 ${successCount} / ${selectedTargetSites.value.length} 个站点。`
  })

  logContent.value += '\n\n--- [开始自动添加任务] ---';
  const downloaderStatusMap: Record<string, { success: boolean, message: string, downloaderName: string }> = {};

  // Set downloader progress total
  const successfulResults = results.filter(r => r.success && r.url);
  downloaderProgress.value.total = successfulResults.length;

  for (const result of successfulResults) {
    const downloaderStatus = await triggerAddToDownloader(result);
    downloaderStatusMap[result.siteName] = downloaderStatus;
    // Update downloader progress
    downloaderProgress.value.current++
  }
  logContent.value += '\n--- [自动添加任务结束] ---';

  const siteLogs = results.map(r => {
    let logEntry = `--- Log for ${r.siteName} ---\n${r.logs || 'No logs available.'}`
    if (downloaderStatusMap[r.siteName]) {
      const status = downloaderStatusMap[r.siteName]
      logEntry += `\n\n--- Downloader Status for ${r.siteName} ---`
      if (status.success) {
        logEntry += `\n✅ 成功: ${status.message}`
      } else {
        logEntry += `\n❌ 失败: ${status.message}`
      }
    }
    return logEntry
  })
  logContent.value = siteLogs.join('\n\n')

  finalResultsList.value = results.map(result => ({
    ...result,
    downloaderStatus: downloaderStatusMap[result.siteName]
  }));

  isLoading.value = false
}

const handlePreviousStep = () => {
  if (activeStep.value > 0) {
    activeStep.value--
  }
}

const getCleanMessage = (logs: string): string => {
  if (!logs || logs === '发布成功') return '发布成功'
  if (logs.includes("种子已存在")) {
    return '种子已存在，发布成功'
  }
  const lines = logs.split('\n').filter(line => line && !line.includes('--- [步骤') && !line.includes('INFO - ---'))
  const cleanLines = lines.map(line => line.replace(/^\d{2}:\d{2}:\d{2} - \w+ - /, ''))
  return cleanLines.filter(Boolean).pop() || '发布成功'
}

const handleApiError = (error: any, defaultMessage: string) => {
  const message = error.response?.data?.logs || error.message || defaultMessage
  ElNotification.error({ title: '操作失败', message, duration: 0, showClose: true })
}

const triggerAddToDownloader = async (result: any) => {
  if (!props.torrent.save_path || !props.torrent.downloaderId) {
    const msg = `[${result.siteName}] 警告: 未能获取到原始保存路径或下载器ID，已跳过自动添加任务。`;
    console.warn(msg);
    logContent.value += `\n${msg}`;
    return { success: false, message: "未能获取到原始保存路径或下载器ID", downloaderName: "" };
  }

  let targetDownloaderId = props.torrent.downloaderId;
  let targetDownloaderName = "未知下载器";

  try {
    const configResponse = await axios.get('/api/settings');
    const config = configResponse.data;
    const defaultDownloaderId = config.cross_seed?.default_downloader;
    if (defaultDownloaderId) {
      targetDownloaderId = defaultDownloaderId;
    }
    const downloader = downloaderList.value.find(d => d.id === targetDownloaderId);
    if (downloader) targetDownloaderName = downloader.name;

  } catch (error) {
    // Ignore error
  }

  logContent.value += `\n[${result.siteName}] 正在尝试将新种子添加到下载器 '${targetDownloaderName}'...`;

  try {
    const response = await axios.post('/api/migrate/add_to_downloader', {
      url: result.url,
      savePath: props.torrent.save_path,
      downloaderId: targetDownloaderId,
    });

    if (response.data.success) {
      logContent.value += `\n[${result.siteName}] 成功: ${response.data.message}`;
      return { success: true, message: response.data.message, downloaderName: targetDownloaderName };
    } else {
      logContent.value += `\n[${result.siteName}] 失败: ${response.data.message}`;
      return { success: false, message: response.data.message, downloaderName: targetDownloaderName };
    }
  } catch (error: any) {
    const errorMessage = error.response?.data?.message || error.message;
    logContent.value += `\n[${result.siteName}] 错误: 调用API失败: ${errorMessage}`;
    return { success: false, message: `调用API失败: ${errorMessage}`, downloaderName: targetDownloaderName };
  }
}

const showLogs = async () => {
  if (!taskId.value) {
    ElNotification.warning('没有可用的任务日志')
    return
  }
  try {
    const response = await axios.get(`/api/migrate/logs/${taskId.value}`)
    ElNotification.info({
      title: '转种日志',
      message: response.data.logs,
      duration: 0,
      showClose: true
    })
  } catch (error) {
    handleApiError(error, '获取日志时发生错误')
  }
}

const hideLog = () => {
  showLogCard.value = false
}

const showSiteLog = (siteName: string, logs: string) => {
  let siteLogContent = `--- Log for ${siteName} ---\n${logs || 'No logs available.'}`;
  const siteResult = finalResultsList.value.find((result: any) => result.siteName === siteName);
  if (siteResult && siteResult.downloaderStatus) {
    const status = siteResult.downloaderStatus;
    siteLogContent += `\n\n--- Downloader Status for ${siteName} ---`;
    if (status.success) {
      siteLogContent += `\n✅ 成功: ${status.message}`;
    } else {
      siteLogContent += `\n❌ 失败: ${status.message}`;
    }
  }
  logContent.value = siteLogContent;
  showLogCard.value = true;
}

onMounted(() => {
  fetchSitesStatus();
  fetchTorrentInfo();
});
</script>

<style scoped>
/* ======================================= */
/*        [核心布局样式 - 最终版]        */
/* ======================================= */
:root {
  --header-height: 75px;
  --footer-height: 70px;
}

/* 1. 主面板容器：使用相对定位创建上下文 */
.cross-seed-panel {
  position: relative;
  height: 100%;
  width: 100%;
  /* 为页头和页脚留出空间 */
  padding-top: var(--header-height);
  padding-bottom: var(--footer-height);
  box-sizing: border-box;
}

/* 2. 顶部Header：绝对定位，固定在顶部 */
.panel-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: var(--header-height);
  background-color: #ffffff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-bottom: 10px;
  z-index: 10;
}

/* 3. 中间内容区：占据所有剩余空间，并启用滚动 */
.panel-content {
  height: 640px;
  overflow-y: auto;
  margin-top: 25px;
  padding: 24px;
  position: relative;
}

/* 每个步骤内容的容器 */
.step-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* 4. 底部Footer：绝对定位，固定在底部 */
.panel-footer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: var(--footer-height);
  background-color: #ffffff;
  border-top: 1px solid #e4e7ed;
  box-shadow: 0 -2px 4px rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  padding-top: 10px;
  z-index: 10;
}

.button-group :deep(.el-button.is-disabled) {
  cursor: not-allowed;
}

.button-group :deep(.el-button.is-disabled:hover) {
  transform: none;
}



/* ======================================= */
/*           [组件内部细节样式]            */
/* ======================================= */

/* --- 步骤条 --- */
.custom-steps {
  display: flex;
  align-items: center;
  width: auto;
  margin: 0 auto;
}

.custom-step {
  display: flex;
  align-items: center;
  position: relative;
}

.custom-step:not(.last) {
  min-width: 150px;
}

.step-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  background-color: #dcdfe6;
  color: #606266;
  border: 2px solid #dcdfe6;
  transition: all 0.3s ease;
  flex-shrink: 0;
}

.custom-step.active .step-icon {
  background-color: #409eff;
  border-color: #409eff;
  color: white;
}

.custom-step.completed .step-icon {
  background-color: #67c23a;
  border-color: #67c23a;
  color: white;
}

.step-title {
  margin-left: 8px;
  font-size: 14px;
  color: #909399;
  white-space: nowrap;
}

.custom-step.active .step-title {
  color: #409eff;
  font-weight: 500;
}

.custom-step.completed .step-title {
  color: #67c23a;
}

.step-connector {
  flex: 1;
  height: 2px;
  background-color: #dcdfe6;
  margin: 0 12px;
  min-width: 40px;
}

.custom-step.completed+.custom-step .step-connector {
  background-color: #67c23a;
}

/* --- 步骤 0: 核对详情 --- */
.details-container {
  background-color: #fff;
  border-bottom: 1px solid #e4e7ed;
  height: calc(100% - 1px);
  overflow: hidden;
  display: flex;
}

.details-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
}

:deep(.el-tabs__content) {
  flex: 1;
  overflow: auto;
  padding: 20px;
}

:deep(.el-form-item) {
  margin-bottom: 12px;
}

.fill-height-form {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.is-flexible {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 300px;
}

.is-flexible :deep(.el-form-item__content),
.is-flexible :deep(.el-textarea) {
  flex: 1;
}

.is-flexible :deep(.el-textarea__inner) {
  height: 100% !important;
  resize: vertical;
}

.full-width-form-column {
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
}

.title-components-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px 16px;
  margin-bottom: 20px;
}

.screenshot-container,
.poster-statement-split {
  display: flex;
  gap: 24px;
}

.poster-statement-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  height: 100%;
}

.left-panel,
.right-panel,
.form-column,
.preview-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.screenshot-text-column {
  flex: 3;
}

.screenshot-preview-column {
  flex: 7;
}

.carousel-container {
  height: 100%;
  background-color: #f5f7fa;
  border-radius: 4px;
  padding: 10px;
  min-height: 400px;
}

.carousel-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.carousel-image-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.poster-preview-section {
  flex: 1;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 16px;
  background-color: #f8f9fa;
  display: flex;
  flex-direction: column;
}

.preview-header {
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
  flex-shrink: 0;
}

.image-preview-container {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-image {
  max-width: 100%;
  max-height: 400px;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
}

.preview-placeholder {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  color: #909399;
  font-size: 14px;
}

.filtered-declarations-pane {
  display: flex;
  flex-direction: column;
}

.filtered-declarations-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.filtered-declarations-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.filtered-declarations-header h3 {
  margin: 0;
  font-size: 16px;
}

.filtered-declarations-content {
  flex: 1;
  overflow-y: auto;
}

.declaration-item {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
  background-color: #f8f9fa;
}

.declaration-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.declaration-content {
  margin: 0;
  padding: 12px;
  background-color: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 13px;
}

/* --- 步骤 1: 发布预览 --- */
.publish-preview-container {
  background: #fff;
  border-radius: 8px;
  padding: 5px 15px;
}

.publish-preview-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.preview-row {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background-color: #fff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  margin-bottom: 20px;
  overflow: hidden;
}

.row-label {
  font-weight: 600;
  padding: 12px 16px;
  color: #303133;
  border-bottom: 1px solid #e4e7ed;
  background-color: #f8f9fa;
  border-radius: 8px 8px 0 0;
  font-size: 16px;
  display: flex;
  align-items: center;
}

.row-label::before {
  content: "";
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background-color: #409eff;
  margin-right: 8px;
}

.row-content {
  padding: 16px;
  background-color: #fff;
}

.params-content {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  padding: 0;
}

.param-item {
  display: flex;
  flex-direction: column;
  padding: 16px;
  background-color: #f8f9fa;
  border-radius: 8px;
  border: 1px solid #e9ecef;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.param-item:hover {
  background-color: #fff;
  border-color: #dee2e6;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}

/* IMDb链接和标签在同一行的样式 */
.param-row {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

/* 响应式布局：小屏幕上垂直排列 */
@media (max-width: 768px) {
  .param-row {
    flex-direction: column;
  }

  .half-width {
    width: 100%;
  }
}

.half-width {
  flex: 1;
}

.imdb-item {
  background-color: #e3f2fd;
  border-color: #bbdefb;
}

.imdb-item:hover {
  background-color: #bbdefb;
  border-color: #90caf9;
}

/* IMDb和标签项的内容布局 */
.imdb-item,
.tags-item {
  display: flex;
  flex-direction: column;
}

.imdb-item .param-value,
.tags-item .param-value {
  word-break: break-all;
  line-height: 1.4;
}

.tags-item {
  background-color: #f3e5f5;
  border-color: #ce93d8;
}

.tags-item:hover {
  background-color: #ce93d8;
  border-color: #ba68c8;
}

/* 标签值的特殊处理 */
.tags-item .param-value {
  flex-wrap: wrap;
}

/* 行内参数样式 */
.inline-param {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  padding: 12px 16px;
}

.inline-param .param-label {
  min-width: 80px;
  margin-bottom: 0;
  font-size: 14px;
  padding-top: 2px;
}

.inline-param .param-value {
  flex: 1;
  margin-left: 8px;
  font-size: 14px;
  word-break: break-word;
}

.param-label {
  font-weight: 600;
  color: #495057;
  font-size: 13px;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  display: flex;
  align-items: center;
}

.param-label::before {
  content: "";
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: #409eff;
  margin-right: 6px;
}

.param-value {
  color: #212529;
  font-size: 14px;
  word-break: break-word;
  line-height: 1.5;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
}

.param-value.empty {
  color: #909399;
  font-style: italic;
}

.mediainfo-pre {
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
  max-height: 300px;
  overflow: auto;
}

.section-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

/* BBCode 渲染样式 */
.section-content :deep(blockquote) {
  margin: 10px 0;
  padding: 10px 15px;
  border-left: 4px solid #409eff;
  background-color: #f5f7fa;
  color: #606266;
}

.section-content :deep(strong) {
  font-weight: bold;
}

.section-content :deep(.bbcode-size-5) {
  font-size: 18px;
}

.section-content :deep(.bbcode-size-4) {
  font-size: 16px;
}

.description-row {
  margin-bottom: 30px;
}

.section-title {
  font-weight: bold;
  margin: 15px 0 10px 0;
  color: #303133;
}

.image-gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 10px 0;
}

.preview-image-inline {
  width: 100%;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  object-fit: contain;
}

/* --- 步骤 2: 选择站点 --- */
.site-selection-container {
  text-align: center;
  background: #fff;
  border-radius: 8px;
}

.selection-title {
  font-size: 20px;
  font-weight: 500;
  color: #303133;
}

.selection-subtitle {
  color: #909399;
  margin: 8px 0 24px 0;
}

.select-all-container {
  margin-bottom: 24px;
}

.site-buttons-group {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}

.site-button {
  min-width: 120px;
}

.site-button.is-disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* --- 步骤 3: 发布结果 --- */
.results-grid-container {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  justify-content: center;
  align-content: flex-start;
}

.result-card {
  width: 280px;
  height: 200px;
  /* 增加一点高度以容纳下载器状态 */
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.05);
  padding: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  background: #fff;
}

.result-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
}

.result-card.is-success {
  border-top: 4px solid #67C23A;
}

.result-card.is-error {
  border-top: 4px solid #F56C6C;
}

.card-icon {
  margin-bottom: 12px;
}

.card-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: #303133;
}

.existed-tag {
  margin-bottom: 8px;
}

.card-extra {
  margin-top: auto;
  /* 将按钮推到底部 */
  padding-top: 8px;
  display: flex;
  justify-content: center;
  gap: 8px;
}

.downloader-status {
  display: flex;
  align-items: center;
  margin: 4px 0 8px 0;
  padding: 4px 8px;
  border-radius: 4px;
  background-color: #f5f7fa;
  font-size: 12px;
  width: 100%;
}

.status-icon {
  margin-right: 6px;
  display: flex;
  align-items: center;
}

.status-text.success {
  color: #67C23A;
}

.status-text.error {
  color: #F56C6C;
}

/* --- 进度条样式 --- */
.progress-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 30px;
  padding: 20px;
  background-color: #f5f7fa;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.progress-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-label {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.progress-text {
  font-size: 12px;
  color: #606266;
  text-align: right;
}

/* --- 日志弹窗 --- */
.log-card-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  z-index: 1999;
}

.log-card {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 75vw;
  max-width: 900px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  max-height: 80vh;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.log-card :deep(.el-card__body) {
  overflow-y: auto;
  flex: 1;
}

.log-content-pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  margin: 0;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  color: #606266;
}

.code-font,
.code-font :deep(.el-textarea__inner) {
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}
</style>
