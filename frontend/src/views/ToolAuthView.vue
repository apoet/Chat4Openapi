<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import { useToolsStore } from '../stores/tools'

const store = useToolsStore()
const { t } = useI18n()
const enabledTools = computed(() => store.tools.filter((tool) => tool.enabled))

onMounted(async () => Promise.all([store.loadTools(), store.loadAuthConfig()]))
</script>

<template>
  <main class="management-page narrow-page">
    <header class="page-heading"><div><p class="eyebrow">{{ t('toolAuth.eyebrow') }}</p><h1>{{ t('toolAuth.title') }}</h1><p class="muted">{{ t('toolAuth.subtitle') }}</p></div></header>
    <section class="settings-panel">
      <label class="toggle-row"><span><strong>{{ t('toolAuth.enable') }}</strong><small>{{ t('toolAuth.enableHint') }}</small></span><input v-model="store.authConfig.enabled" type="checkbox" /></label>
      <div class="settings-grid" :class="{ mutedPanel: !store.authConfig.enabled }">
        <label>{{ t('toolAuth.loginTool') }}<select v-model="store.authConfig.login_tool_id" :disabled="!store.authConfig.enabled"><option :value="null">{{ t('toolAuth.selectTool') }}</option><option v-for="tool in enabledTools" :key="tool.id" :value="tool.id">{{ tool.name }} · {{ tool.operation_key }}</option></select></label>
        <label>{{ t('toolAuth.tokenPath') }}<input v-model="store.authConfig.token_json_path" :disabled="!store.authConfig.enabled" /></label>
        <label>{{ t('toolAuth.usernameField') }}<input v-model="store.authConfig.username_field" :disabled="!store.authConfig.enabled" /></label>
        <label>{{ t('toolAuth.passwordField') }}<input v-model="store.authConfig.password_field" :disabled="!store.authConfig.enabled" /></label>
        <label>{{ t('toolAuth.idle') }}<input v-model.number="store.authConfig.idle_minutes" type="number" min="1" /></label>
        <label>{{ t('toolAuth.absolute') }}<input v-model.number="store.authConfig.absolute_hours" type="number" min="1" /></label>
      </div>
      <button class="primary-action" @click="store.saveAuthConfig(store.authConfig)">{{ t('toolAuth.save') }}</button>
    </section>
  </main>
</template>
