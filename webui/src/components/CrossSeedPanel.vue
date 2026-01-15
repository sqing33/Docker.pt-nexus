<template>
  <div class="cross-seed-panel">
    <!-- 1. 顶部步骤条 (固定) -->
    <header class="panel-header">
      <div class="custom-steps">
        <div
          v-for="(step, index) in steps"
          :key="index"
          class="custom-step"
          :class="{
            active: index === activeStep,
            completed: index < activeStep,
            last: index === steps.length - 1,
          }"
        >
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

    <!-- 2. 中间内容区 -->
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
                      <template v-if="filteredTitleComponents.length > 0">
                        <el-form-item
                          v-for="param in filteredTitleComponents"
                          :key="param.key"
                          :label="param.key"
                          :class="{
                            'unrecognized-section':
                              param.key === '制作组' &&
                              (!param.value || param.value.toUpperCase() === 'NOGROUP'),
                          }"
                        >
                          <el-input
                            v-model="param.value"
                            @input="(val) => handleTeamInput(param, val)"
                          />
                        </el-form-item>
                      </template>
                      <!-- 当没有解析出标题组件时，显示初始参数框 -->
                      <template v-else>
                        <el-form-item
                          v-for="(param, index) in initialTitleComponents"
                          :key="'init-' + index"
                          :label="param.key"
                          :class="{
                            'unrecognized-section':
                              param.key === '制作组' &&
                              (!param.value || param.value.toUpperCase() === 'NOGROUP'),
                          }"
                        >
                          <el-input
                            v-model="param.value"
                            @input="(val) => handleTeamInput(param, val)"
                          />
                        </el-form-item>
                      </template>
                    </div>
                  </div>

                  <div class="bottom-info-section">
                    <div class="subtitle-unrecognized-grid">
                      <!-- 副标题占4列 -->
                      <div class="subtitle-section" style="grid-column: span 4">
                        <el-form-item label="副标题">
                          <el-input v-model="torrentData.subtitle" />
                        </el-form-item>
                      </div>
                      <!-- 无法识别占1列 -->
                      <div
                        :class="{ 'unrecognized-section': unrecognizedValue }"
                        style="grid-column: span 1"
                      >
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
                          <el-select
                            v-model="torrentData.standardized_params.type"
                            placeholder="请选择类型"
                            clearable
                            :class="{
                              'is-invalid': invalidStandardParams.includes('type'),
                              'is-empty': !torrentData.standardized_params.type,
                            }"
                            data-tag-style
                          >
                            <el-option
                              v-for="(label, value) in reverseMappings.type"
                              :key="value"
                              :label="label"
                              :value="value"
                            />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="媒介 (medium)">
                          <el-select
                            v-model="torrentData.standardized_params.medium"
                            placeholder="请选择媒介"
                            clearable
                            :class="{
                              'is-invalid': invalidStandardParams.includes('medium'),
                              'is-empty': !torrentData.standardized_params.medium,
                            }"
                            data-tag-style
                          >
                            <el-option
                              v-for="(label, value) in reverseMappings.medium"
                              :key="value"
                              :label="label"
                              :value="value"
                            />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="视频编码 (video_codec)">
                          <el-select
                            v-model="torrentData.standardized_params.video_codec"
                            placeholder="请选择视频编码"
                            clearable
                            :class="{
                              'is-invalid': invalidStandardParams.includes('video_codec'),
                              'is-empty': !torrentData.standardized_params.video_codec,
                            }"
                            data-tag-style
                          >
                            <el-option
                              v-for="(label, value) in reverseMappings.video_codec"
                              :key="value"
                              :label="label"
                              :value="value"
                            />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="音频编码 (audio_codec)">
                          <el-select
                            v-model="torrentData.standardized_params.audio_codec"
                            placeholder="请选择音频编码"
                            clearable
                            :class="{
                              'is-invalid': invalidStandardParams.includes('audio_codec'),
                              'is-empty': !torrentData.standardized_params.audio_codec,
                            }"
                            data-tag-style
                          >
                            <el-option
                              v-for="(label, value) in reverseMappings.audio_codec"
                              :key="value"
                              :label="label"
                              :value="value"
                            />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="分辨率 (resolution)">
                          <el-select
                            v-model="torrentData.standardized_params.resolution"
                            placeholder="请选择分辨率"
                            clearable
                            :class="{
                              'is-invalid': invalidStandardParams.includes('resolution'),
                              'is-empty': !torrentData.standardized_params.resolution,
                            }"
                            data-tag-style
                          >
                            <el-option
                              v-for="(label, value) in reverseMappings.resolution"
                              :key="value"
                              :label="label"
                              :value="value"
                            />
                          </el-select>
                        </el-form-item>
                      </div>

                      <!-- 第二行：制作组、产地、标签特殊布局 -->
                      <div class="standard-params-grid second-row">
                        <!-- 【代码修改处】 -->
                        <el-form-item label="制作组 (team)">
                          <el-select
                            v-model="torrentData.standardized_params.team"
                            placeholder="请选择制作组"
                            clearable
                            filterable
                            allow-create
                            default-first-option
                            class="team-select"
                            :class="{
                              'is-invalid': invalidStandardParams.includes('team'),
                            }"
                          >
                            <el-option
                              v-for="(label, value) in reverseMappings.team"
                              :key="value"
                              :label="label"
                              :value="value"
                            />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="产地 (source)">
                          <el-select
                            v-model="torrentData.standardized_params.source"
                            placeholder="请选择产地"
                            clearable
                            :class="{
                              'is-invalid': invalidStandardParams.includes('source'),
                            }"
                            data-tag-style
                          >
                            <el-option
                              v-for="(label, value) in reverseMappings.source"
                              :key="value"
                              :label="label"
                              :value="value"
                            />
                          </el-select>
                        </el-form-item>

                        <el-form-item label="标签 (tags)" class="tags-wide-item">
                          <el-select
                            v-model="torrentData.standardized_params.tags"
                            multiple
                            filterable
                            allow-create
                            default-first-option
                            placeholder="请选择或输入标签"
                            style="width: 100%"
                          >
                            <template #tag="{ data }">
                              <el-tag
                                v-for="item in data"
                                :key="item.value"
                                :type="getTagType(item.value)"
                                :closable="!isRestrictedTag(item.value)"
                                disable-transitions
                                @close="handleTagClose(item.value)"
                                style="margin: 2px"
                              >
                                <span>{{
                                  reverseMappings.tags[item.value] || item.currentLabel
                                }}</span>
                              </el-tag>
                            </template>
                            <el-option
                              v-for="option in allTagOptions"
                              :key="option.value"
                              :label="option.label"
                              :value="option.value"
                            >
                              <span
                                :style="{
                                  color: invalidTagsList.includes(option.value) ? '#F56C6C' : '',
                                }"
                              >
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
                          <el-button
                            :icon="Refresh"
                            @click="refreshPosters"
                            :loading="isRefreshingPosters"
                            size="small"
                            type="text"
                          >
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
                          <img
                            v-for="(url, index) in posterImages"
                            :key="'poster-' + index"
                            :src="getProxyImageUrl(url)"
                            alt="海报预览"
                            class="preview-image"
                            @error="handleImageErrorWithProxy(url, 'poster', index)"
                          />
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
                        <el-button
                          :icon="Refresh"
                          @click="refreshScreenshots"
                          :loading="isRefreshingScreenshots"
                          size="small"
                          type="text"
                        >
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
                      <el-carousel-item
                        v-for="(url, index) in screenshotImages"
                        :key="'ss-' + index"
                      >
                        <div class="carousel-image-wrapper">
                          <img
                            :src="getProxyImageUrl(url)"
                            alt="截图预览"
                            class="carousel-image"
                            @error="handleImageErrorWithProxy(url, 'screenshot', index)"
                          />
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
                    <el-button
                      :icon="Refresh"
                      @click="refreshIntro"
                      :loading="isRefreshingIntro"
                      size="small"
                      type="text"
                    >
                      重新获取
                    </el-button>
                  </div>
                </template>
                <el-input type="textarea" v-model="torrentData.intro.body" :rows="21" />
              </el-form-item>
              <el-row :gutter="20">
                <el-col :span="8">
                  <el-form-item label="豆瓣链接">
                    <el-input v-model="torrentData.douban_link" placeholder="请输入豆瓣电影链接" />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="IMDb链接">
                    <el-input v-model="torrentData.imdb_link" placeholder="请输入IMDb电影链接" />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="TMDb链接">
                    <el-input v-model="torrentData.tmdb_link" placeholder="请输入TMDb电影链接" />
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="媒体信息" name="mediainfo">
            <el-form label-position="top" class="fill-height-form">
              <el-form-item class="is-flexible">
                <template #label>
                  <div class="form-label-with-button">
                    <span>Mediainfo</span>
                    <el-button
                      :icon="Refresh"
                      @click="refreshMediainfo"
                      :loading="isRefreshingMediainfo"
                      size="small"
                      type="text"
                    >
                      重新获取
                    </el-button>
                  </div>
                </template>

                <div class="mediainfo-container">
                  <!-- BDInfo 进度条 -->
                  <div v-if="bdinfoProgress.visible" class="bdinfo-progress-inline">
                    <el-card class="bdinfo-progress-card-inline" shadow="never">
                      <template #header>
                        <div class="progress-header">
                          <span>BDInfo 获取中...</span>
                          <div class="header-buttons">
                            <span class="background-hint">可在后台继续获取</span>
                            <el-button
                              :icon="Monitor"
                              @click="runInBackground"
                              size="small"
                              text
                              type="primary"
                            >
                              放置后台
                            </el-button>
                            <el-button
                              :icon="Close"
                              @click="stopBDInfoSSE"
                              size="small"
                              text
                              type="info"
                            >
                              取消获取
                            </el-button>
                          </div>
                        </div>
                      </template>
                      <el-progress
                        :percentage="bdinfoProgress.percent"
                        :status="bdinfoProgress.percent === 100 ? 'success' : ''"
                      />

                      <div class="progress-details-inline">
                        <div class="progress-info-row">
                          <div class="progress-item">原盘体积: {{ formatFileSize(discSize) }}</div>
                          <div class="progress-item">已用时: {{ bdinfoProgress.elapsedTime }}</div>
                          <div class="progress-item">
                            剩余时间: {{ bdinfoProgress.remainingTime }}
                          </div>
                        </div>
                      </div>
                    </el-card>
                  </div>

                  <!-- Mediainfo 文本框 -->
                  <el-input
                    type="textarea"
                    class="code-font"
                    v-model="torrentData.mediainfo"
                    :rows="bdinfoProgress.visible ? 18 : 26"
                  />
                </div>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <el-tab-pane
            label="已过滤声明"
            name="filtered-declarations"
            class="filtered-declarations-pane"
          >
            <div class="filtered-declarations-container">
              <div class="filtered-declarations-header">
                <h3>已自动过滤的声明内容</h3>
                <el-tag type="warning" size="small">共 {{ filteredDeclarationsCount }} 条</el-tag>
              </div>
              <div class="filtered-declarations-content">
                <template v-if="filteredDeclarationsCount > 0">
                  <div
                    v-for="(declaration, index) in filteredDeclarationsList"
                    :key="index"
                    class="declaration-item"
                  >
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
              {{
                torrentData.final_publish_parameters?.['主标题 (预览)'] ||
                torrentData.original_main_title ||
                '暂无数据'
              }}
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
                  <div style="display: flex">
                    <span style="letter-spacing: 2.6px" class="param-label">豆瓣链接</span>
                    <span style="font-size: 13px">：</span>
                    <span
                      :class="[
                        'param-value',
                        { empty: !torrentData.douban_link || torrentData.douban_link === 'N/A' },
                      ]"
                    >
                      {{ torrentData.douban_link || 'N/A' }}
                    </span>
                  </div>
                  <div style="display: flex">
                    <span class="param-label">IMDb链接：</span>
                    <span
                      :class="[
                        'param-value',
                        { empty: !torrentData.imdb_link || torrentData.imdb_link === 'N/A' },
                      ]"
                    >
                      {{ torrentData.imdb_link || 'N/A' }}
                    </span>
                  </div>
                  <div style="display: flex">
                    <span style="letter-spacing: 0" class="param-label">TMDb链接</span>
                    <span style="font-size: 13px">：</span>
                    <span
                      :class="[
                        'param-value',
                        { empty: !torrentData.tmdb_link || torrentData.tmdb_link === 'N/A' },
                      ]"
                    >
                      {{ torrentData.tmdb_link || 'N/A' }}
                    </span>
                  </div>
                </div>
                <div class="param-item tags-item half-width">
                  <span class="param-label">标签：</span>
                  <div class="param-value-container">
                    <span
                      :class="[
                        'param-value',
                        { empty: !getMappedTags() || getMappedTags().length === 0 },
                      ]"
                    >
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
                    <span :class="['param-value', { empty: !getMappedValue('type') }]">
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
                    <span :class="['param-value', { empty: !getMappedValue('medium') }]">
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
                    <span :class="['param-value', { empty: !getMappedValue('video_codec') }]">
                      {{ getMappedValue('video_codec') || 'N/A' }}
                    </span>
                    <span
                      class="param-standard-key"
                      v-if="torrentData.standardized_params.video_codec"
                    >
                      {{ torrentData.standardized_params.video_codec }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">音频编码：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { empty: !getMappedValue('audio_codec') }]">
                      {{ getMappedValue('audio_codec') || 'N/A' }}
                    </span>
                    <span
                      class="param-standard-key"
                      v-if="torrentData.standardized_params.audio_codec"
                    >
                      {{ torrentData.standardized_params.audio_codec }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">分辨率：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { empty: !getMappedValue('resolution') }]">
                      {{ getMappedValue('resolution') || 'N/A' }}
                    </span>
                    <span
                      class="param-standard-key"
                      v-if="torrentData.standardized_params.resolution"
                    >
                      {{ torrentData.standardized_params.resolution }}
                    </span>
                  </div>
                </div>
                <div class="param-item inline-param">
                  <span class="param-label">制作组：</span>
                  <div class="param-value-container">
                    <span :class="['param-value', { empty: !getMappedValue('team') }]">
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
                    <span :class="['param-value', { empty: !getMappedValue('source') }]">
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
                <div
                  class="section-content"
                  v-html="parseBBCode(torrentData.intro?.statement) || '暂无声明'"
                ></div>
              </div>

              <!-- 海报图片 -->
              <div class="description-section" v-if="posterImages.length > 0">
                <div class="image-gallery">
                  <img
                    v-for="(url, index) in posterImages"
                    :key="'poster-preview-' + index"
                    :src="getProxyImageUrl(url)"
                    :alt="'海报 ' + (index + 1)"
                    class="preview-image-inline"
                    style="width: 300px"
                    @error="handleImageErrorWithProxy(url, 'poster', index)"
                  />
                </div>
              </div>

              <!-- 简介正文 -->
              <div class="description-section">
                <br />
                <div
                  class="section-content"
                  v-html="parseBBCode(torrentData.intro?.body) || '暂无正文'"
                ></div>
              </div>

              <!-- 视频截图 -->
              <div class="description-section" v-if="screenshotImages.length > 0">
                <div class="image-gallery">
                  <img
                    v-for="(url, index) in screenshotImages"
                    :key="'screenshot-preview-' + index"
                    :src="getProxyImageUrl(url)"
                    :alt="'截图 ' + (index + 1)"
                    class="preview-image-inline"
                    @error="handleImageErrorWithProxy(url, 'screenshot', index)"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 步骤 2: 选择发布站点 -->
      <div v-if="activeStep === 2" class="step-container site-selection-container">
        <h3 class="selection-title">请选择要发布的目标站点</h3>
        <p class="selection-subtitle">已存在的站点已被自动禁用。红色站点表示配置不完整。</p>

        <!-- 禁止转载警告 -->
        <el-alert
          v-if="isUbitsDisabled"
          type="error"
          :closable="false"
          style="width: 410px; margin: 0 auto"
        >
          <template #title>
            <span style="font-weight: 600">禁止转载</span>
          </template>
          <div>
            检测到制作组包含禁止转载的内容，已自动禁用 UBits 站点。<br />
            禁止转载的制作组：CMCT、CMCTV、HDSky、HDSWEB、HDS、HDSTV、HDSPad
          </div>
        </el-alert>

        <div class="select-all-container" style="margin-top: 16px">
          <el-button-group>
            <el-button type="primary" @click="selectAllTargetSites">全选</el-button>
            <el-button type="info" @click="clearAllTargetSites">清空</el-button>
          </el-button-group>
        </div>
        <div class="site-buttons-group">
          <el-button
            v-for="site in allSitesStatus.filter((s) => s.is_target)"
            :key="site.name"
            class="site-button"
            :type="getButtonType(site)"
            :plain="!site.has_cookie"
            :disabled="!isTargetSiteSelectable(site.name)"
            @click="toggleSiteSelection(site.name)"
          >
            {{ site.name }}
            <el-tooltip
              v-if="site.name === 'ubits' && !isTargetSiteSelectable(site.name)"
              content="该制作组禁止转载到 uBits 站点"
              placement="top"
            >
              <el-icon style="margin-left: 4px; color: #f56c6c">
                <InfoFilled />
              </el-icon>
            </el-tooltip>
          </el-button>
        </div>
      </div>

      <!-- 步骤 3: 完成发布 -->
      <div v-if="activeStep === 3" class="step-container results-container">
        <!-- 进度条显示 -->
        <div class="progress-section" v-if="activeStep === 3">
          <div class="progress-item" v-if="publishProgress.total > 0">
            <div class="progress-label">发布进度:</div>
            <el-progress
              :percentage="Math.round((publishProgress.current / publishProgress.total) * 100)"
              :show-text="true"
              :stroke-width="8"
            />
            <div class="progress-text">
              {{ publishProgress.current }} / {{ publishProgress.total }}
            </div>
          </div>
          <div class="progress-item" v-if="downloaderProgress.total > 0">
            <div class="progress-label">下载器添加进度:</div>
            <el-progress
              :percentage="
                Math.round((downloaderProgress.current / downloaderProgress.total) * 100)
              "
              :show-text="true"
              :stroke-width="8"
            />
            <div class="progress-text">
              {{ downloaderProgress.current }} / {{ downloaderProgress.total }}
            </div>
          </div>

          <!-- 🚫 发种限制提示 -->
          <div class="limit-alert-section" v-if="limitAlert.visible">
            <div class="limit-alert">
              <div class="limit-alert-content">
                <div class="limit-alert-title">{{ limitAlert.title }}</div>
                <div class="limit-alert-message">{{ limitAlert.message }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="results-rows-container">
          <div v-for="(row, rowIndex) in groupedResults" :key="rowIndex" class="results-row">
            <div class="row-sites">
              <div
                v-for="result in row"
                :key="result.siteName"
                class="result-card"
                :class="{ 'is-success': result.success, 'is-error': !result.success }"
              >
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
                  <span
                    class="status-text"
                    :class="{
                      success: result.downloaderStatus.success,
                      error: !result.downloaderStatus.success,
                    }"
                  >
                    {{
                      result.downloaderStatus.success
                        ? `种子已添加到'${result.downloaderStatus.downloaderName}'`
                        : '添加失败'
                    }}
                  </span>
                </div>

                <!-- 操作按钮 -->
                <div class="card-extra">
                  <el-button
                    type="primary"
                    size="small"
                    @click="showSiteLog(result.siteName, result.logs)"
                  >
                    查看日志
                  </el-button>
                  <a
                    v-if="result.success && result.url"
                    :href="filterUploadedParam(result.url)"
                    target="_blank"
                    rel="noopener noreferrer"
                    style="transform: translateY(-1px)"
                  >
                    <el-button type="success" size="small"> 查看种子 </el-button>
                  </a>
                </div>
              </div>
            </div>
            <div class="row-action">
              <el-button
                type="warning"
                :icon="Refresh"
                size="large"
                @click="openAllSitesInRow(row)"
                :disabled="!hasValidUrlsInRow(row)"
                class="open-all-button"
              >
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
        <transition name="el-fade-in-linear">
          <div v-if="props.showCompleteButton" class="check-hint">
            修改完成后请预览一遍种子信息确保无误后完成修改！
          </div>
        </transition>
        <el-button @click="handleCancelClick">取消</el-button>

        <el-button type="primary" @click="goToPublishPreviewStep" :disabled="isNextButtonDisabled">
          下一步：发布参数预览
        </el-button>

        <!-- 新增：直接在右侧显示的提示文本 -->
        <transition name="el-fade-in-linear">
          <div v-if="isNextButtonDisabled" class="validation-hint">
            <el-icon class="hint-icon">
              <Warning />
            </el-icon>
            <span>{{ nextButtonTooltipContent }}</span>
          </div>
        </transition>
      </div>
      <!-- 步骤 1 的按钮 -->
      <div v-if="activeStep === 1" class="button-group">
        <el-button @click="handlePreviousStep" :disabled="isLoading">上一步</el-button>

        <el-button
          type="primary"
          @click="handleCompleteClick"
          v-if="props.showCompleteButton"
          :disabled="isLoading || !isScrolledToBottom"
          :class="{ 'scrolled-to-bottom': isScrolledToBottom }"
        >
          修改完成
        </el-button>

        <!-- 注意：原本这里的 hint 移到了下面 -->

        <el-button
          type="primary"
          @click="goToSelectSiteStep"
          :disabled="isLoading || !isScrolledToBottom"
          :class="{ 'scrolled-to-bottom': isScrolledToBottom }"
        >
          下一步：选择发布站点
        </el-button>

        <!-- 将所有提示组件移到按钮组的末尾，这样它们会统一显示在按钮组的最右侧 -->

        <!-- 提示 1：针对修改完成按钮 (如果需要区分显示，可以使用 v-else-if，防止重叠) -->
        <transition name="el-fade-in-linear">
          <div v-if="props.showCompleteButton && !isScrolledToBottom" class="validation-hint">
            <el-icon class="hint-icon">
              <Warning />
            </el-icon>
            <span>请滚动到页面底部检查完种子信息无误再发布！</span>
          </div>
        </transition>

        <!-- 提示 2：针对下一步按钮 -->
        <!-- 使用 v-else-if 避免两个提示同时出现重叠显示 -->
        <transition name="el-fade-in-linear">
          <div v-if="!props.showCompleteButton && !isScrolledToBottom" class="validation-hint">
            <el-icon class="hint-icon">
              <Warning />
            </el-icon>
            <span>请先滚动到页面底部检查完种子信息再发布！</span>
          </div>
        </transition>
      </div>
      <!-- 步骤 2 的按钮 -->
      <div v-if="activeStep === 2" class="button-group">
        <el-button @click="handleCancelClick" :disabled="isLoading">取消</el-button>
        <el-button
          type="primary"
          @click="handlePublish"
          :loading="isLoading"
          :disabled="selectedTargetSites.length === 0"
        >
          立即发布
        </el-button>
      </div>
      <!-- 步骤 3 的按钮 -->
      <div v-if="activeStep === 3" class="button-group">
        <el-button type="primary" @click="handleCompleteClick">完成</el-button>
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

  <!-- [新增] 抓取失败详情弹窗 -->
  <el-dialog
    v-model="showErrorDialog"
    title="抓取失败 - 详细日志"
    width="800px"
    destroy-on-close
    append-to-body
    class="error-log-dialog"
  >
    <div class="error-log-container">
      <el-alert
        title="获取种子信息过程中发生错误"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom: 15px"
      >
        <template #default>
          <div>请查看下方详细日志以排查问题（如 Python 堆栈信息）。</div>
        </template>
      </el-alert>

      <el-scrollbar height="500px">
        <div class="log-timeline">
          <div
            v-for="log in parsedErrorLogs"
            :key="log.id"
            class="log-entry"
            :class="{ 'is-error': log.isError }"
          >
            <!-- 日志头部：时间与摘要 -->
            <div class="log-entry-header">
              <span class="log-time">{{ log.time }}</span>
              <el-tag
                :type="getLogLevelType(log.level)"
                size="small"
                effect="dark"
                class="log-level-tag"
              >
                {{ log.level }}
              </el-tag>
              <span class="log-site" v-if="log.site">[{{ log.site }}]</span>
              <span class="log-text">{{ log.message }}</span>
            </div>

            <!-- 日志详情（报错堆栈） -->
            <div v-if="log.details" class="log-entry-details">
              <pre class="code-block">{{ log.details }}</pre>
            </div>
          </div>
        </div>
      </el-scrollbar>
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="showErrorDialog = false">关闭</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// ... 你的 <script setup> 部分完全保持不变 ...
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { ElNotification, ElMessageBox, ElProgress } from 'element-plus'
import { ElTooltip } from 'element-plus'
import axios from 'axios'
import {
  Refresh,
  CircleCheckFilled,
  CircleCloseFilled,
  Close,
  InfoFilled,
  Warning,
  Monitor,
} from '@element-plus/icons-vue'
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
  text = text.replace(
    /(\[(?:b|color)[^\]]*\][\s\S]*?)\n\s*\n([\s\S]*?\[\/(?:b|color)\])/gi,
    '$1\n$2',
  )
  // 处理多层嵌套标签
  for (let i = 0; i < 3; i++) {
    text = text.replace(
      /(\[(?:quote|b|color|size)[^\]]*\][\s\S]*?)\n\s*\n([\s\S]*?\[\/(?:quote|b|color|size)\])/gi,
      '$1\n$2',
    )
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
  text = text.replace(
    /\[color=(\w+|#[0-9a-fA-F]{3,6})\]([\s\S]*?)\[\/color\]/gi,
    '<span style="color: $1;">$2</span>',
  )

  // 处理 [size] 标签，映射到具体的像素值
  text = text.replace(
    /\[size=(\d+)\]([\s\S]*?)\[\/size\]/gi,
    (match: string, size: string, content: string): string => {
      // 根据 size 值映射到具体的像素值
      const sizeMap: { [key: string]: string } = {
        '1': '12',
        '2': '14',
        '3': '16',
        '4': '18',
        '5': '24',
        '6': '32',
        '7': '48',
      }
      const pixelSize = sizeMap[size] || parseInt(size) * 4
      return `<span style="font-size: ${pixelSize}px;">${content}</span>`
    },
  )

  // 处理换行符
  text = text.replace(/\n/g, '<br>')

  return text
}

// --- [新增] 日志解析函数：将后端返回的文本日志解析为结构化数据 ---
const parseLogText = (text: string) => {
  if (!text) return []

  const lines = text.split('\n')
  const results: any[] = []
  let currentEntry: any = null

  // 正则匹配日志行：[站点名] HH:mm:ss - LEVEL - 内容
  // 参考你的日志格式: [不可说] 21:29:26 - INFO - ...
  const logRegex = /^\[(.*?)\]\s+(\d{2}:\d{2}:\d{2})\s+-\s+([A-Z]+)\s+-\s+(.*)$/

  lines.forEach((line, index) => {
    const trimmedLine = line.trimEnd()
    if (!trimmedLine) return

    const match = trimmedLine.match(logRegex)

    if (match) {
      // 这是一个新的日志行
      currentEntry = {
        id: index,
        site: match[1],
        time: match[2],
        level: match[3],
        message: match[4],
        details: '', // 用于存放后续的堆栈信息
        isError: match[3] === 'ERROR' || match[3] === 'CRITICAL',
      }
      // 如果消息本身就包含 Traceback 关键字，标记为错误
      if (currentEntry.message.includes('Traceback')) {
        currentEntry.isError = true
      }
      results.push(currentEntry)
    } else {
      // 这不是标准的日志头（例如 Python 的 Traceback 堆栈信息）
      if (currentEntry) {
        // 追加到上一条日志的详情中
        currentEntry.details += (currentEntry.details ? '\n' : '') + trimmedLine
        // 如果包含 File "...", line ... 这种堆栈特征，强制标记上一条为错误
        if (trimmedLine.trim().startsWith('File "')) {
          currentEntry.isError = true
        }
      } else {
        // 只有第一行就是非标准格式时才会走到这里
        results.push({
          id: index,
          site: 'System',
          time: '',
          level: 'INFO',
          message: trimmedLine,
          details: '',
          isError: false,
        })
      }
    }
  })

  return results
}

// --- [新增] 获取日志等级对应的标签颜色 ---
const getLogLevelType = (level: string) => {
  switch (level) {
    case 'SUCCESS':
      return 'success'
    case 'ERROR':
      return 'danger'
    case 'WARNING':
      return 'warning'
    case 'DEBUG':
      return 'info'
    default:
      return 'primary' // INFO
  }
}

interface SiteStatus {
  name: string
  site: string
  has_cookie: boolean
  has_passkey: boolean
  is_source: boolean
  is_target: boolean
}

interface Torrent {
  name: string
  save_path: string
  size: number
  size_formatted: string
  progress: number
  state: string
  sites: Record<string, any>
  total_uploaded: number
  total_uploaded_formatted: string
  downloaderId?: string
}

const props = defineProps({
  showCompleteButton: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['complete', 'cancel', 'close-with-refresh'])

const crossSeedStore = useCrossSeedStore()

const torrent = computed(() => crossSeedStore.workingParams as Torrent)
const sourceSite = computed(() => crossSeedStore.sourceInfo?.name || '')

const getInitialTorrentData = () => ({
  seed_id: null,
  title_components: [] as { key: string; value: string }[],
  original_main_title: '',
  subtitle: '',
  imdb_link: '',
  douban_link: '',
  tmdb_link: '',
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
    tags: [] as string[],
  },
  final_publish_parameters: {},
  complete_publish_params: {},
  raw_params_for_preview: {},
})

const parseImageUrls = (text: string) => {
  if (!text || typeof text !== 'string') return []
  const regex = /\[img\](https?:\/\/[^\s[\]]+)\[\/img\]/gi
  const matches = [...text.matchAll(regex)]
  return matches.map((match) => match[1])
}

// 图片代理URL处理
const imageProxyMap = ref(new Map<string, string>())

const getProxyImageUrl = (originalUrl: string): string => {
  // 如果已经尝试过代理URL，直接返回
  if (imageProxyMap.value.has(originalUrl)) {
    return imageProxyMap.value.get(originalUrl)!
  }

  // 首次尝试原始URL
  imageProxyMap.value.set(originalUrl, originalUrl)
  return originalUrl
}

const handleImageErrorWithProxy = (url: string, type: 'poster' | 'screenshot', index: number) => {
  // 检查是否已经尝试过代理
  const currentUrl = imageProxyMap.value.get(url)
  if (currentUrl && !currentUrl.startsWith('http://pt-nexus-proxy.sqing33.dpdns.org/')) {
    // 尝试使用代理URL
    const proxyUrl = `http://pt-nexus-proxy.sqing33.dpdns.org/${url}`
    imageProxyMap.value.set(url, proxyUrl)

    // 强制更新图片显示
    const imgElements = document.querySelectorAll(`img[src="${currentUrl}"]`)
    imgElements.forEach((img) => {
      img.setAttribute('src', proxyUrl)
    })

    console.log(`图片加载失败，尝试使用代理URL: ${proxyUrl}`)
    return // 不调用原有的错误处理，给代理URL一次机会
  }

  // 如果代理URL也失败了，调用原有的错误处理
  handleImageError(url, type, index)
}

const activeStep = ref(0)
const activeTab = ref('main')
const isScrolledToBottom = ref(false)

// Progress tracking variables
const publishProgress = ref({ current: 0, total: 0 })
const downloaderProgress = ref({ current: 0, total: 0 })

// 🚫 发种限制提示
const limitAlert = ref({
  visible: false,
  title: '',
  message: '',
})

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
  fetchSitesStatus()
  fetchTorrentInfo()

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
  { title: '完成发布' },
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
const downloaderList = ref<{ id: string; name: string }[]>([])
const isDataFromDatabase = ref(false) // Flag to track if data was loaded from database

// BDInfo SSE相关变量
const bdinfoEventSource = ref<EventSource | null>(null)

// BDInfo 进度相关变量
const bdinfoProgress = ref({
  visible: false,
  percent: 0,
  currentFile: '',
  elapsedTime: '',
  remainingTime: '',
})

// BDInfo 状态变量
const bdinfoStatus = ref('')

// BDInfo 碟片大小
const discSize = ref(0)

// 格式化文件大小
const formatFileSize = (bytes: number) => {
  if (!bytes) return ''

  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unitIndex = 0

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }

  return `${size.toFixed(2)} ${units[unitIndex]}`
}

// --- [新增] 错误弹窗相关的状态 ---
const showErrorDialog = ref(false)
const parsedErrorLogs = ref<any[]>([])

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
  tags: {},
})

