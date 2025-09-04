// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'

const whiteList: string[] = ['/login', '/first_setup']

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'info',
      component: () => import('../views/InfoView.vue'),
    },
    {
      path: '/torrents',
      name: 'torrents',
      component: () => import('../views/TorrentsView.vue'),
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
      redirect: '/settings/downloader',
      children: [
        {
          path: 'downloader',
          name: 'settings-downloader',
          component: () => import('../components/settings/DownloaderSettings.vue'),
        },
        {
          path: 'user',
          name: 'settings-user',
          component: () => import('../components/settings/UserSettings.vue'),
        },
        {
          path: 'cookie',
          name: 'settings-cookie',
          component: () => import('../components/settings/SitesSettings.vue'),
        },
        {
          path: 'crossseed',
          name: 'settings-crossseed',
          component: () => import('../components/settings/CrossSeedSettings.vue'),
        },
      ],
    },
    {
      path: '/cross_seed',
      name: 'cross_seed',
      component: () => import('../views/CrossSeedView.vue'),
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
    },
    {
      path: '/first_setup',
      name: 'first_setup',
      component: () => import('../views/FirstSetupView.vue'),
    },
  ],
})

// 简单路由守卫：当开启后端认证时，未携带 token 的请求会被 401 拦截
router.beforeEach(async (to, _from, next) => {
  const token = localStorage.getItem('token')
  if (whiteList.includes(to.path)) return next()
  if (!token) {
    // 未登录：若需要强制修改则直接去 first_setup，否则去 login
    try {
      const st = await fetch('/api/auth/status')
      if (st.ok) {
        const js = await st.json()
        if (js?.must_change_password) return next('/first_setup')
      }
    } catch {}
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }
  return next()
})

export default router
