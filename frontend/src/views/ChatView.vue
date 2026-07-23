<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { routeLocationKey } from 'vue-router'

import logoUrl from '../../../logo.png'
import { ApiError, request } from '../api/client'
import type {
  ChatAgentSummary,
  ChatBootstrapResponse,
  ChatTurnRequest,
  ChatTurnResponse,
  SkillSummary,
} from '../api/contracts'
import AgentSelect from '../components/AgentSelect.vue'
import MarkdownMessage from '../components/MarkdownMessage.vue'

type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  kind: 'message' | 'clarification'
}
type LocalChatSessionV3 = {
  version: 3
  id: string
  conversationId: string | null
  title: string
  agentId: number | null
  agentName: string | null
  loadedSkillIds: number[]
  status: 'completed' | 'needs_input'
  pending: Record<string, unknown> | null
  messages: ChatMessage[]
  updatedAt: string
}

const LEGACY_STORAGE_KEY = 'chat4openapi.chat.sessions.v1'
const STORAGE_PREFIX = 'chat4openapi.chat.sessions.v3.'
const { t } = useI18n()
const route = inject(routeLocationKey, null)
const agents = ref<ChatAgentSummary[]>([])
const selectedAgentId = ref<number | null>(null)
const selectedAgentName = ref<string | null>(null)
const skills = ref<SkillSummary[]>([])
const loadedSkillIds = ref<number[]>([])
const input = ref('')
const messages = ref<ChatMessage[]>([])
const conversationId = ref<string | null>(null)
const status = ref<'completed' | 'needs_input'>('completed')
const pending = ref<Record<string, unknown> | null>(null)
const sessions = ref<LocalChatSessionV3[]>([])
const activeSessionId = ref<string | null>(null)
const storageKey = ref<string | null>(null)
let preservedFutureSessions: unknown[] = []
const loginRequired = ref(false)
const authenticated = ref(false)
const username = ref('')
const password = ref('')
const sending = ref(false)
const errorMessage = ref('')
const sessionErrors = ref<Record<string, string>>({})

const suggestedQuestions = computed(() => {
  const selected = agents.value.find((agent) => agent.id === selectedAgentId.value)
  const skillIds = selected?.skill_ids?.length ? selected.skill_ids : loadedSkillIds.value
  const skill = skills.value.find((item) => skillIds.includes(item.id))
  if (!skill) return []
  const detail = skill.description?.trim() || skill.name
  return [
    t('chat.suggestions.task', { detail }),
    t('chat.suggestions.explore', { skill: skill.name }),
  ]
})

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isIdList(value: unknown): value is number[] {
  return Array.isArray(value)
    && value.length <= 32
    && new Set(value).size === value.length
    && value.every((id) => Number.isInteger(id) && id > 0)
}

function parseMessages(
  value: unknown,
  status: 'completed' | 'needs_input',
): ChatMessage[] | null {
  if (!Array.isArray(value) || !value.every((message) =>
    isRecord(message)
    && (message.role === 'user' || message.role === 'assistant')
    && typeof message.content === 'string'
    && (message.kind === undefined || message.kind === 'message' || message.kind === 'clarification'),
  )) return null

  return value.map((message, index) => ({
    role: message.role as ChatMessage['role'],
    content: message.content as string,
    kind: message.kind === 'message' || message.kind === 'clarification'
      ? message.kind
      : (status === 'needs_input'
          && index === value.length - 1
          && message.role === 'assistant'
        ? 'clarification'
        : 'message'),
  }))
}

