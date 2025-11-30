<template>
  <div v-if="dialogVisible" class="modal-overlay">
    <el-card class="site-data-card" shadow="always">
      <template #header>
        <div class="modal-header">
          <span>站点数据查看 - {{ torrentInfo?.name }}</span>
          <el-button type="danger" circle @click="closeDialog" plain>X</el-button>
        </div>
      </template>

      <div class="site-data-content" v-if="torrentInfo">
        <div class="torrent-info">
          <div class="torrent-name">
            <el-icon class="torrent-icon"><Document /></el-icon>
            <span class="name-text">{{ torrentInfo.name }}</span>
          </div>
          <div class="torrent-stats">
            <div class="stat-item stat-item--fixed">
              <el-icon class="stat-icon"><Folder /></el-icon>
              <span class="stat-label">大小</span>
              <span class="stat-value">{{ formatBytes(torrentInfo.size) }}</span>
            </div>
            <div class="stat-item stat-item--fixed">
              <el-icon class="stat-icon"><Upload /></el-icon>
              <span class="stat-label">上传</span>
              <span class="stat-value">{{
                torrentInfo.total_uploaded_formatted || formatBytes(torrentInfo.total_uploaded)
              }}</span>
            </div>
            <div class="stat-item stat-item--path">
              <el-icon class="stat-icon"><Location /></el-icon>
              <span class="stat-label">路径</span>
              <span class="stat-value" :title="torrentInfo.save_path">{{
                torrentInfo.save_path
              }}</span>
            </div>
            <div class="stat-item stat-item--fixed">
              <el-icon class="stat-icon"><Monitor /></el-icon>
              <span class="stat-label">下载器</span>
              <span class="stat-value">{{ getDownloaderDisplay(torrentInfo) }}</span>
            </div>
            <div class="stat-item stat-item--fixed">
              <el-icon class="stat-icon"><Share /></el-icon>
              <span class="stat-label">可转种</span>
              <span class="stat-value">{{ torrentInfo.target_sites_count || 0 }}个</span>
            </div>
          </div>
        </div>

        <div class="content-area">
          <div class="sites-container">
            <div class="sites-grid" v-if="sortedSites.length > 0">
              <div
                v-for="site in sortedSites"
                :key="site.siteName"
                class="site-card"
                :class="{ 'site-card--selected': isSiteSelected(site.siteName) }"
                @click="selectSite(site.siteName)"
              >
                <div class="site-tile">
                  <div class="site-content">
                    <div class="site-name-wrapper">
                      <div class="site-name-with-link">
                        <span class="site-name-text">{{ site.siteName }}</span>
                        <el-link
                          v-if="hasValidLink(site.comment)"
                          :href="getValidLink(site.comment)"
                          target="_blank"
                          :underline="false"
                          class="site-link-icon"
                          @click.stop
                        >
                          <el-icon size="10"><Link /></el-icon>
                        </el-link>
                      </div>
                    </div>
                    <div class="seeders-info">
                      <el-tag :type="site.seeders > 0 ? 'warning' : 'info'" size="small">
                        {{ site.seeders || 0 }}人做种
                      </el-tag>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="right-panel">
            <!-- 下载器列表 -->
            <div class="downloaders-section">
              <div class="section-title">下载器</div>
              <div class="downloaders-list">
                <div
                  v-for="downloader in availableDownloaders"
                  :key="downloader.id"
                  class="downloader-item"
                  :class="{ 'downloader-item--selected': selectedDownloader === downloader.id }"
                  @click="selectDownloader(downloader.id)"
                >
                  {{ downloader.name }}
                </div>
              </div>
            </div>

            <!-- 流程显示 -->
            <div class="flow-section">
              <div class="flow-cards">
                <div class="flow-card">
                  <div class="card-title">选中站点</div>
                  <div class="card-content">
                    <div v-if="!selectedSiteWithSeeders" class="empty-state">未选择</div>
                    <div v-else class="site-info">
                      <div class="site-name">{{ selectedSiteWithSeeders.siteName }}</div>
                      <el-tag
                        :type="selectedSiteWithSeeders.seeders > 0 ? 'warning' : 'info'"
                        size="small"
                      >
                        {{ selectedSiteWithSeeders.seeders }}人做种
                      </el-tag>
                    </div>
                  </div>
                </div>

                <div class="flow-divider">
                  <span>→</span>
                </div>

                <div class="flow-card">
                  <div class="card-title">当前下载器</div>
                  <div class="card-content">
                    <div class="downloader-info current">
                      {{ currentDownloader?.name || '未知' }}
                    </div>
                  </div>
                </div>

                <div class="flow-divider">
                  <span>→</span>
                </div>

                <div class="flow-card">
                  <div class="card-title">目标下载器</div>
                  <div class="card-content">
                    <div class="downloader-info target" :class="{ selected: selectedDownloader }">
                      {{
                        selectedDownloader
                          ? siteDataStore.getDownloaderName(selectedDownloader)
                          : '未选择'
                      }}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 转种流程进度条 -->
            <div class="progress-section">
              <div class="progress-title">转种流程</div>
              <div class="progress-bar-container">
                <el-progress
                  :percentage="progressPercentage"
                  :status="progressStatus"
                  :stroke-width="8"
                  :show-text="true"
                >
                  <template #default="{ percentage }">
                    <span class="progress-percentage">{{ percentage }}%</span>
                  </template>
                </el-progress>
                <div class="progress-steps-info">
                  <div class="step-info" :class="getStepInfoClass(1)">
                    <div class="step-indicator"></div>
                    <div class="step-details">
                      <div class="step-name">暂停种子</div>
                      <div class="step-desc">暂停下载器中选择的站点种子</div>
                    </div>
                  </div>
                  <div class="step-info" :class="getStepInfoClass(2)">
                    <div class="step-indicator"></div>
                    <div class="step-details">
                      <div class="step-name">导出种子</div>
                      <div class="step-desc">导出种子文件并添加到目标下载器</div>
                    </div>
                  </div>
                  <div class="step-info" :class="getStepInfoClass(3)">
                    <div class="step-indicator"></div>
                    <div class="step-details">
                      <div class="step-name">转移完成</div>
                      <div class="step-desc">种子已成功转移到目标下载器</div>
                    </div>
                  </div>
                </div>
                <div class="current-status" v-if="currentStep > 0 && currentStep <= 3">
                  {{ getCurrentStatus() }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <el-button
          type="success"
          @click="performTransfer"
          :disabled="!selectedSite || !selectedDownloader || currentStep > 0"
        >
          执行转种
        </el-button>
        <el-button type="primary" @click="closeDialog">关闭</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useSiteDataStore } from '@/stores/siteData'
