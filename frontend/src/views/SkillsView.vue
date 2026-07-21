<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { SkillSummary, ToolSummary } from '../api/contracts'
import { useSkillsStore } from '../stores/skills'

const store = useSkillsStore()
const { t } = useI18n()
const name = ref('')
const description = ref('')
const systemPrompt = ref('')
const providerId = ref<number | null>(null)
const selectedToolIds = ref<number[]>([])
const promptInput = ref<HTMLTextAreaElement | null>(null)
const editingId = ref<number | null>(null)
const eligibleTools = computed(() => store.tools.filter((tool) => tool.enabled))

onMounted(async () => {
  await store.loadProviders()
  await store.loadTools()
  await store.loadSkills()
  providerId.value = store.providers.find((provider) => provider.enabled)?.id ?? null
})

function referenceTool(tool: ToolSummary): void {
  if (!selectedToolIds.value.includes(tool.id)) selectedToolIds.value.push(tool.id)
  const token = `{{tool:${tool.name}}}`
  const input = promptInput.value
  const start = input?.selectionStart ?? systemPrompt.value.length
  const end = input?.selectionEnd ?? start
  systemPrompt.value = `${systemPrompt.value.slice(0, start)}${token}${systemPrompt.value.slice(end)}`
}

async function save(): Promise<void> {
  if (!providerId.value) return
  await store.save({
    name: name.value,
    description: description.value || null,
    system_prompt: systemPrompt.value,
    provider_id: providerId.value,
    tool_ids: selectedToolIds.value,
  }, editingId.value ?? undefined)
  resetEditor()
}

function edit(skill: SkillSummary): void {
  editingId.value = skill.id
  name.value = skill.name
  description.value = skill.description ?? ''
  systemPrompt.value = skill.system_prompt
  providerId.value = skill.provider_id
  selectedToolIds.value = skill.tools.map((tool) => tool.id)
}

function resetEditor(): void {
  editingId.value = null
  name.value = ''
  description.value = ''
  systemPrompt.value = ''
  selectedToolIds.value = []
  providerId.value = store.providers.find((provider) => provider.enabled)?.id ?? null
}

async function remove(skill: SkillSummary): Promise<void> {
  await store.remove(skill)
  if (editingId.value === skill.id) resetEditor()
}
</script>

<template>
  <main class="management-page">
    <header class="page-heading"><div><p class="eyebrow">{{ t('skills.eyebrow') }}</p><h1>{{ t('skills.title') }}</h1><p class="muted">{{ t('skills.subtitle') }}</p></div></header>
    <div class="skill-workbench">
      <section class="settings-panel skill-editor">
        <div class="settings-grid">
          <label>{{ t('skills.name') }}<input v-model="name" /></label>
          <label>{{ t('skills.provider') }}<select v-model="providerId"><option v-for="provider in store.providers.filter((item) => item.enabled)" :key="provider.id" :value="provider.id">{{ provider.name }} · {{ provider.default_model }}</option></select></label>
        </div>
        <label class="block-label">{{ t('skills.description') }}<input v-model="description" /></label>
        <label class="block-label">{{ t('skills.prompt') }}<textarea ref="promptInput" v-model="systemPrompt" rows="9" /></label>
        <div class="bound-count">{{ t('skills.bound', { count: selectedToolIds.length }) }}</div>
        <div class="row-actions editor-actions"><button class="primary-action" :disabled="!name || !providerId || !systemPrompt" @click="save">{{ t('skills.save') }}</button><button v-if="editingId" class="secondary-action" @click="resetEditor">{{ t('skills.cancel') }}</button></div>
      </section>
      <aside class="tool-reference-tray">
        <p class="eyebrow">{{ t('skills.quickReference') }}</p><h2>{{ t('skills.enabledTools') }}</h2><p class="muted">{{ t('skills.quickHint') }}</p>
        <button v-for="tool in eligibleTools" :key="tool.id" class="reference-tool" @click="referenceTool(tool)"><strong>{{ tool.name }}</strong><small>{{ tool.operation_key }}</small></button>
        <div v-if="eligibleTools.length === 0" class="empty-state">{{ t('skills.noTools') }}</div>
      </aside>
    </div>
    <section class="skill-list">
      <article v-for="skill in store.skills" :key="skill.id" class="resource-row"><span class="resource-icon">SK</span><div><strong>{{ skill.name }}</strong><p>{{ skill.tools.length }} Tools</p></div><footer class="row-actions"><button class="secondary-action" @click="edit(skill)">{{ t('skills.edit') }}</button><button class="secondary-action" @click="store.setRunning(skill, !skill.running)">{{ skill.running ? t('skills.stop') : t('skills.start') }}</button><button class="danger-action" @click="remove(skill)">{{ t('tools.delete') }}</button></footer></article>
    </section>
  </main>
</template>
