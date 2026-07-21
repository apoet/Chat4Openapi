<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, request } from '../api/client'
import type { ChatTurnRequest, ChatTurnResponse, SkillSummary } from '../api/contracts'
import SkillMultiSelect from '../components/SkillMultiSelect.vue'

type ChatMessage = { role: 'user' | 'assistant'; content: string }
type LocalChatSessionV2 = {
  version: 2
  id: string
  conversationId: string | null
  title: string
  skillIds: number[]
  loadedSkillIds: number[]
  status: 'completed' | 'needs_input'
  pending: Record<string, unknown> | null
  messages: ChatMessage[]
  updatedAt: string
}

const STORAGE_KEY = 'chatapi.chat.sessions.v1'
const { t } = useI18n()
const skills = ref<SkillSummary[]>([])
const selectedSkillIds = ref<number[]>([])
const loadedSkillIds = ref<number[]>([])
const input = ref('')
const messages = ref<ChatMessage[]>([])
const conversationId = ref<string | null>(null)
const status = ref<'completed' | 'needs_input'>('completed')
const pending = ref<Record<string, unknown> | null>(null)
const sessions = ref<LocalChatSessionV2[]>(loadSessions())
const activeSessionId = ref<string | null>(sessions.value[0]?.id ?? null)
const loginRequired = ref(false)
const authenticated = ref(false)
const username = ref('')
const password = ref('')
const sending = ref(false)
const errorMessage = ref('')

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isIdList(value: unknown): value is number[] {
  return Array.isArray(value)
    && value.length <= 32
    && new Set(value).size === value.length
    && value.every((id) => Number.isInteger(id) && id > 0)
}

function isMessages(value: unknown): value is ChatMessage[] {
  return Array.isArray(value) && value.every((message) =>
    isRecord(message)
    && (message.role === 'user' || message.role === 'assistant')
    && typeof message.content === 'string',
  )
}

function parseSession(value: unknown): LocalChatSessionV2 | null {
  if (!isRecord(value)
    || typeof value.id !== 'string'
    || !(value.conversationId === null || typeof value.conversationId === 'string')
    || typeof value.title !== 'string'
    || !isMessages(value.messages)
    || typeof value.updatedAt !== 'string') return null

  if (value.version === 2) {
    if (!isIdList(value.skillIds)
      || !isIdList(value.loadedSkillIds)
      || (value.status !== 'completed' && value.status !== 'needs_input')
      || !(value.pending === null || isRecord(value.pending))) return null
    return {
      version: 2,
      id: value.id,
      conversationId: value.conversationId,
      title: value.title,
      skillIds: [...value.skillIds],
      loadedSkillIds: [...value.loadedSkillIds],
      status: value.status,
      pending: value.pending ? { ...value.pending } : null,
      messages: value.messages.map((message) => ({ ...message })),
      updatedAt: value.updatedAt,
    }
  }

  if (!Number.isInteger(value.skillId) || (value.skillId as number) <= 0) return null
  return {
    version: 2,
    id: value.id,
    conversationId: value.conversationId,
    title: value.title,
    skillIds: [value.skillId as number],
    loadedSkillIds: [],
    status: 'completed',
    pending: null,
    messages: value.messages.map((message) => ({ ...message })),
    updatedAt: value.updatedAt,
  }
}

function loadSessions(): LocalChatSessionV2[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    const loaded = Array.isArray(value)
      ? value.map(parseSession).filter((session): session is LocalChatSessionV2 => session !== null)
      : []
    localStorage.setItem(STORAGE_KEY, JSON.stringify(loaded))
    return loaded
  } catch {
    localStorage.setItem(STORAGE_KEY, '[]')
    return []
  }
}

function persistSessions(): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.value))
}

function createLocalId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function skillNames(ids: number[]): string {
  if (ids.length === 0) return t('chat.autoSelect')
  return ids.map((id) => skills.value.find((skill) => skill.id === id)?.name ?? t('chat.unknownSkill')).join(', ')
}

function saveActiveSession(): void {
  if (messages.value.length === 0) return
  const now = new Date().toISOString()
  let session = sessions.value.find((item) => item.id === activeSessionId.value)
  if (!session) {
    session = {
      version: 2,
      id: activeSessionId.value ?? createLocalId(),
      conversationId: conversationId.value,
      title: messages.value.find((message) => message.role === 'user')?.content.slice(0, 48) || t('chat.untitled'),
      skillIds: [],
      loadedSkillIds: [],
      status: 'completed',
      pending: null,
      messages: [],
      updatedAt: now,
    }
    activeSessionId.value = session.id
    sessions.value.unshift(session)
  }
  session.conversationId = conversationId.value
  session.skillIds = [...selectedSkillIds.value]
  session.loadedSkillIds = [...loadedSkillIds.value]
  session.status = status.value
  session.pending = pending.value ? { ...pending.value } : null
  session.messages = messages.value.map((message) => ({ ...message }))
  session.updatedAt = now
  sessions.value = [session, ...sessions.value.filter((item) => item.id !== session!.id)]
  persistSessions()
}

function openSession(session: LocalChatSessionV2): void {
  activeSessionId.value = session.id
  conversationId.value = session.conversationId
  selectedSkillIds.value = [...session.skillIds]
  loadedSkillIds.value = [...session.loadedSkillIds]
  status.value = session.status
  pending.value = session.pending ? { ...session.pending } : null
  messages.value = session.messages.map((message) => ({ ...message }))
  input.value = ''
  errorMessage.value = ''
}