import { Link, Document, Folder, Upload, Share, Location, Monitor } from '@element-plus/icons-vue'
import type { Torrent } from '@/types'

// Props
interface Props {
  torrent?: Torrent | null
}

const props = defineProps<Props>()

// Define emits
const emit = defineEmits<{
  refresh: []
}>()

// Store
const siteDataStore = useSiteDataStore()

// Dialog visibility
const dialogVisible = computed(() => siteDataStore.dialogVisible)
const torrentInfo = computed(() => siteDataStore.currentTorrent)

// Selected site (single selection)
const selectedSite = ref<string | null>(null)

// Selected downloader (single selection)
const selectedDownloader = ref<string | null>(null)

// 计算排序后的站点列表（按做种人数从高到低）
const sortedSites = computed(() => {
  if (!torrentInfo.value || !torrentInfo.value.sites) return []

  return Object.entries(torrentInfo.value.sites)
    .map(([siteName, siteData]) => ({ siteName, ...siteData }))
    .sort((a, b) => (b.seeders || 0) - (a.seeders || 0))
})

// Close dialog
const closeDialog = () => {
  resetProgress() // 关闭时重置进度
  siteDataStore.closeDialog()
}

// Format bytes
const formatBytes = (b: number | null): string => {
  if (b == null || b <= 0) return '0 B'
  const s = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(b) / Math.log(1024))
  return `${(b / Math.pow(1024, i)).toFixed(2)} ${s[i]}`
}

// Check if comment has valid link
const hasValidLink = (comment: string): boolean => {
  return Boolean(comment && (comment.startsWith('http') || /^\d+$/.test(comment)))
}

// Get valid link
const getValidLink = (comment: string): string => {
  if (comment.startsWith('http')) return comment

  // 这里需要 site_link_rules，但为了简化，暂时返回注释
  // 实际项目中应该从 store 或 props 获取这个数据
  return comment
}

