<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AgentConfig, AgentConfigWrite, LlmProviderSummary, SkillSummary } from '../api/contracts'

const props = defineProps<{
  agent: AgentConfig | null
  providers: LlmProviderSummary[]
  skills: SkillSummary[]
  pending?: boolean
}>()
const emit = defineEmits<{
  save: [payload: AgentConfigWrite, skillIds: number[]]
  cancel: []
}>()
const { t } = useI18n()
const search = ref('')
const boundSkillIds = ref<number[]>([])
const form = reactive<AgentConfigWrite>({
  name: '', description: null, enabled: true, system_prompt: '', provider_id: null,
  model: null, mode: 'human_in_loop', max_iterations: 8,
})

watch(() => props.agent, (agent) => {
  Object.assign(form, agent ? {
    name: agent.name,
    description: agent.description,
    enabled: agent.enabled,
    system_prompt: agent.system_prompt,
    provider_id: agent.provider_id,
    model: agent.model,
    mode: agent.mode,
    max_iterations: agent.max_iterations,
  } : {
    name: '', description: null, enabled: true, system_prompt: '', provider_id: null,
    model: null, mode: 'human_in_loop', max_iterations: 8,
  })
  boundSkillIds.value = agent?.skill_ids.slice() ?? []
  search.value = ''
}, { immediate: true })

const enabledProviders = computed(() => props.providers.filter((provider) => provider.enabled))
const boundSkills = computed(() => boundSkillIds.value.map((id) => {
  const skill = props.skills.find((item) => item.id === id)
  return skill ? { ...skill, unavailable: false } : {
    id,
    name: t('agent.unavailableSkill', { id }),
    description: null,
    system_prompt: '',
    running: false,
    tools: [],
    unavailable: true,
  }
}))
const availableSkills = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  return props.skills.filter((skill) => !boundSkillIds.value.includes(skill.id)
    && (!query || `${skill.name} ${skill.description ?? ''}`.toLocaleLowerCase().includes(query)))
})
const canSave = computed(() => Boolean(
  form.name.trim() && form.system_prompt.trim()
  && form.max_iterations >= 2 && form.max_iterations <= 32,
))

function addSkill(skill: SkillSummary): void {
  boundSkillIds.value.push(skill.id)
}

function removeSkill(id: number): void {
  boundSkillIds.value = boundSkillIds.value.filter((skillId) => skillId !== id)
}

function moveSkill(index: number, delta: -1 | 1): void {
  const target = index + delta
  if (target < 0 || target >= boundSkillIds.value.length) return
  const next = boundSkillIds.value.slice()
  ;[next[index], next[target]] = [next[target], next[index]]
  boundSkillIds.value = next
}

function save(): void {
  if (!canSave.value || props.pending) return
  emit('save', {
    name: form.name.trim(),
    description: form.description?.trim() || null,
    enabled: props.agent?.enabled ?? true,
    system_prompt: form.system_prompt.trim(),
    provider_id: form.provider_id,
    model: form.model?.trim() || null,
    mode: form.mode,
    max_iterations: form.max_iterations,
  }, boundSkillIds.value.slice())
}
</script>

<template>
  <section class="settings-panel agent-editor-panel" :aria-label="t('agent.editorTitle')">
    <header class="panel-heading">
      <div>
        <p class="eyebrow">{{ agent ? t('agent.editing') : t('agent.creating') }}</p>
        <h2>{{ agent?.name || t('agent.newAgent') }}</h2>
      </div>
      <span v-if="agent" :class="['status-pill', agent.enabled ? 'enabled' : 'disabled']">
        {{ agent.enabled ? t('tools.enabled') : t('tools.disabled') }}
      </span>
    </header>

    <div class="settings-grid agent-fields">
      <label>{{ t('agent.name') }}<input v-model="form.name" :disabled="pending" /></label>
      <label>{{ t('agent.provider') }}
        <select v-model="form.provider_id" :disabled="pending">
          <option :value="null">{{ t('agent.selectProvider') }}</option>
          <option v-for="provider in enabledProviders" :key="provider.id" :value="provider.id">
            {{ provider.name }} · {{ provider.default_model }}
          </option>
        </select>
      </label>
      <label>{{ t('agent.model') }}<input v-model="form.model" :disabled="pending" :placeholder="t('agent.modelHint')" /></label>
      <label>{{ t('agent.mode') }}
        <select v-model="form.mode" :disabled="pending">
          <option value="human_in_loop">{{ t('agent.humanInLoop') }}</option>
          <option value="react">{{ t('agent.react') }}</option>
        </select>
      </label>
      <label>{{ t('agent.maxIterations') }}<input v-model.number="form.max_iterations" type="number" min="2" max="32" :disabled="pending" /></label>
    </div>
    <label class="block-label">{{ t('agent.description') }}<textarea v-model="form.description" rows="3" maxlength="4000" :disabled="pending" /></label>
    <label class="block-label">{{ t('agent.systemPrompt') }}<textarea v-model="form.system_prompt" rows="7" :disabled="pending" /></label>

    <section class="skill-binding" role="region" :aria-label="t('agent.boundSkills')">
      <div class="panel-heading compact-heading">
        <div><h3>{{ t('agent.boundSkills') }}</h3><p class="muted">{{ t('agent.skillOrderHint') }}</p></div>
        <span class="bound-count">{{ t('agent.skillCount', { count: boundSkillIds.length }) }}</span>
      </div>
      <ol class="bound-skill-list">
        <li v-for="(skill, index) in boundSkills" :key="skill.id">
          <span class="skill-order">{{ index + 1 }}</span>
          <div><strong>{{ skill.name }}</strong><small v-if="skill.unavailable" class="stopped-label">{{ t('agent.unavailable') }}</small><small v-else-if="!skill.running" class="stopped-label">{{ t('agent.stopped') }}</small></div>
          <div class="skill-order-actions">
            <button type="button" :disabled="pending || index === 0" :aria-label="t('agent.moveUp', { name: skill.name })" @click="moveSkill(index, -1)">↑</button>
            <button type="button" :disabled="pending || index === boundSkills.length - 1" :aria-label="t('agent.moveDown', { name: skill.name })" @click="moveSkill(index, 1)">↓</button>
            <button type="button" class="danger-action" :disabled="pending" :aria-label="t('agent.removeSkill', { name: skill.name })" @click="removeSkill(skill.id)">×</button>
          </div>
        </li>
      </ol>
      <p v-if="boundSkills.length === 0" class="empty-inline">{{ t('agent.noBoundSkills') }}</p>
      <label class="skill-search">{{ t('agent.searchSkills') }}<input v-model="search" :disabled="pending" :placeholder="t('agent.searchSkillsHint')" /></label>
      <div class="available-skills">
        <button v-for="skill in availableSkills" :key="skill.id" type="button" :disabled="pending" :aria-label="t('agent.addSkill', { name: skill.name })" @click="addSkill(skill)">
          <span><strong>{{ skill.name }}</strong><small>{{ skill.description }}</small></span>
          <span :class="['status-pill', skill.running ? 'enabled' : 'disabled']">{{ skill.running ? t('agent.running') : t('agent.stopped') }}</span>
        </button>
      </div>
    </section>

    <div class="row-actions editor-actions">
      <button type="button" class="primary-action" :disabled="!canSave || pending" @click="save">{{ pending ? t('agent.saving') : t('agent.save') }}</button>
      <button v-if="!agent" type="button" class="secondary-action" :disabled="pending" @click="emit('cancel')">{{ t('skills.cancel') }}</button>
    </div>
  </section>
</template>
