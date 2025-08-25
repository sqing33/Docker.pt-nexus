// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'

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
    },
    {
      path: '/cross_seed',
      name: 'cross_seed',
      component: () => import('../views/CrossSeedView.vue'),
    },
  ],
})

export default router