// Get downloader display
const getDownloaderDisplay = (torrent: Torrent): string => {
  if (torrent.downloaderIds && torrent.downloaderIds.length > 0) {
    // 如果有多个下载器，显示第一个并加上数量
    if (torrent.downloaderIds.length === 1) {
      return siteDataStore.getDownloaderName(torrent.downloaderIds[0])
    } else {
      const firstName = siteDataStore.getDownloaderName(torrent.downloaderIds[0])
      return `${firstName} +${torrent.downloaderIds.length - 1}`
    }
  } else if (torrent.downloaderId) {
    return siteDataStore.getDownloaderName(torrent.downloaderId)
  } else {
    return '未知'
  }
}

// Select site (single selection)
const selectSite = (siteName: string) => {
  selectedSite.value = siteName
}

// Check if site is selected
const isSiteSelected = (siteName: string): boolean => {
  return selectedSite.value === siteName
}

// Get selected site with seeders info
const selectedSiteWithSeeders = computed(() => {
  if (!selectedSite.value || !torrentInfo.value || !torrentInfo.value.sites) return null

  const siteData = torrentInfo.value.sites[selectedSite.value]
  return {
    siteName: selectedSite.value,
    seeders: siteData?.seeders || 0,
    state: siteData?.state || '未知',
  }
})

// Select downloader (single selection)
const selectDownloader = (downloaderId: string) => {
  selectedDownloader.value = downloaderId
}

// Get all available downloaders
const availableDownloaders = computed(() => {
  return siteDataStore.getAllDownloaders()
})

// Get current downloader
const currentDownloader = computed(() => {
  if (!torrentInfo.value) return null

  const ids = torrentInfo.value.downloaderIds || []
  const singleId = torrentInfo.value.downloaderId

  if (ids.length > 0) {
    return {
      id: ids[0],
      name: siteDataStore.getDownloaderName(ids[0]),
    }
  } else if (singleId) {
    return {
      id: singleId,
      name: siteDataStore.getDownloaderName(singleId),
    }
  }

  return null
})

// Progress step state
const currentStep = ref(0) // 0: 未开始, 1: 暂停种子, 2: 导出种子, 3: 推送完成

// Progress percentage and status
const progressPercentage = computed(() => {
  switch (currentStep.value) {
    case 0:
      return 0
    case 1:
      return 33
    case 2:
      return 66
    case 3:
      return 100
    default:
      return 0
  }
})

const progressStatus = computed(() => {
  if (currentStep.value === 0) return undefined
  if (currentStep.value === 3) return 'success'
  return undefined
})

// Get step info class
const getStepInfoClass = (stepNumber: number) => {
  return {
    'step-info--pending': currentStep.value < stepNumber,
    'step-info--active': currentStep.value === stepNumber,
    'step-info--completed': currentStep.value > stepNumber,
  }
}

// Get current status text
const getCurrentStatus = () => {
  switch (currentStep.value) {
    case 1:
      return '正在暂停种子...'
    case 2:
      return '正在导出种子文件并添加...'
    case 3:
      return '转种完成！'
    default:
      return ''
  }
}

// Reset progress
const resetProgress = () => {
  currentStep.value = 0
}

