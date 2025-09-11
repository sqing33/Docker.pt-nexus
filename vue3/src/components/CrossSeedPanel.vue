<template>
  <div class="cross-seed-panel">
    <div class="steps-header">
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
    </div>

    <div class="panel-content">
      <!-- 步骤 0: 核对种子详情 -->
      <div v-if="activeStep === 0" class="details-container">
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
          <el-tab-pane label="发布参数预览" name="publish-preview" class="params-pane">
            <div class="code-block fill-height-pre">
              <pre>{{ JSON.stringify(torrentData.final_publish_parameters, (key, value) => {
                // 为了更好的可读性，如果简介或Mediainfo过长，则进行截断
                if ((key === '简介 (完整BBCode)' || key === 'Mediainfo') && typeof value === 'string' && value.length > 1000) {
                  return value.substring(0, 1000) + '\n\n... (内容过长，已截断显示)';
                }
                return value;
              }, 2) }}</pre>
            </div>
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
        <div class="button-group">
          <el-button @click="$emit('cancel')">取消</el-button>
          <el-button type="primary" @click="goToSelectSiteStep" :disabled="isLoading || !canProceedToNextStep">
            下一步：选择发布站点
          </el-button>
        </div>
      </div>

      <!-- 步骤 1: 选择发布站点 -->
      <div v-if="activeStep === 1" class="form-container">
        <div class="site-selection-container">
          <h3 class="selection-title">请选择要发布的目标站点 (可多选)</h3>
          <div class="select-all-container">
            <el-button @click="selectAllTargetSites" size="small" type="primary" plain>
              全选
            </el-button>
            <el-button @click="clearAllTargetSites" size="small" type="danger" plain>
              清空
            </el-button>
          </div>
          <div class="site-buttons-group">
            <el-button 
              v-for="site in allSitesStatus.filter(s => s.is_target)" :key="site.name"
              :type="selectedTargetSites.includes(site.name) ? 'primary' : 'default'"
              :class="{ 'site-button': true, 'is-disabled': !isTargetSiteSelectable(site.name) }"
              :disabled="!isTargetSiteSelectable(site.name)"
              @click="toggleSiteSelection(site.name)">
              {{ site.name }}
            </el-button>
          </div>
        </div>
        <div class="button-group">
          <el-button @click="handlePreviousStep" :disabled="isLoading">上一步</el-button>
          <el-button type="success" @click="handlePublish" :loading="isLoading"
            :disabled="selectedTargetSites.length === 0">
            确认并发布种子
          </el-button>
        </div>
      </div>

      <!-- 步骤 2: 完成发布 -->
      <div v-if="activeStep === 2" class="form-container">
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
              <span class="status-text" :class="{ 'success': result.downloaderStatus.success, 'error': !result.downloaderStatus.success }">
                {{ result.downloaderStatus.success ? `成功将种子添加到下载器 '${result.downloaderStatus.downloaderName}'` : '添加失败' }}
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
        <div class="button-group">
          <el-button type="primary" @click="$emit('complete')">完成</el-button>
        </div>
      </div>
    </div>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElNotification, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { Refresh, CircleCheckFilled, CircleCloseFilled, Close } from '@element-plus/icons-vue'

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

// ======================= [核心修改点 1] =======================
// 将 removed_ardtudeclarations 的初始值设为空数组 []
const getInitialTorrentData = () => ({
  title_components: [] as { key: string, value: string }[],
  original_main_title: '',
  subtitle: '',
  imdb_link: '',
  douban_link: '',
  intro: { statement: '', poster: '', body: '', screenshots: '', removed_ardtudeclarations: [] },
  mediainfo: '',
  source_params: {},
  final_publish_parameters: {}, // <-- [新增] 为新数据添加一个空的初始对象
})

const parseImageUrls = (text: string) => {
  if (!text || typeof text !== 'string') return []
  const regex = /\[img\](https?:\/\/[^\s[\]]+)\[\/img\]/gi
  const matches = [...text.matchAll(regex)]
  return matches.map((match) => match[1])
}

const activeStep = ref(0)
const activeTab = ref('main')