const posterImages = computed(() => parseImageUrls(torrentData.value.intro.poster))
const screenshotImages = computed(() => parseImageUrls(torrentData.value.intro.screenshots))

const filteredDeclarationsList = computed(() => {
  const removedDeclarations = torrentData.value.intro.removed_ardtudeclarations
  if (Array.isArray(removedDeclarations)) {
    return removedDeclarations
  }
  return []
})
const filteredDeclarationsCount = computed(() => filteredDeclarationsList.value.length)

const isTargetSiteSelectable = (siteName: string): boolean => {
  // 步骤 1: 查找站点的状态信息
  const siteStatus = allSitesStatus.value.find((s) => s.name === siteName)

  // 条件 1: 如果找不到站点信息或站点没有配置Cookie，则不可选
  if (!siteStatus || !siteStatus.has_cookie) {
    return false
  }

  // 对于杜比(hddolby)和HDTime站点，还需要检查passkey
  if (
    (siteName === '杜比' || siteName === 'HDtime' || siteName === '肉丝') &&
    !siteStatus.has_passkey
  ) {
    return false
  }

  // 条件 2: 如果种子已经存在于该站点，则不可选
  if (torrent.value?.sites?.[siteName]) {
    return false
  }

  // 条件 3: 检查是否为ubits站点并应用特殊禁转规则
  if (siteName.toLowerCase() === 'ubits') {
    const team = torrentData.value.standardized_params.team
    const titleComponents = torrentData.value.title_components

    // 检查标准化参数中的制作组
    if (
      team &&
      ['cmct', 'cmctv', 'hdsky', 'hdsweb', 'hds', 'hdstv', 'hdspad'].includes(team.toLowerCase())
    ) {
      return false
    }

    // 检查标题组件中的制作组
    const teamComponent = titleComponents.find((param) => param.key === '制作组')
    if (teamComponent && teamComponent.value) {
      const teamValue = teamComponent.value.toLowerCase()
      const forbiddenTeams = [
        'cmct',
        'cmctv',
        'telesto',
        'shadow610',
        'hdsky',
        'hdsweb',
        'hds',
        'hdstv',
        'hdspad',
      ]

      for (const forbiddenTeam of forbiddenTeams) {
        if (teamValue.includes(forbiddenTeam)) {
          return false
        }
      }
    }
  }

  // 如果所有检查都通过，则站点可选
  return true
}

