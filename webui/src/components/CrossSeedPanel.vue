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
    <main class="panel-content" v-loading="isLoading" element-loading-text="正在获取种子信息，请稍候..."
      element-loading-background="rgba(255, 255, 255, 0.9)">
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
                      <template v-if="filteredTitleComponents.length > 0">
                        <el-form-item v-for="param in filteredTitleComponents" :key="param.key" :label="param.key">
                          <el-input v-model="param.value" />
                        </el-form-item>
                      </template>
                      <!-- 当没有解析出标题组件时，显示初始参数框 -->
                      <template v-else>
                        <el-form-item v-for="(param, index) in initialTitleComponents" :key="'init-' + index"
                          :label="param.key">
                          <el-input v-model="param.value" />
                        </el-form-item>
                      </template>
                    </div>
                  </div>

                  <div class="bottom-info-section">
                    <div class="subtitle-unrecognized-grid">
                      <!-- 副标题占4列 -->
                      <div class="subtitle-section" style="grid-column: span 4;">
                        <el-form-item label="副标题">
                          <el-input v-model="torrentData.subtitle" />
                        </el-form-item>
                      </div>
                      <!-- 无法识别占1列 -->
                      <div :class="{ 'unrecognized-section': unrecognizedValue }" style="grid-column: span 1;">
                        <el-form-item label="无法识别">
                          <el-input v-model="unrecognizedValue" />
                        </el-form-item>
                      </div>
                    </div>

                    <!-- 标准参数区域 -->
                    <!-- [最终版本] 标准参数区域 -->
                    <div class="standard-params-section">
                      <!-- 第一行：类型、媒介、视频编码、音频编码、分辨率 -->
                      <div class="standard-params-grid">
                        <el-form-item label="类型 (type)">
                          <el-select v-model="torrentData.standardized_params.type" placeholder="请选择类型" clearable
                            :class="{ 'is-invalid': invalidStandardParams.includes('type') }" data-tag-style>
                            <el-option v-for="(label, value) in reverseMappings.type" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="媒介 (medium)">
                          <el-select v-model="torrentData.standardized_params.medium" placeholder="请选择媒介" clearable
                            :class="{ 'is-invalid': invalidStandardParams.includes('medium') }" data-tag-style>
                            <el-option v-for="(label, value) in reverseMappings.medium" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="视频编码 (video_codec)">
                          <el-select v-model="torrentData.standardized_params.video_codec" placeholder="请选择视频编码"
                            clearable :class="{ 'is-invalid': invalidStandardParams.includes('video_codec') }"
                            data-tag-style>
                            <el-option v-for="(label, value) in reverseMappings.video_codec" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="音频编码 (audio_codec)">
                          <el-select v-model="torrentData.standardized_params.audio_codec" placeholder="请选择音频编码"
                            clearable :class="{ 'is-invalid': invalidStandardParams.includes('audio_codec') }"
                            data-tag-style>
                            <el-option v-for="(label, value) in reverseMappings.audio_codec" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="分辨率 (resolution)">
                          <el-select v-model="torrentData.standardized_params.resolution" placeholder="请选择分辨率" clearable
                            :class="{ 'is-invalid': invalidStandardParams.includes('resolution') }" data-tag-style>
                            <el-option v-for="(label, value) in reverseMappings.resolution" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>
                      </div>

                      <!-- 第二行：制作组、产地、标签特殊布局 -->
                      <div class="standard-params-grid second-row">
                        <!-- 【代码修改处】 -->
                        <el-form-item label="制作组 (team)">
                          <el-select v-model="torrentData.standardized_params.team" placeholder="请选择制作组" clearable
                            filterable allow-create default-first-option class="team-select"
                            :class="{ 'is-invalid': invalidStandardParams.includes('team') }">
                            <el-option v-for="(label, value) in reverseMappings.team" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="产地 (source)">
                          <el-select v-model="torrentData.standardized_params.source" placeholder="请选择产地" clearable
                            :class="{ 'is-invalid': invalidStandardParams.includes('source') }" data-tag-style>
                            <el-option v-for="(label, value) in reverseMappings.source" :key="value" :label="label"
                              :value="value" />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="标签 (tags)" class="tags-wide-item">
                          <el-select v-model="torrentData.standardized_params.tags" multiple filterable allow-create
                            default-first-option placeholder="请选择或输入标签" style="width: 100%">
                            <template #tag="{ data }">
                              <el-tag v-for="item in data" :key="item.value" :type="getTagType(item.value)" closable
                                disable-transitions @close="handleTagClose(item.value)" style="margin: 2px;">
                                <span>{{ item.currentLabel }}</span>
                              </el-tag>
                            </template>
                            <el-option v-for="option in allTagOptions" :key="option.value" :label="option.label"
                              :value="option.value">
                              <span :style="{ color: invalidTagsList.includes(option.value) ? '#F56C6C' : '' }">
                                {{ option.label }}
                              </span>
                            </el-option>
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
                    <el-form-item>
                      <template #label>
                        <div class="form-label-with-button">
                          <span>海报链接</span>
                          <el-button :icon="Refresh" @click="refreshPosters" :loading="isRefreshingPosters" size="small"
                            type="text">
                            重新获取
                          </el-button>
                        </div>
                      </template>
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
                          size="small" type="text">
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
                      type="text">
                      重新获取
                    </el-button>
                  </div>
                </template>
                <el-input type="textarea" v-model="torrentData.intro.body" :rows="18" />
              </el-form-item>
              <el-form-item label="豆瓣链接">
                <el-input v-model="torrentData.douban_link" placeholder="请输入豆瓣电影链接" />
              </el-form-item>
              <el-form-item label="IMDb链接">
                <el-input v-model="torrentData.imdb_link" placeholder="请输入IMDb电影链接" />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="媒体信息" name="mediainfo">
            <el-form label-position="top" class="fill-height-form">
              <el-form-item class="is-flexible">
                <template #label>
                  <div class="form-label-with-button">
                    <span>Mediainfo</span>
                    <el-button :icon="Refresh" @click="refreshMediainfo" :loading="isRefreshingMediainfo" size="small"
                      type="text">
                      重新获取
                    </el-button>
                  </div>
                </template>
                <el-input type="textarea" class="code-font" v-model="torrentData.mediainfo" :rows="26" />
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
                  <div style="display: flex; ">
                    <span class="param-label">IMDb链接：</span>
                    <span
                      :class="['param-value', { 'empty': !torrentData.imdb_link || torrentData.imdb_link === 'N/A' }]">
                      {{ torrentData.imdb_link || 'N/A' }}
                    </span>
                  </div>
                  <div style="display: flex; ">
                    <span style="letter-spacing: 2.6px;" class="param-label">豆瓣链接</span>
                    <span style="font-size: 13px;">：</span>
                    <span
                      :class="['param-value', { 'empty': !torrentData.douban_link || torrentData.douban_link === 'N/A' }]">
                      {{ torrentData.douban_link || 'N/A' }}
                    </span>
                  </div>

                </div>
                <div class="param-item tags-item half-width">
                  <span class="param-label">标签：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { 'empty': !getMappedTags() || getMappedTags().length === 0 }]">
                      {{ getMappedTags().join(', ') || 'N/A' }}
                    </span>
                    <span class="param-standard-key" v-if="filteredTags && filteredTags.length > 0">
                      {{ filteredTags.join(', ') }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- 其他参数在第二行开始排列 -->
              <div class="params-content">
                <div class="param-item inline-param">
                  <span class="param-label">类型：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { 'empty': !getMappedValue('type') }]">
                      {{ getMappedValue('type') || 'N/A' }}
                    </span>
                    <span class="param-standard-key" v-if="torrentData.standardized_params.type">
                      {{ torrentData.standardized_params.type }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">媒介：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { 'empty': !getMappedValue('medium') }]">
                      {{ getMappedValue('medium') || 'N/A' }}
                    </span>
                    <span class="param-standard-key" v-if="torrentData.standardized_params.medium">
                      {{ torrentData.standardized_params.medium }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">视频编码：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { 'empty': !getMappedValue('video_codec') }]">
                      {{ getMappedValue('video_codec') || 'N/A' }}
                    </span>
                    <span class="param-standard-key" v-if="torrentData.standardized_params.video_codec">
                      {{ torrentData.standardized_params.video_codec }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">音频编码：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { 'empty': !getMappedValue('audio_codec') }]">
                      {{ getMappedValue('audio_codec') || 'N/A' }}
                    </span>
                    <span class="param-standard-key" v-if="torrentData.standardized_params.audio_codec">
                      {{ torrentData.standardized_params.audio_codec }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">分辨率：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { 'empty': !getMappedValue('resolution') }]">
                      {{ getMappedValue('resolution') || 'N/A' }}
                    </span>
                    <span class="param-standard-key" v-if="torrentData.standardized_params.resolution">
                      {{ torrentData.standardized_params.resolution }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">制作组：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { 'empty': !getMappedValue('team') }]">
                      {{ getMappedValue('team') || 'N/A' }}
                    </span>
                    <span class="param-standard-key" v-if="torrentData.standardized_params.team">
                      {{ torrentData.standardized_params.team }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">产地/来源：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { 'empty': !getMappedValue('source') }]">
                      {{ getMappedValue('source') || 'N/A' }}
                    </span>
                    <span class="param-standard-key" v-if="torrentData.standardized_params.source">
                      {{ torrentData.standardized_params.source }}
                    </span>
                  </div>
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
                    :alt="'海报 ' + (index + 1)" class="preview-image-inline" style="width: 300px;"
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
        <p class="selection-subtitle">只有Cookie配置正常的站点才会在此处显示。已存在的站点已被自动禁用。</p>
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

        <div class="results-rows-container">
          <div v-for="(row, rowIndex) in groupedResults" :key="rowIndex" class="results-row">
            <div class="row-sites">
              <div v-for="result in row" :key="result.siteName" class="result-card"
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
                  <el-tag type="warning" size="small">已存在</el-tag>
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
                    {{ result.downloaderStatus.success ? `种子已添加到 '${result.downloaderStatus.downloaderName}'` : '添加失败'
                    }}
                  </span>
                </div>

                <!-- 操作按钮 -->
                <div class="card-extra">
                  <el-button type="primary" size="small" @click="showSiteLog(result.siteName, result.logs)">
                    查看日志
                  </el-button>
                  <a v-if="result.success && result.url" :href="result.url" target="_blank" rel="noopener noreferrer"
                    style="transform: translateY(-3px);">
                    <el-button type="success" size="small">
                      查看种子
                    </el-button>
                  </a>
                </div>
              </div>
            </div>
            <div class="row-action">
              <el-button type="warning" :icon="Refresh" size="large" @click="openAllSitesInRow(row)"
                :disabled="!hasValidUrlsInRow(row)" class="open-all-button">
                <div class="button-subtitle">打开{{ getValidUrlsCount(row) }}个站点</div>
              </el-button>
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

        <el-tooltip content="存在待修改的参数 (请确保mediainfo或bdinfo内容有效且包含必要的媒体信息)" placement="top"
          :disabled="!isNextButtonDisabled">
          <!-- 添加一个 span 作为包裹元素 -->

          <el-button type="primary" @click="goToPublishPreviewStep" :disabled="isNextButtonDisabled">
            下一步：发布参数预览
          </el-button>

        </el-tooltip>
      </div>
      <!-- 步骤 1 的按钮 -->
      <div v-if="activeStep === 1" class="button-group">
        <el-button @click="handlePreviousStep" :disabled="isLoading">上一步</el-button>
        <el-button type="primary" @click="$emit('complete')" v-if="props.showCompleteButton">修改完成</el-button>
        <el-tooltip :content="isScrolledToBottom ? '' : '请先滚动到页面底部审查完种子信息再发布！'" :disabled="isScrolledToBottom"
          placement="top">
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

  <!-- 日志进度组件 -->
  <LogProgress 
    :visible="showLogProgress" 
    :taskId="logProgressTaskId"
    @complete="handleLogProgressComplete"
    @close="showLogProgress = false"
  />
</template>

<script setup lang="ts">
// ... 你的 <script setup> 部分完全保持不变 ...
import { ref, onMounted, computed, nextTick, watch } from 'vue'
import { ElNotification, ElMessageBox } from 'element-plus'
import { ElTooltip } from 'element-plus'
import axios from 'axios'
import { Refresh, CircleCheckFilled, CircleCloseFilled, Close } from '@element-plus/icons-vue'
import { useCrossSeedStore } from '@/stores/crossSeed'
import LogProgress from './LogProgress.vue'

// 过滤多余空行的辅助函数
const filterExtraEmptyLines = (text: string): string => {
  if (!text) return ''
  // 过滤掉多余的空行，保留项目间的单个空行
  // 先去除行尾空格和其他空白字符
  text = text.replace(/[ \t\f\v]+$/gm, '')
  // 去除开头和结尾的空行
  text = text.replace(/^\s*\n+/, '').replace(/\n\s*$/, '')
  // 将两个或更多连续的空行替换为单个换行符（即一个空行）
  text = text.replace(/(\n\s*){2,}/g, '\n\n')
  // 处理句子和列表之间的多余空行（更通用的处理方式）
  text = text.replace(/([^\n]+。)\s*\n\s*\n(\s*\d+\.)/g, '$1\n$2')
  // 处理列表项之间的多余空行
  text = text.replace(/(\d+\.[\s\S]*?)\n\s*\n(\s*\d+\.)/g, '$1\n$2')
  // 处理嵌套标签内的多余空行（例如[b][color]标签内的空行）
  text = text.replace(/(\[(?:b|color)[^\]]*\][\s\S]*?)\n\s*\n([\s\S]*?\[\/(?:b|color)\])/gi, '$1\n$2')
  // 处理多层嵌套标签
  for (let i = 0; i < 3; i++) {
    text = text.replace(/(\[(?:quote|b|color|size)[^\]]*\][\s\S]*?)\n\s*\n([\s\S]*?\[\/(?:quote|b|color|size)\])/gi, '$1\n$2')
  }
  // 再次处理可能仍然存在的多余空行
  text = text.replace(/(\n\s*){2,}/g, '\n\n')
  return text
}

// BBCode 解析函数
const parseBBCode = (text: string): string => {
  if (!text) return ''

  // 过滤掉多余的空行，只保留单个空行
  text = filterExtraEmptyLines(text)

  // 处理 [quote] 标签
  text = text.replace(/\[quote\]([\s\S]*?)\[\/quote\]/gi, '<blockquote>$1</blockquote>')

  // 处理 [b] 标签
  text = text.replace(/\[b\]([\s\S]*?)\[\/b\]/gi, '<strong>$1</strong>')

  // 处理 [color] 标签
  text = text.replace(/\[color=(\w+|\#[0-9a-fA-F]{3,6})\]([\s\S]*?)\[\/color\]/gi, '<span style="color: $1;">$2</span>')

  // 处理 [size] 标签，映射到具体的像素值
  text = text.replace(/\[size=(\d+)\]([\s\S]*?)\[\/size\]/gi, (match: string, size: string, content: string): string => {
    // 根据 size 值映射到具体的像素值
    const sizeMap: { [key: string]: string } = {
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

const props = defineProps({
  showCompleteButton: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['complete', 'cancel']);

const crossSeedStore = useCrossSeedStore();

const torrent = computed(() => crossSeedStore.workingParams as Torrent);
const sourceSite = computed(() => crossSeedStore.sourceInfo?.name || '');

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
const isRefreshingMediainfo = ref(false)
const isRefreshingPosters = ref(false)
const isHandlingScreenshotError = ref(false) // 防止重复处理截图错误
const screenshotValid = ref(true) // 跟踪截图是否有效
const logContent = ref('')
const showLogCard = ref(false)
const downloaderList = ref<{ id: string, name: string }[]>([])
const isDataFromDatabase = ref(false) // Flag to track if data was loaded from database

// 日志进度组件相关
const showLogProgress = ref(false)
const logProgressTaskId = ref('')

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
  if (!torrent.value || !torrent.value.sites) {
    return true;
  }
  return !torrent.value.sites[siteName];
};


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
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
    }
  };

  try {
    const response = await axios.post('/api/media/validate', payload);
    ElNotification.closeAll();

    if (response.data.success && response.data.intro) {
      torrentData.value.intro.body = filterExtraEmptyLines(response.data.intro);

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

  // 防止重复请求
  if (isRefreshingScreenshots.value) {
    ElNotification.info({
      title: '正在处理中',
      message: '截图重新生成请求已在处理中，请稍候...',
    });
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
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
    },
    savePath: torrent.value.save_path,
    torrentName: torrent.value.name,
    downloaderId: torrent.value.downloaderId // 添加下载器ID
  };

  try {
    const response = await axios.post('/api/media/validate', payload);
    ElNotification.closeAll();

    if (response.data.success && response.data.screenshots) {
      torrentData.value.intro.screenshots = response.data.screenshots;
      screenshotValid.value = true; // 标记截图有效
      ElNotification.success({
        title: '重新获取成功',
        message: '已成功生成并加载了新的截图。',
      });
    } else {
      // 如果重新获取截图失败，标记截图无效
      screenshotValid.value = false;
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
    // 如果重新获取截图失败，标记截图无效
    screenshotValid.value = false;
  } finally {
    isRefreshingScreenshots.value = false;
  }
};

const refreshMediainfo = async () => {
  // 移除标题检查，允许任何时候重新获取
  // 防止重复请求
  if (isRefreshingMediainfo.value) {
    ElNotification.info({
      title: '正在处理中',
      message: '媒体信息重新获取请求已在处理中，请稍候...',
    });
    return;
  }

  isRefreshingMediainfo.value = true;
  ElNotification.info({
    title: '正在重新获取',
    message: '正在从视频重新生成媒体信息...',
    duration: 0
  });

  const payload = {
    type: 'mediainfo',
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
    },
    current_mediainfo: torrentData.value.mediainfo, // 传递当前mediainfo，但后端会强制重新获取
    savePath: torrent.value.save_path,
    torrentName: torrent.value.name,
    downloaderId: torrent.value.downloaderId // 添加下载器ID
  };

  try {
    const response = await axios.post('/api/media/validate', payload);
    ElNotification.closeAll();

    if (response.data.success && response.data.mediainfo) {
      torrentData.value.mediainfo = response.data.mediainfo;
      ElNotification.success({
        title: '重新获取成功',
        message: '已成功生成并加载了新的媒体信息。',
      });
    } else {
      ElNotification.error({
        title: '重新获取失败',
        message: response.data.error || '无法从后端获取新的媒体信息。',
      });
    }
  } catch (error: any) {
    ElNotification.closeAll();
    const errorMsg = error.response?.data?.error || '重新获取媒体信息时发生网络错误';
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    });
  } finally {
    isRefreshingMediainfo.value = false;
  }
};

const refreshPosters = async () => {
  if (!torrentData.value.original_main_title) {
    ElNotification.warning('标题为空，无法重新获取海报。');
    return;
  }

  // 防止重复请求
  if (isRefreshingPosters.value) {
    ElNotification.info({
      title: '正在处理中',
      message: '海报重新获取请求已在处理中，请稍候...',
    });
    return;
  }

  isRefreshingPosters.value = true;
  ElNotification.info({
    title: '正在重新获取',
    message: '正在重新生成海报...',
    duration: 0
  });

  const payload = {
    type: 'poster',
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
    },
    savePath: torrent.value.save_path,
    torrentName: torrent.value.name,
    downloaderId: torrent.value.downloaderId // 添加下载器ID
  };

  try {
    const response = await axios.post('/api/media/validate', payload);
    ElNotification.closeAll();

    if (response.data.success && response.data.posters) {
      torrentData.value.intro.poster = response.data.posters;
      ElNotification.success({
        title: '重新获取成功',
        message: '已成功生成并加载了新的海报。',
      });
    } else {
      ElNotification.error({
        title: '重新获取失败',
        message: response.data.error || '无法从后端获取新的海报。',
      });
    }
  } catch (error: any) {
    ElNotification.closeAll();
    const errorMsg = error.response?.data?.error || '重新获取海报时发生网络错误';
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    });
  } finally {
    isRefreshingPosters.value = false;
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
  // 防止重复处理截图错误
  if (type === 'screenshot' && isHandlingScreenshotError.value) {
    console.log(`截图错误已正在处理中，跳过重复请求: ${url}`);
    return;
  }

  console.error(`图片加载失败: 类型=${type}, URL=${url}, 索引=${index}`)
  if (type === 'screenshot') {
    isHandlingScreenshotError.value = true;
    screenshotValid.value = false; // 标记截图无效
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
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
    },
    savePath: torrent.value.save_path,
    torrentName: torrent.value.name,
    downloaderId: torrent.value.downloaderId // 添加下载器ID
  }

  try {
    const response = await axios.post('/api/media/validate', payload)
    if (response.data.success) {
      if (type === 'screenshot' && response.data.screenshots) {
        torrentData.value.intro.screenshots = response.data.screenshots;
        screenshotValid.value = true; // 标记截图有效
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
      // 如果更新截图失败，保持screenshotValid为false
      if (type === 'screenshot') {
        screenshotValid.value = false;
      }
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
  } finally {
    // 重置截图处理状态
    if (type === 'screenshot') {
      isHandlingScreenshotError.value = false;
      // 注意：不重置 screenshotValid 状态，保持当前的截图有效状态
    }
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
  if (!sourceSite.value || !torrent.value) return;

  const siteDetails = torrent.value.sites[sourceSite.value];
  // 首先检查是否有存储的种子ID
  let torrentId = siteDetails.torrentId || null;

  // 如果没有存储的ID，则尝试从链接中提取
  if (!torrentId) {
    const idMatch = siteDetails.comment?.match(/id=(\d+)/);
    if (!idMatch || !idMatch[1]) {
      ElNotification.error(`无法从源站点 ${sourceSite.value} 的链接中提取种子ID。`);
      emit('cancel');
      return;
    }
    torrentId = idMatch[1];
  }

  isLoading.value = true
  
  // 生成任务ID并显示进度组件
  const tempTaskId = `fetch_${torrentId}_${Date.now()}`
  logProgressTaskId.value = tempTaskId
  showLogProgress.value = true

  let dbError = null;

  // 步骤1: 尝试从数据库读取种子信息
  try {
    const englishSiteName = await getEnglishSiteName(sourceSite.value);
    console.log(`尝试从数据库读取种子信息: ${torrentId} from ${sourceSite.value} (${englishSiteName})`);
    const dbResponse = await axios.get('/api/migrate/get_db_seed_info', {
      params: {
        torrent_id: torrentId,
        site_name: englishSiteName,
        task_id: tempTaskId  // 传递task_id给后端
      },
      timeout: 120000 // 120秒超时
    });

    // 检查是否需要继续抓取（202状态码）
    if (dbResponse.status === 202 && dbResponse.data.should_fetch) {
      console.log('数据库中没有缓存，继续使用同一日志流从源站点抓取...');
      // 使用返回的task_id继续抓取（不关闭日志流）
      const continuedTaskId = dbResponse.data.task_id || tempTaskId;
      
      // 直接调用 fetch_and_store，传入相同的 task_id
      try {
        const storeResponse = await axios.post('/api/migrate/fetch_and_store', {
          sourceSite: sourceSite.value,
          searchTerm: torrentId,
          savePath: torrent.value.save_path,
          torrentName: torrent.value.name,
          downloaderId: torrent.value.downloaderId,
          task_id: continuedTaskId  // 传递相同的task_id以继续使用同一日志流
        }, {
          timeout: 120000
        });

        if (!storeResponse.data.success) {
          ElNotification.closeAll();
          ElNotification.error({
            title: '抓取失败',
            message: storeResponse.data.message || '从源站点抓取失败',
            duration: 0,
            showClose: true,
          });
          emit('cancel');
          isLoading.value = false;
          return;
        }

        // 抓取成功后，再次从数据库读取（使用相同逻辑）
        const finalDbResponse = await axios.get('/api/migrate/get_db_seed_info', {
          params: {
            torrent_id: torrentId,
            site_name: englishSiteName
          },
          timeout: 120000
        });

        if (!finalDbResponse.data.success) {
          ElNotification.closeAll();
          ElNotification.error({
            title: '读取失败',
            message: '数据抓取成功但从数据库读取失败',
            duration: 0,
            showClose: true,
          });
          emit('cancel');
          isLoading.value = false;
          return;
        }

        // 处理成功的数据（与下面的逻辑相同）
        ElNotification.closeAll();
        ElNotification.success({
          title: '抓取成功',
          message: '种子信息已成功抓取并存储到数据库，请核对。'
        });

        const dbData = finalDbResponse.data.data;
        if (finalDbResponse.data.reverse_mappings) {
          reverseMappings.value = finalDbResponse.data.reverse_mappings;
        }

        torrentData.value = {
          original_main_title: dbData.title || '',
          title_components: dbData.title_components || [],
          subtitle: dbData.subtitle,
          imdb_link: dbData.imdb_link,
          douban_link: dbData.douban_link,
          intro: {
            statement: filterExtraEmptyLines(dbData.statement) || '',
            poster: dbData.poster || '',
            body: filterExtraEmptyLines(dbData.body) || '',
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

        taskId.value = storeResponse.data.task_id;
        isDataFromDatabase.value = true;
        activeStep.value = 0;
        
        nextTick(() => {
          checkScreenshotValidity();
        });
        
        isLoading.value = false;
        return;
      } catch (error: any) {
        ElNotification.closeAll();
        handleApiError(error, '从源站点抓取时发生网络错误');
        emit('cancel');
        isLoading.value = false;
        return;
      }
    } else if (dbResponse.data.success) {
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
        original_main_title: dbData.title || '',
        title_components: dbData.title_components || [],
        subtitle: dbData.subtitle,
        imdb_link: dbData.imdb_link,
        douban_link: dbData.douban_link,
        intro: {
          statement: filterExtraEmptyLines(dbData.statement) || '',
          poster: dbData.poster || '',
          body: filterExtraEmptyLines(dbData.body) || '',
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

      // 直接使用从数据库返回的 taskId，如果后端没有返回则生成标识符
      if (dbResponse.data.task_id) {
        taskId.value = dbResponse.data.task_id; // 使用从数据库返回的 taskId
        ElNotification.success({
          title: '缓存准备完成',
          message: '发布任务已准备就绪'
        });
      } else {
        // 如果后端未返回task_id，回退到标识符
        taskId.value = `db_${torrentId}_${englishSiteName}`;
        console.warn('后端未返回taskId，使用标识符');
      }
      isDataFromDatabase.value = true; // Mark that data was loaded from database

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
      // Check screenshot validity after loading data
      nextTick(() => {
        checkScreenshotValidity();
      });
      // Set flag to indicate data was loaded from database
      isDataFromDatabase.value = true;
      // 【修复】在从数据库成功读取后关闭加载动画
      isLoading.value = false;
      // Skip the scraping part since we have data from database
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
      sourceSite: sourceSite.value,
      searchTerm: torrentId,
      savePath: torrent.value.save_path,
      torrentName: torrent.value.name,
      downloaderId: torrent.value.downloaderId || (torrent.value.downloaderIds?.length > 0 ? torrent.value.downloaderIds[0] : null),
    }, {
      timeout: 120000 // 120秒超时，用于抓取和存储
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
          const retryEnglishSiteName = await getEnglishSiteName(sourceSite.value);
          console.log(`重试从数据库读取种子信息: ${torrentId} from ${sourceSite.value} (${retryEnglishSiteName})`);
          dbResponseAfterStore = await axios.get('/api/migrate/get_db_seed_info', {
            params: {
              torrent_id: torrentId,
              site_name: retryEnglishSiteName
            },
            timeout: 120000 // 120秒超时
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
          original_main_title: dbData.title || '',
          title_components: dbData.title_components || [],
          subtitle: dbData.subtitle,
          imdb_link: dbData.imdb_link,
          douban_link: dbData.douban_link,
          intro: {
            statement: filterExtraEmptyLines(dbData.statement) || '',
            poster: dbData.poster || '',
            body: filterExtraEmptyLines(dbData.body) || '',
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
        isDataFromDatabase.value = true; // Mark that data was loaded from database

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
        // Check screenshot validity after loading data
        nextTick(() => {
          checkScreenshotValidity();
        });
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

// 检查标准化参数是否符合格式的辅助函数
const invalidStandardParams = computed(() => {
  const standardizedParams = torrentData.value.standardized_params;
  const standardParamKeys = ['type', 'medium', 'video_codec', 'audio_codec', 'resolution', 'team', 'source'];
  const invalidParamsList = [];

  // 【修改】使用与 invalidTagsList 相同的、更强大的正则表达式
  const flexibleRegex = new RegExp(/^[\p{L}\p{N}_-]+\.[\p{L}\p{N}_-]+$/u);

  for (const key of standardParamKeys) {
    const value = standardizedParams[key];

    // 【修改】使用新的正则表达式进行判断
    if (value && typeof value === 'string' && value.trim() !== '' && !flexibleRegex.test(value)) {
      invalidParamsList.push(key);
    }
  }

  // 这里逻辑保持不变
  if (invalidTagsList.value.length > 0) {
    invalidParamsList.push('tags');
  }

  return invalidParamsList;
});

const goToPublishPreviewStep = async () => {
  // 检查是否有不符合格式的标准化参数
  const invalidParams = invalidStandardParams.value;
  if (invalidParams.length > 0) {
    // 显示提示信息
    const paramNames = {
      'type': '类型',
      'medium': '媒介',
      'video_codec': '视频编码',
      'audio_codec': '音频编码',
      'resolution': '分辨率',
      'team': '制作组',
      'source': '产地',
      'tags': '标签'
    };

    const invalidParamNames = invalidParams.map(param => paramNames[param] || param);

    ElNotification({
      title: '参数格式不正确',
      message: `以下参数格式不正确，请修改为 *.* 的标准格式: ${invalidParamNames.join(', ')}`,
      type: 'warning',
      duration: 0,
      showClose: true,
    });
    return;
  }

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

    // 如果数据是从数据库加载的，优先使用数据库模式解析
    if (isDataFromDatabase.value && taskId.value && taskId.value.startsWith('db_')) {
      // 数据库模式: db_${torrentId}_${siteName}
      const parts = taskId.value.split('_');
      if (parts.length >= 3) {
        torrentId = parts[1];
        siteName = parts.slice(2).join('_'); // 处理站点名称中可能有下划线的情况
      }
    } else if (taskId.value && taskId.value.startsWith('db_')) {
      // 原有的数据库模式解析
      const parts = taskId.value.split('_');
      if (parts.length >= 3) {
        torrentId = parts[1];
        siteName = parts.slice(2).join('_'); // 处理站点名称中可能有下划线的情况
      }
    } else {
      // 回退模式：需要从props中获取
      const siteDetails = torrent.value.sites[sourceSite.value];
      torrentId = siteDetails.torrentId || null;
      siteName = await getEnglishSiteName(sourceSite.value);

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

    // 构建更新的参数，应用空行过滤
    const updatedParameters = {
      title: torrentData.value.original_main_title,
      subtitle: torrentData.value.subtitle,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
      poster: torrentData.value.intro.poster,
      screenshots: torrentData.value.intro.screenshots,
      statement: filterExtraEmptyLines(torrentData.value.intro.statement),
      body: filterExtraEmptyLines(torrentData.value.intro.body),
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
      ElNotification.closeAll();
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

// 【新增】计算属性：整合预设标签和当前已选标签，用于渲染下拉列表
const allTagOptions = computed(() => {
  const predefinedTags = Object.keys(reverseMappings.value.tags || {});
  const currentTags = torrentData.value.standardized_params.tags || [];
  const combined = [...new Set([...predefinedTags, ...currentTags])];

  return combined.map(tagValue => ({
    value: tagValue,
    label: reverseMappings.value.tags[tagValue] || tagValue
  }));
});

// 【修改并添加调试代码】方法：根据标签是否有效，返回不同的类型
const getTagType = (tag: string) => {
  // 在浏览器开发者工具的控制台(Console)中打印日志，方便调试
  console.log(`[getTagType] 检查标签: "${tag}", 是否无效: ${invalidTagsList.value.includes(tag)}`);

  // 核心逻辑不变
  return invalidTagsList.value.includes(tag) ? 'danger' : 'info';
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
        upload_data: {
          ...torrentData.value,
          save_path: torrent.value.save_path  // 添加 save_path
        },
        targetSite: siteName,
        sourceSite: sourceSite.value,
        downloaderId: torrent.value.downloaderId,  // 新增：传递下载器ID
        auto_add_to_downloader: true  // 新增：启用自动添加
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

  // 处理自动添加到下载器的结果
  logContent.value += '\n\n--- [自动添加任务结果] ---';
  const downloaderStatusMap: Record<string, { success: boolean, message: string, downloaderName: string }> = {};

  // 从 Python 返回的结果中提取 auto_add_result
  results.forEach(result => {
    if (result.auto_add_result) {
      downloaderStatusMap[result.siteName] = {
        success: result.auto_add_result.success,
        message: result.auto_add_result.message,
        downloaderName: '自动检测'
      };
      const statusIcon = result.auto_add_result.success ? '✅' : '❌';
      const statusText = result.auto_add_result.success ? '成功' : '失败';
      logContent.value += `\n[${result.siteName}] ${statusIcon} ${statusText}: ${result.auto_add_result.message}`;
    } else if (result.success && result.url) {
      // 如果没有 auto_add_result，说明可能跳过了自动添加
      logContent.value += `\n[${result.siteName}] ⚠️  未执行自动添加`;
    }
  });
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

  // 触发种子数据刷新
  try {
    await axios.post('/api/torrents/refresh_data');
    ElNotification.success({
      title: '数据刷新',
      message: '种子数据已刷新'
    });
  } catch (error) {
    console.warn('刷新种子数据失败:', error);
  }

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
  if (!torrent.value.save_path || !torrent.value.downloaderId) {
    const msg = `[${result.siteName}] 警告: 未能获取到原始保存路径或下载器ID，已跳过自动添加任务。`;
    console.warn(msg);
    logContent.value += `\n${msg}`;
    return { success: false, message: "未能获取到原始保存路径或下载器ID", downloaderName: "" };
  }

  let targetDownloaderId = torrent.value.downloaderId;
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
      savePath: torrent.value.save_path,
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
  // 使用 filteredTags 计算属性来过滤掉空标签
  if (!filteredTags.value || !reverseMappings.value.tags) return [];

  return filteredTags.value.map((tag: string) => {
    return reverseMappings.value.tags[tag] || tag;
  });
};

// Computed properties for filtered title components
const filteredTitleComponents = computed(() => {
  return torrentData.value.title_components.filter(param => param.key !== '无法识别');
});
// 计算属性：过滤掉空标签
const filteredTags = computed(() => {
  const tags = torrentData.value.standardized_params.tags;
  return tags?.filter(tag => tag && typeof tag === 'string' && tag.trim() !== '') || [];
});

// 【新增】计算属性：专门用于找出并返回所有格式不正确的标签列表
const invalidTagsList = computed(() => {
  // 定义支持中文和连字符的灵活正则表达式
  // \p{L} -> 匹配任何语言的字母 (包括中文)
  // \p{N} -> 匹配任何语言的数字
  // _-  -> 匹配下划线和连字符
  // u 标志 -> 启用 Unicode 支持
  const flexibleRegex = new RegExp(/^[\p{L}\p{N}_-]+\.[\p{L}\p{N}_-]+$/u);

  // 从已过滤的标签中，再次过滤出不符合新正则的标签
  return filteredTags.value.filter(tag => !flexibleRegex.test(tag));
});
// 计算属性：为未解析的标题提供初始参数框
const initialTitleComponents = computed(() => {
  // 定义常见的标题参数键
  const commonKeys = ['主标题', '季集', '年份', '剧集状态', '发布版本', '分辨率', '片源平台', '媒介', '视频编码', '视频格式', 'HDR格式', '色深', '帧率', '音频编码', '制作组'];
  // 创建带有空值的初始参数数组
  return commonKeys.map(key => ({
    key: key,
    value: ''
  }));
});

const handleTagClose = (tagToRemove: string) => {
  // 找到要删除的标签在数组中的索引
  const index = torrentData.value.standardized_params.tags.indexOf(tagToRemove);

  // 如果找到了，就从数组中移除它
  if (index > -1) {
    torrentData.value.standardized_params.tags.splice(index, 1);
  }
};

const unrecognizedValue = computed({
  // Getter: 当模板需要读取值时调用
  get() {
    const unrecognized = torrentData.value.title_components.find(param => param.key === '无法识别');
    return unrecognized ? unrecognized.value : ''; // 返回找到的值，或者空字符串
  },
  // Setter: 当 v-model 试图修改值时调用
  set(newValue) {
    const index = torrentData.value.title_components.findIndex(param => param.key === '无法识别');

    // 如果新输入的值是空的，就从数组里删除这个项目
    if (newValue === '' || newValue === null) {
      if (index !== -1) {
        torrentData.value.title_components.splice(index, 1);
      }
    } else {
      // 如果项目已存在，就更新它的值
      if (index !== -1) {
        torrentData.value.title_components[index].value = newValue;
      } else {
        // 如果项目不存在，就创建一个新的推进数组
        torrentData.value.title_components.push({
          key: '无法识别',
          value: newValue
        });
      }
    }
  }
});

// 计算属性：检查下一步按钮是否应该禁用
// 只有当"无法识别"的参数为空字符串，截图有效，标准化参数符合格式，且mediainfo/bdinfo内容有效时才允许点击按钮
// mediainfo/bdinfo有效性的检查：非空、长度足够、包含各自格式的关键字段
const isNextButtonDisabled = computed(() => {
  const unrecognized = torrentData.value.title_components.find(param => param.key === '无法识别');
  const hasUnrecognized = unrecognized && unrecognized.value !== '';
  const hasInvalidScreenshots = !screenshotValid.value;

  // 检查 mediainfo/bdinfo 的有效性
  const mediaInfoText = torrentData.value.mediainfo || '';
  const hasInvalidMediaInfo = !mediaInfoText || mediaInfoText.trim() === '';

  // 如果有内容，进一步检查格式有效性
  if (!hasInvalidMediaInfo) {
    // 检查是否为有效的 MediaInfo 或 BDInfo 格式
    const isStandardMediainfo = _isValidMediainfo(mediaInfoText);
    const isBDInfo = _isValidBDInfo(mediaInfoText);

    // 如果既不是有效的 MediaInfo 也不是有效的 BDInfo，则认为无效
    if (!isStandardMediainfo && !isBDInfo) {
      return true;
    }
  }

  // 将 getInvalidStandardParams() 修改为 invalidStandardParams.value
  const hasInvalidStandardParams = invalidStandardParams.value.length > 0;

  if (hasUnrecognized) {
    return true;
  }
  if (hasInvalidScreenshots) {
    return true;
  }
  if (hasInvalidStandardParams) {
    return true;
  }
  if (hasInvalidMediaInfo) {
    return true;
  }

  return false;
});

// 辅助函数：检查是否为有效的 MediaInfo 格式
const _isValidMediainfo = (text: string): boolean => {
  const standardMediainfoKeywords = [
    "General",
    "Video",
    "Audio",
    "Complete name",
    "File size",
    "Duration",
    "Width",
    "Height"
  ];

  const matches = standardMediainfoKeywords.filter(keyword => text.includes(keyword));
  return matches.length >= 3; // 至少匹配3个关键字才认为是有效的MediaInfo
};

// 辅助函数：检查是否为有效的 BDInfo 格式
const _isValidBDInfo = (text: string): boolean => {
  const bdInfoRequiredKeywords = ["DISC INFO", "PLAYLIST REPORT"];
  const bdInfoOptionalKeywords = [
    "VIDEO:",
    "AUDIO:",
    "SUBTITLES:",
    "FILES:",
    "Disc Label",
    "Disc Size",
    "BDInfo:",
    "Protection:",
    "Codec",
    "Bitrate",
    "Language",
    "Description"
  ];

  const requiredMatches = bdInfoRequiredKeywords.filter(keyword => text.includes(keyword)).length;
  const optionalMatches = bdInfoOptionalKeywords.filter(keyword => text.includes(keyword)).length;

  // 必须所有必要关键字都存在，或者至少有1个必要关键字且2个以上可选关键字
  return (requiredMatches === bdInfoRequiredKeywords.length) ||
    (requiredMatches >= 1 && optionalMatches >= 2);
};

// 检查截图有效性
const checkScreenshotValidity = async () => {
  // 检查当前截图的有效性
  const screenshots = screenshotImages.value;
  if (screenshots.length === 0) {
    // 如果没有截图，认为是有效的
    screenshotValid.value = true;
    return;
  }

  // 对于每个截图，创建一个图片对象来检查是否可以加载
  let allValid = true;
  for (const url of screenshots) {
    try {
      await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
          resolve(true);
        };
        img.onerror = () => {
          reject(new Error('Image load failed'));
        };
        img.src = url;
      });
    } catch (error) {
      allValid = false;
      break;
    }
  }

  screenshotValid.value = allValid;
};

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

// 分组结果，每行5个
const groupedResults = computed(() => {
  const results = finalResultsList.value;
  const grouped = [];
  for (let i = 0; i < results.length; i += 5) {
    grouped.push(results.slice(i, i + 5));
  }
  return grouped;
});

// 检查行中是否有有效的URL
const hasValidUrlsInRow = (row: any[]) => {
  return row.some(result => result.success && result.url);
};

// 获取行中有效URL的数量
const getValidUrlsCount = (row: any[]) => {
  return row.filter(result => result.success && result.url).length;
};

// 打开一行中所有有效的种子链接
const openAllSitesInRow = (row: any[]) => {
  const validResults = row.filter(result => result.success && result.url);

  if (validResults.length === 0) {
    ElNotification.warning({
      title: '无法打开',
      message: '该行没有可用的种子链接'
    });
    return;
  }

  // 批量打开所有链接
  validResults.forEach(result => {
    window.open(result.url, '_blank', 'noopener,noreferrer');
  });

  ElNotification.success({
    title: '批量打开成功',
    message: `已打开 ${validResults.length} 个种子页面`
  });
};

// 处理日志进度完成
const handleLogProgressComplete = () => {
  console.log('日志进度处理完成');
  // 进度完成后自动关闭进度窗口
  setTimeout(() => {
    showLogProgress.value = false;
  }, 1000);
};

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
  /* 确保遮罩层能够正确覆盖 */
  isolation: isolate;
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
  gap: 5px 15px;
}

.standard-params-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 5px 15px;
}

.standard-params-grid.second-row .tags-wide-item {
  grid-column: span 3;
}

.subtitle-unrecognized-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px 16px;
  align-items: start;
  min-width: 0;
  /* 防止网格项溢出 */
  width: 100%;
  /* 确保网格占满容器宽度 */
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
  max-height: 540px;
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
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 0;
}

.param-item {
  display: flex;
  padding: 12px;
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
.imdb-item {
  display: flex;
  flex-direction: column;
}

.tags-item {
  display: flex;
}

.imdb-item .param-value,
.tags-item .param-value {
  word-break: break-all;
  line-height: 1.4;
}

.imdb-item .param-value-container,
.tags-item .param-value-container {
  display: flex;
  flex-direction: column;
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

.inline-param .param-value-container {
  flex: 1;
  margin-left: 8px;
  display: flex;
  flex-direction: column;
}

.inline-param .param-value {
  font-size: 14px;
  word-break: break-word;
  line-height: 1.4;
}

.param-standard-key {
  font-size: 12px;
  color: #909399;
  font-style: italic;
  margin-top: 2px;
  line-height: 1.2;
}

.param-label {
  font-weight: 600;
  color: #495057;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
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
.results-rows-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding-bottom: 30px;
}

.results-row {
  display: flex;
  align-items: stretch;
  gap: 16px;
  padding: 16px;
}

.row-sites {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  flex: 1;
  justify-content: flex-start;
  position: relative;
}

.row-action {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 120px;
  flex-shrink: 0;
  position: absolute;
  right: 0;
  margin-top: 50px;
}

.open-all-button {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: auto;
  padding: 5px 3px;
  min-height: 80px;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.open-all-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.open-all-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.open-all-button:disabled:hover {
  transform: none;
  box-shadow: none;
}

.button-subtitle {
  font-size: 12px;
  margin-top: 4px;
  opacity: 0.8;
  font-weight: normal;
  writing-mode: vertical-rl;
  text-orientation: upright;
  letter-spacing: 2px;
  transform: translateX(-5px);
}

.results-grid-container {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  justify-content: center;
  align-content: flex-start;
  padding-bottom: 30px;
}

.result-card {
  width: 150px;
  height: 150px;
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
  flex-shrink: 0;
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

/* .card-icon {
  margin-bottom: 8px;
} */

.card-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: #303133;
}

.existed-tag {
  position: absolute;
  transform: translate(65px, 35px);
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
  transform: translate(10px, 0);
}

/* 海报与声明面板样式 */
.poster-statement-container {
  height: 100%;
}

.poster-statement-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  height: 100%;
}

.left-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.statement-item {
  flex: 1;
  min-height: 0;
}

.statement-item :deep(.el-textarea__inner) {
  height: 100%;
}

.code-font,
.code-font :deep(.el-textarea__inner) {
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}

/* 【新增】无效标签警告信息的样式 */
.invalid-tags-warning {
  margin-top: 5px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  /* 元素之间的间距 */
  line-height: 1.4;
}

.warning-text {
  font-size: 12px;
  color: #f56c6c;
  /* 红色文字 */
  margin-right: 5px;
}


/* ==================================================================== */
/*          [最终方案] 参数验证失败的统一视觉反馈样式                 */
/* ==================================================================== */

/* --- 1. 将单选 el-select 的选中值伪装成 el-tag 样式 --- */

/* 1.1 设置基础的 Tag 样式 (内边距、圆角等) */
.el-select[data-tag-style] :deep(.el-select__selected-item) {
  padding: 0 9px;
  text-align: center;
  border-radius: 4px;
  line-height: 20px;
  height: 25px;
  display: inline-block;
  box-sizing: border-box;
  border: 1px solid transparent;
  /* 添加透明边框占位 */
}

/* 1.2 定义“有效”状态下的 Tag 颜色 (蓝色，和标签的 info 类型一致) */
.el-select[data-tag-style]:not(.is-invalid) :deep(.el-select__selected-item) {
  background-color: var(--el-color-info-light-9);
  color: var(--el-color-info);
  border-color: var(--el-color-info-light-8);
}

/* 1.3 定义“无效”状态下的 Tag 颜色 (红色，和标签的 danger 类型一致) */
.el-select[data-tag-style].is-invalid :deep(.el-select__selected-item) {
  background-color: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
  border-color: var(--el-color-danger-light-8);
}

/* --- 2. (可选但推荐) 为所有无效的 el-select 添加外层红框作为额外提示 --- */
.el-select.is-invalid :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset !important;
}

.el-select.team-select :deep(.el-select__selected-item) {
  z-index: -999;
  color: #909399;
  background-color: var(--el-color-info-light-9);
  border-color: var(--el-color-info-light-8);
  border: 1px solid var(--el-color-info-light-8);
  text-align: center;
  border-radius: 4px;
}

.el-select.is-invalid :deep(.el-select__selected-item) {
  z-index: -999;
  color: #F56C6C;
  background-color: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-8);
  border: 1px solid var(--el-color-danger-light-8);
  text-align: center;
  border-radius: 4px;
}

.unrecognized-section :deep(.el-input__inner) {
  z-index: -999;
  color: #F56C6C;
  background-color: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-8);
  border: 1px solid var(--el-color-danger-light-8);
  text-align: center;
  border-radius: 4px;
  height: 25px;
  margin: 3px 0;
}
</style>
