<template>
  <div class="local-query-container">
    <!-- 顶部操作区 -->
    <el-card class="action-card">
      <div class="action-content">
        <div class="action-text">
          <h3>本地文件扫描</h3>
          <p>此功能将扫描数据库中所有种子的保存路径，找出本地已删除的文件或未被任务引用的孤立文件。</p>
        </div>
        <div class="action-controls">
          <el-select v-model="selectedPath" clearable placeholder="选择路径(可选)" style="width: 300px; margin-right: 12px"
            filterable>
            <el-option-group v-for="downloader in downloadersWithPaths" :key="downloader.id"
              :label="downloader.name">
              <el-option v-for="pathItem in downloader.paths" :key="pathItem.path" :label="pathItem.path"
                :value="pathItem.path">
                <span>{{ pathItem.path }}</span>
                <span style="float: right; color: #8492a6; font-size: 13px">({{ pathItem.count }})</span>
              </el-option>
            </el-option-group>
          </el-select>
          <el-button type="primary" size="large" @click="startScan" :loading="scanning" :icon="Search">
            {{ selectedPath ? '扫描选定路径' : '扫描全部路径' }}
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 扫描结果统计 -->
    <el-card v-if="scanResult" class="summary-card">
      <template #header>
        <div class="card-header">
          <span>扫描结果统计</span>
        </div>
      </template>
      <el-row :gutter="20">
        <el-col :span="4">
          <el-statistic title="总种子数" :value="scanResult.scan_summary.total_torrents" />
        </el-col>
        <el-col :span="5">
          <el-statistic title="本地文件/目录数" :value="scanResult.scan_summary.total_local_items" />
        </el-col>
        <el-col :span="5">
          <el-statistic title="缺失文件" :value="scanResult.scan_summary.missing_count" value-style="color: #f56c6c" />
        </el-col>
        <el-col :span="5">
          <el-statistic title="孤立文件" :value="scanResult.scan_summary.orphaned_count" value-style="color: #e6a23c" />
        </el-col>
        <el-col :span="5">
          <el-statistic title="正常做种" :value="scanResult.scan_summary.synced_count" value-style="color: #67c23a" />
        </el-col>
      </el-row>
    </el-card>

    <!-- 结果详情 Tabs -->
    <el-card v-if="scanResult" class="result-card">
      <el-tabs v-model="activeTab">
        <!-- Tab 1: 缺失文件 -->
        <el-tab-pane name="missing">
          <template #label>
            <span>
              缺失文件
              <el-badge v-if="scanResult.scan_summary.missing_count > 0" :value="scanResult.scan_summary.missing_count"
                class="tab-badge" type="danger" />
            </span>
          </template>
          <el-alert type="warning" :closable="false" style="margin-bottom: 16px" show-icon>
            以下种子在下载器中存在任务，但对应的本地文件或文件夹不存在。
          </el-alert>
          <el-table :data="scanResult.missing_files || []" stripe style="width: 100%"
            :default-sort="{ prop: 'size', order: 'descending' }">
            <el-table-column prop="name" label="种子名称" min-width="300" show-overflow-tooltip />
            <el-table-column prop="save_path" label="保存路径" width="200" show-overflow-tooltip />
            <el-table-column prop="size" label="大小" width="120" sortable>
              <template #default="{ row }">
                {{ formatBytes(row.size) }}
              </template>
            </el-table-column>
            <el-table-column prop="downloader_name" label="下载器" width="150" />
          </el-table>
        </el-tab-pane>

        <!-- Tab 2: 孤立文件 -->
        <el-tab-pane label="孤立文件" name="orphaned">
          <template #label>
            <span>
              孤立文件
              <el-badge v-if="scanResult.scan_summary.orphaned_count > 0"
                :value="scanResult.scan_summary.orphaned_count" class="tab-badge" type="warning" />
            </span>
          </template>
          <el-alert type="info" :closable="false" style="margin-bottom: 16px" show-icon>
            以下文件存在于本地但没有对应的种子任务，您可以考虑删除它们或为其添加任务。
          </el-alert>
          <el-table :data="scanResult.orphaned_files || []" stripe style="width: 100%"
            :default-sort="{ prop: 'size', order: 'descending' }">
            <el-table-column prop="name" label="文件/文件夹名称" min-width="300" show-overflow-tooltip />
            <el-table-column prop="path" label="所在路径" width="200" show-overflow-tooltip />
            <el-table-column prop="size" label="大小" width="120" sortable>
              <template #default="{ row }">
                {{ row.size ? formatBytes(row.size) : '未知' }}
              </template>
            </el-table-column>
            <el-table-column prop="is_file" label="类型" width="100">
              <template #default="{ row }">
                <el-tag :type="row.is_file ? 'success' : 'info'" size="small">
                  {{ row.is_file ? '文件' : '文件夹' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="full_path" label="完整路径" min-width="300" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>

        <!-- Tab 3: 正常做种 -->
        <el-tab-pane label="正常做种" name="synced">
          <template #label>
            <span>
              正常做种
              <el-badge v-if="scanResult.scan_summary.synced_count > 0" :value="scanResult.scan_summary.synced_count"
                class="tab-badge" type="success" />
            </span>
          </template>
          <el-table :data="scanResult.synced_torrents || []" stripe style="width: 100%">
            <el-table-column prop="name" label="名称" min-width="300" show-overflow-tooltip />
            <el-table-column prop="path" label="路径" width="250" show-overflow-tooltip />
            <el-table-column prop="torrents_count" label="任务数" width="100" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.torrents_count > 1" type="warning" size="small">
                  {{ row.torrents_count }}
                </el-tag>
                <span v-else>{{ row.torrents_count }}</span>
              </template>
            </el-table-column>
            <el-table-column label="下载器" min-width="200">
              <template #default="{ row }">
                <el-tag v-for="(name, index) in row.downloader_names" :key="index" size="small"
                  style="margin-right: 4px">
                  {{ name }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- Tab 4: 重复分析 -->
        <el-tab-pane label="重复分析" name="duplicates">
          <!-- 此部分功能独立，保持不变 -->
        </el-tab-pane>

      </el-tabs>
    </el-card>

    <el-empty v-if="!scanResult && !scanning" description="点击“开始扫描全部”按钮进行本地文件检查" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { ElMessage, ElMessageBox, ElBadge } from 'element-plus';
import { Search } from '@element-plus/icons-vue';
import axios from 'axios';

const scanning = ref(false);
const activeTab = ref('missing');
const scanResult = ref<any>(null);
const selectedPath = ref<string>('');
const downloadersWithPaths = ref<any[]>([]);

// 获取下载器路径列表
const fetchDownloadersWithPaths = async () => {
  try {
    const res = await axios.get('/api/local_query/downloaders_with_paths');
    downloadersWithPaths.value = res.data.downloaders || [];
  } catch (error) {
    console.error('获取路径列表失败:', error);
  }
};

// 页面加载时获取路径列表
onMounted(() => {
  fetchDownloadersWithPaths();
});

// --- API 调用 ---
const startScan = async () => {
  scanning.value = true;
  scanResult.value = null;
  try {
    const url = selectedPath.value
      ? `/api/local_query/scan?path=${encodeURIComponent(selectedPath.value)}`
      : '/api/local_query/scan';
    const res = await axios.post(url);
    scanResult.value = res.data;
    ElMessage.success('扫描完成！');
  } catch (error) {
    console.error('扫描失败:', error);
    ElMessage.error('扫描失败，请查看控制台获取详情');
  } finally {
    scanning.value = false;
  }
};

// --- 工具函数 ---
const formatBytes = (bytes: number | null | undefined): string => {
  if (bytes === null || bytes === undefined || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};
</script>

<style scoped>
.local-query-container {
  padding: 20px;
  height: 100%;
  overflow: auto;
}

.action-card {
  margin-bottom: 20px;
}

.action-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.action-controls {
  display: flex;
  align-items: center;
}

.action-text h3 {
  margin: 0 0 8px 0;
}

.action-text p {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.summary-card,
.result-card {
  margin-bottom: 20px;
}

.result-card {
  min-height: 500px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tab-badge {
  margin-left: 8px;
  vertical-align: middle;
}

:deep(.el-statistic__content) {
  font-size: 24px;
  font-weight: bold;
}

:deep(.el-statistic__head) {
  margin-bottom: 8px;
  color: #909399;
}

.downloader-tags {
  display: flex;
  flex-wrap: wrap;
}

.downloader-badge {
  margin-left: 5px;
  transform: translateY(-2px);
}
</style>
