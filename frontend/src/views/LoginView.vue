<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const submitting = ref(false)
const errorCode = ref<string | null>(null)

async function submit(): Promise<void> {
  submitting.value = true
  errorCode.value = null
  try {
    await auth.login(username.value, password.value)
    const requested = typeof route.query.redirect === 'string' ? route.query.redirect : '/admin'
    await router.push(requested.startsWith('/') && !requested.startsWith('//') ? requested : '/admin')
  } catch (error) {
    errorCode.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-story auth-story-login">
      <div class="brand-mark"><span>CA</span></div>
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
      </form>
    </section>
  </main>
</template>
