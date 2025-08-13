// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import InfoView from '../views/InfoView.vue'
import TorrentsView from '../views/TorrentsView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'info',
      component: InfoView,
    },
    {
      path: '/torrents',
      name: 'torrents',
      component: TorrentsView,
    },
  ],
})

export default router
