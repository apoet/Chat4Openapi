<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, request } from '../api/client'
import type { AutoAgentifyResult, LlmProviderSummary } from '../api/contracts'
import { useAuthStore } from '../stores/auth'

const emit = defineEmits<{
  generated: [result: AutoAgentifyResult]
  close: []
}>()
const { t } = useI18n()
const auth = useAuthStore()
const providers = ref<LlmProviderSummary[]>([])
const providerId = ref('')
const name = ref('')
const baseUrl = ref('')
const mode = ref<'url' | 'file'>('url')
const sourceUrl = ref('')
const file = ref<File | null>(null)
const allowPrivateNetworks = ref(false)
const submitting = ref(false)
const errorCode = ref<string | null>(null)
const result = ref<AutoAgentifyResult | null>(null)

const ready = computed(() => (
  Boolean(providerId.value)
  && Boolean(name.value.trim())
  && (mode.value === 'url' ? Boolean(sourceUrl.value.trim()) : file.value !== null)
  && !submitting.value
))

onMounted(async () => {
  providers.value = (await request<LlmProviderSummary[]>('/api/admin/build/providers'))
    .filter((provider) => provider.enabled)
  if (providers.value.length === 1) providerId.value = String(providers.value[0].id)
})

function selectFile(event: Event): void {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function errorMessage(code: string): string {
  const known = [
    'plan_invalid',
    'provider_unavailable',
    'provider_failed',
    'openapi_invalid',
    'openapi_unsupported',
    'conflict',
  ]
  const suffix = code.startsWith('auto_agentify.') ? code.slice('auto_agentify.'.length) : ''
  return known.includes(suffix)
    ? t(`autoAgentify.errors.${suffix}`)
    : t('autoAgentify.errors.unknown')
}

async function submit(): Promise<void> {
  if (!ready.value) return
  submitting.value = true
  errorCode.value = null
  result.value = null
  try {
    let generated: AutoAgentifyResult
    if (mode.value === 'url') {
      generated = await request<AutoAgentifyResult>(
        '/api/admin/auto-agentify/url',
        {
          method: 'POST',
          body: JSON.stringify({
            provider_id: Number(providerId.value),
            name: name.value.trim(),
            url: sourceUrl.value.trim(),
            base_url: baseUrl.value.trim() || null,
            allow_private_networks: allowPrivateNetworks.value,
          }),
        },
        auth.csrfToken,
      )
    } else {
      const body = new FormData()
      body.set('provider_id', providerId.value)
      body.set('name', name.value.trim())
      if (baseUrl.value.trim()) body.set('base_url', baseUrl.value.trim())
      body.set('allow_private_networks', String(allowPrivateNetworks.value))
      body.set('document', file.value as File)
      generated = await request<AutoAgentifyResult>(
        '/api/admin/auto-agentify/file',
        { method: 'POST', body },
        auth.csrfToken,
      )
    }
    result.value = generated
    emit('generated', generated)
  } catch (error) {
    errorCode.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="import-panel auto-agentify-panel">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">{{ t('autoAgentify.eyebrow') }}</p>
        <h2>{{ t('autoAgentify.title') }}</h2>
        <p class="muted">{{ t('autoAgentify.subtitle') }}</p>
      </div>
      <button type="button" class="text-button" :aria-label="t('autoAgentify.close')" @click="emit('close')">×</button>
    </div>
    <div class="segmented import-mode">
      <button type="button" :class="{ active: mode === 'url' }" @click="mode = 'url'">{{ t('autoAgentify.urlMode') }}</button>
      <button type="button" data-testid="auto-mode-file" :class="{ active: mode === 'file' }" @click="mode = 'file'">{{ t('autoAgentify.fileMode') }}</button>
    </div>
    <div class="form-grid">
      <label>{{ t('autoAgentify.provider') }}
        <select v-model="providerId" data-testid="auto-provider">
          <option value="">{{ t('autoAgentify.selectProvider') }}</option>
          <option v-for="provider in providers" :key="provider.id" :value="String(provider.id)">{{ provider.name }} · {{ provider.default_model }}</option>
        </select>
      </label>
      <label>{{ t('autoAgentify.name') }}<input v-model="name" data-testid="auto-name" /></label>
      <label>{{ t('autoAgentify.baseUrl') }}<input v-model="baseUrl" /></label>
      <label v-if="mode === 'url'">{{ t('autoAgentify.url') }}<input v-model="sourceUrl" data-testid="auto-url" type="url" /></label>
      <label v-else class="file-field">{{ t('autoAgentify.document') }}<input data-testid="auto-file" type="file" accept=".json,.yaml,.yml,application/json,application/yaml" @change="selectFile" /></label>
    </div>
    <label class="checkbox-label import-private"><input v-model="allowPrivateNetworks" type="checkbox" />{{ t('sources.allowPrivate') }}</label>
    <button data-testid="auto-submit" class="primary-action" :disabled="!ready" @click="submit">{{ submitting ? t('autoAgentify.analyzing') : t('autoAgentify.generate') }}</button>
    <p v-if="submitting" class="muted" role="status">{{ t('autoAgentify.phase') }}</p>
    <p v-if="errorCode" data-testid="auto-error" class="form-error" role="alert">{{ errorMessage(errorCode) }}</p>

    <div v-if="result" class="auto-result" data-testid="auto-result">
      <h3>{{ t('autoAgentify.resultTitle') }}</h3>
      <p>{{ t('autoAgentify.counts', { tools: result.enabled_tool_count, imported: result.imported_tool_count, skills: result.skills.length, agents: result.agents.length }) }}</p>
      <div class="auto-result-grid">
        <section>
          <h4>{{ t('autoAgentify.skills') }}</h4>
          <article v-for="skill in result.skills" :key="skill.id" class="auto-result-card"><strong>{{ skill.name }}</strong><p>{{ skill.value }}</p></article>
        </section>
        <section>
          <h4>{{ t('autoAgentify.agents') }}</h4>
          <article v-for="agent in result.agents" :key="agent.id" class="auto-result-card"><strong>{{ agent.name }}</strong><p>{{ agent.value }}</p><ul><li v-for="useCase in agent.use_cases" :key="useCase">{{ useCase }}</li></ul></article>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.auto-agentify-panel { display: grid; gap: 16px; }
.auto-result { padding-top: 16px; border-top: 1px solid #e1ddd4; }
.auto-result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.auto-result-card { margin-top: 8px; padding: 12px; border: 1px solid #e1ddd4; border-radius: 10px; background: #fff; }
.auto-result-card p { margin: 6px 0; color: #626b7b; }
.auto-result-card ul { margin: 8px 0 0; padding-left: 20px; }
@media (max-width: 760px) { .auto-result-grid { grid-template-columns: 1fr; } }
</style>
