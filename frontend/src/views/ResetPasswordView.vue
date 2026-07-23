<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import logoUrl from '../../../logo.png'
import { ApiError, request } from '../api/client'
import type { AdminPasswordResetIssued } from '../api/contracts'

const STORAGE_KEY = 'chat4openapi.admin-password-reset'
const { t } = useI18n()
const router = useRouter()
const issued = ref<AdminPasswordResetIssued | null>(loadIssued())
const resetKey = ref('')
const password = ref('')
const confirmation = ref('')
const submitting = ref(false)
const requesting = ref(false)
const errorCode = ref<string | null>(null)
const passwordsDiffer = computed(
  () => confirmation.value.length > 0 && confirmation.value !== password.value,
)
const canSubmit = computed(
  () => Boolean(
    issued.value
    && resetKey.value
    && password.value.length >= 6
    && /[A-Za-z]/.test(password.value)
    && /[0-9]/.test(password.value)
    && confirmation.value === password.value
    && !submitting.value
  ),
)

function loadIssued(): AdminPasswordResetIssued | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? 'null')
    if (
      value
      && typeof value.credential_path === 'string'
      && typeof value.expires_at === 'string'
    ) return value
  } catch {
    sessionStorage.removeItem(STORAGE_KEY)
  }
  return null
}

async function requestReset(): Promise<void> {
  requesting.value = true
  errorCode.value = null
  try {
    issued.value = await request<AdminPasswordResetIssued>(
      '/api/admin/auth/password-reset/request',
      { method: 'POST' },
    )
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(issued.value))
  } catch (error) {
    errorCode.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    requesting.value = false
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  submitting.value = true
  errorCode.value = null
  try {
    await request<void>('/api/admin/auth/password-reset/complete', {
      method: 'POST',
      body: JSON.stringify({
        key: resetKey.value,
        new_password: password.value,
        new_password_confirm: confirmation.value,
      }),
    })
    sessionStorage.removeItem(STORAGE_KEY)
    await router.push({ name: 'login', query: { reset: 'success' } })
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
      <div class="brand-mark brand-logo"><img :src="logoUrl" alt="Agent4API" /></div>
      <div>
        <p class="eyebrow">{{ t('passwordReset.eyebrow') }}</p>
        <h1>{{ t('app.name') }}</h1>
        <p class="story-copy">{{ t('passwordReset.story') }}</p>
      </div>
    </section>
    <section class="auth-panel">
      <form class="auth-card compact" @submit.prevent="submit">
        <p class="eyebrow">{{ t('passwordReset.eyebrow') }}</p>
        <h2>{{ t('passwordReset.title') }}</h2>
        <p class="muted">{{ t('passwordReset.description') }}</p>

        <div v-if="issued" class="reset-path">
          <span>{{ t('passwordReset.path') }}</span>
          <code>{{ issued.credential_path }}</code>
          <small>{{ t('passwordReset.expiry', { time: new Date(issued.expires_at).toLocaleString() }) }}</small>
        </div>
        <button
          v-else
          class="secondary-action request-reset-again"
          type="button"
          :disabled="requesting"
          @click="requestReset"
        >
          {{ t('login.requestReset') }}
        </button>

        <label for="reset-key">{{ t('passwordReset.key') }}</label>
        <input id="reset-key" v-model.trim="resetKey" autocomplete="off" />

        <label for="reset-new-password">{{ t('account.newPassword') }}</label>
        <input id="reset-new-password" v-model="password" type="password" autocomplete="new-password" />

        <label for="reset-confirm-password">{{ t('account.confirmNewPassword') }}</label>
        <input id="reset-confirm-password" v-model="confirmation" type="password" autocomplete="new-password" />
        <p v-if="passwordsDiffer" class="field-error">{{ t('setup.mismatch') }}</p>
        <p v-if="errorCode" class="form-error">{{ t(`error.${errorCode}`) }}</p>

        <button class="primary-button" type="submit" :disabled="!canSubmit">
          {{ t('passwordReset.submit') }}
        </button>
      </form>
    </section>
  </main>
</template>
