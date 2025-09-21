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
                      <el-form-item v-for="param in filteredTitleComponents" :key="param.key" :label="param.key">
                        <el-input v-model="param.value" />
                      </el-form-item>
                    </div>
                  </div>

                  <div class="bottom-info-section">
                    <div class="subtitle-unrecognized-grid">
                      <!-- 副标题占3列 -->
                      <div class="subtitle-section">
                        <el-form-item label="副标题">
                          <el-input v-model="torrentData.subtitle" />
                        </el-form-item>
                      </div>
                      <!-- 无法识别占2列 -->
                      <div class="unrecognized-section">
                        <el-form-item v-if="unrecognizedComponent" :key="unrecognizedComponent.key"
                          :label="unrecognizedComponent.key">
                          <el-input v-model="unrecognizedComponent.value" />
                        </el-form-item>
                      </div>
                    </div>

                    <!-- 标准参数区域 -->
                    <div class="standard-params-section">
                      <!-- 第一行：类型、媒介、视频编码、音频编码、分辨率 -->
                      <div class="standard-params-grid">
                        <el-form-item label="类型 (type)">
                          <el-select v-model="torrentData.standardized_params.type" placeholder="请选择类型" clearable>
                            <el-option v-for="(label, value) in reverseMappings.type" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="媒介 (medium)">
                          <el-select v-model="torrentData.standardized_params.medium" placeholder="请选择媒介" clearable>
                            <el-option v-for="(label, value) in reverseMappings.medium" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="视频编码 (video_codec)">
                          <el-select v-model="torrentData.standardized_params.video_codec" placeholder="请选择视频编码"
                            clearable>
                            <el-option v-for="(label, value) in reverseMappings.video_codec" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="音频编码 (audio_codec)">
                          <el-select v-model="torrentData.standardized_params.audio_codec" placeholder="请选择音频编码"
                            clearable>
                            <el-option v-for="(label, value) in reverseMappings.audio_codec" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="分辨率 (resolution)">
                          <el-select v-model="torrentData.standardized_params.resolution" placeholder="请选择分辨率"
                            clearable>
                            <el-option v-for="(label, value) in reverseMappings.resolution" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>
                      </div>

                      <!-- 第二行：制作组、产地、标签特殊布局 -->
                      <div class="standard-params-grid second-row">
                        <el-form-item label="制作组 (team)">
                          <el-select v-model="torrentData.standardized_params.team" placeholder="请选择制作组" clearable
                            filterable allow-create default-first-option>
                            <el-option v-for="(label, value) in reverseMappings.team" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="产地 (source)">
                          <el-select v-model="torrentData.standardized_params.source" placeholder="请选择产地" clearable>
                            <el-option v-for="(label, value) in reverseMappings.source" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="标签 (tags)" class="tags-wide-item">
                          <el-select v-model="torrentData.standardized_params.tags" multiple filterable allow-create
                            default-first-option placeholder="请选择或输入标签" style="width: 100%">
                            <el-option v-for="(label, value) in reverseMappings.tags" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <!-- 占位符1：保持5列结构 -->
                        <div class="placeholder-item"></div>

                        <!-- 占位符2：保持5列结构 -->
                        <div class="placeholder-item"></div>
                      </div>
                    </div>
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
                  <el-form-item class="is-flexible">
                    <template #label>
                      <div class="form-label-with-button">
                        <span>截图</span>
                        <el-button :icon="Refresh" @click="refreshScreenshots" :loading="isRefreshingScreenshots"
                          size="small" type="primary">
                          重新获取
                        </el-button>
                      </div>
                    </template>
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
              <el-form-item class="is-flexible">
                <template #label>
                  <div class="form-label-with-button">
                    <span>正文</span>
                    <el-button :icon="Refresh" @click="refreshIntro" :loading="isRefreshingIntro" size="small"
                      type="primary">
                      重新获取
                    </el-button>
                  </div>
                </template>
                <el-input type="textarea" v-model="torrentData.intro.body" :rows="18" />
              </el-form-item>
              <el-form-item label="豆瓣链接" v-if="torrentData.douban_link">
                <el-input v-model="torrentData.douban_link" placeholder="请输入豆瓣电影链接" />
              </el-form-item>
              <el-form-item label="IMDb链接" v-if="torrentData.imdb_link">
                <el-input v-model="torrentData.imdb_link" placeholder="请输入IMDb电影链接" />
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
              {{ torrentData.final_publish_parameters?.['主标题 (预览)'] || torrentData.original_main_title || '暂无数据' }}
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
                  <span
                    :class="['param-value', { 'empty': !torrentData.imdb_link || torrentData.imdb_link === 'N/A' }]">
                    {{ torrentData.imdb_link || 'N/A' }}
                  </span>
                </div>
                <div class="param-item tags-item half-width">
                  <span class="param-label">标签：</span>
                  <span :class="['param-value', { 'empty': !getMappedTags() || getMappedTags().length === 0 }]">
                    {{ getMappedTags().join(', ') || 'N/A' }}
                  </span>
                </div>
              </div>

              <!-- 其他参数在第二行开始排列 -->
              <div class="params-content">
                <div class="param-item inline-param">
                  <span class="param-label">类型：</span>
                  <span :class="['param-value', { 'empty': !getMappedValue('type') }]">
                    {{ getMappedValue('type') || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">媒介：</span>
                  <span :class="['param-value', { 'empty': !getMappedValue('medium') }]">
                    {{ getMappedValue('medium') || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">视频编码：</span>
                  <span :class="['param-value', { 'empty': !getMappedValue('video_codec') }]">
                    {{ getMappedValue('video_codec') || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">音频编码：</span>
                  <span :class="['param-value', { 'empty': !getMappedValue('audio_codec') }]">
                    {{ getMappedValue('audio_codec') || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">分辨率：</span>
                  <span :class="['param-value', { 'empty': !getMappedValue('resolution') }]">
                    {{ getMappedValue('resolution') || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">制作组：</span>
                  <span :class="['param-value', { 'empty': !getMappedValue('team') }]">
                    {{ getMappedValue('team') || 'N/A' }}
                  </span>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">产地/来源：</span>
                  <span :class="['param-value', { 'empty': !getMappedValue('source') }]">
                    {{ getMappedValue('source') || 'N/A' }}
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
            <el-progress :percentage="Math.round((publishProgress.current / publishProgress.total) * 100)"
              :show-text="true" />
            <div class="progress-text">{{ publishProgress.current }} / {{ publishProgress.total }}</div>
          </div>
          <div class="progress-item" v-if="downloaderProgress.total > 0">
            <div class="progress-label">下载器添加进度:</div>
            <el-progress :percentage="Math.round((downloaderProgress.current / downloaderProgress.total) * 100)"
              :show-text="true" />
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
        <el-tooltip :content="isScrolledToBottom ? '' : '请先滚动到页面底部'" :disabled="isScrolledToBottom" placement="top">
          <el-button type="primary" @click="goToSelectSiteStep" :disabled="isLoading || !isScrolledToBottom"
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
  site: string;
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
  standardized_params: {
    type: '',
    medium: '',
    video_codec: '',
    audio_codec: '',
    resolution: '',
    team: '',
    source: '',
    tags: [] as string[]
  },
  final_publish_parameters: {},
  complete_publish_params: {},
  raw_params_for_preview: {}
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
const isRefreshingScreenshots = ref(false)
const isRefreshingIntro = ref(false)
const reportedFailedScreenshots = ref(false)
const logContent = ref('')
const showLogCard = ref(false)
const downloaderList = ref<{ id: string, name: string }[]>([])

// 反向映射表，用于将标准值映射到中文显示名称
const reverseMappings = ref({
  type: {},
  medium: {},
  video_codec: {},
  audio_codec: {},
  resolution: {},
  source: {},
  team: {},
  tags: {}
})

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

const refreshIntro = async () => {
  if (!torrentData.value.douban_link && !torrentData.value.imdb_link) {
    ElNotification.warning('没有豆瓣或IMDb链接，无法重新获取简介。');
    return;
  }

  isRefreshingIntro.value = true;
  ElNotification.info({
    title: '正在重新获取',
    message: '正在从豆瓣/IMDb重新获取简介...',
    duration: 0
  });

  const payload = {
    type: 'intro',
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: props.sourceSite,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
    }
  };

  try {
    const response = await axios.post('/api/media/validate', payload);
    ElNotification.closeAll();

    if (response.data.success && response.data.intro) {
      torrentData.value.intro.body = response.data.intro;

      // 如果返回了新的IMDb链接，也更新它
      if (response.data.extracted_imdb_link && !torrentData.value.imdb_link) {
        torrentData.value.imdb_link = response.data.extracted_imdb_link;
      }

      ElNotification.success({
        title: '重新获取成功',
        message: '已成功从豆瓣/IMDb获取并更新了简介内容。',
      });
    } else {
      ElNotification.error({
        title: '重新获取失败',
        message: response.data.error || '无法从豆瓣/IMDb获取简介。',
      });
    }
  } catch (error: any) {
    ElNotification.closeAll();
    const errorMsg = error.response?.data?.error || '重新获取简介时发生网络错误';
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    });
  } finally {
    isRefreshingIntro.value = false;
  }
};

const refreshScreenshots = async () => {
  if (!torrentData.value.original_main_title) {
    ElNotification.warning('标题为空，无法重新获取截图。');
    return;
  }

  isRefreshingScreenshots.value = true;
  ElNotification.info({
    title: '正在重新获取',
    message: '正在从视频重新生成截图...',
    duration: 0
  });

  const payload = {
    type: 'screenshot',
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: props.sourceSite,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
    },
    savePath: props.torrent.save_path,
    torrentName: props.torrent.name
  };

  try {
    const response = await axios.post('/api/media/validate', payload);
    ElNotification.closeAll();

    if (response.data.success && response.data.screenshots) {
      torrentData.value.intro.screenshots = response.data.screenshots;
      ElNotification.success({
        title: '重新获取成功',
        message: '已成功生成并加载了新的截图。',
      });
    } else {
      ElNotification.error({
        title: '重新获取失败',
        message: response.data.error || '无法从后端获取新的截图。',
      });
    }
  } catch (error: any) {
    ElNotification.closeAll();
    const errorMsg = error.response?.data?.error || '重新获取截图时发生网络错误';
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    });
  } finally {
    isRefreshingScreenshots.value = false;
  }
};

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

// 通过中文站点名获取英文站点名，用于数据库查询
const getEnglishSiteName = async (chineseSiteName: string): Promise<string> => {
  // 首先尝试从已加载的 allSitesStatus 中获取
  const siteInfo = allSitesStatus.value.find((s: any) => s.name === chineseSiteName);
  if (siteInfo?.site) {
    return siteInfo.site;
  }

  // 如果 allSitesStatus 还没有加载，直接调用接口获取站点信息
  try {
    const response = await axios.get('/api/sites/status');
    allSitesStatus.value = response.data;

    // 再次尝试从更新的 allSitesStatus 中获取
    const updatedSiteInfo = allSitesStatus.value.find((s: any) => s.name === chineseSiteName);
    if (updatedSiteInfo?.site) {
      return updatedSiteInfo.site;
    }
  } catch (error) {
    console.warn('获取站点状态失败:', error);
  }

  // 最后后备方案：使用常见的站点映射
  const commonSiteMapping: Record<string, string> = {
    '人人': 'audiences',
    '不可说': 'ssd',
    '憨憨': 'hhanclub',
    '财神': 'cspt'
    // 可以添加更多常见映射
  };

  return commonSiteMapping[chineseSiteName] || chineseSiteName.toLowerCase();
};

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
    message: '正在读取种子信息，请稍候...',
    type: 'info',
    duration: 0,
  })

  let dbError = null;

  // 步骤1: 尝试从数据库读取种子信息
  try {
    const englishSiteName = await getEnglishSiteName(props.sourceSite);
    console.log(`尝试从数据库读取种子信息: ${torrentId} from ${props.sourceSite} (${englishSiteName})`);
    const dbResponse = await axios.get('/api/migrate/get_db_seed_info', {
      params: {
        torrent_id: torrentId,
        site_name: englishSiteName
      },
      timeout: 10000 // 10秒超时
    });

    if (dbResponse.data.success) {
      ElNotification.closeAll();
      ElNotification.success({
        title: '读取成功',
        message: '种子信息已从数据库成功加载，请核对。'
      });

      // 验证数据库返回的数据完整性
      const dbData = dbResponse.data.data;
      if (!dbData || !dbData.title) {
        throw new Error('数据库返回的种子信息不完整');
      }

      // 从后端响应中提取反向映射表
      if (dbResponse.data.reverse_mappings) {
        reverseMappings.value = dbResponse.data.reverse_mappings;
        console.log('成功加载反向映射表:', reverseMappings.value);
        console.log('type映射数量:', Object.keys(reverseMappings.value.type || {}).length);
        console.log('当前standardized_params:', dbData.standardized_params);
      } else {
        console.warn('后端未返回反向映射表，将使用空的默认映射');
      }

      // 从数据库返回的数据中提取相关信息
      torrentData.value = {
        original_main_title: dbData.title,
        title_components: dbData.title_components || [],
        subtitle: dbData.subtitle,
        imdb_link: dbData.imdb_link,
        douban_link: dbData.douban_link,
        intro: {
          statement: dbData.statement || '',
          poster: dbData.poster || '',
          body: dbData.body || '',
          screenshots: dbData.screenshots || '',
          removed_ardtudeclarations: dbData.removed_ardtudeclarations || []
        },
        mediainfo: dbData.mediainfo || '',
        source_params: dbData.source_params || {},
        standardized_params: {
          type: dbData.type || '',
          medium: dbData.medium || '',
          video_codec: dbData.video_codec || '',
          audio_codec: dbData.audio_codec || '',
          resolution: dbData.resolution || '',
          team: dbData.team || '',
          source: dbData.source || '',
          tags: dbData.tags || []
        },
        final_publish_parameters: dbData.final_publish_parameters || {},
        complete_publish_params: dbData.complete_publish_params || {},
        raw_params_for_preview: dbData.raw_params_for_preview || {}
      };

      // 如果没有解析过的标题组件，自动解析主标题
      if ((!dbData.title_components || dbData.title_components.length === 0) && dbData.title) {
        try {
          const parseResponse = await axios.post('/api/utils/parse_title', { title: dbData.title });
          if (parseResponse.data.success) {
            torrentData.value.title_components = parseResponse.data.components;
            ElNotification.info({
              title: '标题解析',
              message: '已自动解析主标题为组件信息。'
            });
          }
        } catch (error) {
          console.warn('自动解析标题失败:', error);
        }
      }

      console.log('设置torrentData.standardized_params:', torrentData.value.standardized_params);
      console.log('检查绑定 - type:', torrentData.value.standardized_params.type);
      console.log('检查绑定 - medium:', torrentData.value.standardized_params.medium);

      // 如果数据库中有task_id信息，也可以设置（使用英文站点名）
      taskId.value = `db_${torrentId}_${englishSiteName}`;

      // 自动提取链接的逻辑保持不变
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

      activeStep.value = 0;
      return;
    } else {
      // 数据库中不存在该记录，这是正常情况，不需要记录为错误
      console.log('数据库中没有找到种子信息，开始抓取数据...');
    }
  } catch (error) {
    // 捕获数据库读取错误，但继续执行抓取逻辑
    dbError = error;
    console.log('从数据库读取失败，开始抓取数据...', error);

    // 区分网络错误和其他错误
    if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
      console.warn('数据库读取超时，将尝试直接抓取数据...');
    } else if (error.response?.status >= 500) {
      console.warn('数据库服务器错误，将尝试直接抓取数据...');
    } else {
      console.warn('数据库读取发生未知错误，将尝试直接抓取数据...');
    }
  }

  // 步骤2: 如果数据库中没有数据，则进行抓取和存储
  try {
    ElNotification.closeAll();
    ElNotification({
      title: '正在抓取',
      message: '正在从源站点抓取种子信息并存储到数据库...',
      type: 'info',
      duration: 0,
    });

    // 如果有数据库错误，显示警告信息
    if (dbError) {
      console.warn(`由于数据库读取失败（${dbError.message}），正在直接抓取数据...`);
      ElNotification.warning({
        title: '数据库读取失败',
        message: '正在尝试直接抓取数据，请稍候...',
        duration: 3000,
      });
    }

    const storeResponse = await axios.post('/api/migrate/fetch_and_store', {
      sourceSite: props.sourceSite,
      searchTerm: torrentId,
      savePath: props.torrent.save_path,
    }, {
      timeout: 60000 // 60秒超时，用于抓取和存储
    });

    if (storeResponse.data.success) {
      // 抓取成功后，立即从数据库读取数据
      console.log('数据抓取成功，立即从数据库读取...');
      let dbReadAttempt = 0;
      const maxDbReadAttempts = 3;
      let dbResponseAfterStore = null;

      // 重试机制：多次尝试从数据库读取
      while (dbReadAttempt < maxDbReadAttempts) {
        dbReadAttempt++;
        try {
          const retryEnglishSiteName = await getEnglishSiteName(props.sourceSite);
          console.log(`重试从数据库读取种子信息: ${torrentId} from ${props.sourceSite} (${retryEnglishSiteName})`);
          dbResponseAfterStore = await axios.get('/api/migrate/get_db_seed_info', {
            params: {
              torrent_id: torrentId,
              site_name: retryEnglishSiteName
            },
            timeout: 10000 // 10秒超时
          });

          if (dbResponseAfterStore.data.success) {
            break; // 成功读取，退出重试循环
          } else {
            console.warn(`数据库读取第${dbReadAttempt}次失败：${dbResponseAfterStore.data.message}`);
            if (dbReadAttempt < maxDbReadAttempts) {
              await new Promise(resolve => setTimeout(resolve, 1000)); // 等待1秒后重试
            }
          }
        } catch (readError) {
          console.warn(`数据库读取第${dbReadAttempt}次失败：`, readError);
          if (dbReadAttempt < maxDbReadAttempts) {
            await new Promise(resolve => setTimeout(resolve, 1000)); // 等待1秒后重试
          } else {
            throw readError; // 重试次数用尽，抛出错误
          }
        }
      }

      if (dbResponseAfterStore && dbResponseAfterStore.data.success) {
        ElNotification.closeAll();

        // 验证数据完整性
        const dbData = dbResponseAfterStore.data.data;
        if (!dbData || !dbData.title) {
          throw new Error('数据库返回的种子信息不完整');
        }

        // 从后端响应中提取反向映射表
        if (dbResponseAfterStore.data.reverse_mappings) {
          reverseMappings.value = dbResponseAfterStore.data.reverse_mappings;
          console.log('成功加载反向映射表:', reverseMappings.value);
        } else {
          console.warn('后端未返回反向映射表，将使用空的默认映射');
        }

        ElNotification.success({
          title: '抓取成功',
          message: dbError ? '种子信息已成功抓取，请核对。由于数据库读取失败，数据未持久化存储。' : '种子信息已成功抓取并存储到数据库，请核对。'
        });

        torrentData.value = {
          original_main_title: dbData.title,
          title_components: dbData.title_components || [],
          subtitle: dbData.subtitle,
          imdb_link: dbData.imdb_link,
          douban_link: dbData.douban_link,
          intro: {
            statement: dbData.statement || '',
            poster: dbData.poster || '',
            body: dbData.body || '',
            screenshots: dbData.screenshots || '',
            removed_ardtudeclarations: dbData.removed_ardtudeclarations || []
          },
          mediainfo: dbData.mediainfo || '',
          source_params: dbData.source_params || {},
          standardized_params: {
            type: dbData.type || '',
            medium: dbData.medium || '',
            video_codec: dbData.video_codec || '',
            audio_codec: dbData.audio_codec || '',
            resolution: dbData.resolution || '',
            team: dbData.team || '',
            source: dbData.source || '',
            tags: dbData.tags || []
          },
          final_publish_parameters: dbData.final_publish_parameters || {},
          complete_publish_params: dbData.complete_publish_params || {},
          raw_params_for_preview: dbData.raw_params_for_preview || {}
        };

        // 如果没有解析过的标题组件，自动解析主标题
        if ((!dbData.title_components || dbData.title_components.length === 0) && dbData.title) {
          try {
            const parseResponse = await axios.post('/api/utils/parse_title', { title: dbData.title });
            if (parseResponse.data.success) {
              torrentData.value.title_components = parseResponse.data.components;
              ElNotification.info({
                title: '标题解析',
                message: '已自动解析主标题为组件信息。'
              });
            }
          } catch (error) {
            console.warn('自动解析标题失败:', error);
          }
        }

        taskId.value = storeResponse.data.task_id;

        // 自动提取链接的逻辑保持不变
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

        activeStep.value = 0;
      } else {
        ElNotification.closeAll();
        ElNotification.error({
          title: '读取失败',
          message: `数据抓取成功但数据库读取失败，已重试${maxDbReadAttempts}次。请检查数据库连接或稍后重试。`,
          duration: 0,
          showClose: true,
        });
        emit('cancel');
      }
    } else {
      ElNotification.closeAll();
      const errorMessage = storeResponse.data.message || '抓取种子信息失败';

      // 如果是数据库相关的错误，提供更详细的建议
      if (errorMessage.includes('数据库') || dbError) {
        ElNotification.error({
          title: '抓取失败',
          message: `${errorMessage}。可能由于数据库连接问题导致，请检查数据库状态。`,
          duration: 0,
          showClose: true,
        });
      } else {
        ElNotification.error({
          title: '抓取失败',
          message: errorMessage,
          duration: 0,
          showClose: true,
        });
      }
      emit('cancel');
    }
  } catch (error) {
    ElNotification.closeAll();

    // 区分不同类型的错误并提供更具体的错误信息
    if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
      ElNotification.error({
        title: '请求超时',
        message: '抓取种子信息超时，请检查网络连接或稍后重试。',
        duration: 0,
        showClose: true,
      });
    } else if (error.response?.status === 404) {
      ElNotification.error({
        title: '资源未找到',
        message: '在源站点未找到指定的种子，请检查种子ID是否正确。',
        duration: 0,
        showClose: true,
      });
    } else if (error.response?.status >= 500) {
      ElNotification.error({
        title: '服务器错误',
        message: '后端服务器发生错误，请稍后重试或联系管理员。',
        duration: 0,
        showClose: true,
      });
    } else {
      // 使用原有的错误处理
      handleApiError(error, '获取种子信息时发生网络错误');
    }
    emit('cancel');
  } finally {
    isLoading.value = false;
  }
}

