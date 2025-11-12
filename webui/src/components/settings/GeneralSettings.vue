<template>
  <div class="settings-container">
    <div class="settings-grid">
      <!-- 用户信息设置卡片 -->
      <div
        class="settings-card glass-card glass-rounded glass-transparent-header glass-transparent-body"
        :class="{ 'temp-password-highlight': mustChange }"
      >
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon">
              <User />
            </el-icon>
            <h3>账户信息</h3>
            <el-tag type="danger" v-if="mustChange" size="small" effect="dark">
              <el-icon style="vertical-align: middle; margin-right: 4px">
                <Warning />
              </el-icon>
              临时密码-请立即修改
            </el-tag>
          </div>
          <el-button type="primary" :loading="loading" @click="onSubmit" size="small">
            保存
          </el-button>
        </div>

        <div class="card-content">
          <el-form :model="form" label-position="top" class="settings-form">
            <el-form-item label="用户名" class="form-item">
              <el-input v-model="form.username" placeholder="请输入用户名" clearable>
                <template #prefix>
                  <el-icon>
                    <User />
                  </el-icon>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item label="当前密码" required class="form-item">
              <el-input
                v-model="form.old_password"
                type="password"
                placeholder="请输入当前密码"
                show-password
              >
                <template #prefix>
                  <el-icon>
                    <Lock />
                  </el-icon>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item label="新密码" class="form-item">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="至少 6 位"
                show-password
              >
                <template #prefix>
                  <el-icon>
                    <Key />
                  </el-icon>
                </template>
              </el-input>
              <div class="password-hint">
                <el-text type="info" size="small">留空表示不修改密码</el-text>
              </div>
            </el-form-item>

            <div class="form-spacer"></div>

            <el-text v-if="mustChange" type="warning" size="small" class="security-hint">
              <el-icon size="12">
                <Warning />
              </el-icon>
              为确保安全，请立即设置新用户名与密码
            </el-text>
          </el-form>
        </div>
      </div>

      <!-- 背景设置卡片 -->
      <div
        class="settings-card glass-card glass-rounded glass-transparent-header glass-transparent-body"
      >
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon">
              <Picture />
            </el-icon>
            <h3>背景设置</h3>
          </div>
          <el-button
            type="primary"
            :loading="savingBackground"
            @click="saveBackgroundSettings"
            size="small"
          >
            保存
          </el-button>
        </div>

        <div class="card-content">
          <el-form :model="backgroundForm" label-position="top" class="settings-form">
            <el-form-item label="背景图片URL" class="form-item">
              <el-input
                v-model="backgroundForm.background_url"
                placeholder="请输入背景图片的URL地址"
                clearable
              >
                <template #prefix>
                  <el-icon>
                    <Picture />
                  </el-icon>
                </template>
              </el-input>
            </el-form-item>

            <div class="form-spacer"></div>

            <el-text type="info" size="small" class="proxy-hint">
              <el-icon size="12">
                <InfoFilled />
              </el-icon>
              设置应用程序的背景图片，支持在线图片URL
            </el-text>
          </el-form>
        </div>
      </div>

      <!-- IYUU设置卡片 -->
      <div
        class="settings-card glass-card glass-rounded glass-transparent-header glass-transparent-body"
      >
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon">
              <Setting />
            </el-icon>
            <h3>IYUU设置</h3>
          </div>
          <el-button type="primary" :loading="savingIyuu" @click="saveIyuuSettings" size="small">
            保存
          </el-button>
        </div>

        <div class="card-content">
          <el-form :model="iyuuForm" label-position="top" class="settings-form">
            <el-form-item label="IYUU Token" class="form-item">
              <el-input
                v-model="iyuuForm.token"
                type="password"
                placeholder="请输入IYUU Token"
                show-password
              >
                <template #prefix>
                  <el-icon>
                    <Key />
                  </el-icon>
                </template>
              </el-input>
            </el-form-item>

            <div style="flex: 1; display: flex; flex-direction: column; justify-content: center">
              <el-form-item label="自动查询与间隔" class="form-item">
                <div
                  style="
                    display: flex;
                    margin: auto;
                    align-items: center;
                    gap: 20px;
                    justify-content: center;
                    padding: 15px 0;
                  "
                >
                  <el-switch
                    v-model="iyuuForm.auto_query_enabled"
                    active-text="启用"
                    inactive-text="禁用"
                  />
                  <el-input-number
                    v-model="iyuuForm.query_interval_days"
                    :min="1"
                    placeholder="天数"
                    controls-position="right"
                    style="width: 120px"
                  />
                  <span>天</span>
                </div>
              </el-form-item>

              <el-form-item label class="form-item">
                <div
                  style="
                    display: flex;
                    margin: auto;
                    gap: 20px;
                    justify-content: center;
                    padding: 15px 0;
                  "
                >
                  <el-button
                    type="success"
                    @click="triggerIyuuQuery"
                    size="default"
                    style="font-size: 14px; padding: 12px 24px"
                  >
                    手动触发查询
                  </el-button>
                  <el-button
                    type="primary"
                    @click="showIyuuLogs"
                    size="default"
                    style="font-size: 14px; padding: 12px 24px"
                  >
                    查看日志
                  </el-button>
                </div>
              </el-form-item>

              <el-text
                type="info"
                size="small"
                style="display: block; text-align: center; margin: 10px 0"
              >
                <el-icon size="12">
                  <InfoFilled />
                </el-icon>
                种子查询页面的红色表示可辅种但未在做种
              </el-text>
            </div>

            <div class="form-spacer"></div>

            <el-text type="info" size="small" class="proxy-hint">
              <el-icon size="12">
                <InfoFilled />
              </el-icon>
              用于与IYUU平台进行数据同步和通信的身份验证令牌
            </el-text>
          </el-form>
        </div>
      </div>

      <!-- IYUU日志对话框 -->
      <el-dialog v-model="iyuuLogsDialogVisible" title="IYUU 查询日志" width="800px" top="50px">
        <div v-loading="loadingLogs" style="height: 500px; overflow-y: auto">
          <div v-if="iyuuLogs.length === 0" style="text-align: center; padding: 20px; color: #999">
            暂无日志记录
          </div>
          <div v-else>
            <div
              v-for="(log, index) in iyuuLogs"
              :key="index"
              style="padding: 8px 0; border-bottom: 1px solid #eee; font-size: 12px"
            >
              <span style="color: #999; margin-right: 10px">[{{ log.timestamp }}]</span>
              <span
                :style="{
                  color:
                    log.level === 'ERROR'
                      ? '#F56C6C'
                      : log.level === 'WARNING'
                        ? '#E6A23C'
                        : log.level === 'INFO'
                          ? '#409EFF'
                          : '#67C23A',
                }"
                >[{{ log.level }}]</span
              >
              <span style="margin-left: 10px">{{ log.message }}</span>
            </div>
          </div>
        </div>
        <template #footer>
          <div style="text-align: right">
            <el-button @click="iyuuLogsDialogVisible = false">关闭</el-button>
            <el-button type="primary" @click="showIyuuLogs">刷新</el-button>
          </div>
        </template>
      </el-dialog>

      <!-- 图床设置卡片 -->
      <div
        class="settings-card glass-card glass-rounded glass-transparent-header glass-transparent-body"
      >
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon">
              <Picture />
            </el-icon>
            <h3>图床设置</h3>
          </div>
          <el-button
            type="primary"
            @click="saveCrossSeedSettings"
            :loading="savingCrossSeed"
            size="small"
          >
            保存
          </el-button>
        </div>

        <div class="card-content">
          <el-form :model="settingsForm" label-position="top" class="settings-form">
            <el-form-item label="截图图床" class="form-item">
              <el-select v-model="settingsForm.image_hoster" placeholder="请选择图床服务">
                <el-option
                  v-for="item in imageHosterOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </el-form-item>

            <!-- 当选择末日图床时，显示登录凭据输入框 -->
            <transition name="slide" mode="out-in">
              <div
                v-if="settingsForm.image_hoster === 'agsv'"
                key="agsv"
                class="credential-section"
              >
                <div class="credential-header">
                  <el-icon class="credential-icon">
                    <Lock />
                  </el-icon>
                  <span class="credential-title">末日图床账号凭据</span>
                </div>

                <div class="credential-form">
                  <el-form-item label="邮箱" class="form-item compact">
                    <el-input
                      v-model="settingsForm.agsv_email"
                      placeholder="请输入邮箱"
                      size="small"
                    />
                  </el-form-item>

                  <el-form-item label="密码" class="form-item compact">
                    <el-input
                      v-model="settingsForm.agsv_password"
                      type="password"
                      placeholder="请输入密码"
                      show-password
                      size="small"
                    />
                  </el-form-item>
                </div>
              </div>

              <div v-else key="other" class="placeholder-section">
                <el-text type="info" size="small"
                  >当前图床无需额外配置，但是需要代理才能上传</el-text
                >
              </div>
            </transition>
          </el-form>
        </div>
      </div>

      <!-- 默认下载器设置卡片 -->
      <div
        class="settings-card glass-card glass-rounded glass-transparent-header glass-transparent-body"
      >
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon">
              <Document />
            </el-icon>
            <h3>默认下载器设置</h3>
          </div>
          <el-button
            type="primary"
            @click="saveCrossSeedSettings"
            :loading="savingCrossSeed"
            size="small"
          >
            保存
          </el-button>
        </div>

        <div class="card-content">
          <el-form :model="settingsForm" label-position="top" class="settings-form">
            <el-form-item label="默认下载器" class="form-item">
              <el-select
                v-model="settingsForm.default_downloader"
                placeholder="请选择默认下载器"
                clearable
              >
                <el-option label="使用源种子所在的下载器" value="" />
                <el-option
                  v-for="item in downloaderOptions"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>

            <div class="form-spacer"></div>

            <el-text type="info" size="small" class="proxy-hint">
              <el-icon size="12">
                <InfoFilled />
              </el-icon>
              转种完成后自动将种子添加到指定的下载器。选择"使用源种子所在的下载器"或不选择任何下载器，则添加到源种子所在的下载器。
            </el-text>
          </el-form>
        </div>
      </div>

      <!-- 上传设置卡片 -->
      <div
        class="settings-card glass-card glass-rounded glass-transparent-header glass-transparent-body"
      >
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon">
              <Setting />
            </el-icon>
            <h3>转种设置</h3>
          </div>
          <el-button
            type="primary"
            @click="saveUploadSettings"
            :loading="savingUpload"
            size="small"
          >
            保存
          </el-button>
        </div>

        <div class="card-content">
          <el-form :model="uploadForm" label-position="top" class="settings-form">
            <el-form-item label="" class="form-item">
              <div style="display: flex; align-items: center; gap: 20px; padding: 15px 0">
                <el-switch
                  v-model="uploadForm.anonymous_upload"
                  active-text="启用匿名"
                  inactive-text="禁用匿名"
                  size="large"
                />
              </div>
            </el-form-item>

            <div class="form-item" style="margin-bottom: 16px">
              <div
                style="
                  display: flex;
                  align-items: center;
                  justify-content: space-between;
                  margin-bottom: 6px;
                "
              >
                <span
                  style="font-weight: 500; color: var(--el-text-color-regular); font-size: 13px"
                >
                  财神 PTGen API Token（每日100次）
                </span>
                <el-button
                  type="primary"
                  link
                  @click="openCsptPtgenPage"
                  style="white-space: nowrap"
                >
                  <el-icon style="margin-right: 4px">
                    <Link />
                  </el-icon>
                  获取Token
                </el-button>
              </div>
              <el-input
                v-model="uploadForm.cspt_ptgen_token"
                type="password"
                placeholder="请输入财神 PTGen API Token"
                show-password
              >
                <template #prefix>
                  <el-icon>
                    <Key />
                  </el-icon>
                </template>
              </el-input>
            </div>

            <div class="form-spacer"></div>

            <el-text type="info" size="small" class="proxy-hint">
              <el-icon size="12">
                <InfoFilled />
              </el-icon>
              启用后，发布种子时将使用匿名模式，不显示上传者信息<br />
              配置财神 PTGen API Token 后，优先使用该API获取影片信息<br />
              财神 PTGen API 每日限量 100次<br />
              使用完会自动切换内置的其他 PTGen API
            </el-text>
          </el-form>
        </div>
      </div>

      <!-- 功能扩展卡片 -->
      <div
        class="settings-card glass-card glass-rounded glass-transparent-header glass-transparent-body"
      >
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon">
              <Setting />
            </el-icon>
            <h3>功能扩展</h3>
          </div>
        </div>

        <div class="card-content placeholder-content">
          <el-icon class="placeholder-icon">
            <Setting />
          </el-icon>
          <p class="placeholder-text">功能扩展中</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import {
  User,
  Lock,
  Key,
  Warning,
  Setting,
  Connection,
  Document,
  InfoFilled,
  Picture,
  Link,
} from '@element-plus/icons-vue'

