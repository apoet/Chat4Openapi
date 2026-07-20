<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

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
      <div class="sidebar-brand"><span class="brand-mark small">CA</span><strong>ChatAPI</strong></div>
      <nav>
        <RouterLink to="/admin" class="nav-link">⌂ <span>{{ t('nav.overview') }}</span></RouterLink>
        <span class="nav-section">BUILD</span>
        <a class="nav-link disabled">◈ <span>{{ t('overview.providers') }}</span></a>
        <a class="nav-link disabled">⇄ <span>{{ t('overview.sources') }}</span></a>
        <a class="nav-link disabled">⌁ <span>{{ t('overview.tools') }}</span></a>
        <a class="nav-link disabled">✦ <span>{{ t('overview.skills') }}</span></a>
      </nav>
      <div class="sidebar-footer">
        <button class="text-button" @click="toggleLocale">◎ {{ t('nav.language') }}</button>
        <button class="text-button" @click="logout">↪ {{ t('nav.logout') }}</button>
      </div>
    </aside>
    <section class="admin-main">
      <header class="topbar">
        <div><span class="status-dot"></span> System ready</div>
        <div class="admin-identity"><span>{{ auth.admin?.username }}</span><b>{{ initials }}</b></div>
      </header>
      <RouterView />
    </section>
  </div>
</template>
