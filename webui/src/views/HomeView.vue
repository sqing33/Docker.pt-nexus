<template>
  <div class="home-container">
    <div class="warning-banner">
      <div class="warning-content">
        <img src="/favicon.ico" alt="PT Nexus Logo" class="warning-icon" />
        <div class="text-container">
          <div class="marquee-container">
            <div class="marquee-content">
              <span class="warning-text"
                >重要提示：PT Nexus 仅作为转种辅助工具，无法保证 100%
                准确性。转种前请务必仔细检查预览信息，确认参数正确无误。转种后请及时核实种子信息，如有错误请立即修改并反馈
                bug。因使用本工具产生的种子错误问题，需由使用者自行修改，如不修改则本工具不承担任何责任。</span
              >
              <span class="warning-text"
                >重要提示：PT Nexus 仅作为转种辅助工具，无法保证 100%
                准确性。转种前请务必仔细检查预览信息，确认参数正确无误。转种后请及时核实种子信息，如有错误请立即修改并反馈
                bug。因使用本工具产生的种子错误问题，需由使用者自行修改，如不修改则本工具不承担任何责任。</span
              >
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 转种规则说明（下载器卡片上方） -->
    <el-card class="rules-card glass-card glass-rounded">
      <div class="rules-header">
        <div class="rules-title">
          <span>转种限制说明</span>
          <el-tag type="warning" effect="dark" size="small">必读</el-tag>
        </div>
        <el-tag type="info" effect="plain" size="small">请自行确认后重试</el-tag>
      </div>
      <ul class="rules-list">
        <li>
          <el-tag type="danger" size="small" effect="dark">禁转</el-tag>
          <el-tag type="danger" size="small" effect="dark">限转</el-tag>
          <el-tag type="danger" size="small" effect="dark">分集</el-tag>
          一律不可转。
          <div class="rules-sub">限转：不自动检测源站是否取消限转，需自行确认后重新获取种子信息。</div>
          <div class="rules-sub">分集：部分站点不允许转分集，且断种率较高。</div>
        </li>
        <li>
          <el-tag type="warning" size="small" effect="dark">IP 网段限制</el-tag>
          同网段下载器同时最多 <b>15</b> 个在上传种子可转；超过不可转。
          <div class="rules-sub">不计入：添加超 <b>24h</b>、做种人数 <b>&gt; 5</b>；盒子不受限。</div>
          <div class="rules-sub">
            <el-tag type="warning" size="small" effect="dark">大小限制</el-tag>
            一站多种<strong>批量</strong>转种不允许 &lt; <b>1GB</b>；一种多站<strong>单个</strong>转种不受限。
          </div>
        </li>
      </ul>
    </el-card>

    <!-- 下载器信息展示 -->
    <el-row :gutter="24" style="margin-top: 24px">
      <el-col :span="24">
        <div class="downloader-grid">
          <el-card
            v-for="downloader in downloaderInfo"
            :key="downloader.name"
            class="downloader-card glass-card glass-rounded"
            :class="{ disabled: !downloader.enabled }"
          >
            <div class="downloader-header">
              <div class="downloader-name">
                <el-tag :type="downloader.enabled ? 'success' : 'info'" effect="dark" size="small">
                  {{ downloader.type === 'qbittorrent' ? 'QB' : 'TR' }}
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

            <div class="downloader-disabled" v-else>下载器已禁用</div>
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
import { ref, onMounted } from 'vue'
import { ElNotification } from 'element-plus'
import axios from 'axios'

interface DownloaderInfo {
  name: string
  type: string
  enabled: boolean
  status: string
  details: {
    [key: string]: string
  } | null
}

const downloaderInfo = ref<DownloaderInfo[]>([])

const fetchDownloaderInfo = async () => {
  try {
    const response = await axios.get('/api/downloader_info')
    downloaderInfo.value = response.data
  } catch (error) {
    console.error('获取下载器信息失败:', error)
    ElNotification.error({ title: '错误', message: '无法从服务器获取下载器信息' })
  }
}

onMounted(() => {
  fetchDownloaderInfo()

  // 每30秒自动刷新一次下载器信息
  setInterval(() => {
    fetchDownloaderInfo()
  }, 30000)
})
</script>

<style scoped>
.home-container {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
  height: 100vh;
  overflow-y: auto;
  box-sizing: border-box;
}

/* 隐藏滚动条但保持滚动功能 */
.home-container::-webkit-scrollbar {
  display: none;
}

.home-container {
  -ms-overflow-style: none; /* IE and Edge */
  scrollbar-width: none; /* Firefox */
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

.rules-card {
  margin-bottom: 24px;
}

.rules-card :deep(.el-card__body) {
  padding: 12px 16px;
}

.rules-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.rules-title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  color: #303133;
}

.rules-list {
  margin: 0;
  padding-left: 18px;
  color: #303133;
  line-height: 1.55;
  font-size: 13px;
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px 14px;
}

.rules-list li {
  margin: 0;
}

.rules-list :deep(.el-tag) {
  margin-right: 8px;
}

.rules-sub {
  margin-left: 4px;
  color: #606266;
  font-size: 12px;
}

@media (min-width: 980px) {
  .rules-list {
    grid-template-columns: 1fr 1fr;
  }
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
