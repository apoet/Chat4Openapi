<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { routeLocationKey, routerKey } from 'vue-router'

import type { ToolSummary } from '../api/contracts'
import { useToolsStore } from '../stores/tools'

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
  const groups = new Map<number, { id: number; name: string; tools: ToolSummary[] }>()
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
    group.tools.push(tool)
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
    <section v-for="group in groupedTools" :key="group.id" class="tool-source-group">
      <header class="tool-source-heading"><h2>{{ group.name }}</h2><span>{{ t('tools.count', { count: group.tools.length }) }}</span></header>
      <div class="tool-grid">
        <article v-for="tool in group.tools" :key="tool.id" class="tool-card">
          <div class="tool-card-head"><code>{{ tool.operation_key.split(' ')[0] }}</code><span :class="['status-pill', tool.enabled ? 'enabled' : 'disabled']">{{ tool.enabled ? t('tools.enabled') : t('tools.disabled') }}</span></div>
          <h2>{{ tool.name }}</h2><p>{{ tool.description || tool.operation_key }}</p>
          <footer><button class="secondary-action" @click="store.setEnabled(tool, !tool.enabled)">{{ tool.enabled ? t('tools.disable') : t('tools.enable') }}</button><button class="danger-action" @click="store.deleteTool(tool)">{{ t('tools.delete') }}</button></footer>
        </article>
      </div>
    </section>
  </main>
</template>
