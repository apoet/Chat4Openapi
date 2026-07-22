<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '../api/client'
import type { LlmProviderSummary } from '../api/contracts'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const providers = ref<LlmProviderSummary[]>([])
const testingId = ref<number | null>(null)
const editingId = ref<number | null>(null)
const saving = ref(false)
const feedback = ref<Record<number, string>>({})
const form = reactive({ name: '', provider_type: 'openai', base_url: '', api_key: '', default_model: '' })
const editing = computed(() => editingId.value !== null)

function resetForm(): void {
  editingId.value = null
  Object.assign(form, { name: '', provider_type: 'openai', base_url: '', api_key: '', default_model: '' })
}

function edit(provider: LlmProviderSummary): void {
  editingId.value = provider.id
  Object.assign(form, {
    name: provider.name,
    provider_type: provider.provider_type,
    base_url: provider.base_url,
    default_model: provider.default_model,
    api_key: '',
  })
}

async function load(): Promise<void> {
  providers.value = await request<LlmProviderSummary[]>('/api/admin/providers')
}

async function save(): Promise<void> {
  saving.value = true
  try {
    if (editingId.value === null) {
      await request('/api/admin/providers', {
        method: 'POST',
        body: JSON.stringify({ ...form, enabled: true }),
      }, auth.csrfToken)
    } else {
      const payload: Record<string, string> = {
        name: form.name,
        provider_type: form.provider_type,
        base_url: form.base_url,
        default_model: form.default_model,
      }
      if (form.api_key.trim()) payload.api_key = form.api_key
      await request(`/api/admin/providers/${editingId.value}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      }, auth.csrfToken)
    }
    resetForm()
    await load()
  } finally {
    saving.value = false
  }
}

async function testConnection(provider: LlmProviderSummary): Promise<void> {
  testingId.value = provider.id
  try {
    await request(`/api/admin/providers/${provider.id}/test`, { method: 'POST' }, auth.csrfToken)
    feedback.value[provider.id] = t('providers.testSuccess')
  } finally {
    testingId.value = null
  }
}

async function setEnabled(provider: LlmProviderSummary): Promise<void> {
  await request(`/api/admin/providers/${provider.id}`, {
    method: 'PATCH', body: JSON.stringify({ enabled: !provider.enabled }),
  }, auth.csrfToken)
  await load()
}

async function remove(provider: LlmProviderSummary): Promise<void> {
  await request(`/api/admin/providers/${provider.id}`, { method: 'DELETE' }, auth.csrfToken)
  if (editingId.value === provider.id) resetForm()
  await load()
}

onMounted(() => void load())
</script>

<template>
  <main class="management-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">{{ t('providers.eyebrow') }}</p>
        <h1>{{ t('providers.title') }}</h1>
        <p class="muted">{{ t('providers.subtitle') }}</p>
      </div>
    </header>

    <section class="settings-panel">
      <div class="settings-grid">
        <label>{{ t('providers.name') }}<input v-model="form.name" /></label>
        <label>{{ t('providers.type') }}<select v-model="form.provider_type"><option value="openai">OpenAI compatible</option><option value="anthropic">Anthropic compatible</option></select></label>
        <label>{{ t('providers.baseUrl') }}<input v-model="form.base_url" /></label>
        <label>{{ t('providers.model') }}<input v-model="form.default_model" /></label>
        <label>{{ t('providers.apiKey') }}<input v-model="form.api_key" type="password" :placeholder="editing ? t('providers.apiKeyKeep') : ''" /></label>
      </div>
      <div class="form-actions">
        <button class="primary-action" :disabled="saving" @click="save">{{ editing ? t('providers.update') : t('providers.save') }}</button>
        <button v-if="editing" class="secondary-action" :disabled="saving" @click="resetForm">{{ t('providers.cancel') }}</button>
      </div>
    </section>

    <section class="resource-list">
      <article v-for="provider in providers" :key="provider.id" class="resource-row">
        <span class="resource-icon">AI</span>
        <div>
          <strong>{{ provider.name }}</strong>
          <p>{{ provider.provider_type }} · {{ provider.default_model }}</p>
          <small v-if="feedback[provider.id]" class="success-text">{{ feedback[provider.id] }}</small>
        </div>
        <span :class="['status-pill', provider.enabled ? 'enabled' : 'disabled']">{{ provider.enabled ? t('tools.enabled') : t('tools.disabled') }}</span>
        <footer class="row-actions">
          <button class="secondary-action" @click="edit(provider)">{{ t('providers.edit') }}</button>
          <button class="secondary-action" :disabled="testingId === provider.id" @click="testConnection(provider)">{{ testingId === provider.id ? t('providers.testing') : t('providers.test') }}</button>
          <button class="secondary-action" @click="setEnabled(provider)">{{ provider.enabled ? t('tools.disable') : t('tools.enable') }}</button>
          <button class="danger-action" @click="remove(provider)">{{ t('tools.delete') }}</button>
        </footer>
      </article>
    </section>
  </main>
</template>
