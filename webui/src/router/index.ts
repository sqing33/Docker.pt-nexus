// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'

const whiteList: string[] = ['/login']

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
    },
    {
      path: '/info',
      name: 'info',
      component: () => import('../views/InfoView.vue'),
    },
    {
      path: '/torrents',
      name: 'torrents',
      component: () => import('../views/TorrentsView.vue'),
    },
    {
      path: '/data',
      name: 'data',
      component: () => import('../views/CrossSeedDataView.vue'),
    },
    {
      path: '/sites',
      name: 'sites',
      component: () => import('../views/SitesView.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue'),
      redirect: '/settings/general',
      children: [
        {
          path: 'general',
          name: 'settings-general',
          component: () => import('../components/settings/GeneralSettings.vue'),
        },
        {
          path: 'downloader',
          name: 'settings-downloader',
          component: () => import('../components/settings/DownloaderSettings.vue'),
        },
        {
          path: 'cookie',
          name: 'settings-cookie',
          component: () => import('../components/settings/SitesSettings.vue'),
        },
      ],
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
    },
      ],
})

// 简单路由守卫：当开启后端认证时，未携带 token 的请求会被 401 拦截
router.beforeEach(async (to, _from, next) => {
  const token = localStorage.getItem('token')
  if (whiteList.includes(to.path)) return next()
  if (!token) {
    // 未登录：直接去 login
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }
  return next()
})

export default router
