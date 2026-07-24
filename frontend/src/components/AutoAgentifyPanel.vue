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

import { ApiError, request } from '../api/client'
import type {
  ApiSourceSummary,
  AutoAgentifyJob,
  AutoAgentifyJobEvent,
  AutoAgentifyResult,
  LlmProviderSummary,
} from '../api/contracts'
import {
  useAutoAgentifyJob,
  type AutoAgentifySourceInput,
} from '../composables/useAutoAgentifyJob'
import { useToolsStore } from '../stores/tools'

const props = defineProps<{
  source: AutoAgentifySourceInput
  sourceRecord?: ApiSourceSummary | null
  resumeJobId?: string | null
}>()
const emit = defineEmits<{
  generated: [result: AutoAgentifyResult]
  sourceImported: [source: ApiSourceSummary]
  started: [job: AutoAgentifyJob]
  stopped: []
  close: []
}>()
const { t, locale } = useI18n()
const toolsStore = useToolsStore()
const providers = ref<LlmProviderSummary[]>([])
const providerId = ref('')
const activeSource = ref<ApiSourceSummary | null>(props.sourceRecord ?? null)
const importingSource = ref(false)
const importErrorCode = ref<string | null>(null)
const importErrorParams = ref<Record<string, unknown>>({})
const currentStep = ref<1 | 2 | 3 | 4>(1)
const showActivityHistory = ref(false)
const showAllBodySchemaIssues = ref(false)
const selectedSystemCapabilities = ref<string[]>([])
const customCapabilityInput = ref('')
const customCapabilityLabels = ref<string[]>([])
const systemCapabilities = [
  'order_query',
  'order_fulfillment',
  'public_services',
  'intelligent_customer_service',
  'information_search',
  'reporting_analytics',
  'appointment_booking',
  'application_approval',
  'case_ticket_management',
  'customer_management',
  'product_service_catalog',
  'billing_payments',
  'logistics_tracking',
  'task_collaboration',
  'system_configuration',
  'user_permissions',
  'file_management',
  'messaging_notifications',
  'audit_compliance',
  'sensitive_data_security',
] as const
const {
  job,
  events,
  capabilities,
  starting,
  stopping,
  active,
  errorCode,
  errorParams,
  load,
  start,
  stop,
} = useAutoAgentifyJob()

