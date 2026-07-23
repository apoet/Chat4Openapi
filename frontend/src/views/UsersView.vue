<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
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
const form = reactive({ username: '', password: '', locale: 'en-US' as Locale, enabled: true })
const editing = computed(() => editingId.value !== null)

function resetForm(): void {
  editingId.value = null
  errorCode.value = null
  Object.assign(form, { username: '', password: '', locale: 'en-US', enabled: true })
}

function edit(user: ManagedUser): void {
  editingId.value = user.id
  errorCode.value = null
  Object.assign(form, { username: user.username, password: '', locale: user.locale, enabled: user.enabled })
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
    if (form.password) payload.password = form.password
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
        <label>{{ t('users.password') }}<input v-model="form.password" type="password" autocomplete="new-password" :placeholder="editing ? t('users.passwordKeep') : ''" /></label>
        <label>{{ t('users.locale') }}<select v-model="form.locale"><option value="en-US">English</option><option value="zh-CN">简体中文</option></select></label>
        <label class="checkbox-label"><input v-model="form.enabled" type="checkbox" /> {{ t('users.enabled') }}</label>
      </div>
      <p v-if="errorCode" class="form-error">{{ t(`error.${errorCode}`) }}</p>
      <div class="form-actions">
        <button class="primary-action" :disabled="saving || !form.username || (!editing && !form.password)" @click="save">{{ editing ? t('users.update') : t('users.create') }}</button>
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
          <button class="secondary-action" @click="toggle(user)">{{ user.enabled ? t('tools.disable') : t('tools.enable') }}</button>
          <button class="danger-action" @click="remove(user)">{{ t('tools.delete') }}</button>
        </footer>
      </article>
      <p v-if="!users.length" class="empty-state">{{ t('users.empty') }}</p>
    </section>
  </main>
</template>
