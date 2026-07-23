<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, request } from '../api/client'
import type { Locale, ManagedUser } from '../api/contracts'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const users = ref<ManagedUser[]>([])
const editingId = ref<number | null>(null)
const saving = ref(false)
const errorCode = ref<string | null>(null)
const resettingUser = ref<ManagedUser | null>(null)
const resetDialog = ref<HTMLDialogElement | null>(null)
const resetSaving = ref(false)
const resetErrorCode = ref<string | null>(null)
const passwordResetForm = reactive({ password: '', confirmation: '' })
const form = reactive({
  username: '',
  password: '',
  passwordConfirm: '',
  locale: 'en-US' as Locale,
  enabled: true,
})
const editing = computed(() => editingId.value !== null)
const passwordsDiffer = computed(
  () => form.passwordConfirm.length > 0 && form.password !== form.passwordConfirm,
)
const canSave = computed(
  () => Boolean(
    form.username
    && !saving.value
    && (
      editing.value
      || (
        form.password.length >= 6
        && /[A-Za-z]/.test(form.password)
        && /[0-9]/.test(form.password)
        && form.passwordConfirm === form.password
      )
    )
  ),
)
const resetPasswordsDiffer = computed(
  () => passwordResetForm.confirmation.length > 0
    && passwordResetForm.password !== passwordResetForm.confirmation,
)
const canResetPassword = computed(
  () => passwordResetForm.password.length >= 6
    && /[A-Za-z]/.test(passwordResetForm.password)
    && /[0-9]/.test(passwordResetForm.password)
    && passwordResetForm.confirmation === passwordResetForm.password
    && !resetSaving.value,
)

function resetForm(): void {
  editingId.value = null
  errorCode.value = null
  Object.assign(form, {
    username: '',
    password: '',
    passwordConfirm: '',
    locale: 'en-US',
    enabled: true,
  })
}

function edit(user: ManagedUser): void {
  editingId.value = user.id
  errorCode.value = null
  Object.assign(form, {
    username: user.username,
    password: '',
    passwordConfirm: '',
    locale: user.locale,
    enabled: user.enabled,
  })
}

async function load(): Promise<void> {
  users.value = await request<ManagedUser[]>('/api/admin/users')
}

async function save(): Promise<void> {
  saving.value = true
  errorCode.value = null
  try {
    const payload: Record<string, unknown> = {
      username: form.username,
      locale: form.locale,
      enabled: form.enabled,
    }
    if (!editing.value) {
      payload.password = form.password
      payload.password_confirm = form.passwordConfirm
    }
    await request(editing.value ? `/api/admin/users/${editingId.value}` : '/api/admin/users', {
      method: editing.value ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    }, auth.csrfToken)
    resetForm()
    await load()
  } catch (error) {
    errorCode.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    saving.value = false
  }
}