const sourceReady = computed(() => (
  activeSource.value !== null
  || (
    Boolean(props.source.name.trim())
  && (
    props.source.mode === 'url'
      ? Boolean(props.source.sourceUrl.trim())
      : props.source.file !== null
  )
  )
))
const ready = computed(
  () => (
    Boolean(providerId.value)
    && sourceReady.value
    && !importingSource.value
    && !starting.value
    && !active.value
  ),
)
const selectedProvider = computed(
  () => providers.value.find((provider) => String(provider.id) === providerId.value) ?? null,
)
const forbiddenCapabilityCount = computed(
  () => systemCapabilities.length - selectedSystemCapabilities.value.length,
)
const wizardSteps = computed(() => [
  t('autoAgentifyWizard.source'),
  t('autoAgentifyWizard.scope'),
  t('autoAgentifyWizard.analysis'),
  t('autoAgentifyWizard.results'),
])
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
const failureCode = computed(
  () => importErrorCode.value || errorCode.value || job.value?.error_code || null,
)
const failed = computed(
  () => job.value?.status === 'failed'
    || Boolean(importErrorCode.value)
    || Boolean(errorCode.value),
)
const stopped = computed(() => job.value?.status === 'cancelled')
const submitLabel = computed(() => {
  if (importingSource.value) return t('autoAgentify.importingSource')
  if (starting.value) return t('autoAgentify.starting')
  if (active.value) return t('autoAgentify.running')
  if (failed.value || stopped.value) return t('autoAgentify.retry')
  return t('autoAgentify.confirm')
})
const failureMessage = computed(() => {
  if (failureCode.value === 'auth.session_invalid') {
    return t('error.auth.session_invalid')
  }
  if (failureCode.value === 'auto_agentify.source_tools_missing') {
    return t('autoAgentify.sourceToolsMissing')
  }
  const suffix = failureCode.value?.split('.').at(-1) ?? 'unknown'
  return t(`autoAgentify.errors.${suffix}`, t('autoAgentify.errors.unknown'))
})
const failureReason = computed(() => {
  if (failureCode.value === 'auth.session_invalid') return null
  const params = importErrorCode.value
    ? importErrorParams.value
    : (errorCode.value ? errorParams.value : (job.value?.error_params ?? {}))
  return typeof params.reason === 'string' && params.reason.trim()
    ? params.reason.trim()
    : null
})
const showFailureCode = computed(() => failureCode.value !== 'auth.session_invalid')
const currentStageDetail = computed(() => {
  if (stopped.value) return t('autoAgentify.stopped')
  const event = currentEvent.value
  if (!event) return t('autoAgentify.events.queued')
  if (event.kind === 'analysis_strategy_selected') {
    return event.params.mode === 'holistic'
      ? t('autoAgentify.analysisHolistic', {
        operations: event.params.operation_count,
      })
      : t('autoAgentify.analysisDomainStrategy', {
        operations: event.params.operation_count,
        domains: event.params.domain_count,
      })
  }
  if (event.kind === 'capability_batch_started') {
    if (event.params.mode === 'holistic') {
      return t('autoAgentify.analysisHolisticRunning', {
        operations: event.params.operation_count,
      })
    }
    if (event.params.mode === 'domain_groups') {
      return t('autoAgentify.analysisDomainRunning', {
        domain: event.params.domain,
        index: event.params.batch,
        total: event.params.total,
        operations: event.params.operation_count,
      })
    }
    return t('autoAgentify.batchScope', {
      batch: event.params.batch,
      total: event.params.total,
      operations: event.params.operation_count,
    })
  }
  if (event.kind === 'capability_consolidation_started') {
    return t('autoAgentify.analysisConsolidating', {
      capabilities: event.params.input_count,
      domains: event.params.domain_count,
    })
  }
  if (event.kind === 'capability_consolidation_completed') {
    return t('autoAgentify.analysisConsolidated', {
      input: event.params.input_count,
      output: event.params.output_count,
      merged: event.params.merged_count,
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
  if (event.params.domain) {
    details.push({
      label: t('autoAgentify.activityDomain'),
      value: String(event.params.domain),
    })
  }
  if (event.params.domain_count) {
    details.push({
      label: t('autoAgentify.activityDomains'),
      value: String(event.params.domain_count),
    })
  }
  if (event.params.estimated_chars) {
    details.push({
      label: t('autoAgentify.activityContextSize'),
      value: new Intl.NumberFormat(resultLanguage.value).format(
        Number(event.params.estimated_chars),
      ),
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
    if (result) {
      currentStep.value = 4
      emit('generated', result)
    }
  },
)
watch(
  () => job.value?.status,
  (status) => {
    if (status === 'completed' && job.value?.result) currentStep.value = 4
    else if (
      status === 'queued'
      || status === 'running'
      || status === 'failed'
      || status === 'cancelled'
    ) {
      currentStep.value = 3
    }
  },
)

onMounted(async () => {
  providers.value = (await request<LlmProviderSummary[]>('/api/admin/build/providers'))
    .filter((provider) => provider.enabled)
  if (providers.value.length === 1) providerId.value = String(providers.value[0].id)
  if (props.resumeJobId) await load(props.resumeJobId)
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
    source_tools_loaded: t('autoAgentify.sourceToolsLoaded'),
    analysis_strategy_selected: t('autoAgentify.analysisStrategySelected'),
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
    capability_consolidation_started: t('autoAgentify.analysisConsolidationStarted'),
    capability_consolidated: t('autoAgentify.capabilityConsolidated'),
    capability_consolidation_completed: t('autoAgentify.analysisConsolidationCompleted'),
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

async function runGeneration(): Promise<void> {
  currentStep.value = 3
  importErrorCode.value = null
  importErrorParams.value = {}
  if (!activeSource.value) {
    importingSource.value = true
    try {
      activeSource.value = props.source.mode === 'url'
        ? await toolsStore.importUrl(
          props.source.name.trim(),
          props.source.sourceUrl.trim(),
          props.source.baseUrl.trim() || undefined,
          props.source.allowPrivateNetworks,
        )
        : await toolsStore.importFile(
          props.source.name.trim(),
          props.source.file as File,
          props.source.baseUrl.trim() || undefined,
          props.source.allowPrivateNetworks,
        )
      emit('sourceImported', activeSource.value)
    } catch (error) {
      importErrorCode.value = error instanceof ApiError ? error.code : 'unknown'
      importErrorParams.value = error instanceof ApiError ? error.params : {}
      return
    } finally {
      importingSource.value = false
    }
  }
  await start(activeSource.value.id, Number(providerId.value), {
    allowedSystemCapabilities: selectedSystemCapabilities.value,
    customCapabilityLabels: customCapabilityLabels.value,
    resultLanguage: resultLanguage.value,
  })
  if (job.value) emit('started', job.value)
}

async function stopGeneration(): Promise<void> {
  await stop()
  emit('stopped')
}

function continueToScope(): void {
  if (!sourceReady.value || !providerId.value) return
  currentStep.value = 2
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

        <ol class="wizard-steps" :aria-label="t('autoAgentifyWizard.progress')">
          <li
            v-for="(step, index) in wizardSteps"
            :key="step"
            :class="{ current: currentStep === index + 1, complete: currentStep > index + 1 }"
            :aria-current="currentStep === index + 1 ? 'step' : undefined"
          >
            <span>{{ currentStep > index + 1 ? '✓' : index + 1 }}</span>
            <small>{{ step }}</small>
          </li>
        </ol>

        <div class="auto-agentify-body">
          <div v-if="currentStep === 1" class="wizard-intro">
            <p class="section-kicker">{{ t('autoAgentifyWizard.step', { current: 1, total: 4 }) }}</p>
            <h3>{{ t('autoAgentifyWizard.sourceTitle') }}</h3>
            <p>{{ t('autoAgentifyWizard.sourceHint') }}</p>
          </div>
          <div v-if="currentStep === 1" class="source-summary">
            <strong>{{ source.name || t('autoAgentify.missingName') }}</strong>
            <span>{{ source.mode === 'url' ? source.sourceUrl : source.file?.name }}</span>
          </div>
          <div v-if="currentStep === 2" class="wizard-intro">
            <p class="section-kicker">{{ t('autoAgentifyWizard.step', { current: 2, total: 4 }) }}</p>
            <h3>{{ t('autoAgentifyWizard.scopeTitle') }}</h3>
            <p>{{ t('autoAgentify.capabilityPreferencesHint') }}</p>
          </div>
          <div v-if="currentStep === 2" class="wizard-context">
            <span><small>{{ t('autoAgentifyWizard.source') }}</small><strong>{{ source.name }}</strong></span>
            <span><small>{{ t('autoAgentify.provider') }}</small><strong>{{ selectedProvider?.name }}</strong></span>
            <span><small>{{ t('autoAgentifyWizard.allowed') }}</small><strong>{{ selectedSystemCapabilities.length }}</strong></span>
            <span><small>{{ t('autoAgentifyWizard.forbidden') }}</small><strong>{{ forbiddenCapabilityCount }}</strong></span>
          </div>
          <fieldset v-if="currentStep === 2" class="capability-preferences" :disabled="active">
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
          <label v-if="currentStep === 1" class="provider-field">
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

          <p v-if="currentStep === 1 && !sourceReady" class="form-error" role="alert">{{ t('autoAgentify.sourceIncomplete') }}</p>
          <div v-if="currentStep === 1" class="wizard-actions">
            <button data-testid="wizard-next" type="button" class="primary-action" :disabled="!sourceReady || !providerId" @click="continueToScope">
              {{ t('autoAgentifyWizard.nextScope') }}
            </button>
          </div>

          <div v-if="currentStep === 2" data-testid="auto-generation-notice" class="generation-notice">
            <strong>{{ t('autoAgentify.beforeRunTitle') }}</strong>
            <p>{{ t('autoAgentify.beforeRunHint') }}</p>
          </div>

          <div v-if="currentStep === 2" class="wizard-actions split">
            <button type="button" class="secondary-action" @click="currentStep = 1">{{ t('autoAgentifyWizard.back') }}</button>
            <button data-testid="auto-submit" class="primary-action" :disabled="!ready" @click="runGeneration">{{ submitLabel }}</button>
          </div>
          <p v-if="currentStep === 3 && active" class="background-hint">{{ t('autoAgentify.backgroundHint') }}</p>

          <section v-if="currentStep === 3 && importingSource" class="analysis-process" aria-live="polite">
            <div class="section-heading">
              <div>
                <p class="section-kicker">{{ t('autoAgentify.analysisProcessKicker') }}</p>
                <h3>{{ t('autoAgentify.analysisProcess') }}</h3>
              </div>
              <span>5%</span>
            </div>
            <div data-testid="auto-current-stage" class="current-activity">
              <div class="activity-orbit is-loading" aria-hidden="true">
                <Loading
                  class="analysis-loading-icon"
                  data-testid="auto-analysis-loading"
                />
              </div>
              <div class="activity-copy">
                <small>{{ t('autoAgentify.currentActivity') }}</small>
                <strong>{{ t('autoAgentify.importingSourceDetail') }}</strong>
              </div>
            </div>
            <progress data-testid="auto-progress" value="5" max="100"></progress>
          </section>

          <section v-if="currentStep === 3 && job" class="analysis-process" aria-live="polite">
            <div class="section-heading">
              <div>
                <p class="section-kicker">{{ t('autoAgentify.analysisProcessKicker') }}</p>
                <h3>{{ t('autoAgentify.analysisProcess') }}</h3>
              </div>
              <span>{{ job.progress }}%</span>
            </div>
            <div data-testid="auto-current-stage" class="current-activity">
              <div class="activity-orbit" :class="{ 'is-loading': active }" aria-hidden="true">
                <Loading
                  v-if="active"
                  class="analysis-loading-icon"
                  data-testid="auto-analysis-loading"
                />
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
              <p v-if="failureReason" class="auto-error-reason">{{ failureReason }}</p>
              <small v-if="showFailureCode">{{ failureCode }}</small>
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

          <div v-if="currentStep === 3 && active" class="wizard-actions">
            <button
              data-testid="auto-stop"
              type="button"
              class="danger-action"
              :disabled="stopping"
              @click="stopGeneration"
            >
              {{ stopping ? t('autoAgentify.stopping') : t('autoAgentify.stop') }}
            </button>
          </div>

          <div v-if="currentStep === 3 && failureCode && !job" data-testid="auto-error" class="auto-error-panel" role="alert">
            <strong>{{ t('autoAgentify.failedTitle') }}</strong>
            <p>{{ failureMessage }}</p>
            <p v-if="failureReason" class="auto-error-reason">{{ failureReason }}</p>
            <small v-if="showFailureCode">{{ failureCode }}</small>
          </div>

          <div v-if="currentStep === 3 && job?.result" class="wizard-actions">
            <button type="button" class="primary-action" @click="currentStep = 4">{{ t('autoAgentifyWizard.viewResults') }}</button>
          </div>
          <div v-if="currentStep === 3 && (failed || stopped)" class="wizard-actions split">
            <button type="button" class="secondary-action" @click="currentStep = 2">{{ t('autoAgentifyWizard.adjust') }}</button>
            <button data-testid="auto-submit" class="primary-action" :disabled="!ready" @click="runGeneration">{{ submitLabel }}</button>
          </div>

          <section v-if="currentStep === 4 && (capabilities.length || job?.result)" class="recognition-results" data-testid="recognition-results">
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
              <div class="result-hero">
                <span class="result-hero-icon"><MagicStick aria-hidden="true" /></span>
                <div class="result-summary">
                  <strong>{{ t('autoAgentify.resultTitle') }}</strong>
                  <p>{{ t('autoAgentify.counts', { tools: job.result.enabled_tool_count, imported: job.result.imported_tool_count, skills: job.result.skills.length, agents: job.result.agents.length }) }}</p>
                </div>
                <div class="result-actions">
                  <RouterLink class="secondary-action" to="/admin/skills">{{ t('autoAgentify.reviewSkills') }}</RouterLink>
                  <RouterLink class="secondary-action" to="/admin/agent">{{ t('autoAgentify.reviewAgents') }}</RouterLink>
                </div>
              </div>
              <div class="result-metrics">
                <div><strong>{{ job.result.enabled_tool_count }}<small>/{{ job.result.imported_tool_count }}</small></strong><span>{{ t('autoAgentify.enabledTools') }}</span></div>
                <div><strong>{{ job.result.skills.length }}</strong><span>{{ t('autoAgentify.skills') }}</span></div>
                <div><strong>{{ job.result.agents.length }}</strong><span>{{ t('autoAgentify.agents') }}</span></div>
              </div>
              <div class="auto-result-grid">
                <section class="result-column">
                  <header><span>S</span><h4>{{ t('autoAgentify.skills') }}</h4><small>{{ job.result.skills.length }}</small></header>
                  <article v-for="(skill, index) in job.result.skills" :key="skill.id" class="auto-result-card skill-result-card">
                    <div class="result-card-title"><span>{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ skill.name }}</strong></div>
                    <p class="result-card-value">{{ skill.value }}</p>
                    <p class="result-card-description">{{ skill.description }}</p>
                  </article>
                </section>
                <section class="result-column">
                  <header><span>A</span><h4>{{ t('autoAgentify.agents') }}</h4><small>{{ job.result.agents.length }}</small></header>
                  <article v-for="(agent, index) in job.result.agents" :key="agent.id" class="auto-result-card agent-result-card">
                    <div class="result-card-title"><span>{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ agent.name }}</strong></div>
                    <p class="result-card-value">{{ agent.value }}</p>
                    <p class="result-card-description">{{ agent.description }}</p>
                    <div v-if="agent.use_cases.length" class="result-use-cases">
                      <strong>{{ t('autoAgentify.useCases') }}</strong>
                      <ul><li v-for="useCase in agent.use_cases" :key="useCase">{{ useCase }}</li></ul>
                    </div>
                  </article>
                </section>
              </div>
            </div>
            <div class="wizard-actions split result-footer">
              <div class="result-footer-left" data-testid="result-footer-left">
                <button type="button" class="secondary-action" @click="currentStep = 3">{{ t('autoAgentifyWizard.reviewAnalysis') }}</button>
                <button type="button" class="secondary-action" @click="currentStep = 2">{{ t('autoAgentifyWizard.generateAgain') }}</button>
              </div>
              <button
                data-testid="auto-complete"
                type="button"
                class="primary-action"
                @click="emit('close')"
              >
                {{ t('autoAgentifyWizard.complete') }}
              </button>
            </div>
          </section>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.auto-agentify-backdrop { position: fixed; z-index: 1000; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(23,32,51,.48); }
.auto-agentify-modal { width: min(820px, 100%); max-height: calc(100vh - 48px); overflow: hidden; display: grid; grid-template-rows: auto auto minmax(0, 1fr); border-radius: 16px; background: #fff; box-shadow: 0 24px 80px rgba(20,28,45,.28); }
.auto-agentify-modal > .panel-heading { margin: 0; padding: 24px; border-bottom: 1px solid #ebe8e1; background: #fff; }
.auto-agentify-body { min-height: 0; overflow: auto; display: grid; gap: 16px; padding: 20px 24px 24px; }
.wizard-steps { counter-reset: wizard; margin: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); padding: 14px 24px; border-bottom: 1px solid #ebe8e1; background: #fbfaf7; list-style: none; }
.wizard-steps li { position: relative; min-width: 0; display: grid; justify-items: center; gap: 6px; color: #959aa4; text-align: center; }
.wizard-steps li:not(:last-child)::after { content: ""; position: absolute; top: 13px; left: calc(50% + 18px); right: calc(-50% + 18px); height: 2px; background: #e3e0d9; }
.wizard-steps li.complete:not(:last-child)::after { background: #8b82e9; }
.wizard-steps li > span { position: relative; z-index: 1; width: 28px; height: 28px; display: grid; place-items: center; border: 2px solid #ddd9d1; border-radius: 50%; background: #fff; font-size: 11px; font-weight: 850; }
.wizard-steps li.current { color: #4137a7; }
.wizard-steps li.current > span { border-color: #6558e8; color: #fff; background: #6558e8; box-shadow: 0 0 0 5px rgba(101,88,232,.11); }
.wizard-steps li.complete { color: #5148ad; }
.wizard-steps li.complete > span { border-color: #8b82e9; color: #5148ad; background: #eeecff; }
.wizard-steps small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 750; }
.wizard-intro { display: grid; gap: 5px; }
.wizard-intro h3 { margin: 0; color: #303746; font-size: 19px; }
.wizard-intro > p:last-child { margin: 0; color: #697180; font-size: 13px; line-height: 1.55; }
.wizard-context { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; padding: 10px; border: 1px solid #e6e2da; border-radius: 11px; background: #faf9f6; }
.wizard-context > span { min-width: 0; display: grid; gap: 2px; padding: 5px 7px; }
.wizard-context small { color: #7b8290; font-size: 10px; font-weight: 700; }
.wizard-context strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #404756; font-size: 12px; }
.wizard-actions { display: flex; justify-content: flex-end; gap: 9px; padding-top: 4px; }
.wizard-actions.split { justify-content: space-between; }
.wizard-actions .primary-action { margin: 0; }
.result-footer { margin-top: 4px; padding-top: 14px; border-top: 1px solid #e6e2da; }
.result-footer-left { display: flex; flex-wrap: wrap; gap: 9px; }
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
.analysis-process .activity-orbit.is-loading { animation: activity-pulse 1.6s ease-in-out infinite; }
.analysis-process .analysis-loading-icon { animation: activity-spin 1s linear infinite; }
.activity-copy { min-width: 0; display: grid; gap: 4px; }
.activity-copy > small { color: #777f8d; font-size: 11px; font-weight: 750; }
.activity-copy > strong { color: #343b4a; font-size: 14px; line-height: 1.45; }
.activity-details { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; }
.activity-details > span { display: inline-flex; align-items: baseline; gap: 5px; padding: 4px 7px; border-radius: 7px; color: #454d5d; background: #f2f1f7; font-size: 11px; font-weight: 750; }
.activity-details small { color: #7a8190; font-size: 10px; font-weight: 650; }
@keyframes activity-spin { to { transform: rotate(360deg); } }
@keyframes activity-pulse {
  0%, 100% { box-shadow: 0 0 0 5px rgba(101,88,232,.06); }
  50% { box-shadow: 0 0 0 9px rgba(101,88,232,.14); }
}
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
.auto-result { display: grid; gap: 14px; padding-top: 16px; border-top: 1px solid #e1ddd4; }
.result-hero { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 14px; border: 1px solid #ddd8fb; border-radius: 13px; background: linear-gradient(135deg, #f4f1ff 0%, #fbfaff 58%, #fff 100%); }
.result-hero-icon { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 12px; color: #fff; background: linear-gradient(145deg, #6558e8, #8b80f1); box-shadow: 0 7px 18px rgba(89,76,211,.24); }
.result-hero-icon svg { width: 20px; height: 20px; }
.result-summary { min-width: 0; }
.result-summary > strong { color: #312b77; font-size: 15px; }
.result-summary p { margin: 4px 0 0; color: #646c7b; font-size: 12px; line-height: 1.45; }
.result-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }
.result-actions a { display: inline-flex; align-items: center; text-decoration: none; }
.result-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.result-metrics > div { min-width: 0; display: grid; gap: 2px; padding: 11px 13px; border: 1px solid #e6e2da; border-radius: 11px; background: #faf9f6; }
.result-metrics strong { color: #373e4d; font-size: 20px; line-height: 1.1; }
.result-metrics strong small { color: #8b91a0; font-size: 12px; }
.result-metrics span { overflow: hidden; color: #747b89; font-size: 10px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.auto-result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: 14px; }
.result-column { min-width: 0; display: grid; gap: 9px; }
.result-column > header { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 0 2px; }
.result-column > header > span { width: 24px; height: 24px; display: grid; place-items: center; border-radius: 7px; color: #554abd; background: #ece9ff; font-size: 11px; font-weight: 900; }
.result-column > header h4 { margin: 0; color: #3d4452; font-size: 13px; }
.result-column > header small { min-width: 24px; height: 22px; display: grid; place-items: center; border-radius: 99px; color: #696f7b; background: #f0eee9; font-size: 10px; font-weight: 800; }
.auto-result-card { min-width: 0; padding: 13px; border: 1px solid #e2ded6; border-radius: 11px; background: #fff; box-shadow: 0 3px 10px rgba(31,35,48,.035); }
.result-card-title { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 8px; }
.result-card-title > span { color: #9188df; font-size: 10px; font-weight: 850; letter-spacing: .08em; }
.result-card-title > strong { overflow-wrap: anywhere; color: #343b49; font-size: 13px; }
.result-card-value { margin: 10px 0 0; padding: 8px 9px; border-left: 3px solid #8b80ea; border-radius: 0 7px 7px 0; color: #4d45a1; background: #f5f3ff; font-size: 11px; font-weight: 700; line-height: 1.5; }
.result-card-description { margin: 9px 0 0; color: #646c7b; font-size: 11px; line-height: 1.55; }
.result-use-cases { margin-top: 10px; padding-top: 9px; border-top: 1px dashed #e2ded6; }
.result-use-cases > strong { color: #737987; font-size: 10px; letter-spacing: .06em; text-transform: uppercase; }
.result-use-cases ul { display: grid; gap: 4px; margin: 6px 0 0; padding-left: 17px; color: #555d6c; font-size: 11px; line-height: 1.45; }
@media (max-width: 760px) {
  .auto-agentify-backdrop { padding: 12px; }
  .auto-agentify-modal { max-height: calc(100vh - 24px); }
  .auto-agentify-modal > .panel-heading, .auto-agentify-body { padding: 18px; }
  .wizard-steps { padding: 12px 14px; }
  .wizard-steps small { font-size: 9px; }
  .wizard-context { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .auto-result-grid { grid-template-columns: 1fr; }
  .result-hero { grid-template-columns: auto minmax(0, 1fr); }
  .result-actions { grid-column: 1 / -1; justify-content: stretch; }
  .result-actions a { flex: 1; justify-content: center; }
  .current-activity { grid-template-columns: 1fr; }
  .custom-capability-entry > div { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .analysis-process .activity-orbit.is-loading,
  .analysis-process .analysis-loading-icon { animation: none; }
}
</style>
