<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2 class="title">登录 PT Nexus</h2>
      <el-form :model="form" @keyup.enter="onSubmit" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" autocomplete="current-password" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="onSubmit">登录</el-button>
        </el-form-item>
      </el-form>
      <p class="tip">如未开启认证，可直接访问页面。</p>
    </el-card>
  </div>
  
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import axios from 'axios'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const form = ref({ username: '', password: '' })

const onSubmit = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const res = await axios.post('/api/auth/login', form.value)
    if (res.data?.success && res.data?.token) {
      localStorage.setItem('token', res.data.token)
      ElMessage.success('登录成功')
      
      // 修复登录跳转问题：确保正确处理重定向
      const redirect = (route.query.redirect as string) || '/'
      console.log('登录成功，准备跳转到:', redirect)
      
      // 使用 nextTick 确保 DOM 更新后再跳转
      await nextTick()
      await router.replace(redirect)
      
      // 额外确保跳转成功
      setTimeout(() => {
        if (router.currentRoute.value.path === '/login') {
          console.warn('仍在登录页，强制跳转到首页')
          router.replace('/')
        }
      }, 100)
    } else {
      ElMessage.error(res.data?.message || '登录失败')
    }
  } catch (e: any) {
    const msg = e?.response?.data?.message || '登录失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
}
.login-card { width: 420px; }
.title { margin: 0 0 16px; text-align: center; }
.tip { color: #999; font-size: 12px; margin-top: 12px; text-align: center; }
</style>
