<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useSettingsStore } from '../stores/settings'

const store = useSettingsStore()
const { t } = useI18n()
const baseUrl = ref('')
const saved = ref(false)
const pending = ref(false)

onMounted(async () => {
  await store.load()
  baseUrl.value = store.settings.base_url ?? ''
})

async function submit(): Promise<void> {
  pending.value = true
  saved.value = false
  try {
    await store.save(baseUrl.value.trim() || null)
    baseUrl.value = store.settings.base_url ?? ''
    saved.value = true
  } finally { pending.value = false }
}
</script>

<template>
  <main class="management-page">
    <header class="page-heading"><div><p class="eyebrow">{{ t('settings.eyebrow') }}</p><h1>{{ t('settings.title') }}</h1><p class="muted">{{ t('settings.subtitle') }}</p></div></header>
    <section class="import-panel settings-panel">
      <form @submit.prevent="submit">
        <label>{{ t('settings.baseUrl') }}<input v-model="baseUrl" type="url" placeholder="https://chat.example.com" /></label>
        <p class="muted">{{ t('settings.baseUrlHint') }}</p>
        <button class="primary-action" :disabled="pending">{{ t('settings.save') }}</button>
        <p v-if="saved" class="refresh-notice">{{ t('settings.saved') }} {{ store.settings.base_url }}</p>
      </form>
    </section>
  </main>
</template>
