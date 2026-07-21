<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '../api/client'
import type { AgentConfig } from '../api/contracts'
import { useAgentStore } from '../stores/agent'

const store = useAgentStore()
const { t } = useI18n()
const errorMessage = ref('')
const form = reactive<AgentConfig>({
  id: 1,
  name: '',
  enabled: true,
  system_prompt: '',
  provider_id: null,
  model: null,
  mode: 'human_in_loop',
  max_iterations: 8,
})
const enabledProviders = computed(() => store.providers.filter((provider) => provider.enabled))
const canSave = computed(() => Boolean(
  form.name.trim()
  && form.system_prompt.trim()
  && enabledProviders.value.some((provider) => provider.id === form.provider_id)
  && form.max_iterations >= 2
  && form.max_iterations <= 32,
))

onMounted(async () => {
  try {
    await store.load()
    if (store.config) Object.assign(form, store.config)
  } catch {
    errorMessage.value = t('error.agent.load_failed')
  }
})

function actionError(error: unknown, fallback: 'save_failed' | 'reset_failed'): string {
  if (error instanceof ApiError && error.code === 'agent.provider_unavailable') {
    return t('error.agent.provider_unavailable')
  }
  return t(`error.agent.${fallback}`)
}

async function save(): Promise<void> {
  if (!canSave.value) return
  errorMessage.value = ''
  try {
    await store.save({
      name: form.name.trim(),
      enabled: form.enabled,
      system_prompt: form.system_prompt,
      provider_id: form.provider_id as number,
      model: form.model?.trim() || null,
      mode: form.mode,
      max_iterations: form.max_iterations,
    })
    if (store.config) Object.assign(form, store.config)
  } catch (error) {
    errorMessage.value = actionError(error, 'save_failed')
  }
}

async function reset(): Promise<void> {
  errorMessage.value = ''
  try {
    await store.reset()
    if (store.config) Object.assign(form, store.config)
  } catch (error) {
    errorMessage.value = actionError(error, 'reset_failed')
  }
}
</script>

<template>
  <main class="management-page narrow-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">{{ t('agent.eyebrow') }}</p>
        <h1>{{ t('agent.title') }}</h1>
      </div>
    </header>
    <section class="settings-panel">
      <label class="toggle-row"><span><strong>{{ t('agent.enabled') }}</strong><small>{{ t('agent.enabledHint') }}</small></span><input v-model="form.enabled" type="checkbox" /></label>
      <div class="settings-grid">
        <label>{{ t('agent.name') }}<input v-model="form.name" /></label>
        <label>{{ t('agent.provider') }}<select v-model="form.provider_id"><option :value="null">{{ t('agent.selectProvider') }}</option><option v-for="provider in enabledProviders" :key="provider.id" :value="provider.id">{{ provider.name }} · {{ provider.default_model }}</option></select></label>
        <label>{{ t('agent.model') }}<input v-model="form.model" :placeholder="t('agent.modelHint')" /></label>
        <label>{{ t('agent.mode') }}<select v-model="form.mode"><option value="human_in_loop">{{ t('agent.humanInLoop') }}</option><option value="react">{{ t('agent.react') }}</option></select></label>
        <label>{{ t('agent.maxIterations') }}<input v-model.number="form.max_iterations" type="number" min="2" max="32" /></label>
      </div>
      <p class="agent-mode-note">{{ t('agent.toolApprovalNote') }}</p>
      <label class="block-label">{{ t('agent.systemPrompt') }}<textarea v-model="form.system_prompt" rows="12" /></label>
      <p v-if="errorMessage" class="agent-error" role="alert">{{ errorMessage }}</p>
      <div class="row-actions agent-actions"><button class="primary-action" :disabled="!canSave" @click="save">{{ t('agent.save') }}</button><button class="secondary-action" @click="reset">{{ t('agent.reset') }}</button></div>
    </section>
  </main>
</template>
