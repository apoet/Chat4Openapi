<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AgentApiKey } from '../api/contracts'
import { useAgentsStore } from '../stores/agents'

const props = defineProps<{ agentId: number }>()
const emit = defineEmits<{
  error: [error: unknown]
  'busy-change': [busy: boolean]
}>()
const store = useAgentsStore()
const { locale, t } = useI18n()
const label = ref('')
const expiresAt = ref('')
const secret = ref<string | null>(null)
const creatingKey = ref(false)
const copying = ref(false)
const copyFeedback = ref('')
const editingKeyId = ref<number | null>(null)
const editLabel = ref('')
const editExpiry = ref('')
const updatingKey = ref(false)
const labelInput = ref<HTMLInputElement | null>(null)
const createButton = ref<HTMLButtonElement | null>(null)
const copyButton = ref<HTMLButtonElement | null>(null)
const secretDialog = ref<HTMLDialogElement | null>(null)
const keys = computed(() => store.keysByAgent[props.agentId] ?? [])
const localTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone
let mounted = true
let contextGeneration = 0

watch(() => props.agentId, async (agentId) => {
  const generation = ++contextGeneration
  clearSecret(false)
  label.value = ''
  expiresAt.value = ''
  editingKeyId.value = null
  updatingKey.value = false
  try {
    await store.loadKeys(agentId)
  } catch (error) {
    if (mounted && generation === contextGeneration && agentId === props.agentId) emit('error', error)
  }
}, { immediate: true })

onBeforeUnmount(() => {
  mounted = false
  contextGeneration += 1
  clearSecret(false)
})

function clearSecret(restoreFocus = true): void {
  const hadSecret = Boolean(secret.value)
  if (secretDialog.value?.open) secretDialog.value.close()
  secret.value = null
  copyFeedback.value = ''
  if (hadSecret && mounted && !creatingKey.value) emit('busy-change', false)
  if (restoreFocus && mounted) void nextTick(() => labelInput.value?.focus())
}

async function createKey(): Promise<void> {
  if (!label.value.trim() || creatingKey.value || secret.value) return
  const agentId = props.agentId
  const generation = contextGeneration
  creatingKey.value = true
  emit('busy-change', true)
  try {
    const created = await store.createKey(agentId, label.value.trim(), localInputToIso(expiresAt.value))
    if (!mounted || generation !== contextGeneration || agentId !== props.agentId) {
      await store.discardCreatedKey(agentId, created.id)
      return
    }
    secret.value = created.secret
    label.value = ''
    expiresAt.value = ''
    copyFeedback.value = ''
    creatingKey.value = false
    await nextTick()
    secretDialog.value?.showModal()
    copyButton.value?.focus()
  } catch (error) {
    if (mounted && generation === contextGeneration && agentId === props.agentId) emit('error', error)
  } finally {
    if (mounted) {
      creatingKey.value = false
      if (!secret.value) emit('busy-change', false)
    }
  }
}

async function copySecret(): Promise<void> {
  if (!secret.value || copying.value) return
  copying.value = true
  copyFeedback.value = ''
  try {
    await navigator.clipboard.writeText(secret.value)
    copyFeedback.value = t('agent.keys.copySuccess')
  } catch {
    copyFeedback.value = t('agent.keys.copyFailed')
  } finally { copying.value = false }
}

function beginEdit(key: AgentApiKey): void {
  if (secret.value || creatingKey.value) return
  editingKeyId.value = key.id
  editLabel.value = key.label
  editExpiry.value = key.expires_at ? localDateTimeValue(key.expires_at) : ''
}

async function saveEdit(key: AgentApiKey): Promise<void> {
  if (!editLabel.value.trim() || updatingKey.value) return
  const agentId = props.agentId
  const generation = contextGeneration
  updatingKey.value = true
  try {
    await store.updateKey(agentId, key.id, editLabel.value.trim(), localInputToIso(editExpiry.value))
    if (isCurrent(agentId, generation)) editingKeyId.value = null
  } catch (error) {
    if (isCurrent(agentId, generation)) emit('error', error)
  } finally {
    if (isCurrent(agentId, generation)) updatingKey.value = false
  }
}

async function revoke(key: AgentApiKey): Promise<void> {
  const agentId = props.agentId
  const generation = contextGeneration
  try { await store.revokeKey(agentId, key.id) } catch (error) {
    if (isCurrent(agentId, generation)) emit('error', error)
  }
}

async function remove(key: AgentApiKey): Promise<void> {
  const agentId = props.agentId
  const generation = contextGeneration
  try { await store.deleteKey(agentId, key.id) } catch (error) {
    if (isCurrent(agentId, generation)) emit('error', error)
  }
}

function isCurrent(agentId: number, generation: number): boolean {
  return mounted && agentId === props.agentId && generation === contextGeneration
}

