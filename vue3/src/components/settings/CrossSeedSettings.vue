<template>
  <div class="settings-container">
    <el-card class="settings-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>转种设置</span>
        </div>
      </template>

      <el-form :model="settingsForm" label-width="120px" v-loading="loading">
        <el-form-item label="截图图床">
          <el-select v-model="settingsForm.image_hoster" placeholder="请选择图床服务">
            <el-option v-for="item in imageHosterOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <div class="form-item-help">
            选择在转种时，自动生成的视频截图所要上传到的图床。
          </div>
        </el-form-item>

        <!-- 当选择末日图床时，显示登录凭据输入框 -->
        <div v-if="settingsForm.image_hoster === 'agsv'" class="sub-settings">
          <el-form-item label="末日图床邮箱">
            <el-input v-model="settingsForm.agsv_email" placeholder="请输入您在末日图床注册的邮箱" />
          </el-form-item>
          <el-form-item label="末日图床密码">
            <el-input v-model="settingsForm.agsv_password" type="password" placeholder="请输入您的末日图床登录密码"
              show-password />
            <div class="form-item-help">
              您的密码将明文保存在 <code>data/config.json</code> 文件中，请注意安全。
            </div>
          </el-form-item>
        </div>

        <el-form-item>
          <el-button type="primary" @click="handleSave" :loading="saving">
            保存设置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue';
import { ElMessage } from 'element-plus';
import axios from 'axios';

interface CrossSeedSettings {
  image_hoster: string;
  agsv_email?: string;
  agsv_password?: string;
}

const loading = ref(true);
const saving = ref(false);

const settingsForm = reactive<CrossSeedSettings>({
  image_hoster: 'pixhost',
  agsv_email: '',
  agsv_password: '',
});

const imageHosterOptions = [
  { value: 'pixhost', label: 'Pixhost' },
  { value: 'agsv', label: '末日图床' },
];

const fetchSettings = async () => {
  loading.value = true;
  try {
    const response = await axios.get('/api/settings/cross_seed');
    Object.assign(settingsForm, response.data);
  } catch (error) {
    ElMessage.error('无法加载转种设置。');
  } finally {
    loading.value = false;
  }
};

const handleSave = async () => {
  saving.value = true;
  try {
    await axios.post('/api/settings/cross_seed', settingsForm);
    ElMessage.success('设置已成功保存！');
  } catch (error: any) {
    const errorMessage = error.response?.data?.error || '保存失败。';
    ElMessage.error(errorMessage);
  } finally {
    saving.value = false;
  }
};

onMounted(() => {
  fetchSettings();
});
</script>

<style scoped>
/* ... (样式保持不变) ... */
.settings-container {
  padding: 20px;
}

.settings-card {
  max-width: 800px;
  margin: 0 auto;
  border: 1px solid #e4e7ed;
}

.card-header {
  font-weight: bold;
  font-size: 1.1rem;
}

.form-item-help {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 4px;
}

.sub-settings {
  padding-left: 30px;
  border-left: 2px solid #f0f2f5;
  margin: 10px 0 20px 90px;
}

.form-item-help code {
  background-color: #f0f2f5;
  padding: 2px 4px;
  border-radius: 4px;
  font-family: monospace;
}
</style>