// 用户设置相关
const loading = ref(false)
const savingIyuu = ref(false)
const currentUsername = ref('admin')
const mustChange = ref(false)
const form = ref({ old_password: '', username: '', password: '' })

// IYUU设置相关
const iyuuForm = reactive({
  token: '',
  query_interval_hours: 72,
  query_interval_days: 3, // 以天为单位显示
  auto_query_enabled: true,
})

// IYUU日志接口
interface IYUULog {
  timestamp: string
  level: string
  message: string
}

// 转种设置相关
interface CrossSeedSettings {
  image_hoster: string
  agsv_email?: string
  agsv_password?: string
  default_downloader?: string
}

const savingCrossSeed = ref(false)

const settingsForm = reactive<CrossSeedSettings>({
  image_hoster: 'pixhost',
  agsv_email: '',
  agsv_password: '',
  default_downloader: '',
})

const imageHosterOptions = [
  { value: 'pixhost', label: 'Pixhost (免费)' },
  { value: 'agsv', label: '末日图床 (需账号)' },
]

// 下载器选项
const downloaderOptions = ref<{ id: string; name: string }[]>([])

// 实际的 token 值，用于在保存时判断是否需要更新
const actualIyuuToken = ref('')

// IYUU日志相关
const iyuuLogsDialogVisible = ref(false)
const iyuuLogs = ref<IYUULog[]>([])
const loadingLogs = ref(false)

