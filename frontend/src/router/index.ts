import { createRouter, createWebHistory, type Router } from 'vue-router'

import { useAuthStore } from '../stores/auth'

export function createAppRouter(): Router {
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', redirect: '/chat' },
      { path: '/chat', name: 'chat', component: () => import('../views/ChatView.vue') },
      { path: '/setup', name: 'setup', component: () => import('../views/SetupView.vue') },
      { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
      {
        path: '/embed/:publicId',
        name: 'embed-chat',
        component: () => import('../views/EmbedChatView.vue'),
        meta: { publicEmbed: true },
      },
      {
        path: '/admin',
        component: () => import('../layouts/AdminLayout.vue'),
        meta: { requiresAdmin: true },
        children: [
          { path: '', name: 'overview', component: () => import('../views/OverviewView.vue') },
          { path: 'sources', name: 'sources', component: () => import('../views/ApiSourcesView.vue') },
          { path: 'tools', name: 'tools', component: () => import('../views/ToolsView.vue') },
          { path: 'tool-auth', name: 'tool-auth', component: () => import('../views/ToolAuthView.vue') },
          { path: 'providers', name: 'providers', component: () => import('../views/ProvidersView.vue') },
          { path: 'skills', name: 'skills', component: () => import('../views/SkillsView.vue') },
          { path: 'agent', name: 'agent', component: () => import('../views/AgentView.vue') },
          { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
        ],
      },
    ],
  })

  router.beforeEach(async (to) => {
    if (to.meta.publicEmbed) return true
    const auth = useAuthStore()
    if (auth.initialized === null) await auth.loadState()
    if (!auth.initialized && to.name !== 'setup') return { name: 'setup' }
    if (auth.initialized && to.name === 'setup') {
      return auth.admin ? { name: 'overview' } : { name: 'login' }
    }
    if (to.meta.requiresAdmin && !auth.admin) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    if (to.name === 'login' && auth.admin) return { name: 'overview' }
    return true
  })

  return router
}
