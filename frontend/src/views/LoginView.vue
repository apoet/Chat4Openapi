<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import logoUrl from '../../../logo.png'
import { ApiError, request } from '../api/client'
import type { AdminPasswordResetIssued } from '../api/contracts'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const submitting = ref(false)
const requestingReset = ref(false)
const errorCode = ref<string | null>(null)
const githubStars = ref<number | null>(null)
let githubRequest: AbortController | null = null

async function loadGithubStars(): Promise<void> {
  githubRequest = new AbortController()
  const request = githubRequest
  const timeout = window.setTimeout(() => request.abort(), 5000)
  try {
    const response = await fetch('https://api.github.com/repos/apoet/Agent4API', {
      headers: { Accept: 'application/vnd.github+json' },
      signal: request.signal,
    })
    if (!response.ok) return
    const payload = await response.json() as { stargazers_count?: unknown }
    if (
      typeof payload.stargazers_count === 'number'
      && Number.isInteger(payload.stargazers_count)
      && payload.stargazers_count >= 0
    ) {
      githubStars.value = payload.stargazers_count
    }
  } catch {
    // The repository link remains usable when GitHub's public API is unavailable.
  } finally {
    window.clearTimeout(timeout)
    if (githubRequest === request) githubRequest = null
  }
}

onMounted(() => {
  void loadGithubStars()
})

onUnmounted(() => {
  githubRequest?.abort()
})

async function submit(): Promise<void> {
  submitting.value = true
  errorCode.value = null
  try {
    await auth.login(username.value, password.value)
    const fallback = auth.admin?.role === 'admin' ? '/admin' : '/admin/sources'
    const requested = typeof route.query.redirect === 'string' ? route.query.redirect : fallback
    await router.push(requested.startsWith('/') && !requested.startsWith('//') ? requested : fallback)
  } catch (error) {
    errorCode.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    submitting.value = false
  }
}

async function requestPasswordReset(): Promise<void> {
  requestingReset.value = true
  errorCode.value = null
  try {
    const issued = await request<AdminPasswordResetIssued>(
      '/api/admin/auth/password-reset/request',
      { method: 'POST' },
    )
    sessionStorage.setItem(
      'chat4openapi.admin-password-reset',
      JSON.stringify(issued),
    )
    await router.push({ name: 'reset-password' })
  } catch (error) {
    errorCode.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    requestingReset.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <a
      class="login-github-link"
      href="https://github.com/apoet/Agent4API"
      target="_blank"
      rel="noopener noreferrer"
      :aria-label="t('login.github')"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 .7a11.5 11.5 0 0 0-3.64 22.4c.58.1.79-.25.79-.56v-2.24c-3.22.7-3.9-1.37-3.9-1.37-.52-1.34-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.28-5.27-5.68 0-1.25.45-2.28 1.18-3.08-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.16 1.18a10.9 10.9 0 0 1 5.75 0c2.2-1.49 3.16-1.18 3.16-1.18.62 1.58.23 2.75.11 3.04.73.8 1.18 1.83 1.18 3.08 0 4.41-2.71 5.38-5.29 5.67.42.36.79 1.06.79 2.14v3.18c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z" />
      </svg>
      <span>GitHub</span>
      <span class="github-star-count">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="m12 2.3 2.86 5.8 6.4.93-4.63 4.51 1.09 6.38L12 16.9l-5.72 3.02 1.09-6.38-4.63-4.51 6.4-.93L12 2.3Z" />
        </svg>
        {{ githubStars ?? '–' }}
      </span>
    </a>
    <section class="auth-story auth-story-login">
      <div class="brand-mark brand-logo"><img :src="logoUrl" alt="Agent4API" /></div>
      <div>
        <p class="eyebrow">{{ t('login.eyebrow') }}</p>
        <h1>{{ t('app.name') }}</h1>
        <p class="story-copy">{{ t('app.tagline') }}</p>
      </div>
      <blockquote>{{ t('login.quote') }}</blockquote>
    </section>

    <section class="auth-panel">
      <form class="auth-card compact" @submit.prevent="submit">
        <p class="eyebrow">{{ t('login.eyebrow') }}</p>
        <h2>{{ t('login.title') }}</h2>
        <p class="muted">{{ t('login.description') }}</p>

        <label for="login-username">{{ t('login.username') }}</label>
        <input id="login-username" v-model.trim="username" autocomplete="username" autofocus />

        <label for="login-password">{{ t('login.password') }}</label>
        <input
          id="login-password"
          v-model="password"
          type="password"
          autocomplete="current-password"
        />
        <p v-if="errorCode" class="form-error">{{ t(`error.${errorCode}`) }}</p>

        <button class="primary-button" type="submit" :disabled="submitting">
          {{ t('login.submit') }}
        </button>
        <button
          class="password-reset-link"
          type="button"
          :disabled="requestingReset"
          @click="requestPasswordReset"
        >
          {{ requestingReset ? t('login.requestingReset') : t('login.requestReset') }}
        </button>
      </form>
    </section>
  </main>
</template>