// 新增函数：根据站点状态获取按钮类型
const getButtonType = (site: SiteStatus) => {
  // 如果站点已被选中，显示为绿色
  if (selectedTargetSites.value.includes(site.name)) {
    return 'success'
  }
  // 如果站点没有Cookie，显示为红色 (danger)
  if (!site.has_cookie) {
    return 'danger'
  }
  // 对于杜比站点，如果已配置Cookie但未配置Passkey，也显示为红色
  if (
    (site.name === '杜比' || site.name === 'HDtime' || site.name === '肉丝') &&
    !site.has_passkey
  ) {
    return 'danger'
  }
  // 其他情况（可选但未选中），显示为默认样式
  return 'default'
}

const refreshIntro = async () => {
  isRefreshingIntro.value = true
  ElNotification.info({
    title: '正在重新获取',
    message: '正在从豆瓣/IMDb/TMDb重新获取简介...',
    duration: 0,
  })

  const payload = {
    type: 'intro',
    content_name: torrentData.value.original_main_title,
    source_info: {
      main_title: torrentData.value.original_main_title,
      subtitle: torrentData.value.subtitle,
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
      tmdb_link: torrentData.value.tmdb_link,
    },
  }

  try {
    const response = await axios.post('/api/media/validate', payload)
    ElNotification.closeAll()

    if (response.data.success && response.data.intro) {
      torrentData.value.intro.body = filterExtraEmptyLines(response.data.intro)

      // 使用返回的IMDb链接、豆瓣链接、TMDb链接填充
      if (response.data.extracted_imdb_link && !torrentData.value.imdb_link) {
        torrentData.value.imdb_link = response.data.extracted_imdb_link
      }

      if (response.data.extracted_douban_link && !torrentData.value.douban_link) {
        torrentData.value.douban_link = response.data.extracted_douban_link
      }

      if (response.data.extracted_tmdb_link && !torrentData.value.tmdb_link) {
        torrentData.value.tmdb_link = response.data.extracted_tmdb_link
      }

      ElNotification.success({
        title: '重新获取成功',
        message: '已成功从豆瓣/IMDb/TMDb获取并更新了简介内容。',
      })
    } else {
      ElNotification.error({
        title: '重新获取失败',
        message: response.data.error || '无法从豆瓣/IMDb/TMDb获取简介。',
      })
    }
  } catch (error: any) {
    ElNotification.closeAll()
    const errorMsg = error.response?.data?.error || '未能重新获取简介'
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    })
  } finally {
    isRefreshingIntro.value = false
  }
}

const refreshScreenshots = async () => {
  if (!torrentData.value.original_main_title) {
    ElNotification.warning('标题为空，无法重新获取截图。')
    return
  }

  // 防止重复请求
  if (isRefreshingScreenshots.value) {
    ElNotification.info({
      title: '正在处理中',
      message: '截图重新生成请求已在处理中，请稍候...',
    })
    return
  }

  isRefreshingScreenshots.value = true
  ElNotification.info({
    title: '正在重新获取',
    message: '正在从视频重新生成截图...',
    duration: 0,
  })

  const payload = {
    type: 'screenshot',
    content_name: torrentData.value.original_main_title,
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
      tmdb_link: torrentData.value.tmdb_link,
    },
    savePath: torrent.value.save_path,
    torrentName: torrent.value.name,
    downloaderId: torrent.value.downloaderId, // 添加下载器ID
  }

  try {
    const response = await axios.post('/api/media/validate', payload)
    ElNotification.closeAll()

    if (response.data.success && response.data.screenshots) {
      torrentData.value.intro.screenshots = response.data.screenshots
      screenshotValid.value = true // 标记截图有效
      ElNotification.success({
        title: '重新获取成功',
        message: '已成功生成并加载了新的截图。',
      })
    } else {
      // 如果重新获取截图失败，标记截图无效
      screenshotValid.value = false
      ElNotification.error({
        title: '重新获取失败',
        message: response.data.error || '无法从后端获取新的截图，请查看后台日志。',
      })
    }
  } catch (error: any) {
    ElNotification.closeAll()
    const errorMsg = error.response?.data?.error || '未能重新获取截图，请查看后台日志。'
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    })
    // 如果重新获取截图失败，标记截图无效
    screenshotValid.value = false
  } finally {
    isRefreshingScreenshots.value = false
  }
}

const refreshMediainfo = async () => {
  // 移除标题检查，允许任何时候重新获取
  // 防止重复请求
  if (isRefreshingMediainfo.value) {
    ElNotification.info({
      title: '正在处理中',
      message: '媒体信息重新获取请求已在处理中，请稍候...',
    })
    return
  }

  isRefreshingMediainfo.value = true
  ElNotification.info({
    title: '正在重新获取',
    message: '正在从视频重新生成媒体信息...',
    duration: 0,
  })

  try {
    // 使用新的异步 API
    const response = await axios.post('/api/migrate/refresh_mediainfo_async', {
      seed_id: torrentData.value.seed_id,
      save_path: torrent.value.save_path,
      content_name: torrentData.value.original_main_title,
      downloader_id: torrent.value.downloaderId,
      torrent_name: torrent.value.name,
      current_mediainfo: torrentData.value.mediainfo,
      force_refresh: true,
      priority: 1, // 单个种子使用高优先级
    })

    ElNotification.closeAll()

    if (response.data.success) {
      // 如果有 MediaInfo 内容，先更新
      if (response.data.mediainfo) {
        torrentData.value.mediainfo = response.data.mediainfo
      }

      // 如果 BDInfo 在后台处理中，开始SSE连接
      if (response.data.bdinfo_async && response.data.bdinfo_async.bdinfo_status === 'processing') {
        ElNotification.info({
          title: 'BDInfo 处理中',
          message: 'BDInfo 正在后台处理中，完成后将自动更新...',
          duration: 5000,
        })
        startBDInfoSSE()
      } else if (response.data.mediainfo) {
        ElNotification.success({
          title: '重新获取成功',
          message: response.data.message || '已成功生成并加载了新的媒体信息。',
        })
      } else {
        ElNotification.info({
          title: '任务已启动',
          message: response.data.message || 'BDInfo 正在后台处理中...',
        })
      }
    } else {
      ElNotification.error({
        title: '重新获取失败',
        message: response.data.message || '无法从后端获取新的媒体信息，请查看后台日志。',
      })
    }
  } catch (error: any) {
    ElNotification.closeAll()
    const errorMsg =
      error.response?.data?.message ||
      error.response?.data?.error ||
      '未能重新获取媒体信息，请查看后台日志。'
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    })
  } finally {
    isRefreshingMediainfo.value = false
  }
}

// 检查 BDInfo 状态并自动启动进度显示
const checkAndStartBDInfoProgress = async (seedId: string, isFromFetch: boolean = false) => {
  const maxRetries = isFromFetch ? 5 : 3 // 从抓取流程调用时增加重试次数
  const retryDelay = isFromFetch ? 2000 : 1000 // 从抓取流程调用时增加延迟

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const response = await axios.get(`/api/migrate/bdinfo_status/${seedId}`)

      // 添加调试信息
      console.log(`BDInfo 状态 API 响应 (尝试 ${attempt}/${maxRetries}):`, response.data)

      // 修复：直接检查响应数据，不依赖 success 字段
      const data = response.data
      if (data && !data.error) {
        // 修复：从正确的字段获取状态
        const status = data.mediainfo_status || data.task_status?.status

        if (status === 'processing_bdinfo' || status === 'queued') {
          // 启动 BDInfo 进度显示
          console.log(`检测到 BDInfo 任务正在进行中: ${status}`)
          console.log('任务 ID:', data.bdinfo_task_id)
          console.log('进度信息:', data.progress_info)

          startBDInfoSSE()
          bdinfoStatus.value = status
          return // 成功检测到任务，退出重试循环
        } else if (status === 'completed' || status === 'failed') {
          console.log(`BDInfo 任务已结束: ${status}，无需启动进度显示`)
          return // 任务已结束，退出重试循环
        } else {
          console.log(`BDInfo 任务状态: ${status}，尝试 ${attempt}/${maxRetries}`)
        }
      } else {
        console.warn('BDInfo 状态 API 返回错误:', data?.error)
      }
    } catch (error) {
      // 增强错误处理
      if (error.response) {
        // HTTP 错误响应
        const status = error.response.status
        if (status === 404) {
          console.warn(`种子记录不存在: ${seedId} (尝试 ${attempt}/${maxRetries})`)
        } else if (status === 500) {
          console.warn('服务器内部错误，检查 BDInfo 状态失败')
        } else {
          console.warn(`HTTP ${status}: 检查 BDInfo 状态失败`)
        }
      } else if (error.request) {
        // 网络错误
        console.warn('网络连接问题，无法检查 BDInfo 状态')
      } else {
        // 其他错误
        console.warn('检查 BDInfo 状态失败:', error.message)
      }
    }

    // 如果不是最后一次尝试，等待后重试
    if (attempt < maxRetries) {
      console.log(`等待 ${retryDelay}ms 后重试检查 BDInfo 状态...`)
      await new Promise((resolve) => setTimeout(resolve, retryDelay))
    }
  }

  // 所有重试都失败了
  console.warn(`经过 ${maxRetries} 次尝试，未能检测到 BDInfo 任务`)
}

// BDInfo SSE相关函数
const startBDInfoSSE = () => {
  console.log('启动 BDInfo SSE 连接...')

  // 验证 seed_id
  if (!torrentData.value?.seed_id) {
    console.error('seed_id 未设置，无法建立 SSE 连接')
    ElNotification.error({
      title: '连接错误',
      message: '种子ID未设置，无法建立进度连接',
    })
    return
  }

  console.log(`使用 seed_id 建立 SSE 连接: ${torrentData.value.seed_id}`)

  // 关闭之前的连接
  stopBDInfoSSE(false)

  // 显示进度条
  bdinfoProgress.value = {
    visible: true,
    percent: 0,
    currentFile: '正在连接...',
    elapsedTime: '',
    remainingTime: '',
  }

  // 创建EventSource连接
  const url = `/api/migrate/bdinfo_sse/${torrentData.value.seed_id}`
  console.log(`SSE 连接 URL: ${url}`)
  bdinfoEventSource.value = new EventSource(url)

  // 添加连接超时处理
  let connectionTimeout: NodeJS.Timeout | null = setTimeout(() => {
    if (bdinfoEventSource.value?.readyState === EventSource.CONNECTING) {
      console.warn('SSE 连接超时，尝试重新连接')
      bdinfoEventSource.value?.close()
      // 尝试重新连接一次
      if (bdinfoProgress.value.visible) {
        setTimeout(() => {
          console.log('尝试重新建立 SSE 连接...')
          startBDInfoSSE()
        }, 2000)
      }
    }
  }, 5000) // 5秒超时

  // 处理连接成功
  bdinfoEventSource.value.onopen = () => {
    console.log('BDInfo SSE连接已建立')
    if (connectionTimeout) {
      clearTimeout(connectionTimeout)
      connectionTimeout = null
    }
    // 请求当前进度状态
    requestCurrentProgress()
  }

  // 处理消息
  bdinfoEventSource.value.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)

      switch (data.type) {
        case 'connected':
          console.log('SSE连接成功:', data.connection_id)
          break

        case 'progress_update':
          // 更新进度条
          const { progress_percent, current_file, elapsed_time, remaining_time, disc_size } =
            data.data
          bdinfoProgress.value = {
            visible: true,
            percent: Math.round(progress_percent),
            currentFile: current_file,
            elapsedTime: elapsed_time,
            remainingTime: remaining_time,
          }
          // 更新disc size
          if (disc_size) {
            discSize.value = disc_size
          }
          console.log(`BDInfo 进度: ${progress_percent}%`)
          break

        case 'completion':
          // BDInfo 完成
          torrentData.value.mediainfo = data.data.mediainfo
          ElNotification.success({
            title: 'BDInfo 获取完成',
            message: 'BDInfo 已成功获取并更新',
          })
          bdinfoProgress.value.visible = false
          stopBDInfoSSE(false)
          break

        case 'error':
          // BDInfo 失败
          ElNotification.warning({
            title: 'BDInfo 获取失败',
            message: data.data.error || 'BDInfo 获取失败，可手动重试',
          })
          bdinfoProgress.value.visible = false
          stopBDInfoSSE(false)
          break

        case 'heartbeat':
          // 心跳包，保持连接，不更新进度
          return

        default:
          console.log('未知SSE消息类型:', data.type)
      }
    } catch (error) {
      console.error('解析SSE消息失败:', error)
    }
  }

  // 处理错误
  bdinfoEventSource.value.onerror = (error) => {
    console.error('SSE连接错误:', error)
    if (connectionTimeout) {
      clearTimeout(connectionTimeout)
      connectionTimeout = null
    }

    // 检查连接状态
    const readyState = bdinfoEventSource.value?.readyState
    console.log(`SSE 连接状态: ${readyState} (0=CONNECTING, 1=OPEN, 2=CLOSED)`)

    // 如果是连接中或已关闭，尝试重连
    if (readyState === EventSource.CONNECTING || readyState === EventSource.CLOSED) {
      if (bdinfoProgress.value.visible) {
        console.log('尝试重新建立 SSE 连接...')
        bdinfoProgress.value.currentFile = '连接中断，正在重连...'

        // 延迟2秒后重连
        setTimeout(() => {
          if (bdinfoProgress.value.visible) {
            startBDInfoSSE()
          }
        }, 2000)
      }
    } else {
      // 其他错误，显示错误通知
      ElNotification.error({
        title: '连接错误',
        message: 'BDInfo 进度更新连接中断，请刷新页面重试',
      })
      bdinfoProgress.value.visible = false
      stopBDInfoSSE(false)
    }
  }
}

// 停止 BDInfo SSE
const stopBDInfoSSE = (showNotification: boolean | Event = true) => {
  if (bdinfoEventSource.value) {
    bdinfoEventSource.value.close()
    bdinfoEventSource.value = null
  }
  // 隐藏进度条
  bdinfoProgress.value.visible = false
  if (showNotification === true || (typeof showNotification === 'object' && showNotification)) {
    ElNotification.info({
      title: '已取消',
      message: 'BDInfo 获取已取消',
    })
  }
}

// 请求当前进度
const requestCurrentProgress = async () => {
  if (!torrentData.value?.seed_id) {
    console.warn('seed_id 未设置，无法请求当前进度')
    return
  }

  try {
    console.log('请求当前 BDInfo 进度状态...')
    const response = await axios.get(`/api/migrate/bdinfo_status/${torrentData.value.seed_id}`)

    if (response.data && response.data.task_status) {
      const taskStatus = response.data.task_status
      console.log('获取到当前进度状态:', taskStatus)

      // 如果任务正在进行中，更新进度显示
      if (taskStatus.status === 'processing_bdinfo') {
        bdinfoProgress.value = {
          visible: true,
          percent: Math.round(taskStatus.progress_percent || 0),
          currentFile: taskStatus.current_file || '处理中...',
          elapsedTime: taskStatus.elapsed_time || '',
          remainingTime: taskStatus.remaining_time || '',
        }
        console.log(`更新进度显示: ${taskStatus.progress_percent || 0}%`)
      }
    }
  } catch (error) {
    console.error('请求当前进度失败:', error)
    // 静默失败，不影响主要功能
  }
}

