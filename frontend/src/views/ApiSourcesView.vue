<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ApiSourceSummary } from '../api/contracts'
import { useToolsStore } from '../stores/tools'

const store = useToolsStore()
const { t } = useI18n()
const name = ref('')
const baseUrl = ref('')
const file = ref<File | null>(null)
const submitting = ref(false)
const editingId = ref<number | null>(null)
const editName = ref('')
const editBaseUrl = ref('')
const editAllowPrivateNetworks = ref(false)

onMounted(() => void store.loadSources())

function selectFile(event: Event): void {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function submit(): Promise<void> {
  if (!file.value || !name.value) return
  submitting.value = true
  try {
    await store.importFile(name.value, file.value, baseUrl.value || undefined)
    name.value = ''
    baseUrl.value = ''
    file.value = null
  } finally {
    submitting.value = false
  }
}

function startEdit(source: ApiSourceSummary): void {
  editingId.value = source.id
  editName.value = source.name
  editBaseUrl.value = source.base_url
  editAllowPrivateNetworks.value = source.allow_private_networks
}

function cancelEdit(): void {
  editingId.value = null
}

async function saveEdit(source: ApiSourceSummary): Promise<void> {
  await store.updateSource(source, {
    name: editName.value,
    base_url: editBaseUrl.value,
    allow_private_networks: editAllowPrivateNetworks.value,
  })
  editingId.value = null
}
</script>

<template>
  <main class="management-page">
    <header class="page-heading">
      <div><p class="eyebrow">{{ t('sources.eyebrow') }}</p><h1>{{ t('sources.title') }}</h1><p class="muted">{{ t('sources.subtitle') }}</p></div>
    </header>
    <section class="import-panel">
      <div class="form-grid">
        <label>{{ t('sources.name') }}<input v-model="name" /></label>
        <label>{{ t('sources.baseUrl') }}<input v-model="baseUrl" placeholder="https://api.example.com" /></label>
        <label class="file-field">{{ t('sources.document') }}<input type="file" accept=".json,.yaml,.yml,application/json,application/yaml" @change="selectFile" /></label>
      </div>
      <button class="primary-action" :disabled="!name || !file || submitting" @click="submit">{{ submitting ? t('sources.importing') : t('sources.import') }}</button>
    </section>
    <section class="resource-list">
      <div v-if="!store.loading && store.sources.length === 0" class="empty-state">{{ t('sources.empty') }}</div>
      <article v-for="source in store.sources" :key="source.id" class="resource-row">
        <span class="resource-icon">API</span>
        <div v-if="editingId === source.id" class="source-inline-editor">
          <label>{{ t('sources.editName') }}<input v-model="editName" /></label>
          <label>{{ t('sources.editBaseUrl') }}<input v-model="editBaseUrl" /></label>
          <label class="checkbox-label"><input v-model="editAllowPrivateNetworks" type="checkbox" />{{ t('sources.allowPrivate') }}</label>
          <div class="row-actions editor-actions"><button class="primary-action" :disabled="!editName || !editBaseUrl" @click="saveEdit(source)">{{ t('sources.save') }}</button><button class="secondary-action" @click="cancelEdit">{{ t('skills.cancel') }}</button></div>
        </div>
        <template v-else>
          <div><strong>{{ source.name }}</strong><p>{{ source.base_url }}</p></div>
          <span :class="['status-pill', source.enabled ? 'enabled' : 'disabled']">{{ source.enabled ? t('tools.enabled') : t('tools.disabled') }}</span>
          <footer class="row-actions"><button class="secondary-action" @click="startEdit(source)">{{ t('skills.edit') }}</button><button class="secondary-action" @click="store.setSourceEnabled(source, !source.enabled)">{{ source.enabled ? t('tools.disable') : t('tools.enable') }}</button><button class="danger-action" @click="store.deleteSource(source)">{{ t('tools.delete') }}</button></footer>
        </template>
      </article>
    </section>
  </main>
</template>
