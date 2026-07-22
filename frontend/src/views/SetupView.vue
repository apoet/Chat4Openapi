<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import logoUrl from '../../../logo.png'
import { ApiError } from '../api/client'
import type { Locale } from '../api/contracts'
import { setLocale } from '../i18n'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const username = ref('')
const password = ref('')
const confirmation = ref('')
const locale = ref<Locale>('en-US')
const submitting = ref(false)
const errorCode = ref<string | null>(null)

const passwordsDiffer = computed(
  () => confirmation.value.length > 0 && password.value !== confirmation.value,
)
const canSubmit = computed(
  () =>
    username.value.length >= 3 &&
    password.value.length >= 6 &&
    /[A-Za-z]/.test(password.value) &&
    /[0-9]/.test(password.value) &&
    confirmation.value === password.value &&
    !submitting.value,
)

function changeLocale(): void {
  setLocale(locale.value)
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  submitting.value = true
  errorCode.value = null
  try {
    await auth.initialize(username.value, password.value, locale.value)
    await router.push({ name: 'login' })
  } catch (error) {
    errorCode.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-story">
      <div class="brand-mark brand-logo"><img :src="logoUrl" alt="Chat4Openapi" /></div>
      <div>
        <p class="eyebrow">{{ t('setup.eyebrow') }}</p>
        <h1>{{ t('app.name') }}</h1>
        <p class="story-copy">{{ t('app.tagline') }}</p>
      </div>
      <div class="story-grid" aria-hidden="true">
        <span>OpenAPI</span><i></i><span>MCP Tools</span><i></i><span>Skills</span><i></i><span>Agents</span><i></i><span>Chat</span>
      </div>
      <p class="story-note">{{ t('setup.identityNote') }}</p>
    </section>

    <section class="auth-panel">
      <form class="auth-card" @submit.prevent="submit">
        <p class="eyebrow">{{ t('setup.eyebrow') }}</p>
        <h2>{{ t('setup.title') }}</h2>
        <p class="muted">{{ t('setup.description') }}</p>

        <label for="setup-locale">{{ t('setup.locale') }}</label>
        <select id="setup-locale" v-model="locale" @change="changeLocale">
          <option value="en-US">English</option>
          <option value="zh-CN">简体中文</option>
        </select>

        <label for="setup-username">{{ t('setup.username') }}</label>
        <input id="setup-username" v-model.trim="username" autocomplete="username" autofocus />

        <label for="setup-password">{{ t('setup.password') }}</label>
        <input
          id="setup-password"
          v-model="password"
          type="password"
          autocomplete="new-password"
          minlength="6"
          pattern="(?=.*[A-Za-z])(?=.*[0-9]).{6,}"
        />
        <p class="field-hint">{{ t('setup.passwordHint') }}</p>

        <label for="setup-confirmation">{{ t('setup.confirmPassword') }}</label>
        <input
          id="setup-confirmation"
          v-model="confirmation"
          type="password"
          autocomplete="new-password"
          :aria-invalid="passwordsDiffer"
        />
        <p v-if="passwordsDiffer" class="field-error">{{ t('setup.mismatch') }}</p>
        <p v-if="errorCode" class="form-error">{{ t(`error.${errorCode}`) }}</p>

        <button class="primary-button" type="submit" :disabled="!canSubmit">
          {{ t('setup.submit') }}
        </button>
      </form>
    </section>
  </main>
</template>
