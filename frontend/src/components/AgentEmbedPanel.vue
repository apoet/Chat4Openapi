<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AgentEmbedConfig, AgentEmbedWrite } from '../api/contracts'
import { useEmbedsStore } from '../stores/embeds'
import { confirmDestructiveAction } from '../ui/confirmDestructiveAction'

const props = defineProps<{ agentId: number }>()
const store = useEmbedsStore()
const { t } = useI18n()
const name = ref('')
const origins = ref('')
const position = ref<'bottom_right' | 'bottom_left'>('bottom_right')
const pending = ref(false)
const copiedId = ref<number | null>(null)
const copyFailedId = ref<number | null>(null)
const error = ref(false)
const embeds = computed(() => store.byAgent[props.agentId] ?? [])

function originList(value: string): string[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)
}

async function load(): Promise<void> {
  error.value = false
  try { await store.load(props.agentId) } catch { error.value = true }
}
onMounted(load)
watch(() => props.agentId, load)

async function create(): Promise<void> {
  if (!name.value.trim() || pending.value) return
  pending.value = true
  try {
    await store.create(props.agentId, {
      name: name.value.trim(), enabled: true,
      allowed_origins: originList(origins.value), position: position.value,
    })
    name.value = ''
    origins.value = ''
  } finally { pending.value = false }
}

function payload(embed: AgentEmbedConfig, changes: Partial<AgentEmbedWrite> = {}): AgentEmbedWrite {
  return {
    name: embed.name, enabled: embed.enabled, allowed_origins: embed.allowed_origins,
    position: embed.position, ...changes,
  }
}

async function toggle(embed: AgentEmbedConfig): Promise<void> {
  await store.update(props.agentId, embed.id, payload(embed, { enabled: !embed.enabled }))
}

async function save(embed: AgentEmbedConfig): Promise<void> {
  await store.update(props.agentId, embed.id, payload(embed))
}

function setOrigins(embed: AgentEmbedConfig, event: Event): void {
  embed.allowed_origins = originList((event.target as HTMLTextAreaElement).value)
}

function legacyCopy(value: string): boolean {
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.readOnly = true
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  document.body.append(textarea)
  textarea.select()
  textarea.setSelectionRange(0, value.length)
  try {
    return typeof document.execCommand === 'function' && document.execCommand('copy')
  } catch {
    return false
  } finally {
    textarea.remove()
  }
}

async function remove(embed: AgentEmbedConfig): Promise<void> {
  const confirmed = await confirmDestructiveAction({
    title: t('confirmations.dialog.deleteTitle', { item: t('confirmations.dialog.items.embed') }),
    message: t('confirmations.deleteEmbed', { name: embed.name }),
    subject: embed.name,
    warning: t('confirmations.dialog.irreversible'),
    confirmLabel: t('confirmations.dialog.deleteAction', { item: t('confirmations.dialog.items.embed') }),
    cancelLabel: t('confirmations.dialog.cancel'),
  })
  if (!confirmed) return
  await store.remove(props.agentId, embed.id)
}

async function copy(embed: AgentEmbedConfig): Promise<void> {
  if (!embed.script) return
  copyFailedId.value = null
  let copied = false
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(embed.script)
      copied = true
    } catch {
      copied = legacyCopy(embed.script)
    }
  } else {
    copied = legacyCopy(embed.script)
  }
  if (copied) {
    copiedId.value = embed.id
  } else {
    copiedId.value = null
    copyFailedId.value = embed.id
  }
}
</script>

<template>
  <section class="agent-key-panel embed-admin-panel">
    <div class="panel-heading"><div><p class="eyebrow">{{ t('embeds.eyebrow') }}</p><h2>{{ t('embeds.title') }}</h2></div></div>
    <p class="muted">{{ t('embeds.subtitle') }}</p>
    <p v-if="error" class="page-error">{{ t('embeds.loadFailed') }}</p>
    <form class="form-grid embed-create-form" @submit.prevent="create">
      <label>{{ t('embeds.name') }}<input v-model="name" data-testid="embed-name" required /></label>
      <label>{{ t('embeds.position') }}<select v-model="position" data-testid="embed-position"><option value="bottom_right">{{ t('embeds.bottomRight') }}</option><option value="bottom_left">{{ t('embeds.bottomLeft') }}</option></select></label>
      <label class="embed-origins">{{ t('embeds.origins') }}<textarea v-model="origins" :placeholder="t('embeds.originsHint')" /></label>
      <button class="primary-action" :disabled="pending || !name.trim()">{{ t('embeds.create') }}</button>
    </form>
    <div class="embed-list">
      <article v-for="embed in embeds" :key="embed.id" class="resource-row embed-row">
        <div><strong>{{ embed.name }}</strong><p>{{ embed.allowed_origins.join(', ') || t('embeds.noOrigins') }}</p><code>{{ embed.public_id }}</code></div>
        <span :class="['status-pill', embed.enabled ? 'enabled' : 'disabled']">{{ embed.enabled ? t('tools.enabled') : t('tools.disabled') }}</span>
        <footer class="row-actions">
          <button type="button" class="secondary-action" data-testid="copy-script" :disabled="!embed.script" @click="copy(embed)">{{ copiedId === embed.id ? t('embeds.copied') : t('embeds.copy') }}</button>
          <a v-if="embed.script" class="secondary-action" :href="`/embed/${embed.public_id}`" target="_blank" rel="noopener">{{ t('embeds.preview') }}</a>
          <button type="button" class="secondary-action" @click="toggle(embed)">{{ embed.enabled ? t('tools.disable') : t('tools.enable') }}</button>
          <button type="button" class="danger-action" @click="remove(embed)">{{ t('tools.delete') }}</button>
        </footer>
        <p v-if="copyFailedId === embed.id" class="page-error" role="alert">{{ t('embeds.copyFailed') }}</p>
        <code v-if="copyFailedId === embed.id" data-testid="embed-script-fallback">{{ embed.script }}</code>
        <details class="embed-editor">
          <summary>{{ t('embeds.edit') }}</summary>
          <form class="form-grid" @submit.prevent="save(embed)">
            <label>{{ t('embeds.name') }}<input v-model="embed.name" required /></label>
            <label>{{ t('embeds.position') }}<select v-model="embed.position"><option value="bottom_right">{{ t('embeds.bottomRight') }}</option><option value="bottom_left">{{ t('embeds.bottomLeft') }}</option></select></label>
            <label>{{ t('embeds.origins') }}<textarea :value="embed.allowed_origins.join('\n')" @input="setOrigins(embed, $event)" /></label>
            <button class="primary-action">{{ t('embeds.save') }}</button>
          </form>
        </details>
      </article>
    </div>
  </section>
</template>
