<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowDown,
  Clock,
  Close,
  CollectionTag,
  Loading,
  MagicStick,
  Plus,
  WarningFilled,
} from '@element-plus/icons-vue'
import { RouterLink } from 'vue-router'

import { request } from '../api/client'
import type {
  AutoAgentifyJobEvent,
  AutoAgentifyResult,
  LlmProviderSummary,
} from '../api/contracts'
import {
  useAutoAgentifyJob,
  type AutoAgentifySourceInput,
} from '../composables/useAutoAgentifyJob'

const props = defineProps<{ source: AutoAgentifySourceInput }>()
const emit = defineEmits<{
  generated: [result: AutoAgentifyResult]
  close: []
}>()
const { t, locale } = useI18n()
const providers = ref<LlmProviderSummary[]>([])
const providerId = ref('')
const showActivityHistory = ref(false)
const showAllBodySchemaIssues = ref(false)
const selectedSystemCapabilities = ref<string[]>([])
const customCapabilityInput = ref('')
const customCapabilityLabels = ref<string[]>([])
const systemCapabilities = [
  'system_configuration',
  'user_permissions',
  'organization_management',
  'file_management',
  'messaging_notifications',
  'task_scheduling',
  'audit_compliance',
  'reference_data',
  'monitoring_operations',
  'authentication_authorization',
  'sensitive_data_security',
  'developer_tools',
  'ai_platform',
] as const
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
const currentEvent = computed(() => events.value.at(-1) ?? null)
const activityHistory = computed(() => events.value.slice(0, -1).slice(-8).reverse())
const resultLanguage = computed<'zh-CN' | 'en-US'>(
  () => locale.value.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US',
)
const capabilityGroups = computed(() => {
  const groups = new Map<string, typeof capabilities.value>()
  for (const capability of capabilities.value) {
    const category = capability.category || 'core_business'
    const existing = groups.get(category) ?? []
    existing.push(capability)
    groups.set(category, existing)
  }
  return Array.from(groups, ([key, items]) => ({
    key,
    label: systemCapabilities.some((item) => item === key)
      ? t(`autoAgentify.systemCapabilities.${key}`)
      : key === 'core_business'
        ? t('autoAgentify.coreBusiness')
        : key,
    items,
  }))
})
const bodySchemaWarningEvent = computed(
  () => [...events.value].reverse().find((event) => event.kind === 'body_schema_warning'),
)
const bodySchemaIssues = computed(() => {
  const value = bodySchemaWarningEvent.value?.params.issues
    ?? job.value?.metrics.body_schema_issues
  if (!Array.isArray(value)) return []
  return value.filter((item): item is { operation_key: string, reasons: string[] } => (
    typeof item === 'object'
    && item !== null
    && typeof (item as Record<string, unknown>).operation_key === 'string'
    && Array.isArray((item as Record<string, unknown>).reasons)
  ))
})
const bodySchemaIssueCount = computed(() => Number(
  bodySchemaWarningEvent.value?.params.count
  ?? job.value?.metrics.body_schema_issue_count
  ?? bodySchemaIssues.value.length,
))
const visibleBodySchemaIssues = computed(() => (
  showAllBodySchemaIssues.value
    ? bodySchemaIssues.value
    : bodySchemaIssues.value.slice(0, 5)
))
const failureCode = computed(() => errorCode.value || job.value?.error_code || null)
const failed = computed(() => job.value?.status === 'failed' || Boolean(errorCode.value))
const submitLabel = computed(() => {
  if (starting.value) return t('autoAgentify.starting')
  if (active.value) return t('autoAgentify.running')
  if (failed.value) return t('autoAgentify.retry')
  return t('autoAgentify.confirm')
})
const failureMessage = computed(() => {
  const suffix = failureCode.value?.split('.').at(-1) ?? 'unknown'
  return t(`autoAgentify.errors.${suffix}`, t('autoAgentify.errors.unknown'))
})
const currentStageDetail = computed(() => {
  const event = currentEvent.value
  if (!event) return t('autoAgentify.events.queued')
  if (event.kind === 'capability_batch_started') {
    return t('autoAgentify.batchScope', {
      batch: event.params.batch,
      total: event.params.total,
      operations: event.params.operation_count,
    })
  }
  if (event.kind === 'operations_discovered') {
    return t('autoAgentify.operationScope', { count: event.params.count })
  }
  return eventLabel(event)
})
const currentActivityDetails = computed(() => {
  const event = currentEvent.value
  if (!event) return []
  const details: Array<{ label: string, value: string }> = []
  if (event.params.batch && event.params.total) {
    details.push({
      label: t('autoAgentify.activityBatch'),
      value: `${String(event.params.batch)} / ${String(event.params.total)}`,
    })
  }
  const operationCount = event.params.operation_count
    ?? event.params.count
    ?? job.value?.metrics.operation_count
  if (operationCount) {
    details.push({
      label: t('autoAgentify.activityOperations'),
      value: String(operationCount),
    })
  }
  for (const [key, label] of [
    ['capability_count', t('autoAgentify.activityCapabilities')],
    ['skill_count', t('autoAgentify.activitySkills')],
    ['agent_count', t('autoAgentify.activityAgents')],
  ]) {
    if (event.params[key]) {
      details.push({ label, value: String(event.params[key]) })
    }
  }
  details.push({
    label: t('autoAgentify.activityUpdated'),
    value: new Intl.DateTimeFormat(resultLanguage.value, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date(event.created_at)),
  })
  return details
})
const canAddCustomCapability = computed(() => {
  const value = customCapabilityInput.value.trim()
  return (
    Boolean(value)
    && value.length <= 80
    && customCapabilityLabels.value.length < 20
    && !customCapabilityLabels.value.includes(value)
  )
})

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
  if (job.value) {
    providerId.value = String(job.value.provider_id)
    const restoredSystemCapabilities = job.value.metrics.allowed_system_capabilities
    if (Array.isArray(restoredSystemCapabilities)) {
      selectedSystemCapabilities.value = restoredSystemCapabilities.filter(
        (item): item is string => (
          typeof item === 'string'
          && systemCapabilities.some((capability) => capability === item)
        ),
      )
    }
    const restoredCustomLabels = job.value.metrics.custom_capability_labels
    if (Array.isArray(restoredCustomLabels)) {
      customCapabilityLabels.value = restoredCustomLabels.filter(
        (item): item is string => typeof item === 'string',
      )
    }
  }
})

