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
      
      // 检查是否使用临时密码
      const isTempPassword = res.data.is_temp_password || res.data.must_change_password
      
      if (isTempPassword) {
        // 使用临时密码登录，显示警告并引导修改密码
        ElMessage.warning({
          message: '您正在使用临时密码，为了账户安全，请立即修改密码！',
          duration: 5000,
          showClose: true
        })
        
        // 延迟跳转到设置页面
        await nextTick()
        await router.replace('/settings')
        
        // 再次提示用户修改密码
        setTimeout(() => {
          ElMessage.warning({
            message: '请在"账户"标签页中修改您的用户名和密码',
            duration: 8000,
            showClose: true
          })
        }, 500)
      } else {
        // 正常登录，跳转到原目标页面
        ElMessage.success('登录成功')
        
        const redirect = (route.query.redirect as string) || '/'
        console.log('登录成功，准备跳转到:', redirect)
        
        await nextTick()
        await router.replace(redirect)
        
        // 额外确保跳转成功
        setTimeout(() => {
          if (router.currentRoute.value.path === '/login') {
            console.warn('仍在登录页，强制跳转到首页')
            router.replace('/')
          }
        }, 100)
      }
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
