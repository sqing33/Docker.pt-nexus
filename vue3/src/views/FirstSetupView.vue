<template>
  <div class="setup-page">
    <el-card class="setup-card">
      <h2 class="title">首次使用：请设置管理员账号</h2>
      <el-form :model="form" label-width="100px" @keyup.enter="onSubmit">
        <el-form-item label="新用户名">
          <el-input v-model="form.username" placeholder="admin" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="form.password" type="password" placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="onSubmit">保存并登录</el-button>
        </el-form-item>
      </el-form>
      <p class="tip">系统默认用户名为 admin。首次启动会生成一次性临时密码，请尽快修改。</p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

const router = useRouter()
const loading = ref(false)
const form = ref({ username: 'admin', password: '' })

onMounted(async () => {
  try {
    const res = await axios.get('/api/auth/status')
    if (res.data?.success && !res.data.must_change_password) {
      router.replace('/')
    }
  } catch {}
})

const onSubmit = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const res = await axios.post('/api/auth/change_password', form.value)
    if (res.data?.success) {
      ElMessage.success('修改成功，请使用新账号登录')
      localStorage.removeItem('token')
      router.replace('/login')
    } else {
      ElMessage.error(res.data?.message || '修改失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '修改失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.setup-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
}
.setup-card { width: 480px; }
.title { margin: 0 0 16px; text-align: center; }
.tip { color: #999; font-size: 12px; margin-top: 12px; text-align: center; }
</style>


