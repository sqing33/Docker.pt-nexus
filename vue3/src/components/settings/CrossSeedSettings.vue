<template>
  <div class="settings-container">
    <div class="page-header">
      <h2>转种设置</h2>
      <p class="page-description">配置转种过程中的图床、网络代理和默认下载器设置</p>
    </div>
    
    <div class="settings-grid">
      <!-- 图床设置卡片 -->
      <div class="settings-card">
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon"><Picture /></el-icon>
            <h3>图床设置</h3>
          </div>
          <el-button type="primary" @click="saveCrossSeedSettings" :loading="savingCrossSeed" size="small">
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
              <div v-if="settingsForm.image_hoster === 'agsv'" key="agsv" class="credential-section">
                <div class="credential-header">
                  <el-icon class="credential-icon"><Lock /></el-icon>
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
                <el-text type="info" size="small">当前图床无需额外配置</el-text>
              </div>
            </transition>
          </el-form>
        </div>
      </div>
      
      <!-- 网络代理设置卡片 -->
      <div class="settings-card">
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon"><Connection /></el-icon>
            <h3>网络代理设置</h3>
          </div>
          <el-button type="primary" @click="saveProxySettings" :loading="savingProxy" size="small">
            保存
          </el-button>
        </div>
        
        <div class="card-content">
          <el-form :model="settingsForm" label-position="top" class="settings-form">
            <el-form-item label="代理地址" class="form-item">
              <el-input 
                v-model="settingsForm.proxy_url" 
                placeholder="例如：http://127.0.0.1:7890"
              >
                <template #prepend>
                  <el-icon size="12"><Link /></el-icon>
                </template>
              </el-input>
            </el-form-item>
            
            <div class="form-spacer"></div>
            
            <el-text type="warning" size="small" class="proxy-hint">
              <el-icon size="12"><Warning /></el-icon>
              代理设置将应用于所有支持代理的站点请求
            </el-text>
          </el-form>
        </div>
      </div>
      
      <!-- 默认下载器设置卡片 -->
      <div class="settings-card">
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon"><Document /></el-icon>
            <h3>默认下载器设置</h3>
          </div>
          <el-button type="primary" @click="saveCrossSeedSettings" :loading="savingCrossSeed" size="small">
            保存
          </el-button>
        </div>
        
        <div class="card-content">
          <el-form :model="settingsForm" label-position="top" class="settings-form">
            <el-form-item label="默认下载器" class="form-item">
              <el-select v-model="settingsForm.default_downloader" placeholder="请选择默认下载器" clearable>
                <el-option 
                  label="使用源种子所在的下载器" 
                  value=""
                />
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
              <el-icon size="12"><InfoFilled /></el-icon>
              转种完成后自动将种子添加到指定的下载器。选择"使用源种子所在的下载器"或不选择任何下载器，则添加到源种子所在的下载器。
            </el-text>
          </el-form>
        </div>
      </div>
      
      <!-- 占位卡片2 -->
      <div class="settings-card">
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon"><Setting /></el-icon>
            <h3>功能扩展</h3>
          </div>
        </div>
        
        <div class="card-content placeholder-content">
          <el-icon class="placeholder-icon"><Setting /></el-icon>
          <p class="placeholder-text">功能扩展中</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue';
import { ElMessage } from 'element-plus';
import axios from 'axios';
import { Picture, Connection, Lock, Link, Warning, Document, Setting, InfoFilled } from '@element-plus/icons-vue'

interface CrossSeedSettings {
  image_hoster: string;
  agsv_email?: string;
  agsv_password?: string;
  proxy_url?: string;
  default_downloader?: string;
}

const loading = ref(true);
const savingCrossSeed = ref(false);
const savingProxy = ref(false);

const settingsForm = reactive<CrossSeedSettings>({
  image_hoster: 'pixhost',
  agsv_email: '',
  agsv_password: '',
  proxy_url: '',
  default_downloader: '',
});

const imageHosterOptions = [
  { value: 'pixhost', label: 'Pixhost (免费)' },
  { value: 'agsv', label: '末日图床 (需账号)' },
];

// 添加下载器选项状态
const downloaderOptions = ref<{id: string, name: string}[]>([]);

const fetchSettings = async () => {
  loading.value = true;
  try {
    // 获取所有设置
    const response = await axios.get('/api/settings');
    const config = response.data;
    
    // 获取转种设置
    Object.assign(settingsForm, config.cross_seed || {});
    
    // 获取网络代理设置
    if (config.network && config.network.proxy_url && !settingsForm.proxy_url) {
      settingsForm.proxy_url = config.network.proxy_url;
    }
    
    // 获取下载器列表
    const downloaderResponse = await axios.get('/api/downloaders_list');
    downloaderOptions.value = downloaderResponse.data;
  } catch (error) {
    ElMessage.error('无法加载转种设置。');
  } finally {
    loading.value = false;
  }
};

const saveCrossSeedSettings = async () => {
  savingCrossSeed.value = true;
  try {
    // 保存转种设置
    const crossSeedSettings = {
      image_hoster: settingsForm.image_hoster,
      agsv_email: settingsForm.agsv_email,
      agsv_password: settingsForm.agsv_password,
      default_downloader: settingsForm.default_downloader
    };
    
    await axios.post('/api/settings/cross_seed', crossSeedSettings);
    ElMessage.success('转种设置已保存！');
  } catch (error: any) {
    const errorMessage = error.response?.data?.error || '保存失败。';
    ElMessage.error(errorMessage);
  } finally {
    savingCrossSeed.value = false;
  }
};

const saveProxySettings = async () => {
  savingProxy.value = true;
  try {
    // 保存网络代理设置
    if (settingsForm.proxy_url !== undefined) {
      const networkSettings = {
        network: {
          proxy_url: settingsForm.proxy_url
        }
      };
      await axios.post('/api/settings', networkSettings);
      ElMessage.success('代理设置已保存！');
    }
  } catch (error: any) {
    const errorMessage = error.response?.data?.error || '保存失败。';
    ElMessage.error(errorMessage);
  } finally {
    savingProxy.value = false;
  }
};

onMounted(() => {
  fetchSettings();
});
</script>

<style scoped>
.settings-container {
  padding: 20px;
  background-color: var(--el-bg-color-page);
  min-height: 100%;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  font-size: 20px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 4px;
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
  background: var(--el-bg-color);
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid var(--el-border-color);
  background-color: var(--el-fill-color-light);
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

.credential-section {
  background: var(--el-fill-color-light);
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