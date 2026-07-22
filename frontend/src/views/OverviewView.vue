<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { request } from '../api/client'
import type { AgentConfig, ApiSourceSummary, LlmProviderSummary, SkillSummary, ToolSummary } from '../api/contracts'

const { t } = useI18n()
const metrics = ref({ providers: 0, sources: 0, tools: 0, skills: 0, agents: 0 })
const cards = [
  { key: 'providers', icon: '◈', accent: 'violet' },
  { key: 'sources', icon: '⇄', accent: 'blue' },
  { key: 'tools', icon: '⌁', accent: 'amber' },
  { key: 'skills', icon: '✦', accent: 'green' },
  { key: 'agents', icon: '◉', accent: 'blue' },
] as const

async function loadMetrics(): Promise<void> {
  const [providers, sources, tools, skills, agents] = await Promise.allSettled([
    request<LlmProviderSummary[]>('/api/admin/providers'),
    request<ApiSourceSummary[]>('/api/admin/sources'),
    request<ToolSummary[]>('/api/admin/tools'),
    request<SkillSummary[]>('/api/admin/skills'),
    request<AgentConfig[]>('/api/admin/agents'),
  ])
  const count = <T>(result: PromiseSettledResult<T[]>): number =>
    result.status === 'fulfilled' ? result.value.length : 0
  metrics.value = {
    providers: count(providers),
    sources: count(sources),
    tools: count(tools),
    skills: count(skills),
    agents: count(agents),
  }
}

onMounted(loadMetrics)
</script>

<template>
  <main class="overview-page">
    <p class="eyebrow">{{ t('overview.eyebrow') }}</p>
    <h1>{{ t('overview.title') }}</h1>
    <p class="muted overview-subtitle">{{ t('overview.subtitle') }}</p>
    <section class="metric-grid">
      <article v-for="card in cards" :key="card.key" class="metric-card">
        <span class="metric-icon" :class="card.accent">{{ card.icon }}</span>
        <div>
          <strong>{{ t(`overview.${card.key}`) }}</strong>
          <p>{{ t('overview.empty') }}</p>
        </div>
        <b>{{ metrics[card.key] }}</b>
      </article>
    </section>
    <section class="journey-card">
      <div>
        <p class="eyebrow">{{ t('overview.journey.eyebrow') }}</p>
        <h2>{{ t('overview.journey.title') }}</h2>
        <p>{{ t('overview.journey.description') }}</p>
        <RouterLink class="journey-start" :to="{ name: 'providers' }">
          {{ t('overview.journey.start') }}
        </RouterLink>
      </div>
      <ol>
        <li><span>1</span> {{ t('overview.journey.provider') }}</li>
        <li><span>2</span> {{ t('overview.journey.source') }}</li>
        <li><span>3</span> {{ t('overview.journey.tool') }}</li>
        <li><span>4</span> {{ t('overview.journey.skill') }}</li>
        <li><span>5</span> {{ t('overview.journey.agent') }}</li>
      </ol>
    </section>
  </main>
</template>
