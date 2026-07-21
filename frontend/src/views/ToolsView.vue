<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { routeLocationKey, routerKey } from 'vue-router'

import type { ToolSummary } from '../api/contracts'
import { useToolsStore } from '../stores/tools'

interface ToolParameterView {
  name: string
  description: string | null
  type: string
  location: string
  required: boolean
}

interface ToolDisplay extends ToolSummary {
  parameters: ToolParameterView[]
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
  const matchesStatus = filter.value === 'all' || tool.enabled === (filter.value === 'enabled')
  const matchesSource = sourceId.value === null || tool.api_source_id === sourceId.value
  return matchesStatus && matchesSource
}))
const groupedTools = computed(() => {
  const groups = new Map<number, { id: number; name: string; tools: ToolDisplay[] }>()
  for (const tool of visibleTools.value) {
    let group = groups.get(tool.api_source_id)
    if (!group) {
      const source = store.sources.find((item) => item.id === tool.api_source_id)
      const routedName = sourceId.value === tool.api_source_id ? sourceName.value : null
      group = {
        id: tool.api_source_id,
        name: routedName || source?.name || `#${tool.api_source_id}`,
        tools: [],
      }
      groups.set(tool.api_source_id, group)
    }
    group.tools.push({ ...tool, parameters: toolParameters(tool) })
  }
  return [...groups.values()]
})

function clearSourceFilter(): void {
  void router?.replace({ name: 'tools' })
}

onMounted(() => void Promise.all([store.loadTools(), store.loadSources()]))
</script>

<template>
  <main class="management-page">
    <header class="page-heading with-actions"><div><p class="eyebrow">{{ t('tools.eyebrow') }}</p><h1>{{ t('tools.title') }}</h1><p class="muted">{{ t('tools.subtitle') }}</p></div>
      <div class="segmented"><button v-for="value in (['all','enabled','disabled'] as const)" :key="value" :class="{ active: filter === value }" @click="filter = value">{{ t(`tools.filter.${value}`) }}</button></div>
    </header>
    <div v-if="sourceId !== null" class="source-filter-banner"><span>{{ t('tools.sourceFilter', { name: sourceName }) }}</span><button class="secondary-action" @click="clearSourceFilter">{{ t('tools.showAllSources') }}</button></div>
    <div v-if="!store.loading && visibleTools.length === 0" class="empty-state">{{ t('tools.empty') }}</div>
    <details v-for="group in groupedTools" :key="group.id" class="tool-source-group" open>
      <summary class="tool-source-heading"><h2>{{ group.name }}</h2><span>{{ t('tools.count', { count: group.tools.length }) }}</span></summary>
      <div class="tool-grid">
        <article v-for="tool in group.tools" :key="tool.id" class="tool-card">
          <div class="tool-card-head"><code>{{ tool.operation_key.split(' ')[0] }}</code><span :class="['status-pill', tool.enabled ? 'enabled' : 'disabled']">{{ tool.enabled ? t('tools.enabled') : t('tools.disabled') }}</span></div>
          <div v-if="tool.tags?.length" class="tool-tags"><span v-for="tag in tool.tags" :key="tag">{{ tag }}</span></div>
          <h2>{{ tool.name }}</h2><p>{{ tool.description || tool.operation_key }}</p>
          <details v-if="tool.parameters.length" class="tool-parameters">
            <summary>{{ t('tools.parameters', { count: tool.parameters.length }) }}</summary>
            <div class="parameter-list">
              <div v-for="parameter in tool.parameters" :key="parameter.name" class="parameter-row">
                <div class="parameter-heading"><code>{{ parameter.name }}</code><span>{{ t(`tools.location.${parameter.location}`) }}</span><span>{{ parameter.type }}</span><b :class="{ optional: !parameter.required }">{{ parameter.required ? t('tools.required') : t('tools.optional') }}</b></div>
                <p v-if="parameter.description">{{ parameter.description }}</p>
              </div>
            </div>
          </details>
          <footer><button class="secondary-action" @click="store.setEnabled(tool, !tool.enabled)">{{ tool.enabled ? t('tools.disable') : t('tools.enable') }}</button><button class="danger-action" @click="store.deleteTool(tool)">{{ t('tools.delete') }}</button></footer>
        </article>
      </div>
    </details>
  </main>
</template>
