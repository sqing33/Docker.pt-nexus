<template>
  <div class="cookie-view-container">
    <!-- 1. 顶部固定区域 -->
    <div class="top-actions cookie-actions">
      <!-- CookieCloud 表单 -->
      <el-form :model="cookieCloudForm" inline class="cookie-cloud-form">
        <el-form-item label="CookieCloud">
          <el-input v-model="cookieCloudForm.url" placeholder="http://127.0.0.1:8088" clearable
            style="width: 200px"></el-input>
        </el-form-item>
        <el-form-item label="KEY">
          <el-input v-model="cookieCloudForm.key" placeholder="KEY (UUID)" clearable style="width: 100px"></el-input>
        </el-form-item>
        <el-form-item label="端对端密码">
          <el-input v-model="cookieCloudForm.e2e_password" type="password" show-password placeholder="端对端加密密码" clearable
            style="width: 125px"></el-input>
        </el-form-item>
        <el-form-item>
          <!-- [修改] 合并后的按钮 -->
          <el-button type="primary" size="large" @click="handleSaveAndSync" :loading="isCookieActionLoading">
            <el-icon>
              <Refresh />
            </el-icon>
            <span>同步Cookie</span>
          </el-button>
                  </el-form-item>
      </el-form>

      <div class="right-action-group">
        <el-input v-model="searchQuery" placeholder="搜索站点昵称/标识/官组" clearable :prefix-icon="Search"
          class="search-input" />
      </div>
    </div>

    <!-- 2. 中间可滚动内容区域 -->
    <div class="settings-view" v-loading="isSitesLoading">
      <el-table :data="paginatedSites" stripe class="settings-table" height="100%">
        <el-table-column prop="nickname" label="站点昵称" width="150" sortable />
        <el-table-column prop="site" label="站点标识" width="200" show-overflow-tooltip />
        <el-table-column prop="base_url" label="基础URL" width="225" show-overflow-tooltip />
        <el-table-column prop="group" label="官组" show-overflow-tooltip />
        <el-table-column label="限速" width="100" align="center">
          <template #default="scope">
            <div style="display: flex; justify-content: center; align-items: center; width: 100%; height: 100%;">
              <el-tag v-if="scope.row.speed_limit > 0" type="error" size="small">
                {{ scope.row.speed_limit }} MB/s
              </el-tag>
              <el-tag v-else type="success" size="small">
                不限速
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="proxy" label="代理" width="70" align="center">
          <template #default="scope">
            <el-tag :type="scope.row.proxy ? 'success' : 'info'">{{ scope.row.proxy ? '启用' : '关闭' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Cookie" width="100" align="center">
          <template #default="scope">
            <el-tag :type="scope.row.has_cookie ? 'success' : 'danger'">
              {{ scope.row.has_cookie ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
                <el-table-column label="操作" width="180" align="center" fixed="right">
          <template #default="scope">
            <el-button type="primary" :icon="Edit" link @click="handleOpenDialog(scope.row)">
              编辑
            </el-button>
            <el-button type="danger" :icon="Delete" link @click="handleDelete(scope.row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 3. 底部固定区域 -->
    <div class="settings-footer">
      <el-radio-group v-model="siteFilter" @change="handleFilterChange">
        <el-radio-button label="active">现有站点</el-radio-button>
        <el-radio-button label="all">所有站点</el-radio-button>
      </el-radio-group>
      <div class="pagination-container">
        <div class="page-size-text">{{ pagination.pageSize }} 条/页</div>
        <el-pagination v-model:current-page="pagination.currentPage" v-model:page-size="pagination.pageSize"
          :total="pagination.total" layout="total, prev, pager, next, jumper" background />
      </div>
    </div>

    <!-- 编辑站点对话框 -->
    <el-dialog v-model="dialogVisible" title="编辑站点" width="700px"
      :close-on-click-modal="false">
      <el-form :model="siteForm" ref="siteFormRef" label-width="140px" label-position="left">
        <el-form-item label="站点标识" prop="site" required>
          <el-input v-model="siteForm.site" placeholder="例如：pt" disabled></el-input>
          <div class="form-tip">站点标识不可修改。</div>
        </el-form-item>
        <el-form-item label="站点昵称" prop="nickname" required>
          <el-input v-model="siteForm.nickname" placeholder="例如：PT站"></el-input>
        </el-form-item>
        <el-form-item label="基础URL" prop="base_url">
          <el-input v-model="siteForm.base_url" placeholder="例如：pt.com"></el-input>
          <div class="form-tip">用于拼接种子详情页链接。</div>
        </el-form-item>
        <el-form-item label="Tracker域名" prop="special_tracker_domain">
          <el-input v-model="siteForm.special_tracker_domain" placeholder="例如：pt-tracker.com"></el-input>
          <div class="form-tip">
            如果站点的Tracker域名与主域名的二级域名（则域名去掉前缀后缀部分）不同，请在此填写。
          </div>
        </el-form-item>
        <el-form-item label="使用代理">
          <el-switch v-model="siteForm.proxy" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="关联官组" prop="group">
          <el-input v-model="siteForm.group" placeholder="例如：PT, PTWEB"></el-input>
          <div class="form-tip">用于识别种子所属发布组，多个组用英文逗号(,)分隔。</div>
        </el-form-item>
        <el-form-item label="Cookie" prop="cookie">
          <el-input v-model="siteForm.cookie" type="textarea" :rows="3" placeholder="从浏览器获取的Cookie字符串"></el-input>
        </el-form-item>
                <el-form-item label="上传限速 (MB/s)" prop="speed_limit">
          <el-input-number v-model="siteForm.speed_limit" :min="0" :max="1000" placeholder="0 表示不限速"
            style="width: 100%" />
          <div class="form-tip">单位为 MB/s，0 表示不限速</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="handleSave" :loading="isSaving"> 保存 </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Refresh, Search } from '@element-plus/icons-vue'

// --- 状态管理 ---
const isSaving = ref(false) // 用于站点编辑对话框的保存按钮

// --- 站点管理状态 ---
const sitesList = ref([]) // 存储从后端获取的原始列表
const isSitesLoading = ref(false)
const isCookieActionLoading = ref(false) // [新增] 用于新的"同步Cookie"按钮的加载状态
const cookieCloudForm = ref({ url: '', key: '', e2e_password: '' })
const searchQuery = ref('')
const siteFilter = ref('active')

// --- 分页状态 ---
const pagination = ref({
  currentPage: 1,
  pageSize: 30,
  total: 0,
})

// --- 对话框状态 ---
const dialogVisible = ref(false)
const siteFormRef = ref(null)
const siteForm = ref({
  id: null,
  site: '',
  nickname: '',
  base_url: '',
  special_tracker_domain: '',
  group: '',
  cookie: '',
  proxy: 0,
  speed_limit: 0, // 前端显示和输入使用 MB/s 单位
})

const API_BASE_URL = '/api'

// --- 计算属性 ---

// 1. 先根据前端搜索框进行过滤
const filteredSites = computed(() => {
  if (!searchQuery.value) {
    return sitesList.value
  }
  const term = searchQuery.value.toLowerCase()
  return sitesList.value.filter((site) => {
    const nickname = (site.nickname || '').toLowerCase()
    const siteIdentifier = (site.site || '').toLowerCase()
    const group = (site.group || '').toLowerCase()
    return nickname.includes(term) || siteIdentifier.includes(term) || group.includes(term)
  })
})

// 2. 再根据分页信息对过滤后的结果进行切片
const paginatedSites = computed(() => {
  // 更新分页的总数
  pagination.value.total = filteredSites.value.length

  const start = (pagination.value.currentPage - 1) * pagination.value.pageSize
  const end = start + pagination.value.pageSize
  return filteredSites.value.slice(start, end)
})

// 监听搜索词变化，如果变化则返回第一页
watch(searchQuery, () => {
  pagination.value.currentPage = 1
})

onMounted(() => {
  fetchCookieCloudSettings()
  fetchSites()
})

// --- 方法 ---

const fetchCookieCloudSettings = async () => {
  try {
    const response = await axios.get(`${API_BASE_URL}/settings`)
    if (response.data && response.data.cookiecloud) {
      cookieCloudForm.value.url = response.data.cookiecloud.url || ''
      cookieCloudForm.value.key = response.data.cookiecloud.key || ''
      cookieCloudForm.value.e2e_password = ''
    }
  } catch (error) {
    ElMessage.error('加载CookieCloud配置失败！')
  }
}

// fetchSites 方法以接受筛选参数
const fetchSites = async () => {
  isSitesLoading.value = true
  try {
    const response = await axios.get(`${API_BASE_URL}/sites`, {
      params: {
        filter_by_torrents: siteFilter.value,
      },
    })
    sitesList.value = response.data
  } catch (error) {
    ElMessage.error('获取站点列表失败！')
  } finally {
    isSitesLoading.value = false
  }
}

// 当后端筛选器改变时，重置分页并重新获取数据
const handleFilterChange = () => {
  pagination.value.currentPage = 1
  fetchSites()
}

// [新增] 合并后的保存与同步功能
const handleSaveAndSync = async () => {
  // 1. 前端校验
  if (!cookieCloudForm.value.url || !cookieCloudForm.value.key) {
    ElMessage.warning('CookieCloud URL 和 KEY 不能为空！')
    return
  }
  isCookieActionLoading.value = true
  try {
    // 2. 第一步：先保存配置
    await axios.post(`${API_BASE_URL}/settings`, {
      cookiecloud: cookieCloudForm.value,
    })

    // 3. 第二步：配置保存成功后，立即执行同步
    const syncResponse = await axios.post(
      `${API_BASE_URL}/cookiecloud/sync`,
      cookieCloudForm.value
    )

    // 4. 处理同步结果
    if (syncResponse.data.success) {
      // 移除消息中"在 CookieCloud 中另有 X 个未匹配的 Cookie。"部分
      let message = syncResponse.data.message;
      if (message) {
        message = message.replace(/在 CookieCloud 中另有 \d+ 个未匹配的 Cookie。?/, '');
      }
      ElMessage.success(`配置已保存. ${message || '同步完成！'}`)
      await fetchSites() // 同步成功后刷新站点列表
    } else {
      ElMessage.error(syncResponse.data.message || '同步失败，但配置已保存。')
    }
  } catch (error) {
    const errorMessage = error.response?.data?.message || '操作失败，请检查网络或后端服务。'
    ElMessage.error(errorMessage)
  } finally {
    isCookieActionLoading.value = false
  }
}

const handleOpenDialog = (site) => {
  // 统一使用MB/s单位
  const siteData = JSON.parse(JSON.stringify(site))
  siteForm.value = siteData
  dialogVisible.value = true
}

const handleSave = async () => {
  isSaving.value = true
  try {
    // 统一使用MB/s单位
    const siteData = JSON.parse(JSON.stringify(siteForm.value))

    // 自动过滤掉cookie最后的换行符
    if (siteData.cookie) {
      siteData.cookie = siteData.cookie.trim()
    }

    const response = await axios.post(`${API_BASE_URL}/sites/update`, siteData)

    if (response.data.success) {
      ElMessage.success(response.data.message)
      dialogVisible.value = false
      await fetchSites()
    } else {
      ElMessage.error(response.data.message || '操作失败！')
    }
  } catch (error) {
    const msg = error.response?.data?.message || '请求失败，请检查网络或后端服务。'
    ElMessage.error(msg)
  } finally {
    isSaving.value = false
  }
}

const handleDelete = (site) => {
  ElMessageBox.confirm(`您确定要删除站点【${site.nickname}】吗？此操作不可撤销。`, '警告', {
    confirmButtonText: '确定删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(async () => {
      try {
        const response = await axios.post(`${API_BASE_URL}/sites/delete`, { id: site.id })
        if (response.data.success) {
          ElMessage.success('站点已删除。')
          await fetchSites()
        } else {
          ElMessage.error(response.data.message || '删除失败！')
        }
      } catch (error) {
        const msg = error.response?.data?.message || '删除请求失败。'
        ElMessage.error(msg)
      }
    })
    .catch(() => {
      ElMessage.info('操作已取消。')
    })
}

// [移除] 不再需要独立的 saveCookieCloudSettings 和 syncFromCookieCloud 方法
</script>

<style scoped>
/* 样式部分保持不变 */
.cookie-view-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 40px);
  overflow: hidden;
}

.top-actions,
.settings-footer {
  flex-shrink: 0;
}

.top-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  padding: 16px 24px;
  background-color: var(--el-bg-color-page);
  border-bottom: 1px solid var(--el-border-color);
  gap: 16px;
}

.settings-view {
  flex-grow: 1;
  overflow: hidden;
  padding: 0 24px;
}

.settings-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-top: 1px solid var(--el-border-color);
  background-color: var(--el-bg-color-page);
}

.cookie-cloud-form {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.cookie-cloud-form .el-form-item {
  margin-bottom: 0;
}

.right-action-group {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.search-input {
  width: 250px;
}

.settings-table {
  width: 100%;
}

.pagination-container {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-size-text {
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.form-tip {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 4px;
}
</style>
