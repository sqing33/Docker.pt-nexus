<template>
  <div class="home-container">
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

const allSitesStatus = ref<SiteStatus[]>([])

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

onMounted(() => {
  fetchSitesStatus();
});
</script>

<style scoped>
.home-container {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
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
  border-radius: 6px;
  padding: 16px;
  background-color: #fafafa;
  min-height: 200px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-content: flex-start;
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
</style>