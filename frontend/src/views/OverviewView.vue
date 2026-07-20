<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const cards = [
  { key: 'providers', icon: '◈', accent: 'violet' },
  { key: 'sources', icon: '⇄', accent: 'blue' },
  { key: 'tools', icon: '⌁', accent: 'amber' },
  { key: 'skills', icon: '✦', accent: 'green' },
] as const
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
        <b>0</b>
      </article>
    </section>
    <section class="journey-card">
      <div>
        <p class="eyebrow">{{ t('overview.journey.eyebrow') }}</p>
        <h2>{{ t('overview.journey.title') }}</h2>
        <p>{{ t('overview.journey.description') }}</p>
      </div>
      <ol>
        <li><span>1</span> {{ t('overview.journey.provider') }}</li>
        <li><span>2</span> {{ t('overview.journey.source') }}</li>
        <li><span>3</span> {{ t('overview.journey.tool') }}</li>
        <li><span>4</span> {{ t('overview.journey.skill') }}</li>
      </ol>
    </section>
  </main>
</template>