function startNewChat(): void {
  activeSessionId.value = createLocalId()
  conversationId.value = null
  loadedSkillIds.value = []
  status.value = 'completed'
  pending.value = null
  messages.value = []
  input.value = ''
  errorMessage.value = ''
}

function isClarification(message: ChatMessage, index: number): boolean {
  return message.role === 'assistant' && status.value === 'needs_input' && index === messages.value.length - 1
}

onMounted(async () => {
  const restored = sessions.value[0]
  if (restored) openSession(restored)

  const config = await request<{ enabled: boolean }>('/api/tool-session/config')
  loginRequired.value = config.enabled
  if (config.enabled) {
    try {
      await request('/api/tool-session/status')
      authenticated.value = true
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
    }
  }
  skills.value = await request<SkillSummary[]>('/api/skills')
})

async function login(): Promise<void> {
  await request('/api/tool-session/login', {
    method: 'POST',
    body: JSON.stringify({ username: username.value, password: password.value }),
  })
  authenticated.value = true
  password.value = ''
}

async function send(): Promise<void> {
  if (!input.value.trim() || sending.value) return
  const content = input.value.trim()
  const body: ChatTurnRequest = {
    message: content,
    conversation_id: conversationId.value,
    candidate_skill_ids: [...selectedSkillIds.value],
  }
  messages.value.push({ role: 'user', content })
  input.value = ''
  errorMessage.value = ''
  saveActiveSession()
  sending.value = true
  try {
    const result = await request<ChatTurnResponse>('/api/chat/turns', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    conversationId.value = result.conversation_id
    loadedSkillIds.value = [...result.loaded_skill_ids]
    status.value = result.status
    pending.value = result.pending ? { ...result.pending } : null
    messages.value.push({ role: 'assistant', content: result.message })
    saveActiveSession()
  } catch (error) {
    errorMessage.value = error instanceof ApiError
      ? (typeof error.params.reason === 'string' ? error.params.reason : error.code)
      : (error instanceof Error ? error.message : t('error.unknown'))
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <main class="chat-page">
    <header class="chat-header">
      <RouterLink to="/" class="chat-brand"><span class="brand-mark small">CA</span><strong>ChatAPI</strong></RouterLink>
      <span>{{ t('chat.title') }}</span>
    </header>
    <section v-if="loginRequired && !authenticated" class="chat-login">
      <p class="eyebrow">{{ t('chat.apiLogin') }}</p>
      <h1>{{ t('chat.loginTitle') }}</h1>
      <p class="muted">{{ t('chat.loginHint') }}</p>
      <label>{{ t('login.username') }}<input v-model="username" /></label>
      <label>{{ t('login.password') }}<input v-model="password" type="password" /></label>
      <button class="primary-action" @click="login">{{ t('chat.login') }}</button>
    </section>
    <section v-else class="chat-workspace">
      <aside class="chat-history">
        <div class="history-heading"><strong>{{ t('chat.history') }}</strong><button type="button" @click="startNewChat">{{ t('chat.newChat') }}</button></div>
        <p v-if="sessions.length === 0" class="history-empty">{{ t('chat.noHistory') }}</p>
        <button
          v-for="session in sessions"
          :key="session.id"
          type="button"
          :aria-label="session.title"
          :class="['history-item', { active: session.id === activeSessionId }]"
          @click="openSession(session)"
        >
          <span>{{ session.title }}</span><small>{{ skillNames(session.skillIds) }}</small>
        </button>
      </aside>
      <div class="conversation">
        <div class="message-stream">
          <div v-if="messages.length === 0" class="chat-empty">
            <p class="eyebrow">{{ t('chat.eyebrow') }}</p>
            <h1>{{ t('chat.emptyTitle') }}</h1>
            <p>{{ t('chat.emptyHint') }}</p>
          </div>
          <article
            v-for="(message, index) in messages"
            :key="index"
            :class="['message', message.role, { clarification: isClarification(message, index) }]"
          >
            <strong v-if="isClarification(message, index)" class="clarification-label">{{ t('chat.clarification') }}</strong>
            <span>{{ message.content }}</span>
            <small v-if="message.role === 'assistant' && index === messages.length - 1 && loadedSkillIds.length" class="loaded-skills">
              {{ t('chat.loadedSkills', { names: skillNames(loadedSkillIds) }) }}
            </small>
          </article>
          <p v-if="errorMessage" class="chat-error" role="alert">{{ errorMessage }}</p>
        </div>
        <div class="composer">
          <label class="sr-only" for="chat-input">{{ t('chat.message') }}</label>
          <textarea
            id="chat-input"
            v-model="input"
            :placeholder="status === 'needs_input' ? t('chat.answerPlaceholder') : t('chat.placeholder')"
            rows="3"
            @keydown.ctrl.enter="send"
          />
          <button :disabled="sending" @click="send">{{ sending ? t('chat.sending') : t('chat.send') }}</button>
          <div class="skill-dock">
            <SkillMultiSelect v-model="selectedSkillIds" :skills="skills" :disabled="messages.length > 0" />
            <span>{{ messages.length > 0 ? t('chat.scopeLocked') : t('chat.skillHint') }}</span>
          </div>
        </div>
      </div>
    </section>
  </main>
</template>
