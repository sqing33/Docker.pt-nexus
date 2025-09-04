<template>
  <div class="user-settings-container">
    <div class="user-settings-wrapper">
      <el-card class="user-settings-card">
        <template #header>
          <div class="card-header">
            <el-icon class="header-icon"><User /></el-icon>
            <h3>用户设置</h3>
            <el-tag type="warning" v-if="mustChange" size="small">首次登录需修改</el-tag>
          </div>
        </template>

        <el-form :model="form" label-position="top" class="settings-form" @keyup.enter="onSubmit">
          <el-form-item label="用户名">
            <el-input 
              v-model="form.username" 
              placeholder="请输入用户名"
              size="large"
              clearable
            >
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          
          <el-form-item label="当前密码" required>
            <el-input 
              v-model="form.old_password" 
              type="password" 
              placeholder="请输入当前密码"
              size="large"
              show-password
            >
              <template #prefix>
                <el-icon><Lock /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          
          <el-form-item label="新密码">
            <el-input 
              v-model="form.password" 
              type="password" 
              placeholder="至少 6 位"
              size="large"
              show-password
            >
              <template #prefix>
                <el-icon><Key /></el-icon>
              </template>
            </el-input>
            <div class="password-hint">
              <el-text type="info" size="small">留空表示不修改密码</el-text>
            </div>
          </el-form-item>
          
          <div class="form-actions">
            <el-button 
              type="primary" 
              :loading="loading" 
              @click="onSubmit"
              size="large"
              class="action-button"
            >
              保存设置
            </el-button>
            <el-button 
              @click="resetForm"
              size="large"
              class="action-button"
            >
              重置
            </el-button>
          </div>
        </el-form>

        <el-alert
          v-if="mustChange"
          title="为确保安全，请立即设置新用户名与密码。"
          type="warning"
          show-icon
          :closable="false"
          class="security-alert"
        />
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { User, Lock, Key } from '@element-plus/icons-vue'

const loading = ref(false)
const currentUsername = ref('admin')
const mustChange = ref(false)
const form = ref({ old_password: '', username: '', password: '' })

onMounted(async () => {
  try {
    const res = await axios.get('/api/auth/status')
    if (res.data?.success) {
      currentUsername.value = res.data.username || 'admin'
      mustChange.value = !!res.data.must_change_password
      form.value.username = currentUsername.value
    }
  } catch {}
})

const resetForm = () => {
  form.value = { old_password: '', username: currentUsername.value, password: '' }
}

const onSubmit = async () => {
  if (loading.value) return
  if (!form.value.old_password) {
    ElMessage.warning('请填写当前密码')
    return
  }
  if (!form.value.username && !form.value.password) {
    ElMessage.warning('请输入新用户名或新密码')
    return
  }
  if (form.value.username && form.value.username.trim().length < 3) {
    ElMessage.warning('用户名至少 3 个字符')
    return
  }
  if (form.value.password && form.value.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  loading.value = true
  try {
    const payload: any = { old_password: form.value.old_password }
    if (form.value.username) payload.username = form.value.username
    if (form.value.password) payload.password = form.value.password
    const res = await axios.post('/api/auth/change_password', payload)
    if (res.data?.success) {
      ElMessage.success('保存成功，请重新登录')
      localStorage.removeItem('token')
      window.location.href = '/login'
    } else {
      ElMessage.error(res.data?.message || '保存失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '保存失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.user-settings-container {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  min-height: 100%;
  padding: 40px 20px;
  background-color: var(--el-bg-color-page);
}

.user-settings-wrapper {
  width: 100%;
  max-width: 500px;
}

.user-settings-card {
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
  border: 1px solid var(--el-border-color);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon {
  font-size: 20px;
  color: var(--el-color-primary);
}

.card-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.settings-form {
  margin-top: 20px;
}

:deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--el-text-color-regular);
  font-size: 14px;
  margin-bottom: 8px;
}

:deep(.el-input__inner) {
  height: 42px;
  font-size: 14px;
}

:deep(.el-input-group__prepend) {
  background-color: var(--el-fill-color-light);
}

.password-hint {
  margin-top: 6px;
}

.form-actions {
  display: flex;
  gap: 16px;
  margin-top: 32px;
}

.action-button {
  flex: 1;
  height: 42px;
  font-size: 14px;
}

.security-alert {
  margin-top: 24px;
}

@media (max-width: 768px) {
  .user-settings-container {
    padding: 20px 16px;
  }
  
  .form-actions {
    flex-direction: column;
  }
  
  .action-button {
    width: 100%;
  }
}
</style>