function eventLabel(event: Pick<AutoAgentifyJobEvent, 'kind' | 'params'>): string {
  const labels: Record<string, string> = {
    queued: t('autoAgentify.events.queued'),
    document_loaded: t('autoAgentify.events.documentLoaded'),
    openapi_validated: t('autoAgentify.events.openapiValidated'),
    operations_discovered: t('autoAgentify.events.operationsDiscovered'),
    capability_batch_started: t('autoAgentify.events.capabilityBatchStarted'),
    capability_batch_correction_started: t(
      'autoAgentify.events.capabilityBatchCorrectionStarted',
    ),
    capability_batch_fallback: t('autoAgentify.events.capabilityBatchFallback'),
    capability_filtered: t('autoAgentify.events.capabilityFiltered'),
    capability_discovered: t('autoAgentify.events.capabilityDiscovered'),
    capability_batch_completed: t('autoAgentify.events.capabilityBatchCompleted'),
    body_schema_warning: t('autoAgentify.events.bodySchemaWarning'),
    plan_synthesis_started: t('autoAgentify.events.planSynthesisStarted'),
    plan_correction_started: t('autoAgentify.events.planCorrectionStarted'),
    plan_fallback: t('autoAgentify.events.planFallback'),
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
  return labels[event.kind] ?? event.kind
}

function toggleSystemCapability(capability: string): void {
  selectedSystemCapabilities.value = selectedSystemCapabilities.value.includes(capability)
    ? selectedSystemCapabilities.value.filter((item) => item !== capability)
    : [...selectedSystemCapabilities.value, capability]
}

function addCustomCapability(): void {
  if (!canAddCustomCapability.value) return
  customCapabilityLabels.value.push(customCapabilityInput.value.trim())
  customCapabilityInput.value = ''
}

function removeCustomCapability(label: string): void {
  customCapabilityLabels.value = customCapabilityLabels.value.filter(
    (item) => item !== label,
  )
}

function runGeneration(): Promise<void> {
  return start(props.source, Number(providerId.value), {
    allowedSystemCapabilities: selectedSystemCapabilities.value,
    customCapabilityLabels: customCapabilityLabels.value,
    resultLanguage: resultLanguage.value,
  })
}
</script>

<template>
  <Teleport to="body">
    <div class="auto-agentify-backdrop" role="presentation">
      <section class="auto-agentify-modal" role="dialog" aria-modal="true" :aria-label="t('autoAgentify.title')">
        <header class="panel-heading">
          <div>
            <p class="eyebrow">{{ t('autoAgentify.eyebrow') }}</p>
            <h2>{{ t('autoAgentify.title') }}</h2>
            <p class="muted">{{ t('autoAgentify.subtitle') }}</p>
          </div>
          <button data-testid="auto-close" type="button" class="modal-close" :aria-label="t('autoAgentify.close')" @click="emit('close')"><Close aria-hidden="true" /></button>
        </header>

        <div class="auto-agentify-body">
          <div class="source-summary">
            <strong>{{ source.name || t('autoAgentify.missingName') }}</strong>
            <span>{{ source.mode === 'url' ? source.sourceUrl : source.file?.name }}</span>
          </div>
          <fieldset class="capability-preferences" :disabled="active">
            <legend>{{ t('autoAgentify.capabilityPreferences') }}</legend>
            <p>{{ t('autoAgentify.capabilityPreferencesHint') }}</p>
            <div class="system-capability-list">
              <button
                v-for="capability in systemCapabilities"
                :key="capability"
                :data-testid="`capability-system-${capability}`"
                type="button"
                class="capability-chip"
                :class="{ selected: selectedSystemCapabilities.includes(capability) }"
                :aria-pressed="selectedSystemCapabilities.includes(capability)"
                @click="toggleSystemCapability(capability)"
              >
                {{ t(`autoAgentify.systemCapabilities.${capability}`) }}
              </button>
            </div>
            <div class="custom-capability-entry">
              <label for="custom-capability">{{ t('autoAgentify.customCapability') }}</label>
              <div>
                <input
                  id="custom-capability"
                  v-model="customCapabilityInput"
                  data-testid="custom-capability-input"
                  maxlength="80"
                  :placeholder="t('autoAgentify.customCapabilityPlaceholder')"
                  @keydown.enter.prevent="addCustomCapability"
                />
                <button
                  data-testid="add-custom-capability"
                  type="button"
                  class="secondary-action"
                  :disabled="!canAddCustomCapability"
                  :aria-label="t('autoAgentify.addCustomCapability')"
                  @click="addCustomCapability"
                >
                  <Plus aria-hidden="true" />
                  {{ t('autoAgentify.add') }}
                </button>
              </div>
            </div>
            <div v-if="customCapabilityLabels.length" class="custom-capability-list">
              <span v-for="label in customCapabilityLabels" :key="label">
                {{ label }}
                <button type="button" :aria-label="t('autoAgentify.removeCustomCapability', { label })" @click="removeCustomCapability(label)">
                  <Close aria-hidden="true" />
                </button>
              </span>
            </div>
          </fieldset>
          <label class="provider-field">
            <span class="provider-label">{{ t('autoAgentify.provider') }}</span>
            <span class="provider-select-shell">
              <MagicStick class="provider-mark" aria-hidden="true" />
              <select v-model="providerId" data-testid="auto-provider" :disabled="active">
                <option value="">{{ t('autoAgentify.selectProvider') }}</option>
                <option v-for="provider in providers" :key="provider.id" :value="String(provider.id)">
                  {{ provider.name }} · {{ provider.default_model }}
                </option>
              </select>
              <ArrowDown class="provider-chevron" aria-hidden="true" />
            </span>
          </label>

          <div v-if="!job || failed" data-testid="auto-generation-notice" class="generation-notice">
            <strong>{{ t('autoAgentify.beforeRunTitle') }}</strong>
            <p>{{ t('autoAgentify.beforeRunHint') }}</p>
          </div>

          <p v-if="!sourceReady" class="form-error" role="alert">{{ t('autoAgentify.sourceIncomplete') }}</p>
          <button data-testid="auto-submit" class="primary-action" :disabled="!ready" @click="runGeneration">
            {{ submitLabel }}
          </button>
          <p v-if="active" class="background-hint">{{ t('autoAgentify.backgroundHint') }}</p>

          <section v-if="job" class="analysis-process" aria-live="polite">
            <div class="section-heading">
              <div>
                <p class="section-kicker">{{ t('autoAgentify.analysisProcessKicker') }}</p>
                <h3>{{ t('autoAgentify.analysisProcess') }}</h3>
              </div>
              <span>{{ job.progress }}%</span>
            </div>
            <div data-testid="auto-current-stage" class="current-activity">
              <div class="activity-orbit" aria-hidden="true">
                <Loading v-if="active" />
                <Clock v-else />
              </div>
              <div class="activity-copy">
                <small>{{ t('autoAgentify.currentActivity') }}</small>
                <strong>{{ currentStageDetail }}</strong>
                <div v-if="currentActivityDetails.length" class="activity-details">
                  <span v-for="detail in currentActivityDetails" :key="detail.label">
                    <small>{{ detail.label }}</small>{{ detail.value }}
                  </span>
                </div>
              </div>
            </div>
            <progress data-testid="auto-progress" :value="job.progress" max="100"></progress>

            <div v-if="bodySchemaIssueCount" data-testid="body-schema-warning" class="body-schema-warning" role="status">
              <div class="schema-warning-heading">
                <WarningFilled aria-hidden="true" />
                <div>
                  <strong>{{ t('autoAgentify.bodySchemaWarningTitle', { count: bodySchemaIssueCount }) }}</strong>
                  <p>{{ t('autoAgentify.bodySchemaWarningHint') }}</p>
                </div>
              </div>
              <ul v-if="visibleBodySchemaIssues.length" class="schema-issue-list">
                <li v-for="issue in visibleBodySchemaIssues" :key="issue.operation_key">
                  <code>{{ issue.operation_key }}</code>
                  <span>
                    <small v-for="reason in issue.reasons" :key="reason">
                      {{ t(`autoAgentify.bodySchemaReasons.${reason}`) }}
                    </small>
                  </span>
                </li>
              </ul>
              <button
                v-if="bodySchemaIssues.length > 5"
                type="button"
                class="schema-warning-toggle"
                @click="showAllBodySchemaIssues = !showAllBodySchemaIssues"
              >
                {{ showAllBodySchemaIssues ? t('autoAgentify.showFewerBodyIssues') : t('autoAgentify.showAllBodyIssues', { count: bodySchemaIssueCount }) }}
              </button>
            </div>

            <div v-if="failureCode" data-testid="auto-error" class="auto-error-panel" role="alert">
              <strong>{{ t('autoAgentify.failedTitle') }}</strong>
              <p>{{ failureMessage }}</p>
              <small>{{ failureCode }}</small>
            </div>

            <div v-if="activityHistory.length" class="event-section">
              <button
                type="button"
                class="activity-history-toggle"
                :aria-expanded="showActivityHistory"
                @click="showActivityHistory = !showActivityHistory"
              >
                <span>{{ showActivityHistory ? t('autoAgentify.hideActivityHistory') : t('autoAgentify.showActivityHistory') }}</span>
                <small>{{ activityHistory.length }}</small>
              </button>
              <ol class="event-list">
                <li v-for="event in showActivityHistory ? activityHistory : []" :key="event.sequence">
                  <span>{{ eventLabel(event) }}</span><small>{{ event.progress }}%</small>
                </li>
              </ol>
            </div>
          </section>

          <section v-if="capabilities.length || job?.result" class="recognition-results" data-testid="recognition-results">
            <div class="section-heading result-heading">
              <div>
                <p class="section-kicker">{{ t('autoAgentify.recognitionResultsKicker') }}</p>
                <h3>{{ t('autoAgentify.recognitionResults') }}</h3>
              </div>
              <span>{{ capabilities.length }}</span>
            </div>
            <p class="result-hint">{{ t('autoAgentify.recognitionResultsHint') }}</p>
            <div class="capability-groups">
              <section v-for="group in capabilityGroups" :key="group.key" class="capability-group">
                <header>
                  <CollectionTag aria-hidden="true" />
                  <strong>{{ group.label }}</strong>
                  <span>{{ group.items.length }}</span>
                </header>
                <details v-for="capability in group.items" :key="capability.name" class="capability-card">
                  <summary>
                    <span><strong>{{ capability.name }}</strong><span v-if="capability.high_impact" class="impact-pill">{{ t('autoAgentify.highImpact') }}</span></span>
                    <small>{{ capability.value }}</small>
                  </summary>
                  <div class="capability-detail">
                    <p>{{ capability.description }}</p>
                    <ol><li v-for="step in capability.workflow" :key="step">{{ step }}</li></ol>
                  </div>
                </details>
              </section>
            </div>

            <div v-if="job?.result" class="auto-result" data-testid="auto-result">
              <div class="result-summary">
                <strong>{{ t('autoAgentify.resultTitle') }}</strong>
                <p>{{ t('autoAgentify.counts', { tools: job.result.enabled_tool_count, imported: job.result.imported_tool_count, skills: job.result.skills.length, agents: job.result.agents.length }) }}</p>
              </div>
              <div class="result-actions">
                <RouterLink class="secondary-action" to="/admin/skills">{{ t('autoAgentify.reviewSkills') }}</RouterLink>
                <RouterLink class="secondary-action" to="/admin/agent">{{ t('autoAgentify.reviewAgents') }}</RouterLink>
              </div>
              <div class="auto-result-grid">
                <section><h4>{{ t('autoAgentify.skills') }}</h4><article v-for="skill in job.result.skills" :key="skill.id" class="auto-result-card"><strong>{{ skill.name }}</strong><p>{{ skill.description }}</p><p>{{ skill.value }}</p></article></section>
                <section><h4>{{ t('autoAgentify.agents') }}</h4><article v-for="agent in job.result.agents" :key="agent.id" class="auto-result-card"><strong>{{ agent.name }}</strong><p>{{ agent.description }}</p><p>{{ agent.value }}</p><ul><li v-for="useCase in agent.use_cases" :key="useCase">{{ useCase }}</li></ul></article></section>
              </div>
            </div>
          </section>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.auto-agentify-backdrop { position: fixed; z-index: 1000; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(23,32,51,.48); }
.auto-agentify-modal { width: min(760px, 100%); max-height: calc(100vh - 48px); overflow: hidden; display: grid; grid-template-rows: auto minmax(0, 1fr); border-radius: 16px; background: #fff; box-shadow: 0 24px 80px rgba(20,28,45,.28); }
.auto-agentify-modal > .panel-heading { margin: 0; padding: 24px; border-bottom: 1px solid #ebe8e1; background: #fff; }
.auto-agentify-body { min-height: 0; overflow: auto; display: grid; gap: 16px; padding: 20px 24px 24px; }
.modal-close { width: 36px; height: 36px; flex: 0 0 auto; display: grid; place-items: center; padding: 0; border: 0; border-radius: 9px; color: #727987; background: transparent; }
.modal-close:hover { color: var(--ink); background: #f3f1ec; }
.modal-close:focus-visible { outline: 3px solid rgba(101,88,232,.2); outline-offset: 1px; }
.modal-close svg { width: 17px; height: 17px; }
.source-summary { display: grid; gap: 4px; padding: 12px; border-radius: 10px; background: #f5f6f8; overflow-wrap: anywhere; }
.source-summary span { color: #626b7b; font-size: 13px; }
.capability-preferences { min-width: 0; margin: 0; padding: 14px; border: 1px solid #e1ddd4; border-radius: 11px; }
.capability-preferences legend { padding: 0 7px; color: #333b4a; font-size: 13px; font-weight: 800; }
.capability-preferences > p { margin: 0 0 12px; color: #6d7584; font-size: 12px; line-height: 1.5; }
.system-capability-list { display: flex; flex-wrap: wrap; gap: 7px; }
.capability-chip { min-height: 32px; padding: 0 11px; border: 1px solid #ddd9d0; border-radius: 99px; color: #707784; background: #f7f6f3; font-size: 12px; font-weight: 700; transition: border-color .15s ease, color .15s ease, background .15s ease, box-shadow .15s ease; }
.capability-chip:hover:not(:disabled) { border-color: #aaa3da; color: #4d45a1; }
.capability-chip.selected { border-color: #8c82ed; color: #4137a7; background: #eeecff; box-shadow: inset 0 0 0 1px rgba(101,88,232,.08); }
.capability-chip:focus-visible { outline: 3px solid rgba(101,88,232,.18); outline-offset: 1px; }
.custom-capability-entry { display: grid; gap: 6px; margin-top: 13px; }
.custom-capability-entry > label { color: #4f5767; font-size: 12px; font-weight: 800; }
.custom-capability-entry > div { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.custom-capability-entry input { min-width: 0; height: 40px; padding: 0 11px; border: 1px solid #d8d4ca; border-radius: 9px; outline: none; }
.custom-capability-entry input:focus-visible { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(101,88,232,.16); }
.custom-capability-entry .secondary-action { display: inline-flex; align-items: center; gap: 6px; }
.custom-capability-entry svg { width: 15px; height: 15px; }
.custom-capability-list { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }
.custom-capability-list > span { min-height: 30px; display: inline-flex; align-items: center; gap: 6px; padding: 0 5px 0 10px; border: 1px solid #d6cef8; border-radius: 99px; color: #4c429e; background: #f5f2ff; font-size: 12px; font-weight: 750; }
.custom-capability-list button { width: 23px; height: 23px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 50%; color: #7168ba; background: transparent; }
.custom-capability-list button:hover { color: #3d348e; background: #e7e2fb; }
.custom-capability-list svg { width: 13px; height: 13px; }
.provider-field { display: grid; gap: 8px; }
.provider-label { color: #4f5767; font-size: 12px; font-weight: 800; letter-spacing: .04em; }
.provider-select-shell { position: relative; display: block; }
.provider-mark, .provider-chevron { position: absolute; z-index: 1; top: 50%; width: 16px; height: 16px; transform: translateY(-50%); pointer-events: none; }
.provider-mark { left: 15px; color: var(--accent); }
.provider-chevron { right: 16px; color: #777f8d; }
.provider-select-shell select { appearance: none; width: 100%; height: 48px; padding: 0 46px 0 42px; border: 1px solid #d8d4ca; border-radius: 11px; outline: none; color: var(--ink); background: linear-gradient(180deg, #fff 0%, #fbfaf7 100%); box-shadow: 0 1px 2px rgba(20,28,45,.04); font-weight: 650; cursor: pointer; transition: border-color .16s ease, box-shadow .16s ease, background .16s ease; }
.provider-select-shell select:hover:not(:disabled) { border-color: #aaa3da; background: #fff; }
.provider-select-shell select:focus-visible { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(101,88,232,.16); }
.provider-select-shell select:disabled { color: #8a909b; background: #f1f0ec; cursor: not-allowed; }
.generation-notice { padding: 13px 14px; border: 1px solid #dedaf8; border-radius: 11px; background: #f7f5ff; }
.generation-notice strong { color: #4137a7; font-size: 13px; }
.generation-notice p, .background-hint { margin: 5px 0 0; color: #626b7b; font-size: 13px; line-height: 1.5; }
.background-hint { margin: -6px 0 0; text-align: center; }
progress { width: 100%; height: 9px; overflow: hidden; border: 0; border-radius: 99px; background: #ece9e2; }
progress::-webkit-progress-bar { background: #ece9e2; }
progress::-webkit-progress-value { border-radius: 99px; background: linear-gradient(90deg, #6558e8, #887df2); }
progress::-moz-progress-bar { border-radius: 99px; background: linear-gradient(90deg, #6558e8, #887df2); }
.analysis-process, .recognition-results { display: grid; gap: 12px; padding: 16px; border: 1px solid #dfdbe9; border-radius: 14px; }
.analysis-process { position: relative; overflow: hidden; background: linear-gradient(145deg, #fbfaff 0%, #f4f2ff 56%, #faf9f6 100%); }
.analysis-process::before { content: ""; position: absolute; width: 180px; height: 180px; top: -110px; right: -70px; border-radius: 50%; background: radial-gradient(circle, rgba(101,88,232,.18), rgba(101,88,232,0) 70%); pointer-events: none; }
.section-kicker { margin: 0 0 3px; color: #786fd0; font-size: 10px; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }
.current-activity { position: relative; display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; gap: 13px; padding: 14px; border: 1px solid rgba(115,102,220,.2); border-radius: 12px; background: rgba(255,255,255,.76); box-shadow: 0 8px 24px rgba(69,57,155,.08); backdrop-filter: blur(8px); }
.activity-orbit { width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid #dcd6ff; border-radius: 50%; color: #6558e8; background: #f0edff; box-shadow: 0 0 0 5px rgba(101,88,232,.06); }
.activity-orbit svg { width: 18px; height: 18px; }
.analysis-process .activity-orbit svg.el-icon-loading { animation: activity-spin 1.3s linear infinite; }
.activity-copy { min-width: 0; display: grid; gap: 4px; }
.activity-copy > small { color: #777f8d; font-size: 11px; font-weight: 750; }
.activity-copy > strong { color: #343b4a; font-size: 14px; line-height: 1.45; }
.activity-details { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; }
.activity-details > span { display: inline-flex; align-items: baseline; gap: 5px; padding: 4px 7px; border-radius: 7px; color: #454d5d; background: #f2f1f7; font-size: 11px; font-weight: 750; }
.activity-details small { color: #7a8190; font-size: 10px; font-weight: 650; }
@keyframes activity-spin { to { transform: rotate(360deg); } }
.body-schema-warning { display: grid; gap: 10px; padding: 13px; border: 1px solid #e8c77c; border-radius: 11px; color: #694d12; background: #fff9e9; }
.schema-warning-heading { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; gap: 9px; }
.schema-warning-heading > svg { width: 18px; height: 18px; margin-top: 1px; color: #c18212; }
.schema-warning-heading strong { font-size: 13px; }
.schema-warning-heading p { margin: 4px 0 0; color: #7b642f; font-size: 12px; line-height: 1.5; }
.schema-issue-list { max-height: 210px; overflow: auto; display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.schema-issue-list li { display: grid; gap: 5px; padding: 8px 9px; border-radius: 8px; background: rgba(255,255,255,.7); }
.schema-issue-list code { overflow-wrap: anywhere; color: #59430f; font-size: 11px; font-weight: 750; }
.schema-issue-list li > span { display: flex; flex-wrap: wrap; gap: 5px; }
.schema-issue-list small { padding: 2px 6px; border-radius: 99px; color: #795512; background: #f8e8bd; font-size: 10px; font-weight: 700; }
.schema-warning-toggle { justify-self: start; padding: 0; border: 0; color: #7c5814; background: transparent; font-size: 11px; font-weight: 800; text-decoration: underline; text-underline-offset: 3px; }
.auto-error-panel { padding: 14px; border: 1px solid #efc4c4; border-radius: 11px; color: #8b2929; background: #fff4f4; }
.auto-error-panel p { margin: 5px 0; color: #733737; line-height: 1.5; }
.auto-error-panel small { color: #9c5c5c; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-heading h3, .event-section h3 { margin: 0; font-size: 16px; }
.section-heading > span { min-width: 28px; height: 24px; display: grid; place-items: center; padding: 0 8px; border-radius: 99px; color: #5046b8; background: #eeecff; font-size: 12px; font-weight: 800; }
.recognition-results { background: #fff; }
.result-heading { padding-bottom: 3px; }
.result-hint { margin: -5px 0 2px; color: #6d7584; font-size: 12px; line-height: 1.5; }
.capability-groups { display: grid; gap: 12px; }
.capability-group { display: grid; gap: 8px; padding: 11px; border: 1px solid #e6e2da; border-radius: 12px; background: #faf9f6; }
.capability-group > header { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 8px; color: #3f4654; }
.capability-group > header svg { width: 16px; height: 16px; color: #6558e8; }
.capability-group > header > span { min-width: 24px; height: 22px; display: grid; place-items: center; border-radius: 99px; color: #5a50bd; background: #ece9ff; font-size: 11px; font-weight: 800; }
.capability-card { border: 1px solid #e1ddd4; border-radius: 10px; background: #fff; }
.capability-card summary { padding: 12px 14px; cursor: pointer; list-style-position: outside; }
.capability-card summary > span { display: flex; align-items: center; gap: 8px; }
.capability-card summary small { display: block; margin-top: 5px; color: #6558e8; line-height: 1.45; font-weight: 650; }
.capability-detail { padding: 0 14px 14px; border-top: 1px solid #efede8; }
.capability-detail p { margin: 12px 0 8px; color: #555e6d; line-height: 1.55; }
.capability-detail ol { margin-bottom: 0; padding-left: 22px; }
.impact-pill { padding: 2px 7px; border-radius: 99px; color: #17613a; background: #def7e8; font-size: 11px; }
.event-section { display: grid; gap: 10px; }
.activity-history-toggle { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 4px 2px; border: 0; color: #5e6573; background: transparent; font-size: 12px; font-weight: 750; }
.activity-history-toggle:hover { color: #4e43b5; }
.activity-history-toggle small { min-width: 22px; height: 20px; display: grid; place-items: center; border-radius: 99px; color: #665bc6; background: #ece9ff; }
.event-list { margin: 0; display: grid; gap: 7px; padding-left: 22px; }
.event-list:empty { display: none; }
.event-list li { justify-content: space-between; gap: 12px; color: #5f6674; font-size: 12px; }
.event-list small { color: #626b7b; }
.auto-result { padding-top: 14px; border-top: 1px solid #e1ddd4; }
.result-summary p { margin: 5px 0 0; color: #646c7b; font-size: 13px; }
.result-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.result-actions a { display: inline-flex; align-items: center; text-decoration: none; }
.auto-result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.auto-result-card { margin-top: 8px; padding: 12px; border: 1px solid #e1ddd4; border-radius: 10px; }
@media (max-width: 760px) {
  .auto-agentify-backdrop { padding: 12px; }
  .auto-agentify-modal { max-height: calc(100vh - 24px); }
  .auto-agentify-modal > .panel-heading, .auto-agentify-body { padding: 18px; }
  .auto-result-grid { grid-template-columns: 1fr; }
  .current-activity { grid-template-columns: 1fr; }
  .custom-capability-entry > div { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .analysis-process .activity-orbit svg.el-icon-loading { animation: none; }
}
</style>
