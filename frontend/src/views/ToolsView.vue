<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useToolsStore } from '../stores/tools'

const store = useToolsStore()
const { t } = useI18n()
const filter = ref<'all' | 'enabled' | 'disabled'>('all')
const visibleTools = computed(() => store.tools.filter((tool) => filter.value === 'all' || tool.enabled === (filter.value === 'enabled')))

onMounted(() => void store.loadTools())
</script>

<template>
  <main class="management-page">
    <header class="page-heading with-actions"><div><p class="eyebrow">{{ t('tools.eyebrow') }}</p><h1>{{ t('tools.title') }}</h1><p class="muted">{{ t('tools.subtitle') }}</p></div>
      <div class="segmented"><button v-for="value in (['all','enabled','disabled'] as const)" :key="value" :class="{ active: filter === value }" @click="filter = value">{{ t(`tools.filter.${value}`) }}</button></div>
    </header>
    <section class="tool-grid">
      <div v-if="!store.loading && visibleTools.length === 0" class="empty-state wide">{{ t('tools.empty') }}</div>
      <article v-for="tool in visibleTools" :key="tool.id" class="tool-card">
        <div class="tool-card-head"><code>{{ tool.operation_key.split(' ')[0] }}</code><span :class="['status-pill', tool.enabled ? 'enabled' : 'disabled']">{{ tool.enabled ? t('tools.enabled') : t('tools.disabled') }}</span></div>
        <h2>{{ tool.name }}</h2><p>{{ tool.description || tool.operation_key }}</p>
        <footer><button class="secondary-action" @click="store.setEnabled(tool, !tool.enabled)">{{ tool.enabled ? t('tools.disable') : t('tools.enable') }}</button><button class="danger-action" @click="store.deleteTool(tool)">{{ t('tools.delete') }}</button></footer>
      </article>
    </section>
  </main>
</template>
