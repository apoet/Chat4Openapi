<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { SkillSummary } from '../api/contracts'
import ToolCatalogPanel from '../components/ToolCatalogPanel.vue'
import { type IndexedTool, useToolCatalog } from '../composables/useToolCatalog'
import { useSkillsStore } from '../stores/skills'

const store = useSkillsStore()
const { t } = useI18n()
const name = ref('')
const description = ref('')
const systemPrompt = ref('')
const selectedToolIds = ref<number[]>([])
const promptInput = ref<HTMLTextAreaElement | null>(null)
const editingId = ref<number | null>(null)
const mentionStart = ref<number | null>(null)
const mentionEnd = ref<number | null>(null)
const mentionQuery = ref('')
const activeMentionIndex = ref(0)
const mentionOptionElements = new Map<number, HTMLElement>()
const catalog = useToolCatalog(
  computed(() => store.tools),
  computed(() => store.sources),
  computed(() => store.eligibleToolIds),
)
const mentionResult = computed(() => {
  if (mentionStart.value === null) return catalog.query({ skillEligible: true }, 0)
  return catalog.query({ query: mentionQuery.value, skillEligible: true }, 50)
})
const mentionTools = computed(() => mentionResult.value.tools)

onMounted(async () => {
  await Promise.all([store.loadTools(), store.loadSources(), store.loadSkills()])
})

function canonicalReference(tool: IndexedTool): string {
  return `{{tool:${tool.name}}}`
}

function bindTool(tool: IndexedTool): void {
  if (tool.skillEligible && !selectedToolIds.value.includes(tool.id)) {
    selectedToolIds.value.push(tool.id)
  }
}

function referenceTool(tool: IndexedTool): void {
  if (!tool.skillEligible) return
  bindTool(tool)
  const token = canonicalReference(tool)
  const input = promptInput.value
  const start = input?.selectionStart ?? systemPrompt.value.length
  const end = input?.selectionEnd ?? start
  systemPrompt.value = `${systemPrompt.value.slice(0, start)}${token}${systemPrompt.value.slice(end)}`
}

function updateMention(): void {
  const input = promptInput.value
  const cursor = input?.selectionStart ?? systemPrompt.value.length
  const beforeCursor = systemPrompt.value.slice(0, cursor)
  const match = beforeCursor.match(/(?:^|\s)@([^@\n]*)$/)
  if (!match) {
    closeMention()
    return
  }
  mentionStart.value = cursor - match[1].length - 1
  mentionEnd.value = cursor
  mentionQuery.value = match[1]
  activeMentionIndex.value = 0
}

function closeMention(): void {
  mentionStart.value = null
  mentionEnd.value = null
  mentionQuery.value = ''
  activeMentionIndex.value = 0
}

async function chooseMention(tool: IndexedTool): Promise<void> {
  if (!tool.skillEligible || mentionStart.value === null || mentionEnd.value === null) return
  bindTool(tool)
  const token = canonicalReference(tool)
  const cursor = mentionStart.value + token.length
  systemPrompt.value = `${systemPrompt.value.slice(0, mentionStart.value)}${token}${systemPrompt.value.slice(mentionEnd.value)}`
  closeMention()
  await nextTick()
  promptInput.value?.focus()
  promptInput.value?.setSelectionRange(cursor, cursor)
}

function setMentionOption(toolId: number, element: unknown): void {
  if (element instanceof HTMLElement) mentionOptionElements.set(toolId, element)
  else mentionOptionElements.delete(toolId)
}

async function moveActiveMention(delta: number): Promise<void> {
  activeMentionIndex.value = (
    activeMentionIndex.value + delta + mentionTools.value.length
  ) % mentionTools.value.length
  await nextTick()
  const tool = mentionTools.value[activeMentionIndex.value]
  if (tool) mentionOptionElements.get(tool.id)?.scrollIntoView({ block: 'nearest' })
}

function handlePromptKeydown(event: KeyboardEvent): void {
  if (mentionStart.value === null) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeMention()
  } else if (event.key === 'ArrowDown' && mentionTools.value.length) {
    event.preventDefault()
    void moveActiveMention(1)
  } else if (event.key === 'ArrowUp' && mentionTools.value.length) {
    event.preventDefault()
    void moveActiveMention(-1)
  } else if (event.key === 'Enter' && mentionTools.value.length) {
    event.preventDefault()
    void chooseMention(mentionTools.value[activeMentionIndex.value])
  }
}