function parseSession(value: unknown): LocalChatSessionV3 | null {
  if (!isRecord(value)
    || typeof value.id !== 'string'
    || !(value.conversationId === null || typeof value.conversationId === 'string')
    || typeof value.title !== 'string'
    || typeof value.updatedAt !== 'string') return null

  if (value.version === 3) {
    if (!isIdList(value.loadedSkillIds)
      || !(value.agentId === null || (Number.isInteger(value.agentId) && (value.agentId as number) > 0))
      || !(value.agentName === null || typeof value.agentName === 'string')
      || (value.status !== 'completed' && value.status !== 'needs_input')
      || !(value.pending === null || isRecord(value.pending))) return null
    const messages = parseMessages(value.messages, value.status)
    if (!messages) return null
    return {
      version: 3,
      id: value.id,
      conversationId: value.conversationId,
      title: value.title,
      agentId: value.agentId as number | null,
      agentName: value.agentName as string | null,
      loadedSkillIds: [...value.loadedSkillIds],
      status: value.status,
      pending: value.pending ? { ...value.pending } : null,
      messages,
      updatedAt: value.updatedAt,
    }
  }

  if (value.version !== undefined && value.version !== 1 && value.version !== 2) return null

  const legacyStatus = value.version === 2 && value.status === 'needs_input'
    ? 'needs_input'
    : 'completed'
  if (value.version === 2
    && (!isIdList(value.loadedSkillIds)
      || (value.status !== 'completed' && value.status !== 'needs_input')
      || !(value.pending === null || isRecord(value.pending)))) return null
  const messages = parseMessages(value.messages, legacyStatus)
  if (!messages) return null
  return {
    version: 3,
    id: value.id,
    conversationId: value.conversationId,
    title: value.title,
    agentId: null,
    agentName: null,
    loadedSkillIds: value.version === 2 ? [...value.loadedSkillIds as number[]] : [],
    status: legacyStatus,
    pending: value.version === 2 && value.pending ? { ...value.pending as Record<string, unknown> } : null,
    messages,
    updatedAt: value.updatedAt,
  }
}

function loadSessions(key: string): LocalChatSessionV3[] {
  const namespacedValue = localStorage.getItem(key)
  const legacyValue = namespacedValue === null
    ? localStorage.getItem(LEGACY_STORAGE_KEY)
    : null
  const claimsLegacyHistory = namespacedValue === null && legacyValue !== null
  let loaded: LocalChatSessionV3[] = []

  try {
    const value: unknown = JSON.parse(namespacedValue ?? legacyValue ?? '[]')
    preservedFutureSessions = Array.isArray(value)
      ? value.filter((item) => isRecord(item)
        && item.version !== undefined
        && item.version !== 1
        && item.version !== 2
        && item.version !== 3)
      : []
    loaded = Array.isArray(value)
      ? value
          .filter((item) => !preservedFutureSessions.includes(item))
          .map(parseSession)
          .filter((session): session is LocalChatSessionV3 => session !== null)
      : []
  } catch {
    preservedFutureSessions = []
  }

  try {
    localStorage.setItem(key, JSON.stringify([...loaded, ...preservedFutureSessions]))
  } catch {
    return loaded
  }

  if (claimsLegacyHistory) localStorage.removeItem(LEGACY_STORAGE_KEY)
  return loaded
}

function persistSessions(): void {
  if (storageKey.value === null) return
  localStorage.setItem(
    storageKey.value,
    JSON.stringify([...sessions.value, ...preservedFutureSessions]),
  )
}

function createLocalId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function selectDefaultAgent(): void {
  const defaultAgent = agents.value.find((agent) => agent.is_default) ?? agents.value[0]
  selectedAgentId.value = defaultAgent?.id ?? null
  selectedAgentName.value = defaultAgent?.name ?? null
}

function requestedAgent(): ChatAgentSummary | undefined {
  const value = route?.query.agent_id
  if (typeof value !== 'string' || !/^\d+$/.test(value)) return undefined
  const id = Number(value)
  return agents.value.find((agent) => agent.id === id)
}

function skillNames(ids: number[]): string {
  return ids.map((id) => skills.value.find((skill) => skill.id === id)?.name ?? t('chat.unknownSkill')).join(', ')
}