// 后台运行
const runInBackground = () => {
  // 停止SSE连接但保持任务运行
  if (bdinfoEventSource.value) {
    bdinfoEventSource.value.close()
    bdinfoEventSource.value = null
  }
  handleCancelClick()
}

// 手动刷新 BDInfo
const refreshBDInfo = async () => {
  try {
    const response = await axios.post(`/api/migrate/refresh_bdinfo/${torrentData.value.seed_id}`)

    if (response.data.success) {
      ElNotification.success({
        title: '任务已启动',
        message: 'BDInfo 重新获取任务已启动',
      })
      startBDInfoSSE()
    } else {
      ElNotification.error({
        title: '启动失败',
        message: response.data.error || 'BDInfo 重新获取失败',
      })
    }
  } catch (error: any) {
    console.error('刷新 BDInfo 失败:', error)
    ElNotification.error({
      title: '操作失败',
      message: 'BDInfo 重新获取失败',
    })
  }
}

// 在组件卸载时清理轮询
onUnmounted(() => {
  if (bdinfoEventSource.value) {
    bdinfoEventSource.value.close()
    bdinfoEventSource.value = null
  }
})

const refreshPosters = async () => {
  if (!torrentData.value.original_main_title) {
    ElNotification.warning('标题为空，无法重新获取海报。')
    return
  }

  // 防止重复请求
  if (isRefreshingPosters.value) {
    ElNotification.info({
      title: '正在处理中',
      message: '海报重新获取请求已在处理中，请稍候...',
    })
    return
  }

  isRefreshingPosters.value = true
  ElNotification.info({
    title: '正在重新获取',
    message: '正在重新生成海报...',
    duration: 0,
  })

  const payload = {
    type: 'poster',
    content_name: torrentData.value.original_main_title,
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
      tmdb_link: torrentData.value.tmdb_link,
    },
    savePath: torrent.value.save_path,
    torrentName: torrent.value.name,
    downloaderId: torrent.value.downloaderId, // 添加下载器ID
  }

  try {
    const response = await axios.post('/api/media/validate', payload)
    ElNotification.closeAll()

    if (response.data.success && response.data.posters) {
      torrentData.value.intro.poster = response.data.posters

      // 同时更新链接（如果返回了的话）
      if (response.data.extracted_imdb_link && !torrentData.value.imdb_link) {
        torrentData.value.imdb_link = response.data.extracted_imdb_link
      }
      if (response.data.extracted_douban_link && !torrentData.value.douban_link) {
        torrentData.value.douban_link = response.data.extracted_douban_link
      }
      if (response.data.extracted_tmdb_link && !torrentData.value.tmdb_link) {
        torrentData.value.tmdb_link = response.data.extracted_tmdb_link
      }

      ElNotification.success({
        title: '重新获取成功',
        message: '已成功生成并加载了新的海报。',
      })
    } else {
      ElNotification.error({
        title: '重新获取失败',
        message: response.data.error || '无法从后端获取新的海报，请查看后台日志。',
      })
    }
  } catch (error: any) {
    ElNotification.closeAll()
    const errorMsg = error.response?.data?.error || '未能重新获取海报，请查看后台日志。'
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    })
  } finally {
    isRefreshingPosters.value = false
  }
}

const reparseTitle = async () => {
  if (!torrentData.value.original_main_title) {
    ElNotification.warning('标题为空，无法解析。')
    return
  }
  isReparsing.value = true
  try {
    const response = await axios.post('/api/utils/parse_title', {
      title: torrentData.value.original_main_title,
      mediainfo: torrentData.value.mediainfo || '', // 传递 mediainfo 以便修正 Blu-ray/BluRay 格式
    })
    if (response.data.success) {
      torrentData.value.title_components = response.data.components
      ElNotification.success('标题已重新解析！')
    } else {
      ElNotification.error(response.data.message || '解析失败')
    }
  } catch (error) {
    handleApiError(error, '未能重新解析标题，请查看后台日志。')
  } finally {
    isReparsing.value = false
  }
}

const handleImageError = async (url: string, type: 'poster' | 'screenshot', index: number) => {
  // 如果是 pixhost.to 的图片，跳过检测
  if (url && url.includes('pixhost.to')) {
    console.log(`检测到 pixhost.to 图片，跳过有效性检测: ${url}`)
    return
  }

  // 防止重复处理截图错误
  if (type === 'screenshot' && isHandlingScreenshotError.value) {
    console.log(`截图错误已正在处理中，跳过重复请求: ${url}`)
    return
  }

  console.error(`图片加载失败: 类型=${type}, URL=${url}, 索引=${index}`)
  if (type === 'screenshot') {
    isHandlingScreenshotError.value = true
    screenshotValid.value = false // 标记截图无效
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
    content_name: torrentData.value.original_main_title,
    source_info: {
      main_title: torrentData.value.original_main_title,
      source_site: sourceSite.value,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
      tmdb_link: torrentData.value.tmdb_link,
    },
    savePath: torrent.value.save_path,
    torrentName: torrent.value.name,
    downloaderId: torrent.value.downloaderId, // 添加下载器ID
  }

  try {
    const response = await axios.post('/api/media/validate', payload)
    if (response.data.success) {
      if (type === 'screenshot' && response.data.screenshots) {
        torrentData.value.intro.screenshots = response.data.screenshots
        screenshotValid.value = true // 标记截图有效
        ElNotification.success({
          title: '截图已更新',
          message: '已成功生成并加载了新的截图。',
        })
      } else if (type === 'poster' && response.data.posters) {
        torrentData.value.intro.poster = response.data.posters
        ElNotification.success({
          title: '海报已更新',
          message: '已成功生成并加载了新的海报。',
        })
      }
    } else {
      // 如果更新截图失败，保持screenshotValid为false
      if (type === 'screenshot') {
        screenshotValid.value = false
      }
      ElNotification.error({
        title: '更新失败',
        message:
          response.data.error || `无法从后端获取新的${type === 'poster' ? '海报' : '截图'}。`,
      })
    }
  } catch (error: any) {
    const errorMsg =
      error.response?.data?.error ||
      `发送失效${type === 'poster' ? '海报' : '截图'}信息请求时发生错误，请查看后台日志。`
    console.error('发送失效图片信息请求时发生错误:', error)
    ElNotification.error({
      title: '操作失败',
      message: errorMsg,
    })
  } finally {
    // 重置截图处理状态
    if (type === 'screenshot') {
      isHandlingScreenshotError.value = false
      // 注意：不重置 screenshotValid 状态，保持当前的截图有效状态
    }
  }
}

// 通过中文站点名获取英文站点名，用于数据库查询
const getEnglishSiteName = async (chineseSiteName: string): Promise<string> => {
  // 首先尝试从已加载的 allSitesStatus 中获取
  const siteInfo = allSitesStatus.value.find((s: any) => s.name === chineseSiteName)
  if (siteInfo?.site) {
    return siteInfo.site
  }

  // 如果 allSitesStatus 还没有加载，直接调用接口获取站点信息
  try {
    const response = await axios.get('/api/sites/status')
    allSitesStatus.value = response.data

    // 再次尝试从更新的 allSitesStatus 中获取
    const updatedSiteInfo = allSitesStatus.value.find((s: any) => s.name === chineseSiteName)
    if (updatedSiteInfo?.site) {
      return updatedSiteInfo.site
    }
  } catch (error) {
    console.warn('获取站点状态失败:', error)
  }

  return chineseSiteName.toLowerCase()
}

// 提取出来的处理数据库数据的辅助函数 (避免代码重复)
const processDbData = (dataRes: any, tId: string) => {
  const dbData = dataRes.data
  if (!dbData || !dbData.title) throw new Error('数据库返回的种子信息不完整')

  if (dataRes.reverse_mappings) {
    reverseMappings.value = dataRes.reverse_mappings
  }

  torrentData.value = {
    seed_id: tId,
    original_main_title: dbData.title || '',
    title_components: dbData.title_components || [],
    subtitle: dbData.subtitle,
    imdb_link: dbData.imdb_link,
    douban_link: dbData.douban_link,
    tmdb_link: dbData.tmdb_link,
    intro: {
      statement: filterExtraEmptyLines(dbData.statement) || '',
      poster: dbData.poster || '',
      body: filterExtraEmptyLines(dbData.body) || '',
      screenshots: dbData.screenshots || '',
      removed_ardtudeclarations: dbData.removed_ardtudeclarations || [],
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
      tags: (dbData.tags || []).sort((a: any, b: any) => {
        const restricted = ['禁转', 'tag.禁转', '限转', 'tag.限转', '分集', 'tag.分集']
        const isRa = restricted.includes(a)
        const isRb = restricted.includes(b)
        return isRa === isRb ? 0 : isRa ? -1 : 1
      }),
    },
    final_publish_parameters: dbData.final_publish_parameters || {},
    complete_publish_params: dbData.complete_publish_params || {},
    raw_params_for_preview: dbData.raw_params_for_preview || {},
  }

  // 自动解析标题逻辑
  if ((!dbData.title_components || dbData.title_components.length === 0) && dbData.title) {
    axios
      .post('/api/utils/parse_title', { title: dbData.title })
      .then((res) => {
        if (res.data.success) torrentData.value.title_components = res.data.components
      })
      .catch(console.warn)
  }

  taskId.value = tId
  isDataFromDatabase.value = true
  activeStep.value = 0
  nextTick(() => {
    checkScreenshotValidity()
  })
  isLoading.value = false
}

const fetchSitesStatus = async () => {
  try {
    const response = await axios.get('/api/sites/status')
    allSitesStatus.value = response.data
    const downloaderResponse = await axios.get('/api/downloaders_list')
    downloaderList.value = downloaderResponse.data
  } catch (error) {
    ElNotification.error({ title: '错误', message: '无法从服务器获取站点状态列表或下载器列表' })
  }
}