// Perform actual torrent transfer
const performTransfer = async () => {
  if (!selectedSite.value || !selectedDownloader.value || !torrentInfo.value) {
    return
  }

  // 获取当前下载器ID
  const currentDownloaderId =
    torrentInfo.value.downloaderId ||
    (torrentInfo.value.downloaderIds && torrentInfo.value.downloaderIds.length > 0
      ? torrentInfo.value.downloaderIds[0]
      : null)

  if (!currentDownloaderId) {
    alert('无法获取当前下载器信息')
    return
  }

  resetProgress()

  try {
    // Step 1: 准备转移 - 查找并验证种子
    currentStep.value = 1

    const prepareResponse = await fetch('/api/torrent/transfer/prepare', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        source_downloader_id: currentDownloaderId,
        target_downloader_id: selectedDownloader.value,
        site_name: selectedSite.value,
        torrent_name: torrentInfo.value.name,
        torrent_size: torrentInfo.value.size,
        save_path: torrentInfo.value.save_path,
      }),
    })

    const prepareResult = await prepareResponse.json()

    if (!prepareResult.success) {
      // 如果有相似种子建议，显示给用户
      if (prepareResult.suggestions && prepareResult.suggestions.length > 0) {
        const suggestionList = prepareResult.suggestions
          .map((torrent: any, index: number) => {
            return `${index + 1}. ${torrent.name}\n   站点: ${torrent.sites}\n   大小: ${(torrent.size / 1024 ** 3).toFixed(2)} GB\n   路径: ${torrent.save_path}`
          })
          .join('\n\n')

        const userChoice = confirm(
          `准备转移失败: ${prepareResult.message}\n\n` +
            `找到 ${prepareResult.suggestion_count} 个相似的种子:\n\n${suggestionList}\n\n` +
            `是否要使用第一个相似种子继续转移？`,
        )

        if (userChoice && prepareResult.suggestions.length > 0) {
          // 使用第一个相似种子的信息重试
          const similarTorrent = prepareResult.suggestions[0]

          // 更新当前种子信息为相似种子的信息
          if (torrentInfo.value) {
            torrentInfo.value.sites = {
              [similarTorrent.sites]: torrentInfo.value.sites[selectedSite.value] || {},
            }
          }

          // 重新尝试转移，使用相似种子的实际参数
          await retryTransferWithSimilarTorrent(similarTorrent)
        } else {
          resetProgress()
        }
      } else {
        alert(`准备转移失败: ${prepareResult.message}`)
        resetProgress()
      }
      return
    }

    console.log(`找到 ${prepareResult.found_count} 个匹配的种子`)

    // Step 2: 执行转移 - 暂停、导出、添加
    currentStep.value = 2

    const executeResponse = await fetch('/api/torrent/transfer/execute', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        source_downloader_id: currentDownloaderId,
        target_downloader_id: selectedDownloader.value,
        site_name: selectedSite.value,
        torrent_name: torrentInfo.value.name,
        torrent_size: torrentInfo.value.size,
        save_path: torrentInfo.value.save_path,
      }),
    })

    const executeResult = await executeResponse.json()

    if (!executeResult.success) {
      alert(`转移失败: ${executeResult.message}`)
      resetProgress()
      return
    }

    // Step 3: 完成
    currentStep.value = 3

    console.log('转移完成:', executeResult)

    // 显示成功提示
    const methodText = executeResult.method === 'torrent_file' ? '种子文件' : '未知方式'
    console.log(`转移方式: ${methodText}`)

    // 触发父组件刷新种子数据
    emit('refresh')

    // 成功后保持状态，等待用户手动关闭
  } catch (error: any) {
    console.error('转移过程中发生错误:', error)
    alert(`转移过程中发生错误: ${error?.message || '未知错误'}`)
    resetProgress()
  }
}

// Retry transfer with similar torrent
const retryTransferWithSimilarTorrent = async (similarTorrent: any) => {
  if (!selectedDownloader.value || !torrentInfo.value) {
    return
  }

  // 获取当前下载器ID
  const currentDownloaderId =
    torrentInfo.value.downloaderId ||
    (torrentInfo.value.downloaderIds && torrentInfo.value.downloaderIds.length > 0
      ? torrentInfo.value.downloaderIds[0]
      : null)

  if (!currentDownloaderId) {
    alert('无法获取当前下载器信息')
    resetProgress()
    return
  }

  try {
    console.log('使用相似种子重试转移:', similarTorrent)

    // Step 2: 执行转移 - 暂停、导出、添加
    currentStep.value = 2

    const executeResponse = await fetch('/api/torrent/transfer/execute', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        source_downloader_id: currentDownloaderId,
        target_downloader_id: selectedDownloader.value,
        site_name: similarTorrent.sites,
        torrent_name: similarTorrent.name,
        torrent_size: similarTorrent.size,
        save_path: similarTorrent.save_path,
      }),
    })

    const executeResult = await executeResponse.json()

    if (!executeResult.success) {
      alert(`转移失败: ${executeResult.message}`)
      resetProgress()
      return
    }

    // Step 3: 完成
    currentStep.value = 3

    console.log('转移完成:', executeResult)

    // 显示成功提示
    const methodText = executeResult.method === 'torrent_file' ? '种子文件' : '未知方式'
    console.log(`转移方式: ${methodText}`)

    // 触发父组件刷新种子数据
    emit('refresh')

    // 成功后保持状态，等待用户手动关闭
  } catch (error: any) {
    console.error('重试转移过程中发生错误:', error)
    alert(`重试转移过程中发生错误: ${error?.message || '未知错误'}`)
    resetProgress()
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 2000;
}

