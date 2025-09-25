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

    <el-row :gutter="24">
      <el-col :span="12">
        <h3 class="site-list-title">支持的源站点</h3>
        <p class="site-list-tip">
          <el-tag type="success" size="small" effect="dark" style="margin-right: 5px;">绿色</el-tag>
          表示已配置Cookie<br>
          <el-tag type="primary" size="small" effect="dark" style="margin-right: 5px;">蓝色</el-tag>
          表示站点支持但未配置Cookie
        </p>
        <div class="site-list-box">
          <el-tag v-for="site in sourceSitesList" :key="site.name" class="site-tag"
            :type="site.has_cookie ? 'success' : 'primary'">
            {{ site.name }}
          </el-tag>
          <div v-if="!sourceSitesList.length" class="empty-placeholder">加载中...</div>
        </div>
      </el-col>
      <el-col :span="12">
        <h3 class="site-list-title">支持的目标站点</h3>
        <p class="site-list-tip">
          <el-tag type="success" size="small" effect="dark" style="margin-right: 5px;">绿色</el-tag>
          表示Cookie/Passkey齐全<br>
          <el-tag type="primary" size="small" effect="dark" style="margin-right: 5px;">蓝色</el-tag>
          表示站点支持但未配置Cookie/Passkey
        </p>
        <div class="site-list-box">
          <el-tag v-for="site in targetSitesList" :key="site.name" class="site-tag"
            :type="site.has_cookie && site.has_passkey ? 'success' : 'primary'">
            {{ site.name }}
          </el-tag>
          <div v-if="!targetSitesList.length" class="empty-placeholder">加载中...</div>
        </div>
      </el-col>
    </el-row>

    <!-- 下载器信息展示 -->
    <el-row :gutter="24" style="margin-top: 24px;">
      <el-col :span="24">
        <h3 class="downloader-title">下载器状态</h3>
        <div class="downloader-grid">
          <el-card v-for="downloader in downloaderInfo" :key="downloader.name" class="downloader-card"
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
  has_passkey: boolean;
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
.home-container {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.warning-banner {
  background: linear-gradient(135deg, #f0f4ff 0%, #e6eeff 100%);
  border-radius: 12px;
  padding: 25px;
  margin-bottom: 24px;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.05);
  color: #333;
  overflow: hidden;
  border: 1px solid #dcdfe6;
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

.site-list-title {
  text-align: center;
  color: #303133;
  font-weight: 500;
  margin: 0 0 8px;
}

.site-list-tip {
  font-size: 12px;
  color: #909399;
  text-align: center;
  margin: 0 0 12px;
}

.site-list-box {
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  padding: 20px;
  background: linear-gradient(135deg, #fafbff 0%, #f0f4ff 100%);
  min-height: 200px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-content: flex-start;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.03);
}

.site-tag {
  font-size: 14px;
  height: 28px;
  line-height: 26px;
}

.empty-placeholder {
  width: 100%;
  text-align: center;
  color: #909399;
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

.downloader-card {
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  transition: all 0.3s;
}

.downloader-card:hover {
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
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
