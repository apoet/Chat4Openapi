<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { IndexedTool, ToolCatalog, ToolCatalogState } from '../composables/useToolCatalog'

const PANEL_HEIGHT_KEY = 'chat4openapi.skill-tool-catalog-height'
const DEFAULT_PANEL_HEIGHT = 900
const PREVIOUS_DEFAULT_PANEL_HEIGHTS = new Set([680, 780])
const MIN_PANEL_HEIGHT = 420
const MAX_PANEL_HEIGHT = 1200
const ROW_LIMIT = 100

const props = defineProps<{
  catalog: ToolCatalog
  modelValue: number[]
}>()
const emit = defineEmits<{
  'update:modelValue': [value: number[]]
  reference: [tool: IndexedTool]
}>()

const { t } = useI18n()
const searchQuery = ref('')
const sourceId = ref('all')
const tag = ref('all')
const state = ref<ToolCatalogState>('all')
const collapsedSources = ref(new Set<number>())
const collapsedTags = ref(new Set<string>())
const height = ref(readPanelHeight())
const sourceOptions = computed(() => props.catalog.index.value.sources)
const tagOptions = computed(() => props.catalog.index.value.tags)
const result = computed(() => props.catalog.query({
  query: searchQuery.value,
  sourceId: sourceId.value === 'all' ? null : Number(sourceId.value),
  tag: tag.value === 'all' ? null : tag.value,
  state: state.value,
  pinnedIds: props.modelValue,
}, ROW_LIMIT))

function boundedHeight(value: number): number {
  return Math.min(MAX_PANEL_HEIGHT, Math.max(MIN_PANEL_HEIGHT, value))
}

function readPanelHeight(): number {
  try {
    const value = Number.parseInt(localStorage.getItem(PANEL_HEIGHT_KEY) || '', 10)
    if (PREVIOUS_DEFAULT_PANEL_HEIGHTS.has(value)) {
      localStorage.setItem(PANEL_HEIGHT_KEY, String(DEFAULT_PANEL_HEIGHT))
      return DEFAULT_PANEL_HEIGHT
    }
    return Number.isFinite(value) ? boundedHeight(value) : DEFAULT_PANEL_HEIGHT
  } catch {
    return DEFAULT_PANEL_HEIGHT
  }
}

function persistHeight(): void {
  try {
    localStorage.setItem(PANEL_HEIGHT_KEY, String(height.value))
  } catch {
    // Browser privacy settings may reject storage; the in-memory size still works.
  }
}

function resizeBy(delta: number): void {
  height.value = boundedHeight(height.value + delta)
  persistHeight()
}

function handleResizeKeydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowUp') resizeBy(40)
  else if (event.key === 'ArrowDown') resizeBy(-40)
  else if (event.key === 'Home') {
    height.value = MIN_PANEL_HEIGHT
    persistHeight()
  } else if (event.key === 'End') {
    height.value = MAX_PANEL_HEIGHT
    persistHeight()
  } else return
  event.preventDefault()
}

function captureNativeResize(event: MouseEvent): void {
  const element = event.currentTarget as HTMLElement
  if (element.offsetHeight) height.value = boundedHeight(element.offsetHeight)
  persistHeight()
}

function isBound(toolId: number): boolean {
  return props.modelValue.includes(toolId)
}

function setBound(tool: IndexedTool, checked: boolean): void {
  if (checked && !tool.skillEligible) return
  const next = props.modelValue.filter((id) => id !== tool.id)
  if (checked) next.push(tool.id)
  emit('update:modelValue', next)
}

function toggleSource(sourceId: number): void {
  const next = new Set(collapsedSources.value)
  if (next.has(sourceId)) next.delete(sourceId)
  else next.add(sourceId)
  collapsedSources.value = next
}

function tagKey(sourceId: number, tagName: string): string {
  return `${sourceId}:${tagName}`
}