const fetchTorrentInfo = async () => {
  if (!sourceSite.value || !torrent.value) return

  const siteDetails = torrent.value.sites[sourceSite.value]
  // 首先检查是否有存储的种子ID
  let torrentId = siteDetails.torrentId || null

  // 如果没有存储的ID，则尝试从链接中提取
  if (!torrentId) {
    const idMatch = siteDetails.comment?.match(/id=(\d+)/)
    if (!idMatch || !idMatch[1]) {
      ElNotification.error(`无法从源站点 ${sourceSite.value} 的链接中提取种子ID。`)
      emit('cancel')
      return
    }
    torrentId = idMatch[1]
  }

  isLoading.value = true

  // 生成任务ID并显示进度组件
  const tempTaskId = `fetch_${torrentId}_${Date.now()}`
  logProgressTaskId.value = tempTaskId
  showLogProgress.value = true

  let dbError = null

  // 步骤1: 尝试从数据库读取种子信息
  try {
    const englishSiteName = await getEnglishSiteName(sourceSite.value)
    console.log(
      `尝试从数据库读取种子信息: ${torrentId} from ${sourceSite.value} (${englishSiteName})`,
    )
    const dbResponse = await axios.get('/api/migrate/get_db_seed_info', {
      params: {
        torrent_id: torrentId,
        site_name: englishSiteName,
        task_id: tempTaskId, // 传递task_id给后端
      },
      timeout: 120000, // 120秒超时
    })

    // 检查是否需要继续抓取（202状态码）
    if (dbResponse.status === 202 && dbResponse.data.should_fetch) {
      console.log('数据库中没有缓存，继续使用同一日志流从源站点抓取...')
      // 使用返回的task_id继续抓取（不关闭日志流）
      const continuedTaskId = dbResponse.data.task_id || tempTaskId

      // 直接调用 fetch_and_store，传入相同的 task_id
      try {
        const storeResponse = await axios.post(
          '/api/migrate/fetch_and_store',
          {
            sourceSite: sourceSite.value,
            searchTerm: torrentId,
            savePath: torrent.value.save_path,
            torrentName: torrent.value.name,
            downloaderId: torrent.value.downloaderId,
            task_id: continuedTaskId, // 传递相同的task_id以继续使用同一日志流
          },
          {
            timeout: 120000,
          },
        )

        if (!storeResponse.data.success) {
          ElNotification.closeAll()

          // 1. 获取错误消息
          const errorMsg = storeResponse.data.message || '从源站点抓取失败'

          // 2. 解析日志内容
          parsedErrorLogs.value = parseLogText(errorMsg)

          // 3. 打开美化后的错误弹窗
          showErrorDialog.value = true

          // 4. 停止加载，但不触发取消（修复问题：避免组件销毁导致弹窗无法显示）
          isLoading.value = false
          return
        }

        // 抓取成功后，再次从数据库读取（使用相同逻辑）
        const finalDbResponse = await axios.get('/api/migrate/get_db_seed_info', {
          params: {
            torrent_id: torrentId,
            site_name: englishSiteName,
          },
          timeout: 120000,
        })

        if (!finalDbResponse.data.success) {
          ElNotification.closeAll()

          // 1. 获取错误消息
          const errorMsg = '数据抓取成功但从数据库读取失败'

          // 2. 解析日志内容
          parsedErrorLogs.value = parseLogText(errorMsg)

          // 3. 打开美化后的错误弹窗
          showErrorDialog.value = true

          // 4. 停止加载，但不触发取消（修复问题：避免组件销毁导致弹窗无法显示）
          isLoading.value = false
          return
        }

        // 处理成功的数据（与下面的逻辑相同）
        ElNotification.closeAll()
        ElNotification.success({
          title: '抓取成功',
          message: '种子信息已成功抓取并存储到数据库，请核对。',
        })

        const dbData = finalDbResponse.data.data
        if (finalDbResponse.data.reverse_mappings) {
          reverseMappings.value = finalDbResponse.data.reverse_mappings
        }

        // 构建复合主键作为seed_id
        const compositeSeedId = `${dbData.hash || torrentId}_${torrentId}_${englishSiteName}`

        torrentData.value = {
          seed_id: compositeSeedId,
          original_main_title: dbData.title || '',
          title_components: dbData.title_components || [],
          subtitle: dbData.subtitle,
          imdb_link: dbData.imdb_link,
          douban_link: dbData.douban_link,
          tmdb_link: dbData.tmdb_link,
          intro: {
            statement: filterExtraEmptyLines(dbData.statement) || '',
            poster: dbData.poster || '',
            body: filterExtraEmptyLines(dbData.body) || '',
            screenshots: dbData.screenshots || '',
            removed_ardtudeclarations: dbData.removed_ardtudeclarations || [],
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
            tags: (dbData.tags || []).sort((a, b) => {
              const restricted = ['禁转', 'tag.禁转', '限转', 'tag.限转', '分集', 'tag.分集']
              const isRa = restricted.includes(a)
              const isRb = restricted.includes(b)
              return isRa === isRb ? 0 : isRa ? -1 : 1
            }),
          },
          final_publish_parameters: dbData.final_publish_parameters || {},
          complete_publish_params: dbData.complete_publish_params || {},
          raw_params_for_preview: dbData.raw_params_for_preview || {},
        }

        taskId.value = storeResponse.data.task_id
        isDataFromDatabase.value = true
        activeStep.value = 0

        // 检查 BDInfo 进度状态（从抓取流程调用，增加重试次数和延迟）
        checkAndStartBDInfoProgress(compositeSeedId, true)

        nextTick(() => {
          checkScreenshotValidity()
        })

        isLoading.value = false
        return
      } catch (error: any) {
        ElNotification.closeAll()
        handleApiError(error, '从源站点抓取时发生错误，请查看后台日志。')
        isLoading.value = false
        return
      }
    } else if (dbResponse.data.success) {
      ElNotification.closeAll()
      ElNotification.success({
        title: '读取成功',
        message: '种子信息已从数据库成功加载，请核对。',
      })

      // 验证数据库返回的数据完整性
      const dbData = dbResponse.data.data
      if (!dbData || !dbData.title) {
        throw new Error('数据库返回的种子信息不完整')
      }

      // 从后端响应中提取反向映射表
      if (dbResponse.data.reverse_mappings) {
        reverseMappings.value = dbResponse.data.reverse_mappings
        console.log('成功加载反向映射表:', reverseMappings.value)
        console.log('type映射数量:', Object.keys(reverseMappings.value.type || {}).length)
        console.log('当前standardized_params:', dbData.standardized_params)
      } else {
        console.warn('后端未返回反向映射表，将使用空的默认映射')
      }

      // 构建复合主键作为seed_id
      const compositeSeedId = `${dbData.hash || torrentId}_${torrentId}_${englishSiteName}`

      // 从数据库返回的数据中提取相关信息
      torrentData.value = {
        seed_id: compositeSeedId,
        original_main_title: dbData.title || '',
        title_components: dbData.title_components || [],
        subtitle: dbData.subtitle,
        imdb_link: dbData.imdb_link,
        douban_link: dbData.douban_link,
        tmdb_link: dbData.tmdb_link,
        intro: {
          statement: filterExtraEmptyLines(dbData.statement) || '',
          poster: dbData.poster || '',
          body: filterExtraEmptyLines(dbData.body) || '',
          screenshots: dbData.screenshots || '',
          removed_ardtudeclarations: dbData.removed_ardtudeclarations || [],
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
          tags: (dbData.tags || []).sort((a, b) => {
            const restricted = ['禁转', 'tag.禁转', '限转', 'tag.限转', '分集', 'tag.分集']
            const isRa = restricted.includes(a)
            const isRb = restricted.includes(b)
            return isRa === isRb ? 0 : isRa ? -1 : 1
          }),
        },
        final_publish_parameters: dbData.final_publish_parameters || {},
        complete_publish_params: dbData.complete_publish_params || {},
        raw_params_for_preview: dbData.raw_params_for_preview || {},
      }

      // 如果没有解析过的标题组件，自动解析主标题
      if ((!dbData.title_components || dbData.title_components.length === 0) && dbData.title) {
        try {
          const parseResponse = await axios.post('/api/utils/parse_title', { title: dbData.title })
          if (parseResponse.data.success) {
            torrentData.value.title_components = parseResponse.data.components
            ElNotification.info({
              title: '标题解析',
              message: '已自动解析主标题为组件信息。',
            })
          }
        } catch (error) {
          console.warn('自动解析标题失败:', error)
        }
      }

      console.log('设置torrentData.standardized_params:', torrentData.value.standardized_params)
      console.log('检查绑定 - type:', torrentData.value.standardized_params.type)
      console.log('检查绑定 - medium:', torrentData.value.standardized_params.medium)

      // 直接使用从数据库返回的 taskId，如果后端没有返回则生成标识符
      if (dbResponse.data.task_id) {
        taskId.value = dbResponse.data.task_id // 使用从数据库返回的 taskId
        ElNotification.success({
          title: '缓存准备完成',
          message: '发布任务已准备就绪',
        })
      } else {
        // 如果后端未返回task_id，回退到标识符
        taskId.value = `db_${torrentId}_${englishSiteName}`
        console.warn('后端未返回taskId，使用标识符')
      }
      isDataFromDatabase.value = true // Mark that data was loaded from database

      // 检查 BDInfo 进度状态（从数据库读取，使用默认重试设置）
      checkAndStartBDInfoProgress(compositeSeedId, false)

      // 自动提取链接的逻辑保持不变
      if (
        (!torrentData.value.imdb_link || !torrentData.value.douban_link) &&
        torrentData.value.intro.body
      ) {
        let imdbExtracted = false
        let doubanExtracted = false
        if (!torrentData.value.imdb_link) {
          const imdbRegex = /(https?:\/\/www\.imdb\.com\/title\/tt\d+)/
          const imdbMatch = torrentData.value.intro.body.match(imdbRegex)
          if (imdbMatch && imdbMatch[1]) {
            torrentData.value.imdb_link = imdbMatch[1]
            imdbExtracted = true
          }
        }
        if (!torrentData.value.douban_link) {
          const doubanRegex = /(https:\/\/movie\.douban\.com\/subject\/\d+)/
          const doubanMatch = torrentData.value.intro.body.match(doubanRegex)
          if (doubanMatch && doubanMatch[1]) {
            torrentData.value.douban_link = doubanMatch[1]
            doubanExtracted = true
          }
        }
        if (imdbExtracted || doubanExtracted) {
          const messages = []
          if (imdbExtracted) messages.push('IMDb链接')
          if (doubanExtracted) messages.push('豆瓣链接')
          ElNotification.info({
            title: '自动填充',
            message: `已从简介正文中自动提取并填充 ${messages.join(' 和 ')}。`,
          })
        }
      }

      activeStep.value = 0
      // Check screenshot validity after loading data
      nextTick(() => {
        checkScreenshotValidity()
      })
      // Set flag to indicate data was loaded from database
      isDataFromDatabase.value = true
      // 【修复】在从数据库成功读取后关闭加载动画
      isLoading.value = false
      // Skip the scraping part since we have data from database
      return
    } else {
      // 数据库中不存在该记录，这是正常情况，不需要记录为错误
      console.log('数据库中没有找到种子信息，开始抓取数据...')
    }
  } catch (error) {
    // 捕获数据库读取错误，但继续执行抓取逻辑
    dbError = error
    console.log('从数据库读取失败，开始抓取数据...', error)

    // 区分网络错误和其他错误
    if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
      console.warn('数据库读取超时，将尝试直接抓取数据...')
    } else if (error.response?.status >= 500) {
      console.warn('数据库服务器错误，将尝试直接抓取数据...')
    } else {
      console.warn('数据库读取发生未知错误，将尝试直接抓取数据...')
    }
  }

  // 步骤2: 如果数据库中没有数据，则进行抓取和存储
  try {
    ElNotification.closeAll()
    ElNotification({
      title: '正在抓取',
      message: '正在从源站点抓取种子信息并存储到数据库...',
      type: 'info',
      duration: 0,
    })

    // 如果有数据库错误，显示警告信息
    if (dbError) {
      console.warn(`由于数据库读取失败（${dbError.message}），正在直接抓取数据...`)
      ElNotification.warning({
        title: '数据库读取失败',
        message: '正在尝试直接抓取数据，请稍候...',
        duration: 3000,
      })
    }

    const storeResponse = await axios.post(
      '/api/migrate/fetch_and_store',
      {
        sourceSite: sourceSite.value,
        searchTerm: torrentId,
        savePath: torrent.value.save_path,
        torrentName: torrent.value.name,
        downloaderId:
          torrent.value.downloaderId ||
          (torrent.value.downloaderIds?.length > 0 ? torrent.value.downloaderIds[0] : null),
      },
      {
        timeout: 120000, // 120秒超时，用于抓取和存储
      },
    )

    if (storeResponse.data.success) {
      // 抓取成功后，立即从数据库读取数据
      console.log('数据抓取成功，立即从数据库读取...')
      let dbReadAttempt = 0
      const maxDbReadAttempts = 3
      let dbResponseAfterStore = null

      // 重试机制：多次尝试从数据库读取
      while (dbReadAttempt < maxDbReadAttempts) {
        dbReadAttempt++
        try {
          const retryEnglishSiteName = await getEnglishSiteName(sourceSite.value)
          console.log(
            `重试从数据库读取种子信息: ${torrentId} from ${sourceSite.value} (${retryEnglishSiteName})`,
          )
          dbResponseAfterStore = await axios.get('/api/migrate/get_db_seed_info', {
            params: {
              torrent_id: torrentId,
              site_name: retryEnglishSiteName,
            },
            timeout: 120000, // 120秒超时
          })

          if (dbResponseAfterStore.data.success) {
            break // 成功读取，退出重试循环
          } else {
            console.warn(`数据库读取第${dbReadAttempt}次失败：${dbResponseAfterStore.data.message}`)
            if (dbReadAttempt < maxDbReadAttempts) {
              await new Promise((resolve) => setTimeout(resolve, 1000)) // 等待1秒后重试
            }
          }
        } catch (readError) {
          console.warn(`数据库读取第${dbReadAttempt}次失败：`, readError)
          if (dbReadAttempt < maxDbReadAttempts) {
            await new Promise((resolve) => setTimeout(resolve, 1000)) // 等待1秒后重试
          } else {
            throw readError // 重试次数用尽，抛出错误
          }
        }
      }

      if (dbResponseAfterStore && dbResponseAfterStore.data.success) {
        ElNotification.closeAll()

        // 验证数据完整性
        const dbData = dbResponseAfterStore.data.data
        if (!dbData || !dbData.title) {
          throw new Error('数据库返回的种子信息不完整')
        }

        // 从后端响应中提取反向映射表
        if (dbResponseAfterStore.data.reverse_mappings) {
          reverseMappings.value = dbResponseAfterStore.data.reverse_mappings
          console.log('成功加载反向映射表:', reverseMappings.value)
        } else {
          console.warn('后端未返回反向映射表，将使用空的默认映射')
        }

        ElNotification.success({
          title: '抓取成功',
          message: dbError
            ? '种子信息已成功抓取，请核对。由于数据库读取失败，数据未持久化存储。'
            : '种子信息已成功抓取并存储到数据库，请核对。',
        })

        // 构建复合主键作为seed_id
        const compositeSeedId = `${dbData.hash || torrentId}_${torrentId}_${englishSiteName}`

        torrentData.value = {
          seed_id: compositeSeedId,
          original_main_title: dbData.title || '',
          title_components: dbData.title_components || [],
          subtitle: dbData.subtitle,
          imdb_link: dbData.imdb_link,
          douban_link: dbData.douban_link,
          tmdb_link: dbData.tmdb_link,
          intro: {
            statement: filterExtraEmptyLines(dbData.statement) || '',
            poster: dbData.poster || '',
            body: filterExtraEmptyLines(dbData.body) || '',
            screenshots: dbData.screenshots || '',
            removed_ardtudeclarations: dbData.removed_ardtudeclarations || [],
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
            tags: (dbData.tags || []).sort((a, b) => {
              const restricted = ['禁转', 'tag.禁转', '限转', 'tag.限转', '分集', 'tag.分集']
              const isRa = restricted.includes(a)
              const isRb = restricted.includes(b)
              return isRa === isRb ? 0 : isRa ? -1 : 1
            }),
          },
          final_publish_parameters: dbData.final_publish_parameters || {},
          complete_publish_params: dbData.complete_publish_params || {},
          raw_params_for_preview: dbData.raw_params_for_preview || {},
        }

        // 如果没有解析过的标题组件，自动解析主标题
        if ((!dbData.title_components || dbData.title_components.length === 0) && dbData.title) {
          try {
            const parseResponse = await axios.post('/api/utils/parse_title', {
              title: dbData.title,
            })
            if (parseResponse.data.success) {
              torrentData.value.title_components = parseResponse.data.components
              ElNotification.info({
                title: '标题解析',
                message: '已自动解析主标题为组件信息。',
              })
            }
          } catch (error) {
            console.warn('自动解析标题失败:', error)
          }
        }

        taskId.value = storeResponse.data.task_id
        isDataFromDatabase.value = true // Mark that data was loaded from database

        // 自动提取链接的逻辑保持不变
        if (
          (!torrentData.value.imdb_link || !torrentData.value.douban_link) &&
          torrentData.value.intro.body
        ) {
          let imdbExtracted = false
          let doubanExtracted = false
          if (!torrentData.value.imdb_link) {
            const imdbRegex = /(https?:\/\/www\.imdb\.com\/title\/tt\d+)/
            const imdbMatch = torrentData.value.intro.body.match(imdbRegex)
            if (imdbMatch && imdbMatch[1]) {
              torrentData.value.imdb_link = imdbMatch[1]
              imdbExtracted = true
            }
          }
          if (!torrentData.value.douban_link) {
            const doubanRegex = /(https:\/\/movie\.douban\.com\/subject\/\d+)/
            const doubanMatch = torrentData.value.intro.body.match(doubanRegex)
            if (doubanMatch && doubanMatch[1]) {
              torrentData.value.douban_link = doubanMatch[1]
              doubanExtracted = true
            }
          }
          if (imdbExtracted || doubanExtracted) {
            const messages = []
            if (imdbExtracted) messages.push('IMDb链接')
            if (doubanExtracted) messages.push('豆瓣链接')
            ElNotification.info({
              title: '自动填充',
              message: `已从简介正文中自动提取并填充 ${messages.join(' 和 ')}。`,
            })
          }
        }

        activeStep.value = 0
        // Check screenshot validity after loading data
        nextTick(() => {
          checkScreenshotValidity()
        })
      } else {
        ElNotification.closeAll()

        // 1. 获取错误消息
        const errorMsg = `数据抓取成功但数据库读取失败，已重试${maxDbReadAttempts}次。请检查数据库连接或稍后重试。`

        // 2. 解析日志内容
        parsedErrorLogs.value = parseLogText(errorMsg)

        // 3. 打开美化后的错误弹窗
        showErrorDialog.value = true

        // 4. 停止加载，但不触发取消（修复问题：避免组件销毁导致弹窗无法显示）
        isLoading.value = false
      }
    } else {
      ElNotification.closeAll()
      const errorMessage = storeResponse.data.message || '抓取种子信息失败'

      // 1. 获取错误消息
      let errorMsg = errorMessage

      // 2. 如果是数据库相关的错误，提供更详细的建议
      if (errorMessage.includes('数据库') || dbError) {
        errorMsg = `${errorMessage}。可能由于数据库连接问题导致，请检查数据库状态。`
      }

      // 3. 解析日志内容
      parsedErrorLogs.value = parseLogText(errorMsg)

      // 4. 打开美化后的错误弹窗
      showErrorDialog.value = true

      // 5. 停止加载，但不触发取消（修复问题：避免组件销毁导致弹窗无法显示）
      isLoading.value = false
    }
  } catch (error) {
    ElNotification.closeAll()

    // 区分不同类型的错误并提供更具体的错误信息
    if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
      // 1. 获取错误消息
      const msg = '抓取种子信息超时，请检查网络连接或稍后重试。'
      parsedErrorLogs.value = parseLogText(msg)
      showErrorDialog.value = true
    } else if (error.response?.status === 404) {
      // 1. 获取错误消息
      const msg = '在源站点未找到指定的种子，请检查种子ID是否正确。'
      parsedErrorLogs.value = parseLogText(msg)
      showErrorDialog.value = true
    } else if (error.response?.status >= 500) {
      // 1. 获取错误消息
      const msg = '后端服务器发生错误，请稍后重试或联系管理员。'
      parsedErrorLogs.value = parseLogText(msg)
      showErrorDialog.value = true
    } else {
      // 使用原有的错误处理
      const msg = error.message || '获取种子信息时发生错误，请查看后台日志。'
      parsedErrorLogs.value = parseLogText(msg)
      showErrorDialog.value = true
    }
  } finally {
    isLoading.value = false
  }
}

// 检查标准化参数是否符合格式的辅助函数
const invalidStandardParams = computed(() => {
  const standardizedParams = torrentData.value.standardized_params
  const standardParamKeys = [
    'type',
    'medium',
    'video_codec',
    'audio_codec',
    'resolution',
    'team',
    'source',
  ]
  const invalidParamsList = []

  // 【修改】使用与 invalidTagsList 相同的、更强大的正则表达式
  const flexibleRegex = new RegExp(/^[\p{L}\p{N}_-]+\.[\p{L}\p{N}_+-]+$/u)

  for (const key of standardParamKeys) {
    const value = standardizedParams[key]

    // 【修改】使用新的正则表达式进行判断
    if (value && typeof value === 'string' && value.trim() !== '' && !flexibleRegex.test(value)) {
      invalidParamsList.push(key)
    }
  }

  // 这里逻辑保持不变
  if (invalidTagsList.value.length > 0) {
    invalidParamsList.push('tags')
  }

  return invalidParamsList
})

// 辅助函数：处理制作组，去掉横杠
const cleanTeamValue = (value: string): string => {
  if (!value || typeof value !== 'string') {
    return value
  }
  return value.replace(/^-/, '')
}

// 处理制作组输入，自动去掉横杠
const handleTeamInput = (param: any, value: string) => {
  if (param.key === '制作组') {
    param.value = cleanTeamValue(value)
  }
}

