<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '../api/client'
import type { AutoAgentifyResult, LlmProviderSummary } from '../api/contracts'
import {
  useAutoAgentifyJob,
  type AutoAgentifySourceInput,
} from '../composables/useAutoAgentifyJob'

const props = defineProps<{ source: AutoAgentifySourceInput }>()
const emit = defineEmits<{
  generated: [result: AutoAgentifyResult]
  close: []
}>()
const { t } = useI18n()
const providers = ref<LlmProviderSummary[]>([])
const providerId = ref('')
const {
  job,
  events,
  capabilities,
  starting,
  active,
  errorCode,
  recover,
  start,
} = useAutoAgentifyJob()

const sourceReady = computed(() => (
  Boolean(props.source.name.trim())
  && (
    props.source.mode === 'url'
      ? Boolean(props.source.sourceUrl.trim())
      : props.source.file !== null
  )
))
const ready = computed(
  () => Boolean(providerId.value) && sourceReady.value && !starting.value && !active.value,
)

watch(
  () => job.value?.result,
  (result) => {
    if (result) emit('generated', result)
  },
)

onMounted(async () => {
  providers.value = (await request<LlmProviderSummary[]>('/api/admin/build/providers'))
    .filter((provider) => provider.enabled)
  if (providers.value.length === 1) providerId.value = String(providers.value[0].id)
  await recover()
  if (job.value) providerId.value = String(job.value.provider_id)
})

function eventLabel(kind: string): string {
  const labels: Record<string, string> = {
    queued: t('autoAgentify.events.queued'),
    document_loaded: t('autoAgentify.events.documentLoaded'),
    openapi_validated: t('autoAgentify.events.openapiValidated'),
    operations_discovered: t('autoAgentify.events.operationsDiscovered'),
    capability_batch_started: t('autoAgentify.events.capabilityBatchStarted'),
    capability_discovered: t('autoAgentify.events.capabilityDiscovered'),
    capability_batch_completed: t('autoAgentify.events.capabilityBatchCompleted'),
    plan_synthesis_started: t('autoAgentify.events.planSynthesisStarted'),
    plan_correction_started: t('autoAgentify.events.planCorrectionStarted'),
    capabilities_merged: t('autoAgentify.events.capabilitiesMerged'),
    skill_selected: t('autoAgentify.events.skillSelected'),
    agent_synthesized: t('autoAgentify.events.agentSynthesized'),
    plan_validated: t('autoAgentify.events.planValidated'),
    persistence_started: t('autoAgentify.events.persistenceStarted'),
    configuration_created: t('autoAgentify.events.configurationCreated'),
    completed: t('autoAgentify.events.completed'),
    failed: t('autoAgentify.events.failed'),
    interrupted: t('autoAgentify.events.interrupted'),
  }
  return labels[kind] ?? kind
}
</script>