// 背景设置相关
const savingBackground = ref(false)
const backgroundForm = reactive({
  background_url: '',
})

// 上传设置相关
const savingUpload = ref(false)
const uploadForm = reactive({
  anonymous_upload: true, // 默认启用匿名上传
  cspt_ptgen_token: '', // 财神ptgen token
})

// 打开财神PTGen网页获取Token
const openCsptPtgenPage = () => {
  window.open('https://cspt.top/ptgen.php', '_blank')
}

// 获取所有设置
const fetchSettings = async () => {
  try {
    // 获取用户认证状态
    const res = await axios.get('/api/auth/status')
    if (res.data?.success) {
      currentUsername.value = res.data.username || 'admin'
      mustChange.value = !!res.data.must_change_password
      form.value.username = currentUsername.value
    }

    // 获取所有设置
    const settingsRes = await axios.get('/api/settings')
    const config = settingsRes.data

    // 获取IYUU token设置
    if (config.iyuu_token) {
      // 保存实际的 token 值
      actualIyuuToken.value = config.iyuu_token
      // 显示为隐藏状态（用星号代替）
      iyuuForm.token = config.iyuu_token ? '********' : ''
    }

    // 获取IYUU设置
    if (config.iyuu_settings) {
      iyuuForm.query_interval_hours = config.iyuu_settings.query_interval_hours || 72
      // 将小时转换为天数显示（向上取整）
      iyuuForm.query_interval_days = Math.ceil(iyuuForm.query_interval_hours / 24)
      iyuuForm.auto_query_enabled = config.iyuu_settings.auto_query_enabled !== false // 默认为true
    }

    // 获取转种设置
    Object.assign(settingsForm, config.cross_seed || {})

    // 获取背景设置
    if (config.ui_settings && config.ui_settings.background_url) {
      backgroundForm.background_url = config.ui_settings.background_url
    }

    // 获取上传设置
    if (config.upload_settings) {
      uploadForm.anonymous_upload = config.upload_settings.anonymous_upload !== false // 默认为true
    }

    // 获取财神ptgen token（从cross_seed配置中读取）
    if (config.cross_seed && config.cross_seed.cspt_ptgen_token) {
      uploadForm.cspt_ptgen_token = config.cross_seed.cspt_ptgen_token
    }

    // 获取下载器列表
    const downloaderResponse = await axios.get('/api/downloaders_list')
    downloaderOptions.value = downloaderResponse.data
  } catch (error) {
    ElMessage.error('无法加载设置。')
  }
}