const goToPublishPreviewStep = async () => {
  // 打印从store获取的已存在站点信息
  console.log('=== 从store获取的已存在站点信息 ===')
  console.log('torrent.value:', torrent.value)
  console.log('torrent.value.sites:', torrent.value?.sites)
  if (torrent.value?.sites) {
    const existingSites = Object.keys(torrent.value.sites)
    console.log('已存在的站点列表:', existingSites)
    console.log('已存在站点详细信息:', torrent.value.sites)
  } else {
    console.log('未找到已存在站点信息')
  }
  console.log('=====================================')

  // 检查是否有不符合格式的标准化参数
  const invalidParams = invalidStandardParams.value
  if (invalidParams.length > 0) {
    // 显示提示信息
    const paramNames = {
      type: '类型',
      medium: '媒介',
      video_codec: '视频编码',
      audio_codec: '音频编码',
      resolution: '分辨率',
      team: '制作组',
      source: '产地',
      tags: '标签',
    }

    const invalidParamNames = invalidParams.map((param) => paramNames[param] || param)

    ElNotification({
      title: '参数格式不正确',
      message: `以下参数格式不正确，请修改为 *.* 的标准格式: ${invalidParamNames.join(', ')}`,
      type: 'warning',
      duration: 0,
      showClose: true,
    })
    return
  }

  isLoading.value = true
  try {
    ElNotification({
      title: '正在处理',
      message: '正在更新参数并生成预览...',
      type: 'info',
      duration: 0,
    })

    // 从taskId中提取torrent_id和site_name
    // taskId可能格式: db_${torrentId}_${siteName} 或原始task_id
    let torrentId, siteName

    // 如果数据是从数据库加载的，优先使用数据库模式解析
    if (isDataFromDatabase.value && taskId.value && taskId.value.startsWith('db_')) {
      // 数据库模式: db_${torrentId}_${siteName}
      const parts = taskId.value.split('_')
      if (parts.length >= 3) {
        torrentId = parts[1]
        siteName = parts.slice(2).join('_') // 处理站点名称中可能有下划线的情况
      }
    } else if (taskId.value && taskId.value.startsWith('db_')) {
      // 原有的数据库模式解析
      const parts = taskId.value.split('_')
      if (parts.length >= 3) {
        torrentId = parts[1]
        siteName = parts.slice(2).join('_') // 处理站点名称中可能有下划线的情况
      }
    } else {
      // 回退模式：需要从props中获取
      const siteDetails = torrent.value.sites[sourceSite.value]
      torrentId = siteDetails.torrentId || null
      siteName = await getEnglishSiteName(sourceSite.value)

      if (!torrentId) {
        const idMatch = siteDetails.comment?.match(/id=(\d+)/)
        if (idMatch && idMatch[1]) {
          torrentId = idMatch[1]
        }
      }
    }

    if (!torrentId || !siteName) {
      ElNotification.error({
        title: '参数错误',
        message: '无法获取种子ID或站点名称',
        duration: 0,
        showClose: true,
      })
      return
    }

    console.log(`更新种子参数: ${torrentId} from ${siteName}`)

    // 清理 title_components 中的制作组，去掉横杠
    const cleanedTitleComponents = torrentData.value.title_components.map((component) => {
      if (component.key === '制作组') {
        return {
          ...component,
          value: cleanTeamValue(component.value),
        }
      }
      return component
    })

    // 构建更新的参数，应用空行过滤
    const updatedParameters = {
      title: torrentData.value.original_main_title,
      subtitle: torrentData.value.subtitle,
      imdb_link: torrentData.value.imdb_link,
      douban_link: torrentData.value.douban_link,
      tmdb_link: torrentData.value.tmdb_link,
      poster: torrentData.value.intro.poster,
      screenshots: torrentData.value.intro.screenshots,
      statement: filterExtraEmptyLines(torrentData.value.intro.statement),
      body: filterExtraEmptyLines(torrentData.value.intro.body),
      mediainfo: torrentData.value.mediainfo,
      source_params: torrentData.value.source_params,
      title_components: cleanedTitleComponents,
      // 包含用户修改的标准参数
      standardized_params: torrentData.value.standardized_params,
    }

    console.log('发送到后端的标准参数:', torrentData.value.standardized_params)

    // 调用新的更新接口，此时会将 is_reviewed 设置为 true
    const response = await axios.post('/api/migrate/update_db_seed_info', {
      torrent_name: torrent.value.name,
      torrent_id: torrentId,
      site_name: siteName,
      updated_parameters: updatedParameters,
    })

    console.log('已调用更新接口，is_reviewed 将被设置为 true')

    ElNotification.closeAll()

    if (response.data.success) {
      ElNotification.closeAll()
      // 更新成功后，获取重新标准化后的参数
      const {
        standardized_params,
        final_publish_parameters,
        complete_publish_params,
        raw_params_for_preview,
        reverse_mappings: updatedReverseMappings,
      } = response.data

      // 更新反向映射表（如果后端返回了更新的映射表）
      if (updatedReverseMappings) {
        reverseMappings.value = updatedReverseMappings
        console.log('成功更新反向映射表:', reverseMappings.value)
      }

      // 更新本地数据，保留用户修改的内容
      torrentData.value = {
        ...torrentData.value,
        standardized_params: standardized_params || {},
        final_publish_parameters: final_publish_parameters || {},
        complete_publish_params: complete_publish_params || {},
        raw_params_for_preview: raw_params_for_preview || {},
      }

      ElNotification.success({
        title: '更新成功',
        message: '参数已更新并重新标准化，请核对预览内容。',
      })

      activeStep.value = 1
    } else {
      ElNotification.error({
        title: '更新失败',
        message: response.data.message || '更新参数失败',
        duration: 0,
        showClose: true,
      })
    }
  } catch (error) {
    ElNotification.closeAll()
    handleApiError(error, '更新预览数据时发生错误，请查看后台日志。')
  } finally {
    isLoading.value = false
  }
}

// 【新增】计算属性：整合预设标签和当前已选标签，用于渲染下拉列表
// 过滤掉禁转标签，防止用户从下拉框选择或取消选择
const allTagOptions = computed(() => {
  const predefinedTags = Object.keys(reverseMappings.value.tags || {})
  const currentTags = torrentData.value.standardized_params.tags || []
  const combined = [...new Set([...predefinedTags, ...currentTags])]

  // 过滤掉禁转标签
  const filtered = combined.filter((tag) => !isRestrictedTag(tag))

  return filtered.map((tagValue) => ({
    value: tagValue,
    label: reverseMappings.value.tags[tagValue] || tagValue,
  }))
})

// 【修改并添加调试代码】方法：根据标签是否有效，返回不同的类型
const getTagType = (tag: string) => {
  // 优先检查是否为禁转标签
  if (
    tag === '禁转' ||
    tag === 'tag.禁转' ||
    tag === '限转' ||
    tag === 'tag.限转' ||
    tag === '分集' ||
    tag === 'tag.分集'
  ) {
    return 'danger' // 红色
  }

  // 在浏览器开发者工具的控制台(Console)中打印日志，方便调试
  console.log(`[getTagType] 检查标签: "${tag}", 是否无效: ${invalidTagsList.value.includes(tag)}`)

  // 核心逻辑不变
  return invalidTagsList.value.includes(tag) ? 'danger' : 'info'
}

const goToSelectSiteStep = async () => {
  // 检查已存在站点数量，如果少于2个则重新获取（因为默认会有源站点本身）
  const existingSitesCount = torrent.value?.sites ? Object.keys(torrent.value.sites).length : 0

  if (existingSitesCount < 2) {
    console.log(`已存在站点数量不足(${existingSitesCount}个)，正在重新获取种子数据...`)

    try {
      ElNotification.info({
        title: '正在更新数据',
        message: '正在重新获取种子站点信息...',
        duration: 0,
      })

      // 调用后端接口重新获取单个种子数据
      const params = new URLSearchParams({
        page: '1',
        pageSize: '1',
        nameSearch: torrent.value.name,
      })

      const response = await axios.get(`/api/data?${params.toString()}`)
      const result = response.data

      if (result.error) {
        throw new Error(result.error)
      }

      if (result.data && result.data.length > 0) {
        const updatedTorrent = result.data[0]
        console.log('重新获取到的种子数据:', updatedTorrent)
        console.log('重新获取到的站点信息:', updatedTorrent.sites)
        console.log(
          `站点数量从 ${existingSitesCount} 更新到 ${Object.keys(updatedTorrent.sites).length}`,
        )

        // 更新 store 中的种子信息
        crossSeedStore.setParams(updatedTorrent)

        ElNotification.success({
          title: '数据更新成功',
          message: `已重新获取种子站点信息，发现 ${Object.keys(updatedTorrent.sites).length} 个站点`,
        })
      } else {
        ElNotification.warning({
          title: '未找到种子',
          message: '未能找到匹配的种子数据',
        })
      }
    } catch (error: any) {
      console.error('重新获取种子数据时出错:', error)
      ElNotification.error({
        title: '数据更新失败',
        message: error.message || '重新获取种子数据时发生错误',
      })
    }
  } else {
    console.log(`已存在站点数量充足(${existingSitesCount}个)，跳过重新获取`)
  }

  activeStep.value = 2
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
    .filter((s) => s.is_target && isTargetSiteSelectable(s.name))
    .map((s) => s.name)
  selectedTargetSites.value = selectableSites
}

const clearAllTargetSites = () => {
  selectedTargetSites.value = []
}

