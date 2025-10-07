<template>
  <div class="home-container">

    <div class="warning-banner">
      <div class="warning-content">
        <img src="/favicon.ico" alt="PT Nexus Logo" class="warning-icon">
        <div class="text-container">
          <div class="marquee-container">
            <div class="marquee-content">
              <span class="warning-text">重要提示：PT Nexus 仅作为转种辅助工具，无法保证 100%
                准确性。转种前请务必仔细检查预览信息，确认参数正确无误。转种后请及时核实种子信息，如有错误请立即修改并反馈
                bug。因使用本工具产生的种子错误问题，需由使用者自行修改，如不修改则本工具不承担任何责任。</span>
              <span class="warning-text">重要提示：PT Nexus 仅作为转种辅助工具，无法保证 100%
                准确性。转种前请务必仔细检查预览信息，确认参数正确无误。转种后请及时核实种子信息，如有错误请立即修改并反馈
                bug。因使用本工具产生的种子错误问题，需由使用者自行修改，如不修改则本工具不承担任何责任。</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-card class="site-card">
      <template #header>
        <div class="site-card-header">
          <span class="site-card-title">站点支持列表</span>
          <div class="site-legend">
            <span class="legend-item">
              <span class="legend-dot legend-dot-success"></span>
              配置完整
            </span>
            <span class="legend-item">
              <span class="legend-dot legend-dot-primary"></span>
              配置不完整
            </span>
          </div>
        </div>
      </template>
      <div class="combined-legend">
        <span class="role-legend-item">
          <span class="role-tag role-source">源</span>
          源站点
        </span>
        <span class="role-legend-item">
          <span class="role-tag role-target">目标</span>
          目标站点
        </span>
        <span class="role-legend-item">
          <span class="role-tag role-both">源/目标</span>
          同时支持源和目标
        </span>
      </div>
      <div class="site-grid">
        <div v-for="site in combinedSitesList" :key="site.name" class="site-item" :class="getSiteClass(site)">
          <div class="site-content">
            <div class="site-name-container">
              <span class="site-name">{{ site.name }}</span>
            </div>
          </div>
          <div class="site-roles">
            <span v-if="site.is_source && site.is_target" class="role-tag role-both">源/目标</span>
            <span v-else-if="site.is_source" class="role-tag role-source">源</span>
            <span v-else-if="site.is_target" class="role-tag role-target">目标</span>
          </div>
        </div>
        <div v-if="!combinedSitesList.length" class="empty-placeholder">加载中...</div>
      </div>
    </el-card>

    <!-- 下载器信息展示 -->
    <el-row :gutter="24" style="margin-top: 24px;">
      <el-col :span="24">
        <h3 class="downloader-title">下载器状态</h3>
        <div class="downloader-grid">
          <el-card v-for="downloader in downloaderInfo" :key="downloader.name" class="downloader-card glass-card glass-rounded"
            :class="{ 'disabled': !downloader.enabled }">
            <div class="downloader-header">
              <div class="downloader-name">
                <el-tag :type="downloader.enabled ? 'success' : 'info'" effect="dark" size="small">
                  {{ downloader.type === 'qbittorrent' ? 'qB' : 'TR' }}
                </el-tag>
                {{ downloader.name }}
              </div>
              <el-tag :type="downloader.status === '已连接' ? 'success' : 'danger'" size="small">
                {{ downloader.status }}
              </el-tag>
            </div>

            <div class="downloader-details" v-if="downloader.enabled">
              <div class="detail-row">
                <span class="detail-label">版本:</span>
                <span class="detail-value">{{ downloader.details?.版本 || 'N/A' }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">今日上传:</span>
                <span class="detail-value">{{ downloader.details?.['今日上传量'] || '0 B' }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">今日下载:</span>
                <span class="detail-value">{{ downloader.details?.['今日下载量'] || '0 B' }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">累计上传:</span>
                <span class="detail-value">{{ downloader.details?.['累计上传量'] || '0 B' }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">累计下载:</span>
                <span class="detail-value">{{ downloader.details?.['累计下载量'] || '0 B' }}</span>
              </div>
            </div>

            <div class="downloader-disabled" v-else>
              下载器已禁用
            </div>
          </el-card>

          <div v-if="!downloaderInfo.length" class="empty-downloader-placeholder">
            暂无下载器配置
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElNotification } from 'element-plus'
import axios from 'axios'

interface SiteStatus {
  name: string;
  has_cookie: boolean;
  is_source: boolean;
  is_target: boolean;
}

interface DownloaderInfo {
  name: string;
  type: string;
  enabled: boolean;
  status: string;
  details: {
    [key: string]: string;
  } | null;
}

const allSitesStatus = ref<SiteStatus[]>([])
const downloaderInfo = ref<DownloaderInfo[]>([])

const sourceSitesList = computed(() => allSitesStatus.value.filter(s => s.is_source));
const targetSitesList = computed(() => allSitesStatus.value.filter(s => s.is_target));

// 合并站点列表，去除重复项
const combinedSitesList = computed(() => {
  const uniqueSites = new Map();

  // 添加源站点
  sourceSitesList.value.forEach(site => {
    uniqueSites.set(site.name, {
      ...site,
      is_source: true,
      is_target: false
    });
  });

  // 添加目标站点，如果已存在则更新属性
  targetSitesList.value.forEach(site => {
    if (uniqueSites.has(site.name)) {
      // 站点同时是源和目标，合并属性
      const existingSite = uniqueSites.get(site.name);
      uniqueSites.set(site.name, {
        ...existingSite,
        ...site,
        is_source: true,
        is_target: true,
        // 确保保留源站点的Cookie状态
        has_cookie: existingSite.has_cookie || site.has_cookie
      });
    } else {
      // 站点仅是目标
      uniqueSites.set(site.name, {
        ...site,
        is_source: false,
        is_target: true
      });
    }
  });

  // 转换为数组并排序（源站点在前，目标站点在后，同时支持的站点在最前）
  return Array.from(uniqueSites.values()).sort((a, b) => {
    // 同时支持源和目标的站点排在最前面
    if (a.is_source && a.is_target) return -1;
    if (b.is_source && b.is_target) return 1;

    // 源站点排在前面
    if (a.is_source && !b.is_source) return -1;
    if (!a.is_source && b.is_source) return 1;

    // 目标站点
    return 0;
  });
});

// 获取站点的CSS类
const getSiteClass = (site: SiteStatus) => {
  // 检查配置状态
  let isConfigured = false;
  if (site.is_source && !site.is_target) {
    // 仅源站点，检查Cookie
    isConfigured = site.has_cookie;
  } else if (!site.is_source && site.is_target) {
    // 仅目标站点，检查Cookie
    isConfigured = site.has_cookie;
  } else if (site.is_source && site.is_target) {
    // 同时是源和目标，需要Cookie
    isConfigured = site.has_cookie;
  }

  return {
    'site-configured': isConfigured,
    'site-unconfigured': !isConfigured
  };
};

// 获取站点的提示信息
const getSiteTooltip = (site: SiteStatus) => {
  let configStatus = '';
  if (site.is_source && !site.is_target) {
    // 仅源站点
    configStatus = site.has_cookie ? '已配置Cookie' : '未配置Cookie';
  } else if (!site.is_source && site.is_target) {
    // 仅目标站点
    configStatus = site.has_cookie ? '已配置Cookie' : '未配置Cookie';
  } else if (site.is_source && site.is_target) {
    // 同时是源和目标
    if (site.has_cookie) {
      configStatus = '已配置Cookie';
    } else {
      configStatus = '未配置Cookie';
    }
  }

  let roleStatus = '';
  if (site.is_source && site.is_target) {
    roleStatus = '（源/目标）';
  } else if (site.is_source) {
    roleStatus = '（源）';
  } else if (site.is_target) {
    roleStatus = '（目标）';
  }

  return `${configStatus}${roleStatus}`;
};

const fetchSitesStatus = async () => {
  try {
    const response = await axios.get('/api/sites/status');
    allSitesStatus.value = response.data;
  } catch (error) {
    ElNotification.error({ title: '错误', message: '无法从服务器获取站点状态列表' });
  }
}

const fetchDownloaderInfo = async () => {
  try {
    const response = await axios.get('/api/downloader_info');
    downloaderInfo.value = response.data;
  } catch (error) {
    console.error('获取下载器信息失败:', error);
    ElNotification.error({ title: '错误', message: '无法从服务器获取下载器信息' });
  }
}

onMounted(() => {
  fetchSitesStatus();
  fetchDownloaderInfo();

  // 每30秒自动刷新一次下载器信息
  setInterval(() => {
    fetchDownloaderInfo();
  }, 30000);
});
</script>

<style scoped>
@import '@/assets/styles/glass-morphism.scss';

.home-container {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.warning-banner {
  background: rgba(240, 244, 255, 0.7);
  backdrop-filter: blur(10px);
  border-radius: 12px;
  padding: 25px;
  margin-bottom: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  color: #333;
  overflow: hidden;
  border: 1px solid rgba(220, 223, 230, 0.5);
}

.warning-content {
  display: flex;
  align-items: center;
  gap: 20px;
}

.warning-icon {
  width: 70px;
  height: 70px;
  flex-shrink: 0;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
  animation: pulse 3s infinite;
}

@keyframes pulse {
  0% {
    transform: scale(1);
  }

  50% {
    transform: scale(1.2);
  }

  100% {
    transform: scale(1);
  }
}

.text-container {
  flex: 1;
  display: flex;
  align-items: center;
}

.marquee-container {
  overflow: hidden;
  white-space: nowrap;
  width: 100%;
}

.marquee-content {
  display: inline-block;
  animation: marquee 25s linear infinite;
  white-space: nowrap;
}

.warning-text {
  display: inline-block;
  margin: 0;
  color: red;
  font-size: 22px;
  line-height: 1.6;
  text-shadow: 0 1px 1px rgba(255, 255, 255, 0.8);
  padding-right: 50px;
  font-weight: 500;
}

@keyframes marquee {
  0% {
    transform: translateX(0);
  }

  100% {
    transform: translateX(-50%);
  }
}

/* 站点卡片样式 */
.site-card {
  background-color: rgba(255, 255, 255, 0.7) !important;
  backdrop-filter: blur(10px);
  border: 1px solid rgba(228, 231, 237, 0.5);
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  margin-bottom: 24px;
}

.site-card :deep(.el-card__header) {
  background-color: transparent;
  border-bottom: 1px solid rgba(228, 231, 237, 0.5);
}

.site-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;

}

.site-card :deep(.el-card__body) {
  padding: 0 10px 10px
}

.site-card-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.site-legend {
  display: flex;
  gap: 16px;
}

.legend-item {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #606266;
}

.legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}

.legend-dot-success {
  background-color: #67c23a;
}

.legend-dot-primary {
  background-color: #409eff;
}

.combined-legend {
  display: flex;
  gap: 24px;
  padding: 12px 0;
  border-bottom: 1px solid #e4e7ed;
}

.role-legend-item {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #606266;
}

.combined-legend .role-tag {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 500;
  margin-right: 4px;
}

.combined-legend .role-source {
  background-color: #ecf5ff;
  color: #409eff;
  border: 1px solid #b3d8ff;
}

.combined-legend .role-target {
  background-color: #f0f9ff;
  color: #67c23a;
  border: 1px solid #b3e0ff;
}

.combined-legend .role-both {
  background-color: #fdf6ec;
  color: #e6a23c;
  border: 1px solid #f5dab1;
}

.site-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 10px;
  padding: 12px 0;
  min-height: 180px;
}

.site-item {
  display: flex;
  align-items: center;
  padding: 8px 10px;
  border-radius: 4px;
  position: relative;
}

.site-item::before {
  content: "";
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 8px;
  flex-shrink: 0;
}

.site-configured {
  background-color: #f0f9ff;
  border: 1px solid #b3e0ff;
  color: #606266;
  font-weight: 500;
}

.site-configured::before {
  background-color: #67c23a;
}

.site-unconfigured {
  background-color: #f5f7fa;
  border: 1px solid #dcdfe6;
  color: #909399;
}

.site-unconfigured::before {
  background-color: #409eff;
}

.site-content {
  flex: 1;
  display: flex;
  align-items: center;
}

.site-name-container {
  flex: 1;
  min-width: 0;
}

.site-name {
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}

.site-roles {
  display: flex;
  gap: 3px;
  margin-left: 6px;
}

.role-tag {
  display: inline-block;
  padding: 0px 3px;
  border-radius: 2px;
  font-size: 11px;
  font-weight: 500;
}

.role-source {
  background-color: #ecf5ff;
  color: #409eff;
  border: 1px solid #b3d8ff;
}

.role-target {
  background-color: #f0f9ff;
  color: #67c23a;
  border: 1px solid #b3e0ff;
}

.role-both {
  background-color: #fdf6ec;
  color: #e6a23c;
  border: 1px solid #f5dab1;
}

.empty-placeholder {
  width: 100%;
  text-align: center;
  color: #909399;
  grid-column: 1 / -1;
  padding: 40px 0;
}

/* 下载器信息样式 */
.downloader-title {
  text-align: center;
  color: #303133;
  font-weight: 500;
  margin: 0 0 16px;
}

.downloader-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.downloader-card :deep(.el-card__body) {
  background-color: transparent;
}

.downloader-card.disabled {
  opacity: 0.6;
}

.downloader-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.downloader-name {
  font-size: 16px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 8px;
}

.downloader-details {
  padding: 8px 0;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 14px;
}

.detail-row:last-child {
  margin-bottom: 0;
}

.detail-label {
  color: #606266;
}

.detail-value {
  color: #303133;
  font-weight: 500;
}

.downloader-disabled {
  text-align: center;
  color: #909399;
  padding: 20px 0;
  font-size: 14px;
}

.empty-downloader-placeholder {
  width: 100%;
  text-align: center;
  color: #909399;
  padding: 40px 0;
  font-size: 14px;
}
</style>
