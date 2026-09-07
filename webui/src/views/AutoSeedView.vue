<template>
  <div class="auto-seed-view">
    <el-tabs v-model="activeTab" class="auto-tabs">
      <el-tab-pane label="自动发种列表" name="items">
        <div class="toolbar glass-table">
          <el-button type="primary" @click="openRuleDialog()">新增规则</el-button>
          <el-button @click="manualDialogVisible = true">添加种子地址</el-button>
          <el-select v-model="filters.source_site" placeholder="源站" clearable class="filter">
            <el-option v-for="site in sourceSiteNames" :key="site" :label="site" :value="site" />
          </el-select>
          <el-select v-model="filters.status" placeholder="状态" clearable class="filter">
            <el-option label="未推送" value="not_pushed" />
            <el-option label="已推送" value="pushed" />
            <el-option label="已整理" value="organized" />
            <el-option label="已发布" value="published" />
            <el-option label="有未推送原因" value="rejected" />
          </el-select>
          <el-select v-model="filters.downloader_id" placeholder="下载器" clearable class="filter">
            <el-option
              v-for="item in downloaders"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
          <el-input
            v-model="filters.search"
            placeholder="搜索名称或地址"
            clearable
            class="search"
          />
          <el-button @click="fetchItems">筛选</el-button>
          <div class="spacer" />
          <el-button
            :disabled="selectedRows.length === 0"
            type="primary"
            :icon="Upload"
            @click="pushItems(selectedRows)"
          >
            批量推送
          </el-button>
          <el-button
            :disabled="selectedRows.length === 0"
            type="success"
            @click="openPublishDialog(selectedRows)"
          >
            批量发布
          </el-button>
          <el-button
            :disabled="selectedRows.length === 0"
            type="danger"
            @click="deleteItems(selectedRows)"
          >
            批量删除
          </el-button>
        </div>

        <el-table
          :data="items"
          row-key="id"
          height="100%"
          border
          class="glass-table table"
          v-loading="loading"
          @selection-change="selectedRows = $event"
        >
          <el-table-column type="selection" width="44" />
          <el-table-column prop="source_site" label="源站" width="110" />
          <el-table-column label="名称" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <el-link
                v-if="sourceDetailURL(row)"
                :href="sourceDetailURL(row)"
                target="_blank"
                :underline="false"
                class="source-torrent-link"
              >
                {{ row.name }}
              </el-link>
              <span v-else>{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="副标题" min-width="220">
            <template #default="{ row }">
              <el-tooltip :content="row.subtitle || ''" :disabled="!row.subtitle" placement="top">
                <span class="subtitle-cell">{{ subtitlePreview(row.subtitle) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="90" align="right">
            <template #default="{ row }">{{ formatGB(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="推送时间" width="170">
            <template #default="{ row }">{{ formatElapsedTime(row.pushed_at) }}</template>
          </el-table-column>
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ displayType(row.resource_type) }}</template>
          </el-table-column>
          <el-table-column label="媒介" width="100">
            <template #default="{ row }">{{ displayMedium(row.medium) }}</template>
          </el-table-column>
          <el-table-column label="标签" min-width="140">
            <template #default="{ row }">
              <el-tag v-for="tag in parseJSON(row.tags_json)" :key="tag" size="small" class="tag">
                {{ tag }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{
                statusText(row.status)
              }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column
            prop="reject_reason"
            label="未推送原因"
            min-width="150"
            show-overflow-tooltip
          />
          <el-table-column label="发布结果" min-width="220">
            <template #default="{ row }">
              <div v-if="publishResults(row).length" class="publish-results">
                <el-link
                  v-for="result in publishResults(row)"
                  :key="result.label"
                  :href="result.url || undefined"
                  target="_blank"
                  :underline="false"
                  class="publish-result"
                >
                  {{ result.label }}
                </el-link>
              </div>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="290" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openOrganizeDialog(row)">整理</el-button>
              <el-button
                size="small"
                type="primary"
                :icon="Upload"
                :disabled="isWorkflowStarted(row.status)"
                @click="pushItems([row])"
              >
                推送
              </el-button>
              <el-button size="small" type="success" @click="openPublishDialog([row])"
                >发布</el-button
              >
              <el-button size="small" type="info" @click="openLogs(row)">发布日志</el-button>
              <el-button size="small" type="danger" @click="deleteItems([row])">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[20, 50, 100, 200]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="fetchItems"
            @size-change="handleSizeChange"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane label="规则配置" name="rules">
        <el-table
          :data="rules"
          border
          class="glass-table table"
          height="100%"
          v-loading="rulesLoading"
        >
          <el-table-column prop="name" label="规则名称" min-width="160" />
          <el-table-column prop="source_site" label="源站" width="120" />
          <el-table-column prop="downloader_id" label="下载器" width="150">
            <template #default="{ row }">{{ downloaderName(row.downloader_id) }}</template>
          </el-table-column>
          <el-table-column label="拉取频率" width="110">
            <template #default="{ row }">{{ row.pull_interval_minutes }} 分钟</template>
          </el-table-column>
          <el-table-column label="保种时间" width="110">
            <template #default="{ row }">
              {{ row.seed_retention_minutes > 0 ? `${row.seed_retention_minutes} 分钟` : '不清理' }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-switch
                :model-value="row.enabled"
                active-text="开启"
                inactive-text="暂停"
                inline-prompt
                @change="(val: boolean) => toggleRuleEnabled(row, val)"
              />
            </template>
          </el-table-column>
          <el-table-column
            prop="paused_reason"
            label="暂停原因"
            min-width="180"
            show-overflow-tooltip
          />
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="triggerRule(row)">拉取</el-button>
              <el-button size="small" type="primary" @click="openRuleDialog(row)">修改</el-button>
              <el-button size="small" type="danger" @click="deleteRule(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="下载器进度" name="progress">
        <div class="toolbar glass-table">
          <el-select
            v-model="progressDownloader"
            placeholder="下载器"
            clearable
            class="filter"
            @change="fetchProgress"
          >
            <el-option
              v-for="item in downloaders"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
          <el-button @click="fetchProgress">刷新</el-button>
        </div>
        <el-table
          :data="progressRows"
          border
          class="glass-table table"
          height="100%"
          v-loading="progressLoading"
        >
          <el-table-column prop="name" label="名称" min-width="260" show-overflow-tooltip />
          <el-table-column prop="downloader_id" label="下载器" width="150">
            <template #default="{ row }">{{ downloaderName(row.downloader_id) }}</template>
          </el-table-column>
          <el-table-column label="进度" width="120">
            <template #default="{ row }">{{ Number(row.progress || 0).toFixed(1) }}%</template>
          </el-table-column>
          <el-table-column label="推送时间" width="170">
            <template #default="{ row }">{{ formatElapsedTime(row.pushed_at) }}</template>
          </el-table-column>
          <el-table-column label="分组" width="100">
            <template #default="{ row }">{{ progressGroup(row) }}</template>
          </el-table-column>
          <el-table-column label="发布结果" min-width="260">
            <template #default="{ row }">
              <div v-if="publishResults(row).length" class="publish-results">
                <el-link
                  v-for="result in publishResults(row)"
                  :key="result.label"
                  :href="result.url || undefined"
                  target="_blank"
                  :underline="false"
                  class="publish-result"
                >
                  {{ result.label }}
                </el-link>
              </div>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button
                size="small"
                type="success"
                :disabled="row.status === 'published'"
                @click="openPublishDialog([row])"
              >
                立即发布
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="ruleDialogVisible"
      :title="editingRule.id ? '修改规则' : '新增规则'"
      width="720px"
    >
      <el-form :model="editingRule" label-width="110px">
        <el-form-item label="名称"><el-input v-model="editingRule.name" /></el-form-item>
        <el-form-item label="源站">
          <el-select
            v-model="editingRule.source_site"
            filterable
            clearable
            style="width: 100%"
            :loading="sitesLoading"
          >
            <el-option
              v-for="site in sourceSiteOptions"
              :key="site.name"
              :label="site.name"
              :value="site.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="RSS 地址"><el-input v-model="editingRule.rss_url" /></el-form-item>
        <el-form-item label="下载器">
          <el-select v-model="editingRule.downloader_id" style="width: 100%">
            <el-option
              v-for="item in downloaders"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="下载地址">
          <el-input
            v-model="editingRule.download_url"
            placeholder="自定义种子下载地址，留空则使用 RSS 中的地址"
          />
        </el-form-item>
        <el-form-item label="大小 GB">
          <div class="inline-fields">
            <el-input-number
              v-model="editingRule.min_size_gb"
              :min="0"
              :precision="1"
              placeholder="最小"
            />
            <el-input-number
              v-model="editingRule.max_size_gb"
              :min="0"
              :precision="1"
              placeholder="最大"
            />
          </div>
        </el-form-item>
        <el-form-item label="标签"
          ><el-input v-model="ruleTagsText" placeholder="多个用逗号分隔"
        /></el-form-item>
        <el-form-item label="发布站点">
          <el-select
            v-model="ruleTargetSites"
            multiple
            filterable
            clearable
            collapse-tags
            collapse-tags-tooltip
            placeholder="请选择发布站点"
            style="width: 100%"
            :loading="sitesLoading"
          >
            <el-option
              v-for="site in targetSiteOptions"
              :key="site.name"
              :label="site.name"
              :value="site.name"
              :disabled="site.can_publish === false"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="拉取频率">
          <el-input-number v-model="editingRule.pull_interval_minutes" :min="1" :max="1440" />
          <span class="unit">分钟</span>
        </el-form-item>
        <el-form-item label="保种时间">
          <el-input-number v-model="editingRule.seed_retention_minutes" :min="0" :max="525600" />
          <span class="unit">分钟，0 表示不自动清理</span>
        </el-form-item>
        <el-form-item label="开关">
          <el-switch v-model="editingRule.enabled" active-text="开启" inactive-text="暂停" />
          <el-switch
            v-model="editingRule.auto_pause"
            active-text="添加暂停"
            inactive-text="立即下载"
            class="switch-gap"
          />
          <el-switch
            v-model="editingRule.auto_organize"
            active-text="自动整理"
            inactive-text="手动整理"
            class="switch-gap"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="manualDialogVisible" title="添加种子地址" width="560px">
      <el-form label-width="90px">
        <el-form-item label="种子地址"><el-input v-model="manualForm.torrent_url" /></el-form-item>
        <el-form-item label="源站">
          <el-select
            v-model="manualForm.source_site"
            filterable
            clearable
            style="width: 100%"
            :loading="sitesLoading"
          >
            <el-option
              v-for="site in sourceSiteOptions"
              :key="site.name"
              :label="site.name"
              :value="site.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="下载器">
          <el-select v-model="manualForm.downloader_id" style="width: 100%">
            <el-option
              v-for="item in downloaders"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="addManual">添加</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="organizeDialogVisible" title="整理种子数据" width="560px">
      <el-form :model="organizeForm" label-width="90px">
        <el-form-item label="名称"><el-input v-model="organizeForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="organizeForm.resource_type" style="width: 100%">
            <el-option label="电影" value="电影" />
            <el-option label="电视剧" value="电视剧" />
          </el-select>
        </el-form-item>
        <el-form-item label="媒介">
          <el-select v-model="organizeForm.medium" filterable clearable style="width: 100%">
            <el-option
              v-for="medium in mediumOptions"
              :key="medium"
              :label="medium"
              :value="medium"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标签"><el-input v-model="organizeTagsText" /></el-form-item>
        <el-form-item label="源站 ID"><el-input v-model="organizeForm.torrent_id" /></el-form-item>
        <el-form-item label="源站名"><el-input v-model="organizeForm.site_name" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="organizeDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveOrganize">保存</el-button>
      </template>
    </el-dialog>

    <div v-if="crossSeedDialogVisible" class="auto-cross-seed-overlay">
      <el-card class="auto-cross-seed-card" shadow="always">
        <template #header>
          <div class="auto-cross-seed-header">
            <span>整理种子数据 - {{ organizingRow?.name }}</span>
            <el-button type="danger" circle plain @click="closeCrossSeedOrganize">X</el-button>
          </div>
        </template>
        <CrossSeedPanel
          :key="crossSeedPanelKey"
          publish-scene="auto_seed"
          @seed-info-updated="handleCrossSeedSeedInfoUpdated"
          @complete="handleCrossSeedOrganizeComplete"
          @close-with-refresh="handleCrossSeedOrganizeComplete"
          @cancel="closeCrossSeedOrganize"
        />
      </el-card>
    </div>

    <el-dialog v-model="publishDialogVisible" title="发布到站点" width="520px">
      <el-form label-width="90px">
        <el-form-item label="目标站点">
          <el-select
            v-model="publishTargetSites"
            multiple
            filterable
            clearable
            collapse-tags
            collapse-tags-tooltip
            placeholder="请选择发布站点"
            style="width: 100%"
            :loading="sitesLoading"
          >
            <el-option
              v-for="site in targetSiteOptions"
              :key="site.name"
              :label="site.name"
              :value="site.name"
              :disabled="site.can_publish === false"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="publishDialogVisible = false">取消</el-button>
        <el-button type="success" @click="publishSelected">发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import CrossSeedPanel from '@/components/CrossSeedPanel.vue'
import { useCrossSeedStore } from '@/stores/crossSeed'
import type { WorkingTorrent } from '@/components/cross-seed/panel/types'

type Downloader = { id: string; name: string }
type SiteItem = { name: string; can_publish: boolean }
type Rule = {
  id: number
  name: string
  enabled: boolean
  paused_reason: string
  source_site: string
  rss_url: string
  downloader_id: string
  save_path: string
  download_url: string
  auto_pause: boolean
  auto_organize: boolean
  min_size_gb: number
  max_size_gb: number
  types_json: string
  media_json: string
  tags_json: string
  target_sites_json: string
  pull_interval_minutes: number
  publish_interval_minutes: number
  publish_concurrency: number
  seed_retention_minutes: number
}
type Item = {
  id: number
  source_site: string
  torrent_url: string
  detail_url: string
  name: string
  save_path: string
  size_bytes: number
  resource_type: string
  medium: string
  subtitle: string
  tags_json: string
  status: string
  reject_reason: string
  publish_results_json: string
  downloader_id: string
  downloader_hash: string
  progress: number
  downloaded: boolean
  pushed_at?: string
  torrent_id: string
  site_name: string
}

const activeTab = ref('items')
const loading = ref(false)
const rulesLoading = ref(false)
const progressLoading = ref(false)
const items = ref<Item[]>([])
const rules = ref<Rule[]>([])
const progressRows = ref<Item[]>([])
const downloaders = ref<Downloader[]>([])
const sourceSiteOptions = ref<SiteItem[]>([])
const targetSiteOptions = ref<SiteItem[]>([])
const sitesLoading = ref(false)
const selectedRows = ref<Item[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filters = ref({
  source_site: '',
  status: '',
  downloader_id: '',
  search: '',
})
const progressDownloader = ref('')

const ruleDialogVisible = ref(false)
const manualDialogVisible = ref(false)
const organizeDialogVisible = ref(false)
const publishDialogVisible = ref(false)
const editingRule = ref<Rule>(emptyRule())
const ruleTagsText = ref('')
const ruleTargetSites = ref<string[]>([])
const manualForm = ref({ torrent_url: '', source_site: '', downloader_id: '' })
const organizeForm = ref<Partial<Item>>({})
const organizeTagsText = ref('')
const publishRows = ref<Item[]>([])
const publishTargetSites = ref<string[]>([])
const crossSeedStore = useCrossSeedStore()
const crossSeedDialogVisible = ref(false)
const crossSeedPanelKey = ref(0)
const organizingRow = ref<Item | null>(null)

const mediumOptions = ['Blu-ray', 'Remux', 'WEB-DL', 'WEBRip', 'HDTV', 'DVD', 'UHD']
const typeDisplayMap: Record<string, string> = {
  'category.movie': '电影',
  'category.tv_series': '电视剧',
  'category.tv_shows': '综艺',
  'category.animation': '动画',
  'category.documentaries': '纪录片',
  'category.documentary': '纪录片',
  'category.music': '音乐',
  'category.sports': '体育',
  'category.other': '其他',
}
const mediumDisplayMap: Record<string, string> = {
  'medium.bluray': 'Blu-ray',
  'medium.uhd_bluray': 'UHD Blu-ray',
  'medium.uhd_bluray_remux': 'UHD Blu-ray Remux',
  'medium.remux': 'Remux',
  'medium.encode': 'Encode',
  'medium.webdl': 'WEB-DL',
  'medium.webd': 'WEB-DL',
  'medium.webrip': 'WEBRip',
  'medium.hdtv': 'HDTV',
  'medium.dvd': 'DVD',
  'medium.dvdr': 'DVD',
  'medium.bdrip': 'BDRip',
  'medium.other': '其他',
}
const sourceSiteNames = computed(() => {
  const names = new Set<string>()
  sourceSiteOptions.value.forEach((site) => names.add(site.name))
  items.value
    .map((item) => item.source_site)
    .filter(Boolean)
    .forEach((site) => names.add(site))
  return [...names]
})

function emptyRule(): Rule {
  return {
    id: 0,
    name: '',
    enabled: true,
    paused_reason: '',
    source_site: '',
    rss_url: '',
    downloader_id: '',
    save_path: '',
    download_url: '',
    auto_pause: false,
    auto_organize: true,
    min_size_gb: 0,
    max_size_gb: 0,
    types_json: '[]',
    media_json: '[]',
    tags_json: '["PT Nexus","自动发种"]',
    target_sites_json: '[]',
    pull_interval_minutes: 30,
    publish_interval_minutes: 0,
    publish_concurrency: 1,
    seed_retention_minutes: 0,
  }
}

const splitText = (value: string) =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
const normalizeSiteName = (site: unknown) => {
  if (typeof site === 'string') return site.trim()
  if (site && typeof site === 'object') {
    const record = site as Record<string, unknown>
    return String(record.name || record.site || record.nickname || '').trim()
  }
  return ''
}
const parseJSON = (value: string): string[] => {
  try {
    const parsed = JSON.parse(value || '[]')
    return Array.isArray(parsed) ? parsed.map(String) : []
  } catch {
    return []
  }
}

const fetchDownloaders = async () => {
  const response = await axios.get('/api/all_downloaders')
  downloaders.value = Array.isArray(response.data) ? response.data : []
}

const fetchSiteOptions = async () => {
  sitesLoading.value = true
  try {
    const [listRes, statusRes] = await Promise.all([
      axios.get('/api/sites_list'),
      axios.get('/api/sites/status'),
    ])
    const canPublishMap = new Map<string, boolean>()
    if (Array.isArray(statusRes.data)) {
      for (const site of statusRes.data) {
        const name = normalizeSiteName(site)
        if (name) canPublishMap.set(name, (site as Record<string, unknown>).can_publish !== false)
      }
    }
    const buildSites = (raw: unknown, defaultCanPublish: boolean) => {
      const rows = Array.isArray(raw) ? raw : []
      return rows
        .map((site) => {
          const name = normalizeSiteName(site)
          return name ? { name, can_publish: canPublishMap.get(name) ?? defaultCanPublish } : null
        })
        .filter((site): site is SiteItem => Boolean(site))
    }
    const listData = listRes.data
    if (Array.isArray(listData)) {
      const sites = buildSites(listData, true)
      sourceSiteOptions.value = sites
      targetSiteOptions.value = sites
    } else {
      sourceSiteOptions.value = buildSites(listData?.source_sites, true)
      targetSiteOptions.value = buildSites(listData?.target_sites, true)
    }
  } catch (error) {
    console.error('获取站点列表失败:', error)
  } finally {
    sitesLoading.value = false
  }
}

const fetchRules = async () => {
  rulesLoading.value = true
  try {
    const response = await axios.get('/api/auto-seed/rules')
    rules.value = response.data?.data || []
  } finally {
    rulesLoading.value = false
  }
}

const fetchItems = async () => {
  loading.value = true
  try {
    const response = await axios.get('/api/auto-seed/items', {
      params: { page: page.value, page_size: pageSize.value, ...filters.value },
    })
    items.value = response.data?.data || []
    total.value = Number(response.data?.total || 0)
  } finally {
    loading.value = false
  }
}

const fetchProgress = async () => {
  progressLoading.value = true
  try {
    const response = await axios.get('/api/auto-seed/progress', {
      params: { downloader_id: progressDownloader.value },
    })
    progressRows.value = response.data?.data || []
  } finally {
    progressLoading.value = false
  }
}

const handleSizeChange = () => {
  page.value = 1
  fetchItems()
}

const openRuleDialog = (rule?: Rule) => {
  editingRule.value = rule ? { ...rule } : emptyRule()
  ruleTagsText.value = parseJSON(editingRule.value.tags_json).join(',')
  ruleTargetSites.value = parseJSON(editingRule.value.target_sites_json)
  ruleDialogVisible.value = true
}

const saveRule = async () => {
  const payload = {
    ...editingRule.value,
    save_path: '',
    publish_interval_minutes: 0,
    publish_concurrency: 1,
    types_json: '[]',
    media_json: '[]',
    tags_json: JSON.stringify(splitText(ruleTagsText.value)),
    target_sites_json: JSON.stringify(ruleTargetSites.value),
  }
  const url = payload.id ? `/api/auto-seed/rules/${payload.id}` : '/api/auto-seed/rules'
  await axios[payload.id ? 'put' : 'post'](url, payload)
  ElMessage.success('规则已保存')
  ruleDialogVisible.value = false
  await fetchRules()
}

const toggleRuleEnabled = async (row: Rule, val: boolean) => {
  const prev = row.enabled
  row.enabled = val
  try {
    await axios.put(`/api/auto-seed/rules/${row.id}`, { ...row, enabled: val })
    ElMessage.success(val ? '规则已开启' : '规则已暂停')
  } catch {
    row.enabled = prev
    ElMessage.error('切换失败')
  }
}

const triggerRule = async (rule: Rule) => {
  await axios.post(`/api/auto-seed/rules/${rule.id}/trigger`)
  ElMessage.success('已触发拉取')
}

const deleteRule = async (rule: Rule) => {
  await ElMessageBox.confirm('确定删除这条自动发种规则吗？', '删除规则')
  await axios.delete(`/api/auto-seed/rules/${rule.id}`)
  ElMessage.success('规则已删除')
  await fetchRules()
}

const addManual = async () => {
  await axios.post('/api/auto-seed/items/manual', manualForm.value)
  ElMessage.success('已添加')
  manualDialogVisible.value = false
  manualForm.value = { torrent_url: '', source_site: '', downloader_id: '' }
  await fetchItems()
}

const openOrganizeDialog = (row: Item) => {
  if (!row.torrent_id || !(row.source_site || row.site_name)) {
    ElMessage.warning('缺少源站或种子 ID，无法打开完整整理页面')
    return
  }
  crossSeedStore.reset()
  const sourceName = row.source_site || row.site_name
  const siteIdentifier = row.site_name || sourceName
  const workingTorrent: WorkingTorrent = {
    name: row.name,
    save_path: row.save_path || '',
    size: Number(row.size_bytes || 0),
    size_formatted: formatGB(Number(row.size_bytes || 0)),
    progress: Number(row.progress || 0),
    state: row.downloaded || Number(row.progress || 0) >= 99.9 ? '已完成' : '下载中',
    sites: {
      [sourceName]: {
        comment: row.detail_url || row.torrent_url || row.torrent_id,
        torrentId: row.torrent_id,
        site: siteIdentifier,
        site_name: siteIdentifier,
        migration: 1,
      },
    },
    total_uploaded: 0,
    total_uploaded_formatted: '-',
    downloaderId: row.downloader_id,
    downloaderIds: row.downloader_id ? [row.downloader_id] : [],
    downloaderHash: row.downloader_hash || '',
  }
  crossSeedStore.setParams(workingTorrent)
  crossSeedStore.setSourceInfo({
    name: sourceName,
    site: siteIdentifier,
    torrentId: row.torrent_id,
  })
  crossSeedStore.setTaskId(`db_${row.torrent_id}_${siteIdentifier}`)
  organizingRow.value = row
  crossSeedPanelKey.value += 1
  crossSeedDialogVisible.value = true
}

const saveOrganize = async () => {
  if (!organizeForm.value.id) return
  await axios.put(`/api/auto-seed/items/${organizeForm.value.id}/organize`, {
    ...organizeForm.value,
    tags: splitText(organizeTagsText.value),
  })
  ElMessage.success('已整理')
  organizeDialogVisible.value = false
  await fetchItems()
}

const handleCrossSeedSeedInfoUpdated = async () => {
  const row = organizingRow.value
  if (!row?.id) return
  await axios.put(`/api/auto-seed/items/${row.id}/organize`, {})
  await fetchItems()
  await fetchProgress()
}

const closeCrossSeedOrganize = () => {
  crossSeedDialogVisible.value = false
  organizingRow.value = null
  crossSeedStore.reset()
}

const handleCrossSeedOrganizeComplete = async () => {
  await handleCrossSeedSeedInfoUpdated()
  closeCrossSeedOrganize()
}

const openPublishDialog = (rows: Item[]) => {
  publishRows.value = rows
  publishTargetSites.value = []
  publishDialogVisible.value = true
}

const pushItems = async (rows: Item[]) => {
  const candidates = rows.filter((row) => !isWorkflowStarted(row.status))
  if (!candidates.length) {
    ElMessage.warning('选中的记录都已经进入后续流程了')
    return
  }
  await ElMessageBox.confirm(
    `确定将 ${candidates.length} 条记录推送到下载器并进入后续流程吗？`,
    '推送种子',
  )
  await axios.post('/api/auto-seed/items/push', {
    ids: candidates.map((row) => row.id),
  })
  ElMessage.success(`已推送 ${candidates.length} 条`)
  await fetchItems()
  await fetchProgress()
}

const publishSelected = async () => {
  await axios.post('/api/auto-seed/items/publish', {
    ids: publishRows.value.map((row) => row.id),
    target_sites: publishTargetSites.value,
  })
  ElMessage.success('已加入发布队列')
  publishDialogVisible.value = false
  await fetchItems()
  await fetchProgress()
}

const deleteItems = async (rows: Item[]) => {
  await ElMessageBox.confirm('确定删除记录，并删除下载器里的种子和文件吗？', '删除种子')
  await axios.post('/api/auto-seed/items/delete', {
    ids: rows.map((row) => row.id),
    delete_files: true,
  })
  ElMessage.success('已删除')
  await fetchItems()
  await fetchProgress()
}

const openLogs = (row: Item) => {
  window.open(`/publish-logs?search=${encodeURIComponent(row.torrent_id || row.name)}`, '_blank')
}

const downloaderName = (id: string) =>
  downloaders.value.find((item) => item.id === id)?.name || id || '-'
const sourceDetailURL = (row: Item) => row.detail_url || row.torrent_url || ''
const formatGB = (bytes: number) =>
  bytes > 0 ? `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB` : '-'
const displayType = (value: string) => typeDisplayMap[(value || '').trim()] || value || '-'
const displayMedium = (value: string) => mediumDisplayMap[(value || '').trim()] || value || '-'
const isWorkflowStarted = (status: string) =>
  ['pushed', 'organized', 'published'].includes((status || '').trim())
const subtitlePreview = (value: string) => {
  const text = (value || '').trim()
  if (!text) return '-'
  const chars = Array.from(text)
  return chars.length > 20 ? `${chars.slice(0, 20).join('')}...` : text
}
const statusText = (status: string) =>
  ({
    pending: '未推送',
    pushed: '已推送',
    organized: '已整理',
    published: '已发布',
    rejected: '未推送',
  })[status] || status
const statusType = (status: string) =>
  ({
    pending: 'info',
    pushed: 'primary',
    organized: 'warning',
    published: 'success',
    rejected: 'danger',
  })[status] || 'info'
const progressGroup = (row: Item) => {
  if (row.status === 'published') return '已发布'
  if (row.downloaded || Number(row.progress) >= 99.9) return '待发布'
  return '已下载'
}

const publishResults = (row: Item): { label: string; url?: string }[] => {
  if (!row.publish_results_json) return []
  try {
    const raw = JSON.parse(row.publish_results_json)
    if (!Array.isArray(raw)) return []
    return raw.map((item) => {
      if (typeof item === 'string') return { label: item }
      const target = item?.target_site || item?.targetSite || item?.result?.target_site || '站点'
      const result = item?.result || {}
      const status =
        item?.status_text || result?.message || (result?.success ? '发布成功' : '已入队')
      const seedingTime = item?.seeding_time || elapsedSince(item?.updated_at)
      return {
        label: [target, status, seedingTime].filter(Boolean).join(' · '),
        url: item?.result_url || result?.result_url || result?.url,
      }
    })
  } catch {
    return []
  }
}

const elapsedSince = (value?: string): string => {
  if (!value) return ''
  const publishedAt = new Date(value.replace(' ', 'T'))
  const elapsed = Date.now() - publishedAt.getTime()
  if (!Number.isFinite(elapsed) || elapsed < 0) return ''
  const minutes = Math.floor(elapsed / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时`
  const days = Math.floor(hours / 24)
  return `${days}天${hours % 24 ? `${hours % 24}小时` : ''}`
}

const formatElapsedTime = (value?: string): string => elapsedSince(value) || '-'

watch(activeTab, (tab) => {
  if (tab === 'rules') fetchRules()
  if (tab === 'progress') fetchProgress()
})

onMounted(async () => {
  await Promise.all([fetchDownloaders(), fetchSiteOptions()])
  await Promise.all([fetchItems(), fetchRules()])
})
</script>

<style scoped>
.auto-seed-view {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.auto-tabs {
  flex: 1;
  min-height: 0;
}
.auto-tabs :deep(.el-tabs__content) {
  height: calc(100% - 48px);
}
.auto-tabs :deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.filter {
  width: 130px;
}
.search {
  width: 220px;
}
.spacer {
  flex: 1;
}
.table {
  flex: 1;
  min-height: 0;
}
.subtitle-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  vertical-align: bottom;
}
.pager {
  padding: 10px 14px;
  display: flex;
  justify-content: flex-end;
}
.tag {
  margin: 2px;
}
.publish-results {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.publish-result {
  font-size: 12px;
}
.inline-fields {
  display: flex;
  gap: 10px;
}
.unit {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
}
.switch-gap {
  margin-left: 18px;
}
.auto-cross-seed-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.45);
}
.auto-cross-seed-card {
  width: min(1280px, calc(100vw - 48px));
  height: min(860px, calc(100vh - 48px));
  display: flex;
  flex-direction: column;
}
.auto-cross-seed-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  padding: 0;
}
.auto-cross-seed-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
@media (max-width: 900px) {
  .toolbar {
    flex-wrap: wrap;
  }
  .filter,
  .search {
    width: 100%;
  }
}
</style>