const handlePublish = async () => {
  activeStep.value = 3
  isLoading.value = true
  finalResultsList.value = []

  // Initialize progress tracking - 确保进度条立即显示
  const siteCount = selectedTargetSites.value.length
  publishProgress.value = { current: 0, total: siteCount }
  downloaderProgress.value = { current: 0, total: siteCount }

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
          save_path: torrent.value.save_path, // 添加 save_path
        },
        targetSite: siteName,
        sourceSite: sourceSite.value,
        downloaderId: torrent.value.downloaderId, // 新增：传递下载器ID
        auto_add_to_downloader: true, // 新增：启用自动添加
      })

      const result = {
        siteName,
        message: getCleanMessage(response.data.logs || '发布成功'),
        ...response.data,
      }

      if (response.data.logs && response.data.logs.includes('种子已存在')) {
        result.isExisted = true
      }

      // 🚫 检查发种限制状态
      if (result.auto_add_result && result.auto_add_result.limit_reached) {
        // 提取限制信息用于突出显示
        const limitInfo = result.auto_add_result.message

        result.downloaderStatus = {
          success: false,
          message: result.auto_add_result.message,
          downloaderName: '限制触发',
          limit_reached: true,
        }

        results.push(result)
        finalResultsList.value = [...results]

        // 🚫 显示限制提示
        limitAlert.value = {
          visible: true,
          title: '发种限制触发',
          message: limitInfo,
        }

        // 在日志顶部突出显示限制信息
        logContent.value =
          `\n\n=== 🚫 发种限制触发 ===\n${limitInfo}\n\n=== 🛑 批量发布已停止 ===\n由于发种限制触发，后续 ${selectedTargetSites.value.length - results.length} 个站点发布已暂停。\n\n` +
          logContent.value

        // 显示限制通知
        ElNotification({
          title: '发种限制触发',
          message: `${siteName} 发布成功但因限制无法添加到下载器\n${limitInfo}\n后续站点发布已自动停止。`,
          type: 'warning',
          duration: 0,
          showClose: true,
        })

        // 跳出循环
        break
      }

      // 🚫 检查发布前预检查状态
      if (result.pre_check && result.limit_reached) {
        // 提取限制信息用于突出显示
        const limitInfo = result.message.replace('🚫 发布前预检查触发限制: ', '')

        result.downloaderStatus = {
          success: false,
          message: result.message,
          downloaderName: '发布前限制',
          limit_reached: true,
          pre_check: true,
        }

        results.push(result)
        finalResultsList.value = [...results]

        // 🚫 显示限制提示
        limitAlert.value = {
          visible: true,
          title: '发布前限制触发',
          message: limitInfo,
        }

        // 在日志顶部突出显示限制信息
        logContent.value =
          `\n\n=== 🚫 发种限制触发 ===\n${limitInfo}\n\n=== 🛑 批量发布已停止 ===\n由于发种限制触发，后续 ${selectedTargetSites.value.length - results.length} 个站点发布已暂停。\n\n` +
          logContent.value

        // 显示发布前限制通知
        ElNotification({
          title: '发布前限制触发',
          message: `${siteName} 因发种限制无法发布\n${limitInfo}\n后续站点发布已自动停止。`,
          type: 'warning',
          duration: 0,
          showClose: true,
        })

        // 跳出循环
        break
      }

      // 立即更新下载器状态
      if (result.auto_add_result) {
        // 获取实际的下载器名称
        let downloaderName = '自动检测'
        if (result.auto_add_result.downloader_id) {
          const downloader = downloaderList.value.find(
            (d) => d.id === result.auto_add_result.downloader_id,
          )
          if (downloader) {
            downloaderName = downloader.name
          }
        }

        result.downloaderStatus = {
          success: result.auto_add_result.success,
          message: result.auto_add_result.message,
          downloaderName: downloaderName,
        }

        // 立即更新下载器进度
        if (result.auto_add_result.success) {
          downloaderProgress.value.current++
        }
      }

      results.push(result)
      finalResultsList.value = [...results]

      if (result.success) {
        ElNotification.success({
          title: `发布成功 - ${siteName}`,
          message: '种子已成功发布到该站点',
        })
      }
    } catch (error) {
      const result = {
        siteName,
        success: false,
        logs: error.response?.data?.logs || error.message,
        url: null,
        message: `发布到 ${siteName} 时发生错误，请查看日志。`,
        downloaderStatus: {
          success: false,
          message: '发布失败，无法添加到下载器',
          downloaderName: '错误',
        },
      }
      results.push(result)
      finalResultsList.value = [...results]
      ElNotification.error({
        title: `发布失败 - ${siteName}`,
        message: result.message,
      })
    }
    // Update publish progress
    publishProgress.value.current++
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  ElNotification.closeAll()
  const successCount = results.filter((r) => r.success).length
  ElNotification.success({
    title: '发布完成',
    message: `成功发布到 ${successCount} / ${selectedTargetSites.value.length} 个站点。`,
  })

  // 处理自动添加到下载器的结果
  logContent.value += '\n\n--- [自动添加任务结果] ---'
  const downloaderStatusMap: Record<
    string,
    { success: boolean; message: string; downloaderName: string }
  > = {}

  // 从 Python 返回的结果中提取 auto_add_result
  results.forEach((result) => {
    if (result.auto_add_result) {
      // 优先使用已经存在的 downloaderStatus 中的名称（已在上面正确设置）
      const existingDownloaderName = result.downloaderStatus?.downloaderName || '自动检测'

      downloaderStatusMap[result.siteName] = {
        success: result.auto_add_result.success,
        message: result.auto_add_result.message,
        downloaderName: existingDownloaderName,
      }
      const statusIcon = result.auto_add_result.success ? '✅' : '❌'
      const statusText = result.auto_add_result.success ? '成功' : '失败'
      logContent.value += `\n[${result.siteName}] ${statusIcon} ${statusText}: ${result.auto_add_result.message}`
    } else if (result.success && result.url) {
      // 如果没有 auto_add_result，说明可能跳过了自动添加
      logContent.value += `\n[${result.siteName}] ⚠️  未执行自动添加`
    }
  })
  logContent.value += '\n--- [自动添加任务结束] ---'

  const siteLogs = results.map((r) => {
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

  finalResultsList.value = results.map((result) => ({
    ...result,
    downloaderStatus: downloaderStatusMap[result.siteName],
  }))

  // 触发种子数据刷新
  try {
    await axios.post('/api/refresh_data')
    ElNotification.success({
      title: '数据刷新',
      message: '种子数据已刷新',
    })
  } catch (error) {
    console.warn('刷新种子数据失败:', error)
  }

  isLoading.value = false
}

const handlePreviousStep = () => {
  if (activeStep.value > 0) {
    activeStep.value--
  }
}

// 处理取消按钮点击
const handleCancelClick = () => {
  // 如果在步骤3（完成发布），触发带刷新的关闭
  if (activeStep.value === 3) {
    emit('close-with-refresh')
  } else {
    emit('cancel')
  }
}

// 处理完成按钮点击
const handleCompleteClick = () => {
  emit('complete')
}

const getCleanMessage = (logs: string): string => {
  if (!logs || logs === '发布成功') return '发布成功'
  if (logs.includes('种子已存在')) {
    return '种子已存在，发布成功'
  }
  const lines = logs
    .split('\n')
    .filter((line) => line && !line.includes('--- [步骤') && !line.includes('INFO - ---'))
  const cleanLines = lines.map((line) => line.replace(/^\d{2}:\d{2}:\d{2} - \w+ - /, ''))
  return cleanLines.filter(Boolean).pop() || '发布成功'
}

const handleApiError = (error: any, defaultMessage: string) => {
  const message = error.response?.data?.logs || error.message || defaultMessage
  ElNotification.error({ title: '操作失败', message, duration: 0, showClose: true })
}

const triggerAddToDownloader = async (result: any) => {
  if (!torrent.value.save_path || !torrent.value.downloaderId) {
    const msg = `[${result.siteName}] 警告: 未能获取到原始保存路径或下载器ID，已跳过自动添加任务。`
    console.warn(msg)
    logContent.value += `\n${msg}`
    return { success: false, message: '未能获取到原始保存路径或下载器ID', downloaderName: '' }
  }

  let targetDownloaderId = torrent.value.downloaderId
  let targetDownloaderName = '未知下载器'

  try {
    const configResponse = await axios.get('/api/settings')
    const config = configResponse.data
    const defaultDownloaderId = config.cross_seed?.default_downloader
    if (defaultDownloaderId) {
      targetDownloaderId = defaultDownloaderId
    }
    const downloader = downloaderList.value.find((d) => d.id === targetDownloaderId)
    if (downloader) targetDownloaderName = downloader.name
  } catch (error: unknown) {
    // Ignore error
  }

  logContent.value += `\n[${result.siteName}] 正在尝试将新种子添加到下载器 '${targetDownloaderName}'...`

  try {
    const response = await axios.post('/api/migrate/add_to_downloader', {
      url: result.url,
      savePath: torrent.value.save_path,
      downloaderId: targetDownloaderId,
    })

    if (response.data.success) {
      logContent.value += `\n[${result.siteName}] 成功: ${response.data.message}`
      return { success: true, message: response.data.message, downloaderName: targetDownloaderName }
    } else if (response.data.limit_reached) {
      // 处理发种限制
      logContent.value += `\n[${result.siteName}] 🚫 发种限制: ${response.data.message}`

      // 显示限制通知
      ElNotification({
        title: '发种限制触发',
        message: response.data.message + '\n后续种子发布已自动停止。',
        type: 'warning',
        duration: 0,
        showClose: true,
      })

      return {
        success: false,
        limit_reached: true,
        message: response.data.message,
        downloaderName: targetDownloaderName,
        should_stop_batch: true,
      }
    } else {
      logContent.value += `\n[${result.siteName}] 失败: ${response.data.message}`
      return {
        success: false,
        message: response.data.message,
        downloaderName: targetDownloaderName,
      }
    }
  } catch (error: unknown) {
    let errorMessage = '未知错误'
    if (error instanceof Error) {
      errorMessage = (error as any).response?.data?.message || error.message
    } else if (typeof error === 'object' && error !== null && 'response' in error) {
      errorMessage = (error as any).response?.data?.message || String(error)
    }
    logContent.value += `\n[${result.siteName}] 错误: 调用API失败: ${errorMessage}`
    return {
      success: false,
      message: `调用API失败: ${errorMessage}`,
      downloaderName: targetDownloaderName,
    }
  }
}

// 辅助函数：获取映射后的中文值
const getMappedValue = (category: string) => {
  const standardizedParams = torrentData.value.standardized_params
  if (!standardizedParams || !reverseMappings.value) return 'N/A'

  const standardValue = standardizedParams[category]
  if (!standardValue) return 'N/A'

  const mappings = reverseMappings.value[category]
  if (!mappings) return standardValue

  return mappings[standardValue] || standardValue
}

// 辅助函数：获取映射后的标签列表
const getMappedTags = () => {
  // 使用 filteredTags 计算属性来过滤掉空标签
  if (!filteredTags.value || !reverseMappings.value.tags) return []

  return filteredTags.value.map((tag: string) => {
    return reverseMappings.value.tags[tag] || tag
  })
}

// Computed properties for filtered title components
const filteredTitleComponents = computed(() => {
  return torrentData.value.title_components.filter((param) => param.key !== '无法识别')
})
// 计算属性：过滤掉空标签
const filteredTags = computed(() => {
  const tags = torrentData.value.standardized_params.tags
  return tags?.filter((tag) => tag && typeof tag === 'string' && tag.trim() !== '') || []
})

// 【新增】计算属性：专门用于找出并返回所有格式不正确的标签列表
const invalidTagsList = computed(() => {
  // 定义支持中文和连字符的灵活正则表达式
  // \p{L} -> 匹配任何语言的字母 (包括中文)
  // \p{N} -> 匹配任何语言的数字
  // _-  -> 匹配下划线和连字符
  // u 标志 -> 启用 Unicode 支持
  const flexibleRegex = new RegExp(/^[\p{L}\p{N}_-]+\.[\p{L}\p{N}_+-]+$/u)

  // 从已过滤的标签中，再次过滤出不符合新正则的标签
  return filteredTags.value.filter((tag) => !flexibleRegex.test(tag))
})
// 计算属性：为未解析的标题提供初始参数框
const initialTitleComponents = computed(() => {
  // 定义常见的标题参数键
  const commonKeys = [
    '主标题',
    '季集',
    '年份',
    '剧集状态',
    '发布版本',
    '分辨率',
    '片源平台',
    '媒介',
    '视频编码',
    '视频格式',
    'HDR格式',
    '色深',
    '帧率',
    '音频编码',
    '制作组',
  ]
  // 创建带有空值的初始参数数组
  return commonKeys.map((key) => ({
    key: key,
    value: '',
  }))
})

// 检查是否为受限标签（禁转或tag.禁转）
const isRestrictedTag = (tag: string): boolean => {
  return (
    tag === '禁转' ||
    tag === 'tag.禁转' ||
    tag === '限转' ||
    tag === 'tag.限转' ||
    tag === '分集' ||
    tag === 'tag.分集'
  )
}

// 检查是否包含受限标签
const hasRestrictedTag = computed(() => {
  const tags = torrentData.value.standardized_params.tags || []
  return tags.some((tag) => isRestrictedTag(tag))
})

const handleTagClose = (tagToRemove: string) => {
  // 如果是受限标签，不允许删除
  if (isRestrictedTag(tagToRemove)) {
    ElNotification.warning({
      title: '无法删除',
      message: '禁转/限转/分集标签不允许删除',
      duration: 2000,
    })
    return
  }

  // 找到要删除的标签在数组中的索引
  const index = torrentData.value.standardized_params.tags.indexOf(tagToRemove)

  // 如果找到了，就从数组中移除它
  if (index > -1) {
    torrentData.value.standardized_params.tags.splice(index, 1)
  }
}

const unrecognizedValue = computed({
  // Getter: 当模板需要读取值时调用
  get() {
    const unrecognized = torrentData.value.title_components.find(
      (param) => param.key === '无法识别',
    )
    return unrecognized ? unrecognized.value : '' // 返回找到的值，或者空字符串
  },
  // Setter: 当 v-model 试图修改值时调用
  set(newValue) {
    const index = torrentData.value.title_components.findIndex((param) => param.key === '无法识别')

    // 如果新输入的值是空的，就从数组里删除这个项目
    if (newValue === '' || newValue === null) {
      if (index !== -1) {
        torrentData.value.title_components.splice(index, 1)
      }
    } else {
      // 如果项目已存在，就更新它的值
      if (index !== -1) {
        torrentData.value.title_components[index].value = newValue
      } else {
        // 如果项目不存在，就创建一个新的推进数组
        torrentData.value.title_components.push({
          key: '无法识别',
          value: newValue,
        })
      }
    }
  },
})

// 计算属性：检查ubits是否被禁用
const isUbitsDisabled = computed(() => {
  const team = torrentData.value.standardized_params.team
  const titleComponents = torrentData.value.title_components

  // 检查标准化参数中的制作组
  if (
    team &&
    ['cmct', 'cmctv', 'hdsky', 'hdsweb', 'hds', 'hdstv', 'hdspad'].includes(team.toLowerCase())
  ) {
    return true
  }

  // 检查标题组件中的制作组
  const teamComponent = titleComponents.find((param) => param.key === '制作组')
  if (teamComponent && teamComponent.value) {
    const teamValue = teamComponent.value.toLowerCase()
    const forbiddenTeams = [
      'cmct',
      'cmctv',
      'telesto',
      'shadow610',
      'hdsky',
      'hdsweb',
      'hds',
      'hdstv',
      'hdspad',
    ]

    // 检查是否包含禁止的制作组
    for (const forbiddenTeam of forbiddenTeams) {
      if (teamValue.includes(forbiddenTeam)) {
        return true
      }
    }
  }

  return false
})

// 计算属性：检查下一步按钮是否应该禁用
const isNextButtonDisabled = computed(() => {
  // 1. 检查“无法识别”
  const unrecognized = torrentData.value.title_components.find((param) => param.key === '无法识别')
  const hasUnrecognized = unrecognized && unrecognized.value !== ''

  // 2. 检查禁转标签
  if (hasRestrictedTag.value) {
    return true
  }

  // 3. 【新增】检查简介、海报、截图是否为空
  const intro = torrentData.value.intro
  const hasEmptyPoster = !intro.poster || intro.poster.trim() === ''
  const hasEmptyScreenshots = !intro.screenshots || intro.screenshots.trim() === ''
  const hasEmptyBody = !intro.body || intro.body.trim() === ''

  if (hasEmptyPoster || hasEmptyScreenshots || hasEmptyBody) {
    return true
  }

  // 3.5 检查简介正文完整性
  const introCompleteness = checkIntroCompleteness(intro.body)
  if (!introCompleteness.isComplete) {
    return true
  }

  // 4. 检查标准参数是否为空 (类型、媒介、视频编码、音频编码、分辨率)
  const params = torrentData.value.standardized_params
  const hasEmptyType = !params.type || params.type.trim() === ''
  const hasEmptyMedium = !params.medium || params.medium.trim() === ''
  const hasEmptyVideoCodec = !params.video_codec || params.video_codec.trim() === ''
  const hasEmptyAudioCodec = !params.audio_codec || params.audio_codec.trim() === ''
  const hasEmptyResolution = !params.resolution || params.resolution.trim() === ''

  if (
    hasEmptyType ||
    hasEmptyMedium ||
    hasEmptyVideoCodec ||
    hasEmptyAudioCodec ||
    hasEmptyResolution
  ) {
    return true
  }

  // 5. 检查制作组是否为空或为NOGROUP
  const team = torrentData.value.title_components.find((param) => param.key === '制作组')
  const hasEmptyTeam = !team || !team.value || team.value.trim() === ''
  const isNoGroup = team && team.value.trim().toUpperCase() === 'NOGROUP'

  if (hasEmptyTeam || isNoGroup) {
    return true
  }

  // 6. 检查 Mediainfo 是否为空或格式无效
  const mediaInfoText = torrentData.value.mediainfo || ''
  const hasInvalidMediaInfo = !mediaInfoText || mediaInfoText.trim() === ''

  if (!hasInvalidMediaInfo) {
    // 如果有内容，进一步检查格式有效性
    const isStandardMediainfo = _isValidMediainfo(mediaInfoText)
    const isBDInfo = _isValidBDInfo(mediaInfoText)
    if (!isStandardMediainfo && !isBDInfo) {
      return true
    }
  } else {
    // 如果为空，也禁用
    return true
  }

  // 6. 检查参数格式验证
  const hasInvalidStandardParams = invalidStandardParams.value.length > 0
  if (hasInvalidStandardParams) {
    return true
  }

  // 7. 检查截图链接是否有效 (加载失败的情况)
  // 注意：这里依靠 screenshotValid 状态，但如果截图文本本身为空，在第3步就已经拦截了
  const hasInvalidScreenshots = !screenshotValid.value

  if (hasUnrecognized || hasInvalidScreenshots) {
    return true
  }

  return false
})

// 计算属性：获取下一步按钮的提示文本
const nextButtonTooltipContent = computed(() => {
  // 1. 优先级最高：检查禁转标签
  if (hasRestrictedTag.value) {
    return '检测到禁转/限转/分集标签，不允许继续发布'
  }

  // 2. 检查是否存在"无法识别"的内容
  const unrecognized = torrentData.value.title_components.find((param) => param.key === '无法识别')
  if (unrecognized && unrecognized.value !== '') {
    return '存在无法识别的标题内容，请手动修正或删除'
  }

  // 3. 检查制作组是否为空或为NOGROUP
  const team = torrentData.value.title_components.find((param) => param.key === '制作组')
  const hasEmptyTeam = !team || !team.value || team.value.trim() === ''
  const isNoGroup = team && team.value.trim().toUpperCase() === 'NOGROUP'

  if (hasEmptyTeam) {
    return '无制作组，禁止发布'
  }

  if (isNoGroup) {
    return '制作组为NOGROUP，禁止发布'
  }

  // 4. 检查必填参数是否为空 (包含：简介信息 + 标准化参数)
  const params = torrentData.value.standardized_params
  const intro = torrentData.value.intro
  const missingFields: string[] = []

  // --- 检查简介信息 ---
  if (!intro.poster || intro.poster.trim() === '') missingFields.push('海报')
  if (!intro.screenshots || intro.screenshots.trim() === '') missingFields.push('截图')
  if (!intro.body || intro.body.trim() === '') missingFields.push('简介正文')

  // --- 检查 Mediainfo ---
  if (!torrentData.value.mediainfo || torrentData.value.mediainfo.trim() === '')
    missingFields.push('Mediainfo')

  // --- 检查标准化参数 ---
  if (!params.type || params.type.trim() === '') missingFields.push('类型')
  if (!params.medium || params.medium.trim() === '') missingFields.push('媒介')
  if (!params.video_codec || params.video_codec.trim() === '') missingFields.push('视频编码')
  if (!params.audio_codec || params.audio_codec.trim() === '') missingFields.push('音频编码')
  if (!params.resolution || params.resolution.trim() === '') missingFields.push('分辨率')

  if (missingFields.length > 0) {
    return `请补充必填项：${missingFields.join('、')}`
  }

  // 4.5 检查简介正文完整性
  const introCompleteness = checkIntroCompleteness(intro.body)
  if (!introCompleteness.isComplete) {
    const criticalFields = ['片名', '产地', '简介']
    const missingCriticalFields = criticalFields.filter((field) =>
      introCompleteness.missingFields.includes(field),
    )
    return `简介正文缺少必填字段：${missingCriticalFields.join('、')}`
  }

  // 4. 检查参数格式 (红框/正则验证)
  if (invalidStandardParams.value.length > 0) {
    const paramNameMap: Record<string, string> = {
      type: '类型',
      medium: '媒介',
      video_codec: '视频编码',
      audio_codec: '音频编码',
      resolution: '分辨率',
      team: '制作组',
      source: '产地',
      tags: '标签',
    }
    const invalidNames = invalidStandardParams.value
      .map((key) => paramNameMap[key] || key)
      .join('、')
    return `参数格式不正确 (${invalidNames})`
  }

  // 5. 检查 MediaInfo/BDInfo 格式有效性
  const mediaInfoText = torrentData.value.mediainfo || ''
  if (!_isValidMediainfo(mediaInfoText) && !_isValidBDInfo(mediaInfoText)) {
    return 'MediaInfo 或 BDInfo 格式无效'
  }

  // 6. 检查截图链接有效性
  if (!screenshotValid.value) {
    return '截图链接失效，请等待重新获取或手动修复'
  }

  return '准备就绪'
})

// 辅助函数：检查是否为有效的 MediaInfo 格式
// 辅助函数：检查是否包含禁止模式
const _hasForbiddenPatterns = (text: string): boolean => {
  const forbiddenPatterns = [
    // BBCode 标签
    { pattern: /\[b\]/, description: 'BBCode粗体标签' },
    { pattern: /\[color=[^\]]+\]/, description: 'BBCode颜色标签' },
    { pattern: /\[size=[^\]]+\]/, description: 'BBCode大小标签' },
    { pattern: /\[\/[^\]]+\]/, description: 'BBCode结束标签' },

    // 特殊符号
    { pattern: /★{2,}/, description: '连续的星星符号' },
    { pattern: /。{3,}/, description: '连续的中文句号' },
    { pattern: /…{2,}/, description: '连续的省略号' },
    { pattern: /……{2,}/, description: '连续的中文省略号' },
  ]

  for (const { pattern, description } of forbiddenPatterns) {
    if (pattern.test(text)) {
      console.log(`检测到禁止模式: ${description}`)
      return true
    }
  }
  return false
}

// 辅助函数：检查是否为有效的 MediaInfo 格式
const _isValidMediainfo = (text: string): boolean => {
  const standardMediainfoKeywords = [
    'General',
    'Video',
    'Audio',
    'Complete name',
    'File size',
    'Duration',
    'Width',
    'Height',
  ]

  const matches = standardMediainfoKeywords.filter((keyword) => text.includes(keyword))
  if (matches.length < 3) {
    return false
  }

  // 关键字验证通过后，检查禁止模式
  if (_hasForbiddenPatterns(text)) {
    return false
  }

  return true
}

// 辅助函数：检查是否为有效的 BDInfo 格式
const _isValidBDInfo = (text: string): boolean => {
  const bdInfoRequiredKeywords = ['DISC INFO', 'PLAYLIST REPORT']
  const bdInfoOptionalKeywords = [
    'VIDEO:',
    'AUDIO:',
    'SUBTITLES:',
    'FILES:',
    'Disc Label',
    'Disc Size',
    'BDInfo:',
    'Protection:',
    'Codec',
    'Bitrate',
    'Language',
    'Description',
  ]

  const requiredMatches = bdInfoRequiredKeywords.filter((keyword) => text.includes(keyword)).length
  const optionalMatches = bdInfoOptionalKeywords.filter((keyword) => text.includes(keyword)).length

  // 必须所有必要关键字都存在，或者至少有1个必要关键字且2个以上可选关键字
  const hasRequiredKeywords =
    requiredMatches === bdInfoRequiredKeywords.length ||
    (requiredMatches >= 1 && optionalMatches >= 2)

  if (!hasRequiredKeywords) {
    return false
  }

  // 关键字验证通过后，检查禁止模式
  if (_hasForbiddenPatterns(text)) {
    return false
  }

  return true
}