// 保存用户设置
const resetForm = () => {
  form.value = { old_password: '', username: currentUsername.value, password: '' }
}

// 保存IYUU设置
const saveIyuuSettings = async () => {
  savingIyuu.value = true
  try {
    // 保存 iyuu token 设置
    // 如果显示的是星号，表示没有更改，不需要更新token
    if (iyuuForm.token !== '********') {
      const tokenSettings = {
        iyuu_token: iyuuForm.token,
      }
      await axios.post('/api/settings', tokenSettings)
      // 保存成功后，显示星号而不是明文
      if (iyuuForm.token) {
        iyuuForm.token = '********'
      } else {
        iyuuForm.token = ''
      }
      actualIyuuToken.value = iyuuForm.token
    }

    // 保存IYUU其他设置
    // 将天数转换为小时保存到后端
    const iyuuSettings = {
      query_interval_hours: iyuuForm.query_interval_days * 24,
      auto_query_enabled: iyuuForm.auto_query_enabled,
    }

    await axios.post('/api/iyuu/settings', iyuuSettings)
    // 更新本地的小时值，以便下次加载时正确显示
    iyuuForm.query_interval_hours = iyuuSettings.query_interval_hours
    ElMessage.success('IYUU 设置已保存！')
  } catch (error: any) {
    const errorMessage = error.response?.data?.error || '保存失败。'
    ElMessage.error(errorMessage)
  } finally {
    savingIyuu.value = false
  }
}