async function save(): Promise<void> {
  await store.waitForToolEligibility()
  await store.save({
    name: name.value,
    description: description.value || null,
    system_prompt: systemPrompt.value,
    tool_ids: selectedToolIds.value.filter((id) => store.eligibleToolIds.has(id)),
  }, editingId.value ?? undefined)
  resetEditor()
}

function edit(skill: SkillSummary): void {
  editingId.value = skill.id
  name.value = skill.name
  description.value = skill.description ?? ''
  systemPrompt.value = skill.system_prompt
  selectedToolIds.value = skill.tools.map((tool) => tool.id)
}

function resetEditor(): void {
  editingId.value = null
  name.value = ''
  description.value = ''
  systemPrompt.value = ''
  selectedToolIds.value = []
  closeMention()
}

async function remove(skill: SkillSummary): Promise<void> {
  if (!window.confirm(t('confirmations.deleteSkill', { name: skill.name }))) return
  await store.remove(skill)
  if (editingId.value === skill.id) resetEditor()
}
</script>

<template>
  <main class="management-page">
    <header class="page-heading"><div><p class="eyebrow">{{ t('skills.eyebrow') }}</p><h1>{{ t('skills.title') }}</h1><p class="muted">{{ t('skills.subtitle') }}</p></div></header>
    <div class="skill-workbench">
      <div class="skill-primary-column">
        <section class="settings-panel skill-editor">
          <div class="settings-grid"><label>{{ t('skills.name') }}<input v-model="name" /></label></div>
          <label class="block-label">{{ t('skills.description') }}<input v-model="description" /></label>
          <div class="prompt-field">
            <label class="block-label">{{ t('skills.prompt') }}<textarea ref="promptInput" v-model="systemPrompt" rows="9" aria-autocomplete="list" :aria-controls="mentionTools.length ? 'tool-mention-menu' : undefined" :aria-activedescendant="mentionTools.length ? `tool-mention-${mentionTools[activeMentionIndex].id}` : undefined" :aria-expanded="mentionTools.length > 0" @input="updateMention" @keydown="handlePromptKeydown" /></label>
            <div v-if="mentionTools.length" id="tool-mention-menu" class="tool-mention-menu" role="listbox" :aria-label="t('skills.catalog.suggestions')">
              <div v-for="source in mentionResult.groups" :key="source.id" class="mention-source">
                <div v-for="tagGroup in source.tags" :key="tagGroup.name" role="group" :aria-label="`${source.name} / ${tagGroup.name || t('skills.untagged')}`">
                  <p class="mention-category">{{ source.name }} / {{ tagGroup.name || t('skills.untagged') }}</p>
                  <button v-for="tool in tagGroup.tools" :id="`tool-mention-${tool.id}`" :key="tool.id" :ref="(element) => setMentionOption(tool.id, element)" type="button" role="option" :aria-selected="mentionTools[activeMentionIndex]?.id === tool.id" :class="{ active: mentionTools[activeMentionIndex]?.id === tool.id }" :aria-label="t('skills.mentionTool', { name: tool.name })" @mousedown.prevent @click="chooseMention(tool)"><strong>{{ tool.name }}</strong><small>{{ tool.method }} {{ tool.path }}</small></button>
                </div>
              </div>
            </div>
          </div>
          <div class="bound-count">{{ t('skills.bound', { count: selectedToolIds.length }) }}</div>
          <div class="row-actions editor-actions"><button class="primary-action" :disabled="!name || !systemPrompt" @click="save">{{ t('skills.save') }}</button><button v-if="editingId" class="secondary-action" @click="resetEditor">{{ t('skills.cancel') }}</button></div>
        </section>
        <section class="skill-list">
          <article v-for="skill in store.skills" :key="skill.id" class="resource-row"><span class="resource-icon">SK</span><div><strong>{{ skill.name }}</strong><p>{{ skill.tools.length }} Tools</p></div><footer class="row-actions"><button class="secondary-action" @click="edit(skill)">{{ t('skills.edit') }}</button><button class="secondary-action" @click="store.setRunning(skill, !skill.running)">{{ skill.running ? t('skills.stop') : t('skills.start') }}</button><button class="danger-action" @click="remove(skill)">{{ t('tools.delete') }}</button></footer></article>
        </section>
      </div>
      <ToolCatalogPanel v-model="selectedToolIds" :catalog="catalog" @reference="referenceTool" />
    </div>
  </main>
</template>
