<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import logoUrl from '../../../logo.png'
import { setLocale } from '../i18n'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { locale, t } = useI18n()
const initials = computed(() => auth.admin?.username.slice(0, 2).toUpperCase() ?? 'AD')

function toggleLocale(): void {
  setLocale(locale.value === 'en-US' ? 'zh-CN' : 'en-US')
}

async function logout(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div class="admin-shell">
    <aside class="sidebar">
      <div class="sidebar-brand"><span class="brand-mark brand-logo small"><img :src="logoUrl" alt="Agent4API" /></span><strong>Agent4API</strong></div>
      <nav>
        <RouterLink v-if="auth.admin?.role === 'admin'" to="/admin" class="nav-link">⌂ <span>{{ t('nav.overview') }}</span></RouterLink>
        <template v-if="auth.admin?.role === 'admin'">
          <span class="nav-section">{{ t('nav.system') }}</span>
          <RouterLink to="/admin/settings" class="nav-link">⚙ <span>{{ t('settings.nav') }}</span></RouterLink>
          <RouterLink to="/admin/users" class="nav-link">♙ <span>{{ t('users.nav') }}</span></RouterLink>
          <RouterLink to="/admin/providers" class="nav-link">◈ <span>{{ t('overview.providers') }}</span></RouterLink>
        </template>
        <span class="nav-section">{{ t('nav.build') }}</span>
        <RouterLink to="/admin/sources" class="nav-link">⇄ <span>{{ t('overview.sources') }}</span></RouterLink>
        <RouterLink to="/admin/tools" class="nav-link">⌁ <span>{{ t('overview.tools') }}</span></RouterLink>
        <RouterLink to="/admin/skills" class="nav-link">✦ <span>{{ t('overview.skills') }}</span></RouterLink>
        <RouterLink to="/admin/agent" class="nav-link">◉ <span>{{ t('agent.nav') }}</span></RouterLink>
        <RouterLink to="/chat" class="nav-link">◫ <span>{{ t('chat.title') }}</span></RouterLink>
      </nav>
      <div class="sidebar-footer">
        <button class="text-button" @click="toggleLocale">◎ {{ t('nav.language') }}</button>
        <button class="text-button" @click="logout">↪ {{ t('nav.logout') }}</button>
      </div>
    </aside>
    <section class="admin-main">
      <header class="topbar">
        <div><span class="status-dot"></span> {{ t('status.ready') }}</div>
        <div class="admin-identity"><span>{{ auth.admin?.username }}</span><b>{{ initials }}</b></div>
      </header>
      <RouterView />
    </section>
  </div>
</template>