const steps = [
  { title: '核对种子详情' },
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
// 添加下载器列表状态
const downloaderList = ref<{id: string, name: string}[]>([])
const posterImages = computed(() => parseImageUrls(torrentData.value.intro.poster))
const screenshotImages = computed(() => parseImageUrls(torrentData.value.intro.screenshots))

// ======================= [核心修改点 2] =======================
// 直接返回数组，不再执行 split 操作
const filteredDeclarationsList = computed(() => {
  const removedDeclarations = torrentData.value.intro.removed_ardtudeclarations;
  // 确保返回的是一个数组
  if (Array.isArray(removedDeclarations)) {
    return removedDeclarations;
  }
  return [];
})
const filteredDeclarationsCount = computed(() => filteredDeclarationsList.value.length)

// const sourceSitesList = computed(() => allSitesStatus.value.filter(s => s.is_source));
// 修改targetSitesList计算属性，排除当前种子已存在的站点
// 检查目标站点是否可选（即种子是否已在该站点做种）
const isTargetSiteSelectable = (siteName: string): boolean => {
  // 如果没有torrent数据，所有站点都可选
  if (!props.torrent || !props.torrent.sites) {
    return true;
  }
  
  // 检查种子是否已在该站点做种
  return !props.torrent.sites[siteName];
};

// 检查是否可以进入下一步
const canProceedToNextStep = computed(() => {
  // 如果正在加载，不能进入下一步
  if (isLoading.value) {
    return false;
  }
  
  // 如果正在重新解析标题，不能进入下一步
  if (isReparsing.value) {
    return false;
  }
  
  // 检查是否有截图正在上传（通过检查是否有失效截图的报告）
  if (reportedFailedScreenshots.value) {
    // 如果有失效截图但截图预览区域没有图片，则说明还在上传中
    if (screenshotImages.value.length === 0 && torrentData.value.intro.screenshots) {
      return false;
    }
  }
  
  // 检查是否有无法识别的参数
  const titleComponents = torrentData.value.title_components;
  if (titleComponents && Array.isArray(titleComponents)) {
    // 查找是否有"无法识别"的参数且值不为空
    const unrecognizedParam = titleComponents.find(
      param => param.key === "无法识别" && param.value && param.value.trim() !== ""
    );
    if (unrecognizedParam) {
      return false;
    }
  }
  
  // 检查是否已填写主要信息
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
        // 重置截图上传状态
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
    
    // 同时获取下载器列表
    const downloaderResponse = await axios.get('/api/downloaders_list');
    downloaderList.value = downloaderResponse.data;
  } catch (error) {
    ElNotification.error({ title: '错误', message: '无法从服务器获取站点状态列表或下载器列表' });
  }
}

const fetchTorrentInfo = async () => {
  if (!props.sourceSite || !props.torrent) return;

  const siteDetails = props.torrent.sites[props.sourceSite];
  const idMatch = siteDetails.comment.match(/id=(\d+)/);
  if (!idMatch || !idMatch[1]) {
    ElNotification.error(`无法从源站点 ${props.sourceSite} 的链接中提取种子ID。`);
    emit('cancel');
    return;
  }
  const torrentId = idMatch[1];

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

const goToSelectSiteStep = () => {
  activeStep.value = 1;
}

const toggleSiteSelection = (siteName: string) => {
  const index = selectedTargetSites.value.indexOf(siteName)
  if (index > -1) {
    selectedTargetSites.value.splice(index, 1)
  } else {
    selectedTargetSites.value.push(siteName)
  }
}

// 全选所有可选的目标站点
const selectAllTargetSites = () => {
  const selectableSites = allSitesStatus.value
    .filter(s => s.is_target && isTargetSiteSelectable(s.name))
    .map(s => s.name);
  selectedTargetSites.value = selectableSites;
}

// 清空所有已选的目标站点
const clearAllTargetSites = () => {
  selectedTargetSites.value = [];
}

const handlePublish = async () => {
  isLoading.value = true
  finalResultsList.value = []
  ElNotification({
    title: '正在发布',
    message: `准备向 ${selectedTargetSites.value.length} 个站点发布种子...`,
    type: 'info',
    duration: 0,
  })

  const results = []
  
  // Sequential processing to prevent network overload
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
      
      // 检查是否是种子已存在的情况
      if (response.data.logs && response.data.logs.includes("种子已存在")) {
        result.isExisted = true;
      }
      
      results.push(result)
      
      // Update UI with intermediate results
      finalResultsList.value = [...results]
      
      // Show individual success notification
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
      
      // Show individual error notification
      ElNotification.error({
        title: `发布失败 - ${siteName}`,
        message: result.message
      })
    }
    
    // Add a small delay between requests to reduce server load
    await new Promise(resolve => setTimeout(resolve, 1000))
  }

  ElNotification.closeAll()
  const successCount = results.filter(r => r.success).length
  ElNotification.success({
    title: '发布完成',
    message: `成功发布到 ${successCount} / ${selectedTargetSites.value.length} 个站点。`
  })

  logContent.value += '\n\n--- [开始自动添加任务] ---';
  // 创建一个映射来存储每个站点的下载器状态
  const downloaderStatusMap: Record<string, { success: boolean, message: string, downloaderName: string }> = {};
  
  for (const result of results) {
    if (result.success && result.url) {
      const downloaderStatus = await triggerAddToDownloader(result);
      downloaderStatusMap[result.siteName] = downloaderStatus;
    } else {
      downloaderStatusMap[result.siteName] = { success: false, message: "发布失败，跳过添加到下载器", downloaderName: "" };
    }
  }
  logContent.value += '\n--- [自动添加任务结束] ---';

  // Create separate logs for each site, including downloader status
  const siteLogs = results.map(r => {
    let logEntry = `--- Log for ${r.siteName} ---\n${r.logs || 'No logs available.'}`
    
    // Add downloader status to the log if available
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

  // 将下载器状态添加到结果中
  finalResultsList.value = results.map(result => ({
    ...result,
    downloaderStatus: downloaderStatusMap[result.siteName]
  }));

  activeStep.value = 2
  isLoading.value = false
}

const handlePreviousStep = () => {
  if (activeStep.value > 0) {
    activeStep.value--
  }
}

const getCleanMessage = (logs: string): string => {
  if (!logs || logs === '发布成功') return '发布成功'

  // 检查是否包含种子已存在的信息
  if (logs.includes("种子已存在")) {
    return '种子已存在，发布成功'
  }

  const lines = logs.split('\n').filter(line => {
    return line && !line.includes('--- [步骤') && !line.includes('INFO - ---')
  })

  const cleanLines = lines.map(line => {
    return line.replace(/^\d{2}:\d{2}:\d{2} - \w+ - /, '')
  })

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
    return { success: false, message: "未能获取到原始保存路径或下载器ID，已跳过自动添加任务。", downloaderName: "" };
  }

  // 获取默认下载器设置
  let targetDownloaderId = props.torrent.downloaderId;
  let targetDownloaderName = "";
  
  try {
    // 获取配置以确定使用的下载器
    const configResponse = await axios.get('/api/settings');
    const config = configResponse.data;
    const defaultDownloaderId = config.cross_seed?.default_downloader;
    
    // 如果使用了默认下载器设置
    if (defaultDownloaderId) {
      targetDownloaderId = defaultDownloaderId;
      // 查找下载器名称
      const downloader = downloaderList.value.find(d => d.id === defaultDownloaderId);
      targetDownloaderName = downloader ? downloader.name : "未知下载器";
    } else {
      // 使用源种子所在的下载器
      const downloader = downloaderList.value.find(d => d.id === props.torrent.downloaderId);
      targetDownloaderName = downloader ? downloader.name : "未知下载器";
    }
  } catch (error) {
    targetDownloaderName = "未知下载器";
  }

  logContent.value += `\n[${result.siteName}] 正在尝试将新种子添加到下载器...`;

  try {
    const response = await axios.post('/api/migrate/add_to_downloader', {
      url: result.url,
      savePath: props.torrent.save_path,
      downloaderPath: props.torrent.save_path,
      downloaderId: props.torrent.downloaderId,
      useDefaultDownloader: true, // 添加这个参数以使用默认下载器设置
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
    logContent.value += `\n[${result.siteName}] 错误: 调用“添加到下载器”API失败: ${errorMessage}`;
    return { success: false, message: `调用“添加到下载器”API失败: ${errorMessage}`, downloaderName: targetDownloaderName };
  }
}

const showLogs = async () => {
  if (!taskId.value) {
    ElNotification.warning('没有可用的任务日志')
    return
  }

  try {
    const response = await axios.get(`/api/migrate/logs/${taskId.value}`)
    if (response.data.success) {
      ElNotification.info({
        title: '转种日志',
        message: response.data.logs,
        duration: 0,
        showClose: true
      })
    } else {
      ElNotification.error('获取日志失败')
    }
  } catch (error) {
    handleApiError(error, '获取日志时发生错误')
  }
}

const hideLog = () => {
  showLogCard.value = false
}

// 添加显示特定站点日志的函数
const showSiteLog = (siteName: string, logs: string) => {
  // 查找该站点的完整日志信息
  let siteLogContent = `--- Log for ${siteName} ---\n${logs || 'No logs available.'}`;
  
  // 添加下载器状态信息
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
  
  // 使用与左上角查看日志相同的样式
  logContent.value = siteLogContent;
  showLogCard.value = true;
}

onMounted(() => {
  fetchSitesStatus();
  fetchTorrentInfo();
});
</script>

<style scoped>
/* [所有样式保持不变] */
.cross-seed-panel {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.steps-header {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  margin: 0;
  height: 75px;
  width: 100%;
}

.steps-header .el-button {
  position: absolute;
  left: 0;
}

.custom-steps {
  display: flex;
  align-items: center;
  width: auto;
  height: 100%;
  margin: 0 auto;
}

.custom-step {
  display: flex;
  align-items: center;
  position: relative;
  min-width: 0;
}

.custom-step:not(.last) {
  flex: 1;
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
  overflow: hidden;
  text-overflow: ellipsis;
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

.custom-step.last {
  flex: 0 0 auto;
}

.custom-step.completed+.custom-step .step-connector,
.custom-step.active+.custom-step .step-connector {
  background-color: #67c23a;
}

.panel-content {
  flex: 1;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease-in-out;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.details-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.details-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

:deep(.el-tabs__content) {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
}

.details-tabs .el-tab-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.fill-height-form {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.is-flexible {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.is-flexible :deep(.el-form-item__content),
.is-flexible :deep(.el-textarea) {
  flex: 1;
}

.is-flexible :deep(.el-textarea__inner) {
  height: 100%;
  resize: none;
}

.main-info-container,
.screenshot-container {
  display: flex;
  gap: 24px;
  height: 100%;
  min-height: 0;
}

.form-column,
.preview-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.screenshot-container .screenshot-text-column {
  flex: 3;
  min-width: 0;
}

.screenshot-container .screenshot-preview-column {
  flex: 7;
  min-width: 0;
}

.carousel-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background-color: #f5f7fa;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  padding: 0 10px;
}

.carousel-image-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.carousel-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
}

.image-preview-pane {
  flex: 1;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 8px;
  background-color: #f8f9fa;
  overflow-y: auto;
}

.preview-image {
  max-width: 100%;
  display: block;
  margin-bottom: 8px;
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

.params-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.filtered-declarations-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.filtered-declarations-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.filtered-declarations-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 0 8px;
}

.filtered-declarations-header h3 {
  margin: 0;
  color: #303133;
  font-size: 16px;
}

.filtered-declarations-content {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
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

.declaration-number {
  font-weight: 600;
  color: #606266;
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
  line-height: 1.4;
  max-height: 200px;
  overflow-y: auto;
}

.downloader-status {
  display: flex;
  align-items: center;
  margin: 8px 0;
  padding: 6px 12px;
  border-radius: 4px;
  background-color: #f5f7fa;
  font-size: 14px;
}

.status-icon {
  margin-right: 6px;
  display: flex;
  align-items: center;
}

.status-text.success {
  color: #67C23A;
  font-weight: 500;
}

.status-text.error {
  color: #F56C6C;
  font-weight: 500;
}

.card-extra {
  margin-top: 12px;
  display: flex;
  justify-content: center;
  gap: 8px;
}

.site-log-dialog {
  width: 600px;
}

.site-log-dialog .el-message-box__content {
  padding: 20px;
}

.site-log-dialog .el-message-box__message {
  white-space: pre-wrap;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  line-height: 1.5;
  max-height: 400px;
  overflow-y: auto;
}

.code-block {
  background-color: #f8f9fa;
  padding: 16px;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}

.fill-height-pre {
  flex: 1;
  overflow: auto;
  margin: 0;
}

.title-components-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px 16px;
  margin-bottom: 20px;
}

:deep(.title-components-grid .el-form-item) {
  margin-bottom: 0;
}

:deep(.el-form-item) {
  margin-bottom: 8px;
}

.form-container {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.site-selection-container {
  padding: 20px;
  text-align: center;
  flex: 1;
}

.selection-title {
  margin-bottom: 24px;
  color: #303133;
  font-weight: 500;
}

.site-buttons-group {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}

.select-all-container {
  margin-bottom: 16px;
  text-align: center;
}

.site-button {
  min-width: 120px;
  transition: all 0.2s;
}

.site-button.is-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.results-grid-container {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  justify-content: center;
  padding: 20px;
  align-content: flex-start;
  overflow-y: auto;
  max-height: 500px;
}

.result-card {
  width: 280px;
  height: 180px;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.05);
  padding: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
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

.card-message {
  font-size: 0.85rem;
  color: #909399;
  margin: 0 0 12px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.4;
  height: calc(1.4em * 2);
}

.card-extra a {
  font-size: 0.9rem;
  color: #409EFF;
  text-decoration: none;
  font-weight: 500;
}

.card-extra a:hover {
  text-decoration: underline;
}

.full-width-form-column {
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
}

.bottom-info-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.poster-statement-container {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.poster-statement-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  height: 100%;
}

.left-panel,
.right-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.statement-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.statement-item :deep(.el-form-item__content) {
  flex: 1;
}

.statement-item :deep(.el-textarea) {
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

.image-preview-container {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-header {
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
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

.button-group {
  margin-top: auto;
  padding: 16px;
  display: flex;
  justify-content: center;
  gap: 16px;
  border-top: 1px solid #e4e7ed;
  background-color: #f8f9fa;
  flex-shrink: 0;
}

.code-font :deep(.el-textarea__inner) {
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
  background-color: #f8f9fa;
}

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
</style>