// 辅助函数：检查简介正文完整性 (对应 Python check_intro_completeness)
const checkIntroCompleteness = (
  bodyText: string,
): {
  isComplete: boolean
  missingFields: string[]
  foundFields: string[]
} => {
  if (!bodyText || bodyText.trim() === '') {
    return { isComplete: false, missingFields: ['所有字段'], foundFields: [] }
  }

  const requiredPatterns = {
    片名: [
      /[◎❁]\s*片\s*名/i,
      /[◎❁]\s*译\s*名/i,
      /[◎❁]\s*标\s*题/i,
      /片名\s*[:：]/i,
      /译名\s*[:：]/i,
      /Title\s*[:：]/i,
    ],
    产地: [
      /[◎❁]\s*产\s*地/i,
      /[◎❁]\s*国\s*家/i,
      /[◎❁]\s*地\s*区/i,
      /制片国家\/地区\s*[:：]/i,
      /制片国家\s*[:：]/i,
      /国家\s*[:：]/i,
      /产地\s*[:：]/i,
      /Country\s*[:：]/i,
    ],
    简介: [
      /[◎❁]\s*简\s*介/i,
      /[◎❁]\s*剧\s*情/i,
      /[◎❁]\s*内\s*容/i,
      /简介\s*[:：]/i,
      /剧情\s*[:：]/i,
      /内容简介\s*[:：]/i,
      /Plot\s*[:：]/i,
      /Synopsis\s*[:：]/i,
    ],
  }

  const foundFields: string[] = []
  const missingFields: string[] = []

  for (const [fieldName, patterns] of Object.entries(requiredPatterns)) {
    let fieldFound = false
    for (const pattern of patterns) {
      if (pattern.test(bodyText)) {
        fieldFound = true
        break
      }
    }

    if (fieldFound) {
      foundFields.push(fieldName)
    } else {
      missingFields.push(fieldName)
    }
  }

  const criticalFields = ['片名', '产地', '简介']
  const isComplete = criticalFields.every((field) => foundFields.includes(field))

  return {
    isComplete,
    missingFields,
    foundFields,
  }
}

// 检查截图有效性
const checkScreenshotValidity = async () => {
  // 检查当前截图的有效性
  const screenshots = screenshotImages.value
  if (screenshots.length === 0) {
    // 如果没有截图，认为是有效的
    screenshotValid.value = true
    return
  }

  // 对于每个截图，创建一个图片对象来检查是否可以加载
  let allValid = true
  for (const url of screenshots) {
    try {
      await new Promise((resolve, reject) => {
        const img = new Image()
        img.onload = () => {
          resolve(true)
        }
        img.onerror = () => {
          reject(new Error('Image load failed'))
        }
        img.src = url
      })
    } catch (error) {
      allValid = false
      break
    }
  }

  screenshotValid.value = allValid
}

const hideLog = () => {
  showLogCard.value = false
}

const showSiteLog = (siteName: string, logs: string) => {
  let siteLogContent = `--- Log for ${siteName} ---\n${logs || 'No logs available.'}`
  const siteResult = finalResultsList.value.find((result: any) => result.siteName === siteName)
  if (siteResult && siteResult.downloaderStatus) {
    const status = siteResult.downloaderStatus
    siteLogContent += `\n\n--- Downloader Status for ${siteName} ---`
    if (status.success) {
      siteLogContent += `\n✅ 成功: ${status.message}`
    } else {
      siteLogContent += `\n❌ 失败: ${status.message}`
    }
  }
  logContent.value = siteLogContent
  showLogCard.value = true
}

// 分组结果，每行5个
const groupedResults = computed(() => {
  const results = finalResultsList.value
  const grouped = []
  for (let i = 0; i < results.length; i += 5) {
    grouped.push(results.slice(i, i + 5))
  }
  return grouped
})

// 检查行中是否有有效的URL
const hasValidUrlsInRow = (row: any[]) => {
  return row.some((result) => result.success && result.url)
}

// 获取行中有效URL的数量
const getValidUrlsCount = (row: any[]) => {
  return row.filter((result) => result.success && result.url).length
}

// 打开一行中所有有效的种子链接
const openAllSitesInRow = (row: any[]) => {
  const validResults = row.filter((result) => result.success && result.url)

  if (validResults.length === 0) {
    ElNotification.warning({
      title: '无法打开',
      message: '该行没有可用的种子链接',
    })
    return
  }

  // 批量打开所有链接，并过滤掉URL中的uploaded参数
  validResults.forEach((result) => {
    const filteredUrl = filterUploadedParam(result.url)
    window.open(filteredUrl, '_blank', 'noopener,noreferrer')
  })

  ElNotification.success({
    title: '批量打开成功',
    message: `已打开 ${validResults.length} 个种子页面`,
  })
}

// 处理日志进度完成
const handleLogProgressComplete = () => {
  console.log('日志进度处理完成')
  // 进度完成后自动关闭进度窗口
  setTimeout(() => {
    showLogProgress.value = false
  }, 1000)
}

// 过滤URL中的uploaded参数
const filterUploadedParam = (url: string): string => {
  if (!url) return url

  try {
    const normalizeRousiViewUrl = (urlObj: URL) => {
      if (urlObj.hostname === 'rousi.pro' && urlObj.pathname.startsWith('/api/v1/torrents/')) {
        urlObj.pathname = urlObj.pathname.replace('/api/v1/torrents/', '/torrent/')
      }
    }

    // 处理包含 |DIRECT_DOWNLOAD: 的复合链接
    if (url.includes('|DIRECT_DOWNLOAD:')) {
      // 分割链接，只保留前半部分的查看链接
      const viewUrl = url.split('|DIRECT_DOWNLOAD:')[0]
      const urlObj = new URL(viewUrl)
      normalizeRousiViewUrl(urlObj)
      urlObj.searchParams.delete('uploaded')
      return urlObj.toString()
    }

    // 处理普通链接
    const urlObj = new URL(url)
    normalizeRousiViewUrl(urlObj)
    urlObj.searchParams.delete('uploaded')
    return urlObj.toString()
  } catch (error) {
    // 如果URL格式不正确，返回原始URL
    console.warn('Invalid URL format:', url, error)
    return url
  }
}
</script>

<style scoped>
/* ======================================= */
/*        [核心布局样式 - 最终版]        */
/* ======================================= */

/* Mediainfo 容器样式 */
.mediainfo-container {
  display: flex;
  flex-direction: column;
  width: 100%;
}

/* BDInfo 进度条样式 */
.bdinfo-progress-inline {
  margin-bottom: 12px;
  width: 100%;
  flex-shrink: 0;
}

.bdinfo-progress-card-inline {
  border: 1px solid #e4e7ed;
  background-color: #f9f9f9;
  width: 100%;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.header-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
}

.background-hint {
  font-size: 13px;
  color: #909399;
  margin-right: 12px;
}

.progress-details-inline {
  margin-top: 8px;
  width: 100%;
}

.progress-info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: #606266;
  width: 100%;
}

.progress-item {
  flex: 1;
  text-align: center;
  white-space: nowrap;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
  line-height: 1.5;
}

.progress-item strong {
  display: inline;
  margin-right: 4px;
}

/* 1. 主面板容器：使用 Flexbox 布局 */
.cross-seed-panel {
  display: flex;
  flex-direction: column;
  height: calc(90vh - 50px);
}

/* 2. 顶部Header：固定高度 */
.panel-header {
  height: 35px;
  background-color: #ffffff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  padding-bottom: 10px;
  flex-shrink: 0;
  z-index: 10;
}

/* 3. 中间内容区：自适应高度，启用滚动 */
.panel-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 24px;
}

/* 每个步骤内容的容器 */
.step-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
  /* 关键：允许内容区域收缩 */
}

/* 4. 底部Footer：固定高度，始终可见 */
.panel-footer {
  height: 60px;
  background-color: #ffffff;
  border-top: 1px solid #e4e7ed;
  box-shadow: 0 -2px 4px rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  /* 关键：防止按钮区域被压缩 */
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

.custom-step.completed + .custom-step .step-connector {
  background-color: #67c23a;
}

/* --- 步骤 0: 核对详情 --- */
.details-container {
  background-color: #fff;
  border-bottom: 1px solid #e4e7ed;
  height: calc(100% - 1px);
  overflow: visible;
  display: flex;
}

.details-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
}

:deep(.el-tabs__content) {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 20px;
  height: 100vh;
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.2) rgba(0, 0, 0, 0.05);
}

/* Webkit浏览器滚动条美化 */
:deep(.el-tabs__content::-webkit-scrollbar) {
  width: 6px;
}

:deep(.el-tabs__content::-webkit-scrollbar-track) {
  background: rgba(0, 0, 0, 0.05);
  border-radius: 3px;
}

:deep(.el-tabs__content::-webkit-scrollbar-thumb) {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 3px;
}

:deep(.el-tabs__content::-webkit-scrollbar-thumb:hover) {
  background: rgba(0, 0, 0, 0.3);
}

:deep(.el-form-item) {
  margin-bottom: 16px;
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
  gap: 16px;
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

.screenshot-container {
  display: flex;
  gap: 24px;
  max-height: calc(100vh - 280px);
  overflow: hidden;
}

.screenshot-text-column,
.screenshot-preview-column {
  overflow-y: auto;
  overflow-x: hidden;
}

.poster-statement-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  height: 100%;
  max-height: calc(100vh - 280px);
  overflow: hidden;
}

.left-panel,
.right-panel,
.form-column,
.preview-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
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
  content: '';
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
  content: '';
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
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans',
    'Helvetica Neue', sans-serif;
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
  display: grid;
  grid-template-columns: 1fr 100px;
  gap: 16px;
  padding: 16px;
  align-items: start;
}

.row-sites {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  width: 100%;
  min-width: 0;
}

.row-action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100px;
  flex-shrink: 0;
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
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease;
  background: #fff;
  flex-shrink: 0;
  position: relative;
}

.result-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
}

.result-card.is-success {
  border-top: 4px solid #67c23a;
}

.result-card.is-error {
  border-top: 4px solid #f56c6c;
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
  font-size: 12px;
  width: 100%;
}

.status-icon {
  margin-right: 6px;
  display: flex;
  align-items: center;
}

.status-text {
  white-space: pre-line;
  text-align: center;
}

.status-text.success {
  color: #67c23a;
}

.status-text.error {
  color: #f56c6c;
}

/* --- 进度条样式 --- */
.progress-section {
  display: flex;
  gap: 20px;
  margin-bottom: 30px;
  padding: 20px;
  background-color: #f5f7fa;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  border: 1px solid #e4e7ed;
}

.progress-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 60px;
  flex: 1;
}

.progress-label {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
  margin-bottom: 4px;
}

.progress-text {
  font-size: 12px;
  color: #606266;
  text-align: right;
  margin-top: 4px;
}

/* 确保进度条组件正确显示 */
.progress-item :deep(.el-progress) {
  width: 100%;
  margin: 8px 0;
}

.progress-item :deep(.el-progress-bar__outer) {
  background-color: #e4e7ed;
  border-radius: 4px;
}

.progress-item :deep(.el-progress-bar__inner) {
  border-radius: 4px;
  transition: width 0.3s ease;
}

.progress-item :deep(.el-progress__text) {
  font-size: 14px;
  font-weight: 600;
}

/* 🚫 发种限制提示样式 */
.limit-alert-section {
  margin-top: 20px;
  width: 50%;
}

.limit-alert {
  display: flex;
  align-items: flex-start;
  padding: 16px;
  background: #fef0f0;
  border: 1px solid #f56c6c;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(245, 108, 108, 0.1);
}

.limit-alert-content {
  flex: 1;
}

.limit-alert-title {
  font-weight: 600;
  color: #f56c6c;
  font-size: 16px;
  margin-bottom: 8px;
}

.limit-alert-message {
  color: #606266;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
  color: #303133;
}

/* 响应式布局：小屏幕上垂直排列 */
@media (max-width: 768px) {
  .progress-section {
    flex-direction: column;
    gap: 16px;
  }
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

/* --- 2. 为所有无效的 el-select 添加外层红框作为额外提示 --- */
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
  color: #f56c6c;
  background-color: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-8);
  border: 1px solid var(--el-color-danger-light-8);
  text-align: center;
  border-radius: 4px;
}

.unrecognized-section :deep(.el-input__inner) {
  z-index: -999;
  color: #f56c6c;
  background-color: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-8);
  border: 1px solid var(--el-color-danger-light-8);
  text-align: center;
  border-radius: 4px;
  height: 25px;
  margin: 3px 0;
}

/* --- 类型和媒介未选择时的红色提示样式 --- */
.el-select.is-empty :deep(.el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset !important;
}

.el-select.is-empty :deep(.el-select__placeholder) {
  color: var(--el-color-danger) !important;
}

.el-select.is-empty :deep(.el-select__selected-item) {
  background-color: var(--el-color-danger-light-9) !important;
}

/* --- 底部按钮组样式调整 --- */
.button-group {
  position: relative !important;
  /* 强制生效 */
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  /* 确保宽度只包含按钮，不包含绝对定位的子元素 */
  width: max-content;
  margin: 0 auto;
}

/* 检查提示文本样式 */
.check-hint {
  position: absolute !important;
  /* 强制脱离文档流，不占位置 */
  right: 100% !important;
  /* 定位到按钮组的最右边 */
  top: 50% !important;
  transform: translateY(-50%) !important;
  /* 垂直居中 */
  margin-right: 20px;
  /* 与按钮保持距离 */
  white-space: nowrap;
  /* 防止文字换行 */
  z-index: 10;
  /* 确保显示在最上层 */

  /* 原有美化样式 */
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #f56c6c;
  background-color: #fef0f0;
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid #fde2e2;
  animation: shake 0.5s ease-in-out;
}

/* 验证提示文本样式 */
.validation-hint {
  position: absolute !important;
  /* 强制脱离文档流，不占位置 */
  left: 100% !important;
  /* 定位到按钮组的最右边 */
  top: 50% !important;
  transform: translateY(-50%) !important;
  /* 垂直居中 */
  margin-left: 20px;
  /* 与按钮保持距离 */
  white-space: nowrap;
  /* 防止文字换行 */
  z-index: 10;
  /* 确保显示在最上层 */

  /* 原有美化样式 */
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #f56c6c;
  background-color: #fef0f0;
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid #fde2e2;
  animation: shake 0.5s ease-in-out;
}

/* 动画关键帧 */
@keyframes shake {
  0% {
    transform: translateY(-50%) translateX(0);
  }

  25% {
    transform: translateY(-50%) translateX(-2px);
  }

  50% {
    transform: translateY(-50%) translateX(2px);
  }

  75% {
    transform: translateY(-50%) translateX(-2px);
  }

  100% {
    transform: translateY(-50%) translateX(0);
  }
}

.hint-icon {
  margin-right: 5px;
  font-size: 14px;
}

/* 可选：添加一个轻微的晃动动画，当提示出现时 */
@keyframes shake {
  0% {
    transform: translateX(0);
  }

  25% {
    transform: translateX(-2px);
  }

  50% {
    transform: translateX(2px);
  }

  75% {
    transform: translateX(-2px);
  }

  100% {
    transform: translateX(0);
  }
}

/* --- 错误日志弹窗样式 --- */
.error-log-container {
  padding: 5px;
}

.log-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.log-entry {
  display: flex;
  flex-direction: column;
  padding: 8px 12px;
  border-radius: 6px;
  background-color: #f8f9fa;
  border-left: 3px solid #dcdfe6;
  transition: all 0.2s;
}

/* 错误行高亮 */
.log-entry.is-error {
  background-color: #fef0f0;
  border-left-color: #f56c6c;
}

.log-entry-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  line-height: 24px;
  flex-wrap: wrap;
  /* 防止小屏幕换行问题 */
}

.log-time {
  color: #909399;
  font-family: 'Roboto Mono', monospace;
  font-size: 12px;
  min-width: 60px;
}

.log-level-tag {
  font-weight: bold;
  font-family: sans-serif;
  min-width: 60px;
  text-align: center;
}

.log-site {
  color: #606266;
  font-weight: 600;
}

.log-text {
  color: #303133;
  flex: 1;
  word-break: break-all;
}

.log-entry.is-error .log-text {
  color: #f56c6c;
  font-weight: 500;
}

.log-entry-details {
  margin-top: 8px;
  padding-left: 10px;
}

.code-block {
  background-color: rgba(0, 0, 0, 0.05);
  border-radius: 4px;
  padding: 10px;
  margin: 0;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: #333;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
}

/* 错误堆栈的文字颜色更深一点 */
.log-entry.is-error .code-block {
  background-color: #fff;
  border: 1px solid #fde2e2;
  color: #c0392b;
}
</style>
