<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useToolsStore } from '../stores/tools'

const store = useToolsStore()
const { t } = useI18n()
const name = ref('')
const baseUrl = ref('')
const file = ref<File | null>(null)
const submitting = ref(false)

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
        <span class="resource-icon">API</span><div><strong>{{ source.name }}</strong><p>{{ source.base_url }}</p></div><span class="status-pill enabled">{{ t('tools.enabled') }}</span>
      </article>
    </section>
  </main>
</template>
