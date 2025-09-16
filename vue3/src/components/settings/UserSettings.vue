<template>
  <div class="settings-container">
    <div class="page-header">
      <h2>用户设置</h2>
      <p class="page-description">修改登录用户名和密码</p>
    </div>

    <div class="settings-grid">
      <!-- 用户信息设置卡片 -->
      <div class="settings-card">
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon"><User /></el-icon>
            <h3>账户信息</h3>
            <el-tag type="warning" v-if="mustChange" size="small">首次登录需修改</el-tag>
          </div>
          <el-button
            type="primary"
            :loading="loading"
            @click="onSubmit"
            size="small"
          >
            保存
          </el-button>
        </div>

        <div class="card-content">
          <el-form :model="form" label-position="top" class="settings-form">
            <el-form-item label="用户名" class="form-item">
              <el-input
                v-model="form.username"
                placeholder="请输入用户名"
                clearable
              >
                <template #prefix>
                  <el-icon><User /></el-icon>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item label="当前密码" required class="form-item">
              <el-input
                v-model="form.old_password"
                type="password"
                placeholder="请输入当前密码"
                show-password
              >
                <template #prefix>
                  <el-icon><Lock /></el-icon>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item label="新密码" class="form-item">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="至少 6 位"
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

            <div class="form-spacer"></div>

            <el-text v-if="mustChange" type="warning" size="small" class="security-hint">
              <el-icon size="12"><Warning /></el-icon>
              为确保安全，请立即设置新用户名与密码
            </el-text>
          </el-form>
        </div>
      </div>

      <!-- IYUU设置卡片 -->
      <div class="settings-card">
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon"><Setting /></el-icon>
            <h3>IYUU设置</h3>
          </div>
          <el-button
            type="primary"
            :loading="savingIyuu"
            @click="saveIyuuToken"
            size="small"
          >
            保存
          </el-button>
        </div>

        <div class="card-content">
          <el-form :model="iyuuForm" label-position="top" class="settings-form">
            <el-form-item label="IYUU Token" class="form-item">
              <el-input
                v-model="iyuuForm.token"
                type="password"
                placeholder="请输入IYUU Token"
                show-password
              >
                <template #prefix>
                  <el-icon><Key /></el-icon>
                </template>
              </el-input>
            </el-form-item>

            <div class="form-spacer"></div>

            <el-text type="info" size="small" class="proxy-hint">
              <el-icon size="12"><InfoFilled /></el-icon>
              用于与IYUU平台进行数据同步和通信的身份验证令牌
            </el-text>
          </el-form>
        </div>
      </div>

      <!-- 占位卡片2 -->
      <div class="settings-card">
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon"><Connection /></el-icon>
            <h3>认证设置</h3>
          </div>
        </div>

        <div class="card-content placeholder-content">
          <el-icon class="placeholder-icon"><Connection /></el-icon>
          <p class="placeholder-text">功能扩展中</p>
        </div>
      </div>

      <!-- 占位卡片3 -->
      <div class="settings-card">
        <div class="card-header">
          <div class="header-content">
            <el-icon class="header-icon"><Document /></el-icon>
            <h3>权限管理</h3>
          </div>
        </div>

        <div class="card-content placeholder-content">
          <el-icon class="placeholder-icon"><Document /></el-icon>
          <p class="placeholder-text">功能扩展中</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { User, Lock, Key, Warning, Setting, Connection, Document, InfoFilled } from '@element-plus/icons-vue'

const loading = ref(false)
const savingIyuu = ref(false)
const currentUsername = ref('admin')
const mustChange = ref(false)
const form = ref({ old_password: '', username: '', password: '' })

// 添加 iyuu 设置相关的响应式数据
const iyuuForm = reactive({
  token: ''
})

// 保存实际的 token 值，用于在保存时判断是否需要更新
const actualIyuuToken = ref('')

onMounted(async () => {
  try {
    const res = await axios.get('/api/auth/status')
    if (res.data?.success) {
      currentUsername.value = res.data.username || 'admin'
      mustChange.value = !!res.data.must_change_password
      form.value.username = currentUsername.value
    }

    // 获取 iyuu token 设置
    const settingsRes = await axios.get('/api/settings')
    if (settingsRes.data?.iyuu_token) {
      // 保存实际的 token 值
      actualIyuuToken.value = settingsRes.data.iyuu_token
      // 显示为隐藏状态（用星号代替）
      iyuuForm.token = settingsRes.data.iyuu_token ? '********' : ''
    }
  } catch {}
})

const resetForm = () => {
  form.value = { old_password: '', username: currentUsername.value, password: '' }
}

// 添加保存 iyuu token 的函数
const saveIyuuToken = async () => {
  savingIyuu.value = true
  try {
    // 保存 iyuu token 设置
    // 如果显示的是星号，表示没有更改，不需要更新token
    if (iyuuForm.token === '********') {
      ElMessage.success('IYUU Token 已保存！')
      savingIyuu.value = false
      return
    }

    const settings = {
      iyuu_token: iyuuForm.token
    }

    await axios.post('/api/settings', settings)
    // 保存成功后，显示星号而不是明文
    if (iyuuForm.token) {
      iyuuForm.token = '********'
    } else {
      iyuuForm.token = ''
    }
    ElMessage.success('IYUU Token 已保存！')
  } catch (error: any) {
    const errorMessage = error.response?.data?.error || '保存失败。'
    ElMessage.error(errorMessage)
  } finally {
    savingIyuu.value = false
  }
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

.form-item :deep(.el-form-item__label) {
  font-weight: 500;
  color: var(--el-text-color-regular);
  font-size: 13px;
  margin-bottom: 6px;
  height: auto;
}

.password-hint {
  margin-top: 6px;
}

.form-spacer {
  flex: 1;
}

.security-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 1.4;
  margin-top: auto;
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

:deep(.el-input__inner) {
  height: 36px;
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