function localInputToIso(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

function localDateTimeValue(value: string): string {
  const valueDate = new Date(value)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${valueDate.getFullYear()}-${pad(valueDate.getMonth() + 1)}-${pad(valueDate.getDate())}T${pad(valueDate.getHours())}:${pad(valueDate.getMinutes())}`
}

function status(key: AgentApiKey): string {
  if (key.revoked_at || !key.enabled) return t('agent.keys.revoked')
  if (key.expires_at && new Date(key.expires_at).getTime() <= Date.now()) return t('agent.keys.expired')
  return t('agent.keys.active')
}

function date(value: string | null): string {
  if (!value) return t('agent.keys.never')
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(new Date(value))
}
</script>

<template>
  <section class="settings-panel agent-key-panel">
    <header class="panel-heading">
      <div><p class="eyebrow">{{ t('agent.keys.eyebrow') }}</p><h2>{{ t('agent.keys.title') }}</h2></div>
    </header>
    <div class="key-create-grid">
      <label>{{ t('agent.keys.label') }}<input ref="labelInput" v-model="label" :disabled="creatingKey || Boolean(secret)" /></label>
      <label>{{ t('agent.keys.expiryLocal', { timeZone: localTimeZone }) }}<input v-model="expiresAt" type="datetime-local" :disabled="creatingKey || Boolean(secret)" /></label>
      <button ref="createButton" type="button" class="primary-action" :disabled="!label.trim() || creatingKey || Boolean(secret)" @click="createKey">
        {{ creatingKey ? t('agent.keys.creating') : t('agent.keys.create') }}
      </button>
    </div>

    <dialog v-if="secret" ref="secretDialog" class="secret-dialog" :aria-label="t('agent.keys.newKey')" @cancel.prevent="clearSecret()">
      <p><strong>{{ t('agent.keys.newKey') }}</strong></p>
      <p>{{ t('agent.keys.oneTimeWarning') }}</p>
      <code>{{ secret }}</code>
      <p v-if="copyFeedback" class="copy-feedback" role="status">{{ copyFeedback }}</p>
      <div class="row-actions">
        <button ref="copyButton" type="button" class="secondary-action" @click="copySecret">{{ copying ? t('agent.keys.copying') : t('agent.keys.copy') }}</button>
        <button type="button" class="primary-action" :aria-label="t('agent.keys.closeSecret')" @click="clearSecret()">{{ t('agent.keys.close') }}</button>
      </div>
    </dialog>

    <div class="key-list">
      <article v-for="key in keys" :key="key.id" class="key-row">
        <template v-if="editingKeyId === key.id">
          <div class="key-inline-editor">
            <label>{{ t('agent.keys.editLabel') }}<input v-model="editLabel" /></label>
            <label>{{ t('agent.keys.editExpiryLocal', { timeZone: localTimeZone }) }}<input v-model="editExpiry" type="datetime-local" /></label>
            <div class="row-actions">
              <button type="button" class="primary-action" :disabled="!editLabel.trim() || updatingKey" :aria-label="t('agent.keys.saveNamed', { name: key.label })" @click="saveEdit(key)">{{ t('agent.keys.save') }}</button>
              <button type="button" class="secondary-action" @click="editingKeyId = null">{{ t('skills.cancel') }}</button>
            </div>
          </div>
        </template>
        <template v-else>
          <div><strong>{{ key.label }}</strong><code>{{ key.key_prefix }}</code></div>
          <dl>
            <div><dt>{{ t('agent.keys.status') }}</dt><dd>{{ status(key) }}</dd></div>
            <div><dt>{{ t('agent.keys.expiry') }}</dt><dd>{{ date(key.expires_at) }}</dd></div>
            <div><dt>{{ t('agent.keys.lastUsed') }}</dt><dd>{{ date(key.last_used_at) }}</dd></div>
          </dl>
          <div class="row-actions">
            <button type="button" class="secondary-action" :disabled="Boolean(secret) || creatingKey" :aria-label="t('agent.keys.editNamed', { name: key.label })" @click="beginEdit(key)">{{ t('skills.edit') }}</button>
            <button v-if="key.enabled && !key.revoked_at" type="button" class="secondary-action" :disabled="Boolean(secret) || creatingKey" :aria-label="t('agent.keys.revokeNamed', { name: key.label })" @click="revoke(key)">{{ t('agent.keys.revoke') }}</button>
            <button type="button" class="danger-action" :disabled="Boolean(secret) || creatingKey" :aria-label="t('agent.keys.deleteNamed', { name: key.label })" @click="remove(key)">{{ t('tools.delete') }}</button>
          </div>
        </template>
      </article>
      <p v-if="keys.length === 0" class="empty-inline">{{ t('agent.keys.empty') }}</p>
    </div>
  </section>
</template>
