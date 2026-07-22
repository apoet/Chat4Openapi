<script setup lang="ts">
import { computed, inject, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { routeLocationKey, routerKey } from 'vue-router'

import type { ToolBatchAction, ToolBatchFailed, ToolSummary } from '../api/contracts'
import ToolBulkBar from '../components/ToolBulkBar.vue'
import { useToolsStore } from '../stores/tools'

interface ToolParameterView {
  name: string
  description: string | null
  example: unknown
  type: string
  location: string
  required: boolean
}

interface ToolDisplay extends ToolSummary {
  parameters: ToolParameterView[]
}

interface ToolTagGroup {
  name: string
  tools: ToolDisplay[]
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function parameterType(schema: Record<string, unknown>): string {
  const type = typeof schema.type === 'string' ? schema.type : 'any'
  const format = typeof schema.format === 'string' ? schema.format : null
  if (type === 'array') {
    const itemType = record(schema.items).type
    return typeof itemType === 'string' ? `array<${itemType}>` : 'array'
  }
  return format ? `${type} · ${format}` : type
}

const MAX_BATCH_TOOLS = 200

function displayExample(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function exampleDraft(value: unknown): string {
  if (value === undefined || value === null) return ''
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function parseExample(value: string): unknown | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  try {
    return JSON.parse(trimmed) as unknown
  } catch {
    return trimmed
  }
}

function toolParameters(tool: ToolSummary): ToolParameterView[] {
  const inputSchema = record(tool.input_schema)
  const properties = record(inputSchema.properties)
  const required = new Set(
    Array.isArray(inputSchema.required)
      ? inputSchema.required.filter((item): item is string => typeof item === 'string')
      : [],
  )
  const locations = new Map<string, string>()
  const executionSchema = record(tool.execution_schema)
  const executionParameters = executionSchema.parameters
  if (Array.isArray(executionParameters)) {
    for (const rawParameter of executionParameters) {
      const parameter = record(rawParameter)
      if (typeof parameter.argument === 'string' && typeof parameter.in === 'string') {
        locations.set(parameter.argument, parameter.in)
      }
    }
  }
  const requestBody = record(executionSchema.request_body)
  if (Array.isArray(requestBody.arguments)) {
    for (const argument of requestBody.arguments) {
      if (typeof argument === 'string') locations.set(argument, 'body')
    }
  } else if (typeof requestBody.argument === 'string') {
    locations.set(requestBody.argument, 'body')
  }
  return Object.entries(properties).map(([name, rawSchema]) => {
    const schema = record(rawSchema)
    return {
      name,
      description: typeof schema.description === 'string' ? schema.description : null,
      example: schema.example,
      type: parameterType(schema),
      location: locations.get(name) || 'input',
      required: required.has(name),
    }
  })
}

const store = useToolsStore()
const { t } = useI18n()
const route = inject(routeLocationKey, null)
const router = inject(routerKey, null)
const filter = ref<'all' | 'enabled' | 'disabled'>('all')
const searchQuery = ref('')
const collapsedSourceIds = ref(new Set<number>())
const collapsedTagGroups = ref(new Set<string>())
const editingDescriptionId = ref<number | null>(null)
const descriptionDraft = ref('')
const editingParameter = ref<{ toolId: number, name: string } | null>(null)
const parameterDescriptionDraft = ref('')
const parameterExampleDraft = ref('')
const parameterSaving = ref(false)
const parameterSuccess = ref<{ toolId: number, name: string } | null>(null)
const parameterError = ref('')
const selectedToolIds = ref(new Set<number>())
const batchPending = ref(false)
const pendingToolIds = ref(new Set<number>())
const selectionError = ref('')
const batchRequestError = ref('')
const batchSummary = ref('')
const batchFailures = ref<string[]>([])
const deleteConfirmationOpen = ref(false)
const deleteDialog = ref<HTMLDialogElement | null>(null)
const deleteTrigger = ref<HTMLElement | null>(null)
const sourceId = computed(() => {
  const value = route?.query.source_id
  if (typeof value !== 'string' || !/^\d+$/.test(value)) return null
  return Number(value)
})
const sourceName = computed(() => {
  const value = route?.query.source_name
  return typeof value === 'string' ? value : `#${sourceId.value}`
})
const visibleTools = computed(() => store.tools.filter((tool) => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  const matchesStatus = filter.value === 'all' || tool.enabled === (filter.value === 'enabled')
  const matchesSource = sourceId.value === null || tool.api_source_id === sourceId.value
  const matchesSearch = !query
    || tool.name.toLocaleLowerCase().includes(query)
    || (tool.description || '').toLocaleLowerCase().includes(query)
  return matchesStatus && matchesSource && matchesSearch
}))
function primaryToolTag(tool: ToolSummary): string {
  return tool.tags?.[0] || t('tools.untagged')
}

function tagGroupKey(sourceId: number, tagName: string): string {
  return `${sourceId}:${tagName}`
}

const selectableVisibleTools = computed(() => visibleTools.value.filter((tool) => (
  !collapsedSourceIds.value.has(tool.api_source_id)
  && !collapsedTagGroups.value.has(tagGroupKey(tool.api_source_id, primaryToolTag(tool)))
)))
const groupedTools = computed(() => {
  const groups = new Map<number, {
    id: number
    name: string
    toolCount: number
    tags: Map<string, ToolTagGroup>
  }>()
  for (const tool of visibleTools.value) {
    let group = groups.get(tool.api_source_id)
    if (!group) {
      const source = store.sources.find((item) => item.id === tool.api_source_id)
      const routedName = sourceId.value === tool.api_source_id ? sourceName.value : null
      group = {
        id: tool.api_source_id,
        name: routedName || source?.name || `#${tool.api_source_id}`,
        toolCount: 0,
        tags: new Map(),
      }
      groups.set(tool.api_source_id, group)
    }
    const primaryTag = primaryToolTag(tool)
    let tagGroup = group.tags.get(primaryTag)
    if (!tagGroup) {
      tagGroup = { name: primaryTag, tools: [] }
      group.tags.set(primaryTag, tagGroup)
    }
    tagGroup.tools.push({ ...tool, parameters: toolParameters(tool) })
    group.toolCount += 1
  }
  return [...groups.values()].map((group) => ({
    id: group.id,
    name: group.name,
    toolCount: group.toolCount,
    tags: [...group.tags.values()],
  }))
})
const selectedTools = computed(() => store.tools.filter((tool) => selectedToolIds.value.has(tool.id)))
const selectedSourceCount = computed(() => new Set(
  selectedTools.value.map((tool) => tool.api_source_id),
).size)

function isToolSelected(toolId: number): boolean {
  return selectedToolIds.value.has(toolId)
}

function isToolBatchPending(toolId: number): boolean {
  return pendingToolIds.value.has(toolId)
}

function isToolMutationLocked(toolId: number): boolean {
  return deleteConfirmationOpen.value || isToolBatchPending(toolId)
}

function setToolSelected(toolId: number, selected: boolean): void {
  const next = new Set(selectedTools.value.map((tool) => tool.id))
  if (selected && next.size >= MAX_BATCH_TOOLS) {
    selectionError.value = t('tools.bulk.limit', { limit: MAX_BATCH_TOOLS })
    return
  }
  if (selected) next.add(toolId)
  else next.delete(toolId)
  selectedToolIds.value = next
  selectionError.value = ''
}

function selectVisibleTools(): void {
  const next = new Set([
    ...selectedTools.value.map((tool) => tool.id),
    ...selectableVisibleTools.value.map((tool) => tool.id),
  ])
  if (next.size > MAX_BATCH_TOOLS) {
    selectionError.value = t('tools.bulk.limit', { limit: MAX_BATCH_TOOLS })
    return
  }
  selectedToolIds.value = next
  selectionError.value = ''
}

function toggleSourceCollapsed(sourceId: number): void {
  const next = new Set(collapsedSourceIds.value)
  if (next.has(sourceId)) next.delete(sourceId)
  else next.add(sourceId)
  collapsedSourceIds.value = next
}

function toggleTagCollapsed(sourceId: number, tagName: string): void {
  const key = tagGroupKey(sourceId, tagName)
  const next = new Set(collapsedTagGroups.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedTagGroups.value = next
}

function clearToolSelection(): void {
  selectedToolIds.value = new Set()
  selectionError.value = ''
}

function batchFailureMessage(failure: ToolBatchFailed): string {
  const toolName = store.tools.find((tool) => tool.id === failure.tool_id)?.name
    ?? t('tools.bulk.unknownTool', { id: failure.tool_id })
  const errorKey = ({
    'tools.not_found': 'notFound',
    'tools.source_unavailable': 'sourceUnavailable',
    'tools.login_tool_conflict': 'loginToolConflict',
    'tools.batch_item_failed': 'batchItemFailed',
  } as Record<string, string>)[failure.code] ?? 'unknown'
  return `${toolName}: ${t(`tools.bulk.errors.${errorKey}`)}`
}

async function performBatchAction(action: ToolBatchAction): Promise<void> {
  if (batchPending.value || selectedTools.value.length === 0) return
  const snapshot = selectedTools.value.map((tool) => tool.id)
  batchPending.value = true
  pendingToolIds.value = new Set(snapshot)
  selectionError.value = ''
  batchRequestError.value = ''
  batchSummary.value = ''
  batchFailures.value = []
  try {
    const result = await store.batchTools(action, snapshot)
    const nextSelection = new Set(selectedToolIds.value)
    for (const item of result.succeeded) nextSelection.delete(item.tool_id)
    selectedToolIds.value = nextSelection
    batchSummary.value = t(`tools.bulk.summary.${action}`, {
      succeeded: result.succeeded.length,
      total: result.request_count,
      failed: result.failed.length,
    })
    batchFailures.value = result.failed.map(batchFailureMessage)
  } catch {
    batchRequestError.value = t('tools.bulk.requestError')
  } finally {
    pendingToolIds.value = new Set()
    batchPending.value = false
  }
}

function requestBatchAction(action: ToolBatchAction, trigger?: HTMLElement): void {
  if (action === 'delete') {
    if (selectedTools.value.length === 0) return
    deleteTrigger.value = trigger ?? (document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null)
    deleteConfirmationOpen.value = true
    void nextTick(() => {
      const dialog = deleteDialog.value
      if (!dialog) return
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
      dialog.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()
    })
    return
  }
  void performBatchAction(action)
}

function cancelBulkDelete(): void {
  if (batchPending.value) return
  closeBulkDelete()
}

function closeBulkDelete(): void {
  const dialog = deleteDialog.value
  if (dialog?.open && typeof dialog.close === 'function') dialog.close()
  else dialog?.removeAttribute('open')
  deleteConfirmationOpen.value = false
  const trigger = deleteTrigger.value
  void nextTick(() => {
    if (trigger?.isConnected && !(trigger instanceof HTMLButtonElement && trigger.disabled)) {
      trigger.focus()
    }
  })
}

async function confirmBulkDelete(): Promise<void> {
  if (batchPending.value) return
  await performBatchAction('delete')
  closeBulkDelete()
}

function handleDeleteDialogKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    cancelBulkDelete()
    return
  }
  if (event.key !== 'Tab') return
  const focusable = [...(deleteDialog.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])]
  if (focusable.length === 0) {
    event.preventDefault()
    deleteDialog.value?.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function clearSourceFilter(): void {
  void router?.replace({ name: 'tools' })
}

function startDescriptionEdit(tool: ToolSummary): void {
  if (isToolMutationLocked(tool.id)) return
  editingDescriptionId.value = tool.id
  descriptionDraft.value = tool.description || ''
}

function cancelDescriptionEdit(): void {
  editingDescriptionId.value = null
  descriptionDraft.value = ''
}

async function saveDescription(tool: ToolSummary): Promise<void> {
  if (isToolMutationLocked(tool.id)) return
  await store.updateToolDescription(tool, descriptionDraft.value)
  cancelDescriptionEdit()
}

function setSingleToolEnabled(tool: ToolSummary): void {
  if (isToolMutationLocked(tool.id)) return
  void store.setEnabled(tool, !tool.enabled)
}

function deleteSingleTool(tool: ToolSummary): void {
  if (isToolMutationLocked(tool.id)) return
  void store.deleteTool(tool)
}

function isEditingParameter(tool: ToolSummary, parameter: ToolParameterView): boolean {
  return editingParameter.value?.toolId === tool.id
    && editingParameter.value.name === parameter.name
}

function startParameterEdit(tool: ToolSummary, parameter: ToolParameterView): void {
  if (isToolMutationLocked(tool.id)) return
  editingParameter.value = { toolId: tool.id, name: parameter.name }
  parameterDescriptionDraft.value = parameter.description || ''
  parameterExampleDraft.value = exampleDraft(parameter.example)
  parameterSuccess.value = null
  parameterError.value = ''
}

function cancelParameterEdit(): void {
  editingParameter.value = null
  parameterDescriptionDraft.value = ''
  parameterExampleDraft.value = ''
  parameterError.value = ''
}

async function saveParameter(tool: ToolSummary, parameter: ToolParameterView): Promise<void> {
  if (isToolMutationLocked(tool.id)) return
  parameterSaving.value = true
  parameterError.value = ''
  try {
    await store.updateToolParameter(tool, parameter.name, {
      description: parameterDescriptionDraft.value.trim() || null,
      example: parseExample(parameterExampleDraft.value),
    })
    editingParameter.value = null
    parameterSuccess.value = { toolId: tool.id, name: parameter.name }
  } catch {
    parameterError.value = t('tools.parameterSaveError')
  } finally {
    parameterSaving.value = false
  }
}

onMounted(() => void Promise.all([store.loadTools(), store.loadSources()]))

watch(() => store.tools.map((tool) => tool.id), (toolIds) => {
  const existingIds = new Set(toolIds)
  const next = new Set([...selectedToolIds.value].filter((id) => existingIds.has(id)))
  if (next.size !== selectedToolIds.value.size) selectedToolIds.value = next
})
</script>

<template>
  <main class="management-page" :inert="deleteConfirmationOpen || undefined">
    <header class="page-heading with-actions"><div><p class="eyebrow">{{ t('tools.eyebrow') }}</p><h1>{{ t('tools.title') }}</h1><p class="muted">{{ t('tools.subtitle') }}</p></div>
      <div class="segmented"><button v-for="value in (['all','enabled','disabled'] as const)" :key="value" :class="{ active: filter === value }" @click="filter = value">{{ t(`tools.filter.${value}`) }}</button></div>
    </header>
    <label class="tool-search"><span>{{ t('tools.searchLabel') }}</span><input v-model="searchQuery" type="search" :placeholder="t('tools.searchPlaceholder')" /></label>
    <ToolBulkBar
      :selected-count="selectedTools.length"
      :visible-count="selectableVisibleTools.length"
      :pending="batchPending || deleteConfirmationOpen"
      :error="selectionError || batchRequestError"
      :summary="batchSummary"
      :failures="batchFailures"
      @select-visible="selectVisibleTools"
      @clear="clearToolSelection"
      @action="requestBatchAction"
    />
    <div v-if="sourceId !== null" class="source-filter-banner"><span>{{ t('tools.sourceFilter', { name: sourceName }) }}</span><button class="secondary-action" @click="clearSourceFilter">{{ t('tools.showAllSources') }}</button></div>
    <div v-if="!store.loading && visibleTools.length === 0" class="empty-state">{{ t('tools.empty') }}</div>
    <details v-for="group in groupedTools" :key="group.id" class="tool-source-group" :open="!collapsedSourceIds.has(group.id)">
      <summary class="tool-source-heading" @click.prevent="toggleSourceCollapsed(group.id)"><h2>{{ group.name }}</h2><span>{{ t('tools.count', { count: group.toolCount }) }}</span></summary>
      <details v-for="tagGroup in group.tags" :key="tagGroup.name" class="tool-tag-group" :open="!collapsedTagGroups.has(tagGroupKey(group.id, tagGroup.name))">
        <summary class="tool-tag-heading" @click.prevent="toggleTagCollapsed(group.id, tagGroup.name)"><h3>{{ tagGroup.name }}</h3><span>{{ t('tools.count', { count: tagGroup.tools.length }) }}</span></summary>
        <div class="tool-grid">
        <article v-for="tool in tagGroup.tools" :key="tool.id" class="tool-card">
          <div class="tool-card-head"><label class="tool-select"><input type="checkbox" :checked="isToolSelected(tool.id)" :disabled="deleteConfirmationOpen || pendingToolIds.has(tool.id) || (!isToolSelected(tool.id) && selectedTools.length >= MAX_BATCH_TOOLS)" :aria-label="t('tools.bulk.selectTool', { name: tool.name })" @change="setToolSelected(tool.id, ($event.target as HTMLInputElement).checked)" /></label><code>{{ tool.operation_key.split(' ')[0] }}</code><span :class="['status-pill', tool.enabled ? 'enabled' : 'disabled']">{{ tool.enabled ? t('tools.enabled') : t('tools.disabled') }}</span></div>
          <div v-if="tool.tags?.length" class="tool-tags"><span v-for="tag in tool.tags" :key="tag">{{ tag }}</span></div>
          <h2>{{ tool.name }}</h2>
          <div v-if="editingDescriptionId === tool.id" class="tool-description-editor">
            <label><span>{{ t('tools.descriptionLabel') }}</span><textarea v-model="descriptionDraft" rows="3" maxlength="4000" :disabled="isToolMutationLocked(tool.id)" /></label>
            <div><button class="primary-action" :disabled="isToolMutationLocked(tool.id)" @click="saveDescription(tool)">{{ t('tools.saveDescription') }}</button><button class="secondary-action" @click="cancelDescriptionEdit">{{ t('tools.cancelDescription') }}</button></div>
          </div>
          <template v-else>
            <p>{{ tool.description || tool.operation_key }}</p>
            <button class="description-edit-action" :disabled="isToolMutationLocked(tool.id)" @click="startDescriptionEdit(tool)">{{ t('tools.editDescription') }}</button>
          </template>
          <details v-if="tool.parameters.length" class="tool-parameters">
            <summary>{{ t('tools.parameters', { count: tool.parameters.length }) }}</summary>
            <div class="parameter-list">
              <div v-for="parameter in tool.parameters" :key="parameter.name" class="parameter-row">
                <div class="parameter-heading"><code>{{ parameter.name }}</code><span>{{ t(`tools.location.${parameter.location}`) }}</span><span>{{ parameter.type }}</span><b :class="{ optional: !parameter.required }">{{ parameter.required ? t('tools.required') : t('tools.optional') }}</b></div>
                <template v-if="isEditingParameter(tool, parameter)">
                  <div class="parameter-editor">
                    <label><span>{{ t('tools.parameterDescriptionLabel') }}</span><textarea v-model="parameterDescriptionDraft" rows="3" maxlength="4000" :disabled="isToolMutationLocked(tool.id)" /></label>
                    <label><span>{{ t('tools.parameterExampleLabel') }}</span><textarea v-model="parameterExampleDraft" rows="2" :disabled="isToolMutationLocked(tool.id)" /></label>
                    <p class="parameter-editor-hint">{{ t('tools.parameterExampleHint') }}</p>
                    <p v-if="parameterError" class="parameter-save-error" role="alert">{{ parameterError }}</p>
                    <div class="parameter-editor-actions"><button class="primary-action" :disabled="parameterSaving || isToolMutationLocked(tool.id)" @click="saveParameter(tool, parameter)">{{ t('tools.saveParameter') }}</button><button class="secondary-action" :disabled="parameterSaving" @click="cancelParameterEdit">{{ t('tools.cancelParameter') }}</button></div>
                  </div>
                </template>
                <template v-else>
                  <div class="parameter-guidance">
                    <p v-if="parameter.description"><strong>{{ t('tools.parameterDescription') }}</strong><span>{{ parameter.description }}</span></p>
                    <p v-if="parameter.example !== undefined"><strong>{{ t('tools.parameterExample') }}</strong><code>{{ displayExample(parameter.example) }}</code></p>
                  </div>
                  <button class="parameter-edit-action" :disabled="isToolMutationLocked(tool.id)" @click="startParameterEdit(tool, parameter)">{{ t('tools.editParameter') }}</button>
                  <p v-if="parameterSuccess?.toolId === tool.id && parameterSuccess.name === parameter.name" class="parameter-save-success" role="status">{{ t('tools.parameterSaveSuccess') }}</p>
                </template>
              </div>
            </div>
          </details>
          <footer><button class="secondary-action" :disabled="isToolMutationLocked(tool.id)" @click="setSingleToolEnabled(tool)">{{ tool.enabled ? t('tools.disable') : t('tools.enable') }}</button><button class="danger-action" :disabled="isToolMutationLocked(tool.id)" @click="deleteSingleTool(tool)">{{ t('tools.delete') }}</button></footer>
        </article>
        </div>
      </details>
    </details>
  </main>
  <dialog v-if="deleteConfirmationOpen" ref="deleteDialog" aria-labelledby="bulk-delete-title" class="confirmation-dialog" tabindex="-1" @cancel.prevent="cancelBulkDelete" @keydown="handleDeleteDialogKeydown">
    <h2 id="bulk-delete-title">{{ t('tools.bulk.confirm.title') }}</h2>
    <p>{{ t('tools.bulk.confirm.message', { tools: selectedTools.length, sources: selectedSourceCount }) }}</p>
    <div class="confirmation-actions">
      <button class="secondary-action" :disabled="batchPending" :aria-label="t('tools.bulk.confirm.cancelLabel')" @click="cancelBulkDelete">{{ t('tools.bulk.confirm.cancel') }}</button>
      <button class="danger-action" :disabled="batchPending" :aria-label="t('tools.bulk.confirm.confirmLabel')" @click="confirmBulkDelete">{{ t('tools.bulk.confirm.confirm') }}</button>
    </div>
  </dialog>
</template>
