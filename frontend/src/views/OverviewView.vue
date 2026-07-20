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
    <p class="eyebrow">CHATAPI CONTROL PLANE</p>
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
        <p class="eyebrow">GET STARTED</p>
        <h2>Build your first API Skill</h2>
        <p>Connect a model provider, import an OpenAPI source, curate Tools, then compose a Skill.</p>
      </div>
      <ol>
        <li><span>1</span> Configure a provider</li>
        <li><span>2</span> Import an API source</li>
        <li><span>3</span> Enable selected Tools</li>
        <li><span>4</span> Compose a Skill</li>
      </ol>
    </section>
  </main>
</template>
