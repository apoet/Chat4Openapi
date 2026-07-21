<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
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
const mentionStart = ref<number | null>(null)
const mentionEnd = ref<number | null>(null)
const mentionQuery = ref('')
const mentionTools = computed(() => {
  if (mentionStart.value === null) return []
  const query = mentionQuery.value.toLocaleLowerCase()
  return eligibleTools.value
    .filter((tool) => tool.name.toLocaleLowerCase().includes(query))
    .slice(0, 20)
})
const referenceGroups = computed(() => {
  const sources = new Map<number, {
    id: number
    name: string
    toolCount: number
    tags: Map<string, { name: string; tools: ToolSummary[] }>
  }>()
  for (const tool of eligibleTools.value) {
    let sourceGroup = sources.get(tool.api_source_id)
    if (!sourceGroup) {
      sourceGroup = {
        id: tool.api_source_id,
        name: store.sources.find((source) => source.id === tool.api_source_id)?.name
          || `#${tool.api_source_id}`,
        toolCount: 0,
        tags: new Map(),
      }
      sources.set(tool.api_source_id, sourceGroup)
    }
    const tagName = tool.tags?.[0] || t('skills.untagged')
    let tagGroup = sourceGroup.tags.get(tagName)
    if (!tagGroup) {
      tagGroup = { name: tagName, tools: [] }
      sourceGroup.tags.set(tagName, tagGroup)
    }
    tagGroup.tools.push(tool)
    sourceGroup.toolCount += 1
  }
  return [...sources.values()].map((source) => ({
    id: source.id,
    name: source.name,
    toolCount: source.toolCount,
    tags: [...source.tags.values()],
  }))
})

onMounted(async () => {
  await store.loadProviders()
  await store.loadTools()
  await store.loadSources()
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

function updateMention(): void {
  const input = promptInput.value
  const cursor = input?.selectionStart ?? systemPrompt.value.length
  const beforeCursor = systemPrompt.value.slice(0, cursor)
  const match = beforeCursor.match(/(?:^|\s)@([a-zA-Z0-9_.-]*)$/)
  if (!match) {
    closeMention()
    return
  }
  mentionStart.value = cursor - match[1].length - 1
  mentionEnd.value = cursor
  mentionQuery.value = match[1]
}

function closeMention(): void {
  mentionStart.value = null
  mentionEnd.value = null
  mentionQuery.value = ''
}

async function chooseMention(tool: ToolSummary): Promise<void> {
  if (mentionStart.value === null || mentionEnd.value === null) return
  if (!selectedToolIds.value.includes(tool.id)) selectedToolIds.value.push(tool.id)
  const token = `{{tool:${tool.name}}}`
  const cursor = mentionStart.value + token.length
  systemPrompt.value = `${systemPrompt.value.slice(0, mentionStart.value)}${token}${systemPrompt.value.slice(mentionEnd.value)}`
  closeMention()
  await nextTick()
  promptInput.value?.focus()
  promptInput.value?.setSelectionRange(cursor, cursor)
}

function handlePromptKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    closeMention()
  } else if (event.key === 'Enter' && mentionTools.value.length) {
    event.preventDefault()
    void chooseMention(mentionTools.value[0])
  }
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
  closeMention()
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
        <div class="prompt-field"><label class="block-label">{{ t('skills.prompt') }}<textarea ref="promptInput" v-model="systemPrompt" rows="9" @input="updateMention" @keydown="handlePromptKeydown" /></label><div v-if="mentionTools.length" class="tool-mention-menu"><button v-for="tool in mentionTools" :key="tool.id" type="button" :aria-label="t('skills.mentionTool', { name: tool.name })" @click="chooseMention(tool)"><strong>{{ tool.name }}</strong><small>{{ tool.description || tool.operation_key }}</small></button></div></div>
        <div class="bound-count">{{ t('skills.bound', { count: selectedToolIds.length }) }}</div>
        <div class="row-actions editor-actions"><button class="primary-action" :disabled="!name || !providerId || !systemPrompt" @click="save">{{ t('skills.save') }}</button><button v-if="editingId" class="secondary-action" @click="resetEditor">{{ t('skills.cancel') }}</button></div>
      </section>
      <aside class="tool-reference-tray">
        <p class="eyebrow">{{ t('skills.quickReference') }}</p><h2>{{ t('skills.enabledTools') }}</h2><p class="muted">{{ t('skills.quickHint') }}</p>
        <div class="reference-groups">
          <details v-for="source in referenceGroups" :key="source.id" class="reference-source-group" open>
            <summary><h3>{{ source.name }}</h3><span>{{ t('tools.count', { count: source.toolCount }) }}</span></summary>
            <details v-for="tag in source.tags" :key="tag.name" class="reference-tag-group" open>
              <summary><h4>{{ tag.name }}</h4><span>{{ tag.tools.length }}</span></summary>
              <button v-for="tool in tag.tools" :key="tool.id" class="reference-tool" @click="referenceTool(tool)"><strong>{{ tool.name }}</strong><small>{{ tool.operation_key }}</small></button>
            </details>
          </details>
        </div>
        <div v-if="eligibleTools.length === 0" class="empty-state">{{ t('skills.noTools') }}</div>
      </aside>
    </div>
    <section class="skill-list">
      <article v-for="skill in store.skills" :key="skill.id" class="resource-row"><span class="resource-icon">SK</span><div><strong>{{ skill.name }}</strong><p>{{ skill.tools.length }} Tools</p></div><footer class="row-actions"><button class="secondary-action" @click="edit(skill)">{{ t('skills.edit') }}</button><button class="secondary-action" @click="store.setRunning(skill, !skill.running)">{{ skill.running ? t('skills.stop') : t('skills.start') }}</button><button class="danger-action" @click="remove(skill)">{{ t('tools.delete') }}</button></footer></article>
    </section>
  </main>
</template>