.site-data-card {
  width: 90vw;
  max-width: 1200px;
  height: 90vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.site-data-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 10px;
  min-height: 0; /* 确保flex子元素可以收缩 */
  max-height: calc(90vh - 120px); /* 预留header和footer的空间 */
  overflow: hidden; /* 防止内容溢出 */
}

.torrent-info {
  flex-shrink: 0;
  margin-bottom: 20px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.torrent-name {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.torrent-icon {
  color: #3b82f6;
  font-size: 18px;
  flex-shrink: 0;
}

.name-text {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  line-height: 1.4;
  word-break: break-word;
}

.torrent-stats {
  display: grid;
  grid-template-columns: auto auto auto auto auto;
  gap: 12px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #f1f5f9;
  transition: all 0.2s ease;
}

.stat-item:hover {
  border-color: #3b82f6;
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.1);
  transform: translateY(-1px);
}

.stat-icon {
  color: #3b82f6;
  font-size: 16px;
  flex-shrink: 0;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
  white-space: nowrap;
}

.stat-value {
  font-size: 13px;
  color: #1e293b;
  font-weight: 600;
  margin-left: 8px;
}

.stat-item--fixed {
  flex: 0 0 auto;
  min-width: 100px;
}

.stat-item--path {
  flex: 0 1 auto;
}

.stat-item--path .stat-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-left: 8px;
  max-width: 300px;
}

.content-area {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.sites-container {
  flex: 0 0 50%;
  overflow-y: auto;
  padding-right: 20px;
  min-height: 0;
}

/* 自定义滚动条样式 */
.sites-container::-webkit-scrollbar {
  width: 8px;
}

.sites-container::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 4px;
}

.sites-container::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 4px;
}

.sites-container::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

.right-panel {
  flex: 1;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: 450px;
  align-items: center;
}

/* 下载器选择区域 */
.downloaders-section {
  border-bottom: 1px solid #d1d5db;
  padding-bottom: 16px;
  margin-bottom: 8px;
  width: 100%;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
  text-align: center;
}

.downloaders-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.downloader-item {
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid #d1d5db;
  background: #f9fafb;
  font-size: 12px;
  color: #374151;
  cursor: pointer;
  transition: all 0.2s ease;
}

.downloader-item:hover {
  border-color: #3b82f6;
  background: #f0f9ff;
}

.downloader-item--selected {
  border-color: #3b82f6;
  background: #3b82f6;
  color: #ffffff;
}

/* 流程显示区域 */
.flow-section {
  flex: 1;
  width: 100%;
  height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px 0;
  border-bottom: 1px solid #d1d5db;
}

.flow-cards {
  display: flex;
  align-items: stretch;
  gap: 12px;
  max-width: 600px;
  margin: 0 auto;
}

.flow-card {
  flex: 1;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  width: 75px;
  height: 75px;
}

.card-title {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
  margin-bottom: 8px;
  text-align: center;
}

.card-content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-state {
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
}

.site-info {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  text-align: center;
}