<template>
  <div class="modal-backdrop" role="presentation">
    <section class="auto-agentify-modal" role="dialog" aria-modal="true" :aria-label="t('autoAgentify.title')">
      <header class="panel-heading">
        <div>
          <p class="eyebrow">{{ t('autoAgentify.eyebrow') }}</p>
          <h2>{{ t('autoAgentify.title') }}</h2>
          <p class="muted">{{ t('autoAgentify.subtitle') }}</p>
        </div>
        <button data-testid="auto-close" type="button" class="text-button" :aria-label="t('autoAgentify.close')" @click="emit('close')">×</button>
      </header>

      <div class="source-summary">
        <strong>{{ source.name || t('autoAgentify.missingName') }}</strong>
        <span>{{ source.mode === 'url' ? source.sourceUrl : source.file?.name }}</span>
      </div>
      <label>{{ t('autoAgentify.provider') }}
        <select v-model="providerId" data-testid="auto-provider" :disabled="active">
          <option value="">{{ t('autoAgentify.selectProvider') }}</option>
          <option v-for="provider in providers" :key="provider.id" :value="String(provider.id)">
            {{ provider.name }} · {{ provider.default_model }}
          </option>
        </select>
      </label>

      <p v-if="!sourceReady" class="form-error" role="alert">{{ t('autoAgentify.sourceIncomplete') }}</p>
      <button data-testid="auto-submit" class="primary-action" :disabled="!ready" @click="start(source, Number(providerId))">
        {{ starting ? t('autoAgentify.starting') : active ? t('autoAgentify.running') : t('autoAgentify.confirm') }}
      </button>

      <section v-if="job" class="live-analysis" aria-live="polite">
        <div class="progress-heading">
          <strong>{{ t('autoAgentify.liveProgress') }}</strong>
          <span>{{ job.progress }}%</span>
        </div>
        <progress data-testid="auto-progress" :value="job.progress" max="100"></progress>

        <div v-if="capabilities.length" class="capability-list">
          <h3>{{ t('autoAgentify.capabilities') }}</h3>
          <article v-for="capability in capabilities" :key="capability.name" class="capability-card">
            <div><strong>{{ capability.name }}</strong><span v-if="capability.high_impact" class="impact-pill">{{ t('autoAgentify.highImpact') }}</span></div>
            <p>{{ capability.description }}</p>
            <p class="capability-value">{{ capability.value }}</p>
            <ol><li v-for="step in capability.workflow" :key="step">{{ step }}</li></ol>
          </article>
        </div>

        <ol class="event-list">
          <li v-for="event in events" :key="event.sequence">
            <span>{{ eventLabel(event.kind) }}</span><small>{{ event.progress }}%</small>
          </li>
        </ol>
      </section>

      <p v-if="errorCode || job?.error_code" data-testid="auto-error" class="form-error" role="alert">
        {{ t('autoAgentify.errors.unknown') }} ({{ errorCode || job?.error_code }})
      </p>

      <section v-if="job?.result" class="auto-result" data-testid="auto-result">
        <h3>{{ t('autoAgentify.resultTitle') }}</h3>
        <p>{{ t('autoAgentify.counts', { tools: job.result.enabled_tool_count, imported: job.result.imported_tool_count, skills: job.result.skills.length, agents: job.result.agents.length }) }}</p>
        <div class="auto-result-grid">
          <section><h4>{{ t('autoAgentify.skills') }}</h4><article v-for="skill in job.result.skills" :key="skill.id" class="auto-result-card"><strong>{{ skill.name }}</strong><p>{{ skill.value }}</p></article></section>
          <section><h4>{{ t('autoAgentify.agents') }}</h4><article v-for="agent in job.result.agents" :key="agent.id" class="auto-result-card"><strong>{{ agent.name }}</strong><p>{{ agent.value }}</p><ul><li v-for="useCase in agent.use_cases" :key="useCase">{{ useCase }}</li></ul></article></section>
        </div>
      </section>
    </section>
  </div>
</template>

<style scoped>
.modal-backdrop { position: fixed; z-index: 1000; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(23,32,51,.48); }
.auto-agentify-modal { width: min(760px, 100%); max-height: calc(100vh - 48px); overflow: auto; display: grid; gap: 16px; padding: 24px; border-radius: 16px; background: #fff; box-shadow: 0 24px 80px rgba(20,28,45,.28); }
.source-summary { display: grid; gap: 4px; padding: 12px; border-radius: 10px; background: #f5f6f8; overflow-wrap: anywhere; }
.source-summary span { color: #626b7b; font-size: 13px; }
.progress-heading { display: flex; justify-content: space-between; }
progress { width: 100%; height: 10px; }
.live-analysis, .capability-list { display: grid; gap: 12px; }
.capability-card { padding: 14px; border: 1px solid #e1ddd4; border-radius: 10px; }
.capability-card div { display: flex; align-items: center; gap: 8px; }
.capability-card p { margin: 6px 0; }
.capability-value { color: #6558e8; font-weight: 650; }
.impact-pill { padding: 2px 7px; border-radius: 99px; color: #17613a; background: #def7e8; font-size: 11px; }
.event-list { max-height: 180px; overflow: auto; display: grid; gap: 6px; padding-left: 22px; }
.event-list li { display: flex; justify-content: space-between; gap: 12px; }
.event-list small { color: #626b7b; }
.auto-result { padding-top: 16px; border-top: 1px solid #e1ddd4; }
.auto-result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.auto-result-card { margin-top: 8px; padding: 12px; border: 1px solid #e1ddd4; border-radius: 10px; }
@media (max-width: 760px) { .auto-result-grid { grid-template-columns: 1fr; } }
</style>