// 手动触发IYUU查询
const triggerIyuuQuery = async () => {
  try {
    // 立即显示触发成功的提示
    ElMessage.success('IYUU 查询已触发，请稍后查看结果。')

    // 异步触发后端查询，不等待结果
    axios.post('/api/iyuu/trigger_query').catch((error) => {
      // 如果后台查询失败，记录错误但不显示给用户
      console.error('IYUU 查询后台执行失败:', error)
    })
  } catch (error: any) {
    const errorMessage = error.response?.data?.message || '触发查询失败。'
    ElMessage.error(errorMessage)
  }
}

// 查看IYUU日志
const showIyuuLogs = async () => {
  loadingLogs.value = true
  iyuuLogsDialogVisible.value = true

  try {
    const response = await axios.get('/api/iyuu/logs')
    if (response.data.success) {
      iyuuLogs.value = response.data.logs || []
    } else {
      ElMessage.error(response.data.message || '获取日志失败')
      iyuuLogs.value = []
    }
  } catch (error: any) {
    const errorMessage = error.response?.data?.message || '获取日志失败'
    ElMessage.error(errorMessage)
    iyuuLogs.value = []
  } finally {
    loadingLogs.value = false
  }
}

// 保存用户密码和用户名
const onSubmit = async () => {
  if (loading.value) return
  if (!form.value.old_password) {
    ElMessage.warning('请填写当前密码')
    return
  }
  if (!form.value.username && !form.value.password) {
    ElMessage.warning('请输入新用户名或新密码')
    return
  }
  if (form.value.username && form.value.username.trim().length < 3) {
    ElMessage.warning('用户名至少 3 个字符')
    return
  }
  if (form.value.password && form.value.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  loading.value = true
  try {
    const payload: any = { old_password: form.value.old_password }
    if (form.value.username) payload.username = form.value.username
    if (form.value.password) payload.password = form.value.password
    const res = await axios.post('/api/auth/change_password', payload)
    if (res.data?.success) {
      ElMessage.success('保存成功，请重新登录')
      localStorage.removeItem('token')
      window.location.href = '/login'
    } else {
      ElMessage.error(res.data?.message || '保存失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '保存失败')
  } finally {
    loading.value = false
  }
}

// 保存转种设置
const saveCrossSeedSettings = async () => {
  savingCrossSeed.value = true
  try {
    // 保存转种设置
    const crossSeedSettings = {
      image_hoster: settingsForm.image_hoster,
      agsv_email: settingsForm.agsv_email,
      agsv_password: settingsForm.agsv_password,
      default_downloader: settingsForm.default_downloader,
    }

    await axios.post('/api/settings/cross_seed', crossSeedSettings)
    ElMessage.success('转种设置已保存！')
  } catch (error: any) {
    const errorMessage = error.response?.data?.error || '保存失败。'
    ElMessage.error(errorMessage)
  } finally {
    savingCrossSeed.value = false
  }
}

// 保存背景设置
const saveBackgroundSettings = async () => {
  savingBackground.value = true
  try {
    const uiSettings = {
      ui_settings: {
        background_url: backgroundForm.background_url,
      },
    }
    await axios.post('/api/settings', uiSettings)
    ElMessage.success('背景设置已保存！')

    // 立即更新App.vue的背景
    window.dispatchEvent(
      new CustomEvent('background-updated', {
        detail: { backgroundUrl: backgroundForm.background_url },
      }),
    )
  } catch (error: any) {
    const errorMessage = error.response?.data?.error || '保存失败。'
    ElMessage.error(errorMessage)
  } finally {
    savingBackground.value = false
  }
}

// 保存上传设置
const saveUploadSettings = async () => {
  savingUpload.value = true
  try {
    // 保存匿名上传设置
    const uploadSettings = {
      anonymous_upload: uploadForm.anonymous_upload,
    }
    await axios.post('/api/upload_settings', uploadSettings)

    // 保存财神ptgen token到cross_seed配置
    // 需要包含完整的cross_seed配置，因为后端API要求必须有image_hoster字段
    const crossSeedSettings = {
      image_hoster: settingsForm.image_hoster,
      agsv_email: settingsForm.agsv_email,
      agsv_password: settingsForm.agsv_password,
      default_downloader: settingsForm.default_downloader,
      cspt_ptgen_token: uploadForm.cspt_ptgen_token,
    }
    await axios.post('/api/settings/cross_seed', crossSeedSettings)

    ElMessage.success('上传设置已保存！')
  } catch (error: any) {
    const errorMessage = error.response?.data?.error || '保存失败。'
    ElMessage.error(errorMessage)
  } finally {
    savingUpload.value = false
  }
}

onMounted(() => {
  fetchSettings()
})
</script>

<style scoped>
.settings-container {
  padding: 20px;
  background-color: transparent;
  min-height: calc(100% - 40px);
  overflow-y: auto;
  height: 100%;
}

.page-description {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin: 0;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.settings-card {
  display: flex;
  flex-direction: column;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  flex-shrink: 0;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-content h3 {
  font-size: 16px;
  font-weight: 500;
  margin: 0;
  color: var(--el-text-color-primary);
}

.header-icon {
  font-size: 16px;
  color: var(--el-color-primary);
}

.card-content {
  padding: 16px;
  height: 320px;
  display: flex;
  flex-direction: column;
}

.settings-form {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.form-item {
  margin-bottom: 16px;
}

.form-item.compact {
  margin-bottom: 12px;
}

.form-item :deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--el-text-color-regular);
  font-size: 13px;
  margin-bottom: 6px;
  height: auto;
}

.password-hint {
  margin-top: 6px;
}

.credential-section {
  border-radius: 4px;
  padding: 12px;
  margin-top: 8px;
}

.credential-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
}

.credential-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.credential-icon {
  color: var(--el-color-warning);
  font-size: 14px;
}

.credential-form {
  padding-left: 20px;
}

.placeholder-section {
  margin-top: 8px;
}

.form-spacer {
  flex: 1;
}

.security-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 1.4;
  margin-top: auto;
}

.proxy-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 1.4;
  margin-top: auto;
}

.placeholder-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--el-text-color-secondary);
  height: 100%;
}

