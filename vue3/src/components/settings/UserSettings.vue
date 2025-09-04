<template>
  <div class="user-settings">
    <el-card class="card">
      <template #header>
        <div class="card-header">
          <span>用户管理</span>
          <el-tag type="warning" v-if="mustChange">首次登录需修改</el-tag>
        </div>
      </template>

      <el-form :model="form" label-width="100px" class="form" @keyup.enter="onSubmit">
        <el-form-item label="当前密码" required>
          <el-input v-model="form.old_password" type="password" placeholder="请输入当前密码" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入新用户名" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="form.password" type="password" placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="onSubmit">保存</el-button>
          <el-button @click="resetForm">重置</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="mustChange"
        title="为确保安全，请立即设置新用户名与密码。"
        type="warning"
        show-icon
        :closable="false"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

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
  form.value = { old_password: '', username: '', password: '' }
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
.user-settings { padding: 16px; }
.card { max-width: 560px; }
.card-header { display: flex; align-items: center; gap: 8px; }
.form { margin-top: 8px; }
</style>