function toggleTag(sourceId: number, tagName: string): void {
  const key = tagKey(sourceId, tagName)
  const next = new Set(collapsedTags.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedTags.value = next
}
</script>

<template>
  <aside
    class="tool-catalog-panel"
    role="region"
    :aria-label="t('skills.catalog.title')"
    :style="{ height: `${height}px` }"
    @mouseup="captureNativeResize"
  >
    <header class="catalog-heading">
      <div><p class="eyebrow">{{ t('skills.quickReference') }}</p><h2>{{ t('skills.catalog.title') }}</h2></div>
      <p class="muted">{{ t('skills.quickHint') }}</p>
    </header>
    <div class="catalog-controls">
      <label class="catalog-search"><span>{{ t('skills.catalog.search') }}</span><input v-model="searchQuery" type="search" :placeholder="t('skills.catalog.searchHint')" /></label>
      <label><span>{{ t('skills.catalog.source') }}</span><select v-model="sourceId"><option value="all">{{ t('skills.catalog.allSources') }}</option><option v-for="source in sourceOptions" :key="source.id" :value="String(source.id)">{{ source.name }}</option></select></label>
      <label><span>{{ t('skills.catalog.tag') }}</span><select v-model="tag"><option value="all">{{ t('skills.catalog.allTags') }}</option><option v-for="option in tagOptions" :key="option" :value="option">{{ option }}</option></select></label>
      <label><span>{{ t('skills.catalog.state') }}</span><select v-model="state"><option value="all">{{ t('tools.filter.all') }}</option><option value="enabled">{{ t('tools.enabled') }}</option><option value="disabled">{{ t('tools.disabled') }}</option></select></label>
    </div>
    <p v-if="result.total > result.shown" class="catalog-limit">{{ t('skills.catalog.showing', { shown: result.shown, total: result.total }) }}</p>
    <div class="catalog-groups">
      <details v-for="source in result.groups" :key="source.id" class="catalog-source-group" :open="!collapsedSources.has(source.id)">
        <summary @click.prevent="toggleSource(source.id)"><h3>{{ source.name }}</h3><span>{{ t('tools.count', { count: source.toolCount }) }}</span></summary>
        <details v-for="tagGroup in source.tags" :key="tagGroup.name" class="catalog-tag-group" :open="!collapsedTags.has(tagKey(source.id, tagGroup.name))">
          <summary @click.prevent="toggleTag(source.id, tagGroup.name)"><h4>{{ tagGroup.name || t('skills.untagged') }}</h4><span>{{ tagGroup.tools.length }}</span></summary>
          <article v-for="tool in tagGroup.tools" :key="tool.id" class="catalog-tool-row" :class="{ disabled: !tool.available, unavailable: !tool.skillEligible }" :data-testid="`catalog-tool-${tool.id}`">
            <span data-testid="catalog-tool-row" class="sr-only" aria-hidden="true"></span>
            <label class="catalog-bind"><input type="checkbox" :checked="isBound(tool.id)" :disabled="!tool.skillEligible && !isBound(tool.id)" :aria-label="t('skills.catalog.bind', { name: tool.name })" @change="setBound(tool, ($event.target as HTMLInputElement).checked)" /><span class="sr-only">{{ t('skills.catalog.bind', { name: tool.name }) }}</span></label>
            <div class="catalog-tool-main"><strong>{{ tool.name }}</strong><span class="catalog-operation"><code>{{ tool.method }}</code><code>{{ tool.path }}</code></span></div>
            <div class="catalog-tool-meta"><span>{{ tool.sourceName }}</span><span v-for="toolTag in tool.tags" :key="toolTag" class="catalog-tag">{{ toolTag }}</span><b :class="['catalog-state', tool.available ? 'enabled' : 'disabled']">{{ tool.available ? t('tools.enabled') : t('tools.disabled') }}</b><b v-if="!tool.skillEligible" class="catalog-eligibility unavailable">{{ t('skills.catalog.unavailable') }}</b></div>
            <button type="button" class="catalog-reference" :disabled="!tool.skillEligible" :aria-label="t('skills.catalog.reference', { name: tool.name })" @click="emit('reference', tool)">@</button>
          </article>
        </details>
      </details>
    </div>
    <div v-if="result.total === 0" class="empty-state">{{ t('skills.catalog.empty') }}</div>
    <button
      type="button"
      class="catalog-resize-handle"
      role="separator"
      aria-orientation="horizontal"
      :aria-label="t('skills.catalog.resize')"
      :aria-valuemin="MIN_PANEL_HEIGHT"
      :aria-valuemax="MAX_PANEL_HEIGHT"
      :aria-valuenow="height"
      @keydown="handleResizeKeydown"
    ><span aria-hidden="true"></span></button>
  </aside>
</template>
