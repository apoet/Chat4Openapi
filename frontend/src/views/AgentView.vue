<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { routerKey } from 'vue-router'

import { ApiError } from '../api/client'
import type { AgentConfig, AgentConfigWrite } from '../api/contracts'
import AgentEditor from '../components/AgentEditor.vue'
import AgentKeyPanel from '../components/AgentKeyPanel.vue'
import AgentEmbedPanel from '../components/AgentEmbedPanel.vue'
import { AgentSavePartialError, useAgentsStore } from '../stores/agents'

const store = useAgentsStore()
const { t } = useI18n()
const router = inject(routerKey, null)
const selectedId = ref<number | null>(null)
const creating = ref(false)
const errorMessage = ref('')
const savePending = ref(false)
const actionPending = ref(false)
const keyBusy = ref(false)
let selectionGeneration = 0
const selectedAgent = computed(() => store.agents.find((agent) => agent.id === selectedId.value) ?? null)
const interactionLocked = computed(() => savePending.value || actionPending.value || keyBusy.value)

onMounted(async () => {
  const generation = selectionGeneration
  try {
    await store.load()
    if (generation === selectionGeneration && !creating.value && selectedId.value === null) {
      selectedId.value = store.agents.find((agent) => agent.is_default)?.id ?? store.agents[0]?.id ?? null
    }
  } catch (error) { showError(error, 'load_failed') }
})

function showError(error: unknown, fallback: string): void {
  if (error instanceof ApiError) {
    const known = [
      'agents.default_cannot_disable', 'agents.default_cannot_delete',
      'agents.provider_unavailable', 'agents.no_running_skills',
      'agents.skill_duplicate', 'agents.skill_unavailable', 'agents.not_found',
      'agent_keys.not_found',
    ]
    if (known.includes(error.code)) {
      errorMessage.value = t(`error.${error.code}`, error.params)
      return
    }
  }
  errorMessage.value = t(`error.agents.${fallback}`)
}

function select(agent: AgentConfig): void {
  if (interactionLocked.value) return
  selectionGeneration += 1
  creating.value = false
  selectedId.value = agent.id
  errorMessage.value = ''
}

function createAgent(): void {
  if (interactionLocked.value) return
  selectionGeneration += 1
  creating.value = true
  selectedId.value = null
  errorMessage.value = ''
}

function openChat(agent: AgentConfig): void {
  if (!agent.enabled || interactionLocked.value) return
  void router?.push({ name: 'chat', query: { agent_id: String(agent.id) } })
}

async function save(payload: AgentConfigWrite, skillIds: number[]): Promise<void> {
  if (savePending.value) return
  const generation = selectionGeneration
  errorMessage.value = ''
  savePending.value = true
  try {
    const saved = await store.save(payload, skillIds, creating.value ? undefined : selectedAgent.value?.id)
    if (generation === selectionGeneration) {
      selectedId.value = saved.id
      creating.value = false
    }
  } catch (error) {
    if (error instanceof AgentSavePartialError && generation === selectionGeneration) {
      selectedId.value = error.agentId
      creating.value = false
      errorMessage.value = t('error.agents.partial_save')
    } else { showError(error, 'save_failed') }
  } finally { savePending.value = false }
}

async function lifecycle(action: 'enable' | 'disable' | 'set-default'): Promise<void> {
  if (!selectedAgent.value || actionPending.value) return
  const generation = selectionGeneration
  actionPending.value = true
  errorMessage.value = ''
  try {
    const updated = await store.lifecycle(selectedAgent.value, action)
    if (generation === selectionGeneration) selectedId.value = updated.id
  } catch (error) { showError(error, 'action_failed') } finally { actionPending.value = false }
}

async function remove(): Promise<void> {
  if (!selectedAgent.value || actionPending.value) return
  const generation = selectionGeneration
  actionPending.value = true
  errorMessage.value = ''
  try {
    await store.remove(selectedAgent.value)
    if (generation === selectionGeneration) selectedId.value = store.agents.find((agent) => agent.is_default)?.id ?? store.agents[0]?.id ?? null
  } catch (error) { showError(error, 'delete_failed') } finally { actionPending.value = false }
}
</script>

<template>
  <main class="management-page agent-management-page">
    <header class="page-heading with-actions">
      <div>
        <p class="eyebrow">{{ t('agent.eyebrow') }}</p>
        <h1>{{ t('agent.title') }}</h1>
        <p class="muted">{{ t('agent.subtitle') }}</p>
      </div>
      <button type="button" class="primary-action heading-action" :disabled="interactionLocked" @click="createAgent">{{ t('agent.newAgent') }}</button>
    </header>

    <p v-if="errorMessage" class="agent-error page-error" role="alert">{{ errorMessage }}</p>

    <div class="agent-workspace">
      <aside class="agent-roster" :aria-label="t('agent.listTitle')">
        <div class="panel-heading compact-heading"><h2>{{ t('agent.listTitle') }}</h2><span>{{ store.agents.length }}</span></div>
        <div class="agent-list">
          <div v-for="agent in store.agents" :key="agent.id" class="agent-list-row">
            <button type="button" :class="['agent-list-item', { active: selectedId === agent.id && !creating }]" :disabled="interactionLocked" :aria-current="selectedId === agent.id && !creating ? 'true' : undefined" @click="select(agent)">
              <span class="agent-avatar" aria-hidden="true">{{ agent.name.slice(0, 2).toUpperCase() }}</span>
              <span><strong>{{ agent.name }}</strong><small>{{ agent.enabled ? t('tools.enabled') : t('tools.disabled') }}</small></span>
              <b v-if="agent.is_default">{{ t('agent.default') }}</b>
            </button>
            <button type="button" class="agent-chat-action" :disabled="!agent.enabled || interactionLocked" @click="openChat(agent)">{{ t('agent.chat') }}</button>
          </div>
        </div>
        <p v-if="store.agents.length === 0" class="empty-inline">{{ t('agent.empty') }}</p>
      </aside>

      <div class="agent-detail">
        <template v-if="creating || selectedAgent">
          <div v-if="selectedAgent && !creating" class="agent-lifecycle" :aria-label="t('agent.lifecycle')">
            <button v-if="selectedAgent.enabled" type="button" class="secondary-action" :disabled="selectedAgent.is_default || interactionLocked" @click="lifecycle('disable')">{{ t('agent.disable') }}</button>
            <button v-else type="button" class="secondary-action" :disabled="interactionLocked" @click="lifecycle('enable')">{{ t('agent.enable') }}</button>
            <button v-if="!selectedAgent.is_default" type="button" class="secondary-action" :disabled="interactionLocked" @click="lifecycle('set-default')">{{ t('agent.setDefault') }}</button>
            <button v-if="!selectedAgent.is_default" type="button" class="danger-action" :disabled="interactionLocked" @click="remove">{{ t('agent.delete') }}</button>
          </div>
          <AgentEditor :agent="creating ? null : selectedAgent" :providers="store.providers" :skills="store.skills" :pending="interactionLocked" @save="save" @cancel="creating = false; selectedId = store.agents[0]?.id ?? null" />
          <AgentKeyPanel v-if="selectedAgent && !creating" :agent-id="selectedAgent.id" @busy-change="keyBusy = $event" @error="showError($event, 'keys_failed')" />
          <AgentEmbedPanel v-if="selectedAgent && !creating" :agent-id="selectedAgent.id" />
        </template>
        <section v-else class="empty-state">{{ t('agent.chooseAgent') }}</section>
      </div>
    </div>
  </main>
</template>