async function toggle(user: ManagedUser): Promise<void> {
  await request(`/api/admin/users/${user.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ enabled: !user.enabled }),
  }, auth.csrfToken)
  await load()
}

async function remove(user: ManagedUser): Promise<void> {
  await request(`/api/admin/users/${user.id}`, { method: 'DELETE' }, auth.csrfToken)
  if (editingId.value === user.id) resetForm()
  await load()
}

async function openPasswordReset(user: ManagedUser): Promise<void> {
  resettingUser.value = user
  resetErrorCode.value = null
  Object.assign(passwordResetForm, { password: '', confirmation: '' })
  await nextTick()
  if (typeof resetDialog.value?.showModal === 'function') {
    resetDialog.value.showModal()
  } else {
    resetDialog.value?.setAttribute('open', '')
  }
}

function closePasswordReset(): void {
  if (resetDialog.value?.open && typeof resetDialog.value.close === 'function') {
    resetDialog.value.close()
  }
  resettingUser.value = null
}

async function resetPassword(): Promise<void> {
  if (!resettingUser.value || !canResetPassword.value) return
  resetSaving.value = true
  resetErrorCode.value = null
  try {
    await request(`/api/admin/users/${resettingUser.value.id}/password`, {
      method: 'PUT',
      body: JSON.stringify({
        new_password: passwordResetForm.password,
        new_password_confirm: passwordResetForm.confirmation,
      }),
    }, auth.csrfToken)
    closePasswordReset()
    await load()
  } catch (error) {
    resetErrorCode.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    resetSaving.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <main class="management-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">{{ t('users.eyebrow') }}</p>
        <h1>{{ t('users.title') }}</h1>
        <p class="muted">{{ t('users.subtitle') }}</p>
      </div>
    </header>

    <section class="settings-panel">
      <div class="settings-grid">
        <label>{{ t('users.username') }}<input v-model.trim="form.username" autocomplete="off" /></label>
        <label v-if="!editing">{{ t('users.password') }}<input v-model="form.password" type="password" autocomplete="new-password" /></label>
        <label v-if="!editing">{{ t('users.confirmPassword') }}<input v-model="form.passwordConfirm" type="password" autocomplete="new-password" /></label>
        <label>{{ t('users.locale') }}<select v-model="form.locale"><option value="en-US">English</option><option value="zh-CN">简体中文</option></select></label>
        <label class="checkbox-label"><input v-model="form.enabled" type="checkbox" /> {{ t('users.enabled') }}</label>
      </div>
      <p v-if="passwordsDiffer" class="field-error">{{ t('setup.mismatch') }}</p>
      <p v-if="errorCode" class="form-error">{{ t(`error.${errorCode}`) }}</p>
      <div class="form-actions">
        <button class="primary-action" :disabled="!canSave" @click="save">{{ editing ? t('users.update') : t('users.create') }}</button>
        <button v-if="editing" class="secondary-action" :disabled="saving" @click="resetForm">{{ t('users.cancel') }}</button>
      </div>
    </section>

    <section class="resource-list">
      <article v-for="user in users" :key="user.id" class="resource-row">
        <span class="resource-icon">U</span>
        <div><strong>{{ user.username }}</strong><p>{{ user.locale }}</p></div>
        <span :class="['status-pill', user.enabled ? 'enabled' : 'disabled']">{{ user.enabled ? t('tools.enabled') : t('tools.disabled') }}</span>
        <footer class="row-actions">
          <button class="secondary-action" @click="edit(user)">{{ t('users.edit') }}</button>
          <button class="secondary-action" @click="openPasswordReset(user)">{{ t('users.resetPassword') }}</button>
          <button class="secondary-action" @click="toggle(user)">{{ user.enabled ? t('tools.disable') : t('tools.enable') }}</button>
          <button class="danger-action" @click="remove(user)">{{ t('tools.delete') }}</button>
        </footer>
      </article>
      <p v-if="!users.length" class="empty-state">{{ t('users.empty') }}</p>
    </section>
    <dialog
      v-if="resettingUser"
      ref="resetDialog"
      class="confirmation-dialog password-dialog"
      aria-labelledby="reset-user-password-title"
      @cancel.prevent="closePasswordReset"
    >
      <form @submit.prevent="resetPassword">
        <h2 id="reset-user-password-title">{{ t('users.resetPassword') }}</h2>
        <p>{{ t('users.resetPasswordHint', { username: resettingUser.username }) }}</p>
        <label>
          {{ t('account.newPassword') }}
          <input v-model="passwordResetForm.password" type="password" autocomplete="new-password" />
        </label>
        <label>
          {{ t('account.confirmNewPassword') }}
          <input v-model="passwordResetForm.confirmation" type="password" autocomplete="new-password" />
        </label>
        <p v-if="resetPasswordsDiffer" class="field-error">{{ t('setup.mismatch') }}</p>
        <p v-if="resetErrorCode" class="form-error">{{ t(`error.${resetErrorCode}`) }}</p>
        <div class="confirmation-actions">
          <button type="button" class="secondary-action" @click="closePasswordReset">
            {{ t('users.cancel') }}
          </button>
          <button type="submit" class="primary-action" :disabled="!canResetPassword">
            {{ t('users.resetUserPassword') }}
          </button>
        </div>
      </form>
    </dialog>
  </main>
</template>
