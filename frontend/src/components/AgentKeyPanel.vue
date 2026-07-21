<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AgentApiKey } from '../api/contracts'
import { useAgentsStore } from '../stores/agents'

const props = defineProps<{ agentId: number }>()
const emit = defineEmits<{ error: [error: unknown] }>()
const store = useAgentsStore()
const { locale, t } = useI18n()
const label = ref('')
const expiresAt = ref('')
const secret = ref<string | null>(null)
const copying = ref(false)
const keys = computed(() => store.keysByAgent[props.agentId] ?? [])

watch(() => props.agentId, async (agentId) => {
  clearSecret()
  label.value = ''
  expiresAt.value = ''
  try { await store.loadKeys(agentId) } catch (error) { emit('error', error) }
}, { immediate: true })
onBeforeUnmount(clearSecret)

function clearSecret(): void { secret.value = null }

async function createKey(): Promise<void> {
  if (!label.value.trim()) return
  try {
    const created = await store.createKey(props.agentId, label.value.trim(), expiresAt.value ? new Date(expiresAt.value).toISOString() : null)
    secret.value = created.secret
    label.value = ''
    expiresAt.value = ''
  } catch (error) { emit('error', error) }
}

async function copySecret(): Promise<void> {
  if (!secret.value) return
  copying.value = true
  try { await navigator.clipboard.writeText(secret.value) } finally { copying.value = false }
}

async function revoke(key: AgentApiKey): Promise<void> {
  try { await store.revokeKey(props.agentId, key.id) } catch (error) { emit('error', error) }
}

async function remove(key: AgentApiKey): Promise<void> {
  try { await store.deleteKey(props.agentId, key.id) } catch (error) { emit('error', error) }
}

function status(key: AgentApiKey): string {
  if (key.revoked_at || !key.enabled) return t('agent.keys.revoked')
  if (key.expires_at && new Date(key.expires_at).getTime() <= Date.now()) return t('agent.keys.expired')
  return t('agent.keys.active')
}

function date(value: string | null): string {
  if (!value) return t('agent.keys.never')
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(value))
}
</script>

<template>
  <section class="settings-panel agent-key-panel">
    <header class="panel-heading">
      <div><p class="eyebrow">{{ t('agent.keys.eyebrow') }}</p><h2>{{ t('agent.keys.title') }}</h2></div>
    </header>
    <div class="key-create-grid">
      <label>{{ t('agent.keys.label') }}<input v-model="label" /></label>
      <label>{{ t('agent.keys.expiry') }}<input v-model="expiresAt" type="datetime-local" /></label>
      <button type="button" class="primary-action" :disabled="!label.trim()" @click="createKey">{{ t('agent.keys.create') }}</button>
    </div>

    <div v-if="secret" class="secret-dialog" role="dialog" aria-modal="true" :aria-label="t('agent.keys.newKey')">
      <p><strong>{{ t('agent.keys.newKey') }}</strong></p>
      <p>{{ t('agent.keys.oneTimeWarning') }}</p>
      <code>{{ secret }}</code>
      <div class="row-actions">
        <button type="button" class="secondary-action" @click="copySecret">{{ copying ? t('agent.keys.copying') : t('agent.keys.copy') }}</button>
        <button type="button" class="primary-action" :aria-label="t('agent.keys.closeSecret')" @click="clearSecret">{{ t('agent.keys.close') }}</button>
      </div>
    </div>

    <div class="key-list">
      <article v-for="key in keys" :key="key.id" class="key-row">
        <div><strong>{{ key.label }}</strong><code>{{ key.key_prefix }}</code></div>
        <dl>
          <div><dt>{{ t('agent.keys.status') }}</dt><dd>{{ status(key) }}</dd></div>
          <div><dt>{{ t('agent.keys.expiry') }}</dt><dd>{{ date(key.expires_at) }}</dd></div>
          <div><dt>{{ t('agent.keys.lastUsed') }}</dt><dd>{{ date(key.last_used_at) }}</dd></div>
        </dl>
        <div class="row-actions">
          <button v-if="key.enabled && !key.revoked_at" type="button" class="secondary-action" :aria-label="t('agent.keys.revokeNamed', { name: key.label })" @click="revoke(key)">{{ t('agent.keys.revoke') }}</button>
          <button type="button" class="danger-action" :aria-label="t('agent.keys.deleteNamed', { name: key.label })" @click="remove(key)">{{ t('tools.delete') }}</button>
        </div>
      </article>
      <p v-if="keys.length === 0" class="empty-inline">{{ t('agent.keys.empty') }}</p>
    </div>
  </section>
</template>