.site-name {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.downloader-info {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  text-align: center;
  padding: 8px 12px;
  border-radius: 4px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.downloader-info.current {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1e40af;
}

.downloader-info.target {
  background: #f9fafb;
  border-color: #e5e7eb;
  color: #374151;
}

.downloader-info.target.selected {
  background: #f0fdf4;
  border-color: #10b981;
  color: #047857;
}

.flow-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  font-size: 16px;
  font-weight: bold;
  flex-shrink: 0;
  padding: 0 4px;
}

/* 进度条样式 */
.progress-section {
  flex: 0 0 auto;
  width: 100%;
  padding: 16px;
}

.progress-title {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 16px;
  text-align: center;
}

.progress-bar-container {
  max-width: 500px;
  margin: 0 auto;
}

/* Element Plus Progress 自定义样式 */
:deep(.el-progress-bar__outer) {
  background-color: #f1f5f9;
  border-radius: 4px;
}

:deep(.el-progress-bar__inner) {
  background: linear-gradient(90deg, #3b82f6 0%, #2563eb 100%);
  border-radius: 4px;
  transition: all 0.3s ease;
}

:deep(.el-progress.is-success .el-progress-bar__inner) {
  background: linear-gradient(90deg, #10b981 0%, #059669 100%);
}

:deep(.el-progress__text) {
  color: #374151 !important;
  font-size: 12px !important;
  font-weight: 600 !important;
}

.progress-percentage {
  font-weight: 600;
  color: #374151;
}

.progress-steps-info {
  display: flex;
  justify-content: space-between;
  margin-top: 16px;
  gap: 12px;
}

.step-info {
  flex: 1;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  opacity: 0.6;
  transition: all 0.3s ease;
}

.step-indicator {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #d1d5db;
  flex-shrink: 0;
  margin-top: 4px;
  transition: all 0.3s ease;
}

.step-details {
  flex: 1;
  min-width: 0;
}

.step-name {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 2px;
  transition: all 0.3s ease;
}

.step-desc {
  font-size: 10px;
  color: #9ca3af;
  line-height: 1.3;
  transition: all 0.3s ease;
}

.current-status {
  text-align: center;
  margin-top: 12px;
  font-size: 12px;
  font-weight: 500;
  color: #3b82f6;
}

/* 步骤状态样式 */
.step-info--active {
  opacity: 1;
}

.step-info--active .step-indicator {
  background: #3b82f6;
  width: 14px;
  height: 14px;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
}

.step-info--active .step-name {
  color: #3b82f6;
}

.step-info--active .step-desc {
  color: #6b7280;
}

.step-info--completed {
  opacity: 1;
}

.step-info--completed .step-indicator {
  background: #10b981;
}

.step-info--completed .step-name {
  color: #10b981;
}

.step-info--completed .step-desc {
  color: #6b7280;
}

.sites-grid {
  display: grid;
  grid-template-columns: repeat(6, auto);
  justify-content: start;
  gap: 12px;
  margin-top: 20px;
  min-height: 0; /* 确保网格容器可以收缩 */
  max-width: fit-content; /* 让网格只占用需要的宽度，右侧留出空间 */
}

.site-card {
  height: auto;
  cursor: pointer;
}

.site-tile {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 2px;
  background: #fafbfc;
  transition: all 0.3s ease;
  cursor: pointer;
  width: 75px;
  height: 75px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  text-align: center;
}

.site-tile:hover {
  border-color: #b3d8ff;
  box-shadow: 0 2px 8px 0 rgba(179, 216, 255, 0.12);
  transform: translateY(-1px);
}

.site-card--selected .site-tile {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 2px 8px 0 rgba(59, 130, 246, 0.2);
}

.site-card--selected .site-tile:hover {
  border-color: #2563eb;
  transform: translateY(-1px);
}

.site-content {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  gap: 3px;
}

.site-name-wrapper {
  width: 100%;
  text-align: center;
}

.site-name-with-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
}

.site-name-link {
  font-weight: 600;
  font-size: 14px;
  color: #409eff;
  text-decoration: none;
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.1;
}

.site-name-link:hover {
  color: #337ecc;
}

.site-link-icon {
  color: #f56565;
  text-decoration: none;
  display: flex;
  align-items: center;
}

.site-link-icon:hover {
  color: #e53e3e;
}

.info-item {
  margin-right: 15px;
  font-size: 13px;
  color: #606266;
}

.info-item:last-child {
  margin-right: 0;
}

.site-name-text {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.1;
}

.modal-footer {
  padding: 15px 20px 0;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: flex-end;
  flex-shrink: 0; /* 确保footer不会被压缩 */
}

:deep(.el-card) {
  display: flex;
  flex-direction: column;
}

:deep(.el-card__body) {
  padding: 15px;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden; /* 防止内容溢出 */
}

:deep(.el-descriptions__body) {
  background-color: #fafafa;
}

/* 中等屏幕适配 */
@media (max-width: 1024px) {
  .sites-container {
    flex: 0 0 500px;
    max-width: 55%;
  }

  .right-panel {
    min-width: 350px;
  }
}

.flow-section {
  padding: 12px 0;
}

.flow-cards {
  gap: 8px;
}

.flow-card {
  padding: 12px;
}

.card-title {
  font-size: 11px;
  margin-bottom: 6px;
}

.site-name,
.downloader-info {
  font-size: 12px;
  padding: 6px 8px;
}

.flow-divider {
  font-size: 14px;
}

.progress-section {
  padding: 12px;
}

.progress-title {
  font-size: 13px;
  margin-bottom: 12px;
}

.progress-steps-info {
  gap: 8px;
}

.step-name {
  font-size: 11px;
}

.step-desc {
  font-size: 9px;
}

.current-status {
  font-size: 11px;
  margin-top: 10px;
}
</style>