.placeholder-icon {
  font-size: 32px;
  margin-bottom: 12px;
  opacity: 0.5;
}

.placeholder-text {
  margin: 0;
  font-size: 14px;
}

.slide-enter-active,
.slide-leave-active {
  transition: all 0.2s ease;
}

.slide-enter-from {
  opacity: 0;
  transform: translateY(-10px);
}

.slide-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

/* 临时密码高亮样式 */
.temp-password-highlight {
  position: relative;
  animation: pulse-border 2s ease-in-out infinite;
}

.temp-password-highlight::before {
  content: '';
  position: absolute;
  top: -2px;
  left: -2px;
  right: -2px;
  bottom: -2px;
  background: linear-gradient(45deg, #ff6b6b, #ff8787, #ff6b6b);
  border-radius: 12px;
  z-index: -1;
  opacity: 0.6;
  animation: gradient-shift 3s ease infinite;
}

@keyframes pulse-border {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.01);
  }
}

@keyframes gradient-shift {
  0%,
  100% {
    background-position: 0% 50%;
  }
  50% {
    background-position: 100% 50%;
  }
}

.temp-password-highlight .card-header {
  background: linear-gradient(135deg, rgba(255, 107, 107, 0.1), rgba(255, 135, 135, 0.05));
}

:deep(.el-input__inner),
:deep(.el-select .el-input__inner) {
  height: 36px;
  font-size: 13px;
}

:deep(.el-select-dropdown__item) {
  height: 32px;
  font-size: 13px;
}

@media (max-width: 1200px) {
  .settings-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .settings-container {
    padding: 16px;
  }

  .settings-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .card-header {
    padding: 12px 16px;
  }

  .card-content {
    padding: 16px;
    height: auto;
    min-height: 320px;
  }
}
</style>