const goToPublishPreviewStep = async () => {
  isLoading.value = true;
  try {
    ElNotification({
      title: '正在处理',
      message: '正在更新参数并生成预览...',
      type: 'info',
      duration: 0,
    });

    // 从taskId中提取torrent_id和site_name
    // taskId可能格式: db_${torrentId}_${siteName} 或原始task_id
    let torrentId, siteName;

    if (taskId.value && taskId.value.startsWith('db_')) {
      // 数据库模式: db_${torrentId}_${siteName}
      const parts = taskId.value.split('_');
      if (parts.length >= 3) {
        torrentId = parts[1];
        siteName = parts.slice(2).join('_'); // 处理站点名称中可能有下划线的情况
      }
    } else {
      // 回退模式：需要从props中获取
      const siteDetails = props.torrent.sites[props.sourceSite];
      torrentId = siteDetails.torrentId || null;
      siteName = await getEnglishSiteName(props.sourceSite);

      if (!torrentId) {
        const idMatch = siteDetails.comment?.match(/id=(\d+)/);
        if (idMatch && idMatch[1]) {
          torrentId = idMatch[1];
        }
      }
    }

    if (!torrentId || !siteName) {
      ElNotification.error({
        title: '参数错误',
        message: '无法获取种子ID或站点名称',
        duration: 0,
        showClose: true,
      });
      return;
    }

    console.log(`更新种子参数: ${torrentId} from ${siteName}`);

    // 构建更新的参数
    const updatedParameters = {
      title: torrentData.value.original_main_title,
      subtitle: torrentData.value.subtitle,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
      poster: torrentData.value.intro.poster,
      screenshots: torrentData.value.intro.screenshots,
      statement: torrentData.value.intro.statement,
      body: torrentData.value.intro.body,
      mediainfo: torrentData.value.mediainfo,
      source_params: torrentData.value.source_params,
      title_components: torrentData.value.title_components,
      // 包含用户修改的标准参数
      standardized_params: torrentData.value.standardized_params
    };

    console.log('发送到后端的标准参数:', torrentData.value.standardized_params);

    // 调用新的更新接口
    const response = await axios.post('/api/migrate/update_db_seed_info', {
      torrent_id: torrentId,
      site_name: siteName,
      updated_parameters: updatedParameters
    });

    ElNotification.closeAll();

    if (response.data.success) {
      // 更新成功后，获取重新标准化后的参数
      const { standardized_params, final_publish_parameters, complete_publish_params, raw_params_for_preview, reverse_mappings: updatedReverseMappings } = response.data;

      // 更新反向映射表（如果后端返回了更新的映射表）
      if (updatedReverseMappings) {
        reverseMappings.value = updatedReverseMappings;
        console.log('成功更新反向映射表:', reverseMappings.value);
      }

      // 更新本地数据，保留用户修改的内容
      torrentData.value = {
        ...torrentData.value,
        standardized_params: standardized_params || {},
        final_publish_parameters: final_publish_parameters || {},
        complete_publish_params: complete_publish_params || {},
        raw_params_for_preview: raw_params_for_preview || {}
      };

      ElNotification.success({
        title: '更新成功',
        message: '参数已更新并重新标准化，请核对预览内容。'
      });

      activeStep.value = 1;
    } else {
      ElNotification.error({
        title: '更新失败',
        message: response.data.message || '更新参数失败',
        duration: 0,
        showClose: true,
      });
    }
  } catch (error) {
    ElNotification.closeAll();
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
        sourceSite: props.sourceSite
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

// 辅助函数：获取映射后的中文值
const getMappedValue = (category: string) => {
  const standardizedParams = torrentData.value.standardized_params;
  if (!standardizedParams || !reverseMappings.value) return 'N/A';

  const standardValue = standardizedParams[category];
  if (!standardValue) return 'N/A';

  const mappings = reverseMappings.value[category];
  if (!mappings) return standardValue;

  return mappings[standardValue] || standardValue;
};

// 辅助函数：获取映射后的标签列表
const getMappedTags = () => {
  const standardizedParams = torrentData.value.standardized_params;
  if (!standardizedParams || !standardizedParams.tags || !reverseMappings.value.tags) return [];

  return standardizedParams.tags.map(tag => {
    return reverseMappings.value.tags[tag] || tag;
  });
};

// Computed properties for filtered title components
const filteredTitleComponents = computed(() => {
  return torrentData.value.title_components.filter(param => param.key !== '无法识别');
});

const unrecognizedComponent = computed(() => {
  return torrentData.value.title_components.find(param => param.key === '无法识别');
});

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
  margin: 0 auto;
}

.title-components-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px 16px;
  margin-bottom: 20px;
}

.standard-params-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px 16px;
  margin-bottom: 20px;
}

.standard-params-grid.second-row .tags-wide-item {
  grid-column: span 3;
}

.subtitle-unrecognized-grid {
  display: grid;
  grid-template-columns: 4fr 1fr;
  gap: 12px 16px;
  align-items: start;
}

.placeholder-item {
  opacity: 0;
  pointer-events: none;
  height: 1px;
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

/* 表单标签中的按钮样式 */
.form-label-with-button {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.form-label-with-button .el-button {
  font-size: 12px;
  padding: 4px 12px;
  height: 28px;
  border-radius: 4px;
}

.code-font,
.code-font :deep(.el-textarea__inner) {
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}
</style>