function saveActiveSession(): void {
  if (messages.value.length === 0) return
  const now = new Date().toISOString()
  let session = sessions.value.find((item) => item.id === activeSessionId.value)
  if (!session) {
    session = {
      version: 3,
      id: activeSessionId.value ?? createLocalId(),
      conversationId: conversationId.value,
      title: messages.value.find((message) => message.role === 'user')?.content.slice(0, 48) || t('chat.untitled'),
      agentId: selectedAgentId.value,
      agentName: agents.value.find((agent) => agent.id === selectedAgentId.value)?.name ?? selectedAgentName.value,
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
  session.agentId = selectedAgentId.value
  session.agentName = agents.value.find((agent) => agent.id === selectedAgentId.value)?.name ?? selectedAgentName.value
  session.loadedSkillIds = [...loadedSkillIds.value]
  session.status = status.value
  session.pending = pending.value ? { ...pending.value } : null
  session.messages = messages.value.map((message) => ({ ...message }))
  session.updatedAt = now
  sessions.value = [session, ...sessions.value.filter((item) => item.id !== session!.id)]
  persistSessions()
}

function openSession(session: LocalChatSessionV3): void {
  activeSessionId.value = session.id
  conversationId.value = session.conversationId
  selectedAgentId.value = session.agentId
  selectedAgentName.value = session.agentName
  loadedSkillIds.value = [...session.loadedSkillIds]
  status.value = session.status
  pending.value = session.pending ? { ...session.pending } : null
  messages.value = session.messages.map((message) => ({ ...message }))
  input.value = ''
  errorMessage.value = sessionErrors.value[session.id] ?? ''
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
  selectDefaultAgent()
}

function saveSessionResult(sessionId: string, result: ChatTurnResponse): void {
  const session = sessions.value.find((item) => item.id === sessionId)
  if (!session) return
  session.conversationId = result.conversation_id
  session.agentId = result.agent_id
  session.agentName = result.agent_name
  session.loadedSkillIds = [...result.loaded_skill_ids]
  session.status = result.status
  session.pending = result.pending ? { ...result.pending } : null
  session.messages.push({
    role: 'assistant',
    content: result.message,
    kind: result.status === 'needs_input' ? 'clarification' : 'message',
  })
  session.updatedAt = new Date().toISOString()
  sessions.value = [session, ...sessions.value.filter((item) => item.id !== sessionId)]
  persistSessions()

  if (activeSessionId.value === sessionId) {
    conversationId.value = session.conversationId
    selectedAgentId.value = session.agentId
    selectedAgentName.value = session.agentName
    loadedSkillIds.value = [...session.loadedSkillIds]
    status.value = session.status
    pending.value = session.pending ? { ...session.pending } : null
    messages.value = session.messages.map((message) => ({ ...message }))
  }
}

watch(selectedAgentId, (agentId) => {
  const selected = agents.value.find((agent) => agent.id === agentId)
  if (selected) selectedAgentName.value = selected.name
})

function formatTurnError(error: unknown): string {
  if (error instanceof ApiError && error.code === 'agent.conversation_not_found') {
    return t('error.chat.historyUnavailable')
  }
  if (error instanceof ApiError && error.code === 'agent.unavailable') {
    return t('error.chat.agentUnavailable')
  }
  return error instanceof ApiError
    ? (typeof error.params.reason === 'string' ? error.params.reason : error.code)
    : (error instanceof Error ? error.message : t('error.unknown'))
}

async function recoverBrowserSession(): Promise<void> {
  const bootstrap = await request<ChatBootstrapResponse>('/api/chat/bootstrap')
  agents.value = bootstrap.agents
  storageKey.value = `${STORAGE_PREFIX}${encodeURIComponent(bootstrap.subject_id)}`
  sessions.value = loadSessions(storageKey.value)
  sessionErrors.value = {}
  const restored = sessions.value[0]
  if (restored) {
    openSession(restored)
  } else {
    activeSessionId.value = null
    startNewChat()
  }
  errorMessage.value = t('error.chat.browserSessionChanged')
}

onMounted(async () => {
  const [config, bootstrap, skillList] = await Promise.all([
    request<{ enabled: boolean }>('/api/tool-session/config'),
    request<ChatBootstrapResponse>('/api/chat/bootstrap'),
    request<SkillSummary[]>('/api/skills'),
  ])
  agents.value = bootstrap.agents
  skills.value = skillList
  storageKey.value = `${STORAGE_PREFIX}${encodeURIComponent(bootstrap.subject_id)}`
  sessions.value = loadSessions(storageKey.value)
  activeSessionId.value = sessions.value[0]?.id ?? null
  const restored = sessions.value[0]
  if (restored) openSession(restored)

  loginRequired.value = config.enabled
  if (config.enabled) {
    try {
      await request('/api/tool-session/status')
      authenticated.value = true
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
    }
  }
  const routeAgent = requestedAgent()
  if (routeAgent) {
    startNewChat()
    selectedAgentId.value = routeAgent.id
    selectedAgentName.value = routeAgent.name
  } else if (conversationId.value === null && selectedAgentId.value === null) {
    selectDefaultAgent()
  }
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
  if (!input.value.trim() || sending.value || (conversationId.value === null && selectedAgentId.value === null)) return
  const content = input.value.trim()
  const body: ChatTurnRequest = {
    message: content,
    conversation_id: conversationId.value,
  }
  if (conversationId.value === null && selectedAgentId.value !== null) body.agent_id = selectedAgentId.value
  messages.value.push({ role: 'user', content, kind: 'message' })
  input.value = ''
  errorMessage.value = ''
  saveActiveSession()
  const sessionId = activeSessionId.value
  if (!sessionId) return
  const nextErrors = { ...sessionErrors.value }
  delete nextErrors[sessionId]
  sessionErrors.value = nextErrors
  sending.value = true
  try {
    const result = await request<ChatTurnResponse>('/api/chat/turns', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    saveSessionResult(sessionId, result)
  } catch (error) {
    if (error instanceof ApiError
      && (error.code === 'chat.browser_session_required'
        || error.code === 'chat.browser_session_expired')) {
      try {
        await recoverBrowserSession()
      } catch (recoveryError) {
        errorMessage.value = formatTurnError(recoveryError)
      }
      return
    }
    const message = formatTurnError(error)
    sessionErrors.value = { ...sessionErrors.value, [sessionId]: message }
    if (activeSessionId.value === sessionId) errorMessage.value = message
  } finally {
    sending.value = false
  }
}

function handleEnter(event: KeyboardEvent): void {
  if (event.isComposing || event.shiftKey) return
  event.preventDefault()
  void send()
}

function useSuggestedQuestion(question: string): void {
  input.value = question
}
</script>

<template>
  <main class="chat-page">
    <header class="chat-header">
      <RouterLink to="/" class="chat-brand"><span class="brand-mark brand-logo small"><img :src="logoUrl" alt="Agent4API" /></span><strong>Agent4API</strong></RouterLink>
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
          <span>{{ session.title }}</span><small>{{ session.agentName || t('chat.conversationAgent') }}</small>
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
            :class="['message', message.role, { clarification: message.kind === 'clarification' }]"
          >
            <strong v-if="message.kind === 'clarification'" class="clarification-label">{{ t('chat.clarification') }}</strong>
            <span v-if="message.role === 'user'">{{ message.content }}</span>
            <MarkdownMessage v-else :content="message.content" />
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
            @keydown.enter="handleEnter"
          />
          <button
            :disabled="sending || (conversationId === null && selectedAgentId === null)"
            @click="send"
          >{{ sending ? t('chat.sending') : t('chat.send') }}</button>
          <div class="agent-dock">
            <AgentSelect
              v-model="selectedAgentId"
              :agents="agents"
              :snapshot-name="selectedAgentName"
              :disabled="sending || conversationId !== null"
            />
            <span>{{ conversationId !== null ? t('chat.agentLocked') : t('chat.agentHint') }}</span>
          </div>
          <div v-if="suggestedQuestions.length && status !== 'needs_input'" class="chat-suggestions">
            <span>{{ t('chat.suggestions.label') }}</span>
            <button v-for="question in suggestedQuestions" :key="question" type="button" @click="useSuggestedQuestion(question)">{{ question }}</button>
          </div>
        </div>
      </div>
    </section>
  </main>
</template>
