<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError, request } from '../api/client'
import type { SkillSummary } from '../api/contracts'

type ChatMessage = { role: 'user' | 'assistant'; content: string }
type LocalChatSession = {
  id: string
  conversationId: string | null
  skillId: number
  title: string
  messages: ChatMessage[]
  updatedAt: string
}

const STORAGE_KEY = 'chatapi.chat.sessions.v1'
const { t } = useI18n()
const skills = ref<SkillSummary[]>([])
const selectedSkill = ref<number | null>(null)
const input = ref('')
const messages = ref<ChatMessage[]>([])
const conversationId = ref<string | null>(null)
const sessions = ref<LocalChatSession[]>(loadSessions())
const activeSessionId = ref<string | null>(sessions.value[0]?.id ?? null)
const loginRequired = ref(false)
const authenticated = ref(false)
const username = ref('')
const password = ref('')
const sending = ref(false)
const errorMessage = ref('')

function loadSessions(): LocalChatSession[] {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    if (!Array.isArray(value)) return []
    return value.filter((session): session is LocalChatSession =>
      typeof session?.id === 'string'
      && typeof session?.skillId === 'number'
      && typeof session?.title === 'string'
      && Array.isArray(session?.messages),
    )
  } catch {
    return []
  }
}

function persistSessions(): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.value))
}

function createLocalId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function saveActiveSession(): void {
  if (!selectedSkill.value || messages.value.length === 0) return
  const now = new Date().toISOString()
  let session = sessions.value.find((item) => item.id === activeSessionId.value)
  if (!session) {
    session = {
      id: activeSessionId.value ?? createLocalId(),
      conversationId: conversationId.value,
      skillId: selectedSkill.value,
      title: messages.value.find((message) => message.role === 'user')?.content.slice(0, 48) || t('chat.untitled'),
      messages: [],
      updatedAt: now,
    }
    activeSessionId.value = session.id
    sessions.value.unshift(session)
  }
  session.conversationId = conversationId.value
  session.skillId = selectedSkill.value
  session.messages = messages.value.map((message) => ({ ...message }))
  session.updatedAt = now
  sessions.value = [session, ...sessions.value.filter((item) => item.id !== session!.id)]
  persistSessions()
}

function openSession(session: LocalChatSession): void {
  activeSessionId.value = session.id
  conversationId.value = session.conversationId
  selectedSkill.value = session.skillId
  messages.value = session.messages.map((message) => ({ ...message }))
  errorMessage.value = ''
}

function startNewChat(): void {
  activeSessionId.value = createLocalId()
  conversationId.value = null
  messages.value = []
  input.value = ''
  errorMessage.value = ''
}

onMounted(async () => {
  const restored = sessions.value[0]
  if (restored) openSession(restored)

  const config = await request<{ enabled: boolean }>('/api/tool-session/config')
  loginRequired.value = config.enabled
  if (config.enabled) {
    try { await request('/api/tool-session/status'); authenticated.value = true } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
    }
  }
  skills.value = await request<SkillSummary[]>('/api/skills')
  if (!selectedSkill.value || !skills.value.some((skill) => skill.id === selectedSkill.value)) {
    selectedSkill.value = skills.value[0]?.id ?? null
  }
})

async function login(): Promise<void> {
  await request('/api/tool-session/login', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) })
  authenticated.value = true
  password.value = ''
}

async function send(): Promise<void> {
  if (!input.value.trim() || !selectedSkill.value || sending.value) return
  const content = input.value.trim()
  messages.value.push({ role: 'user', content })
  input.value = ''
  errorMessage.value = ''
  saveActiveSession()
  sending.value = true
  try {
    const result = await request<{ choices: { message: { content: string } }[]; chatapi_conversation_id: string }>('/v1/chat/completions', {
      method: 'POST',
      body: JSON.stringify({ model: `skill-${selectedSkill.value}`, messages: [{ role: 'user', content }], conversation_id: conversationId.value }),
    })
    conversationId.value = result.chatapi_conversation_id
    messages.value.push({ role: 'assistant', content: result.choices[0].message.content })
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
    <header class="chat-header"><RouterLink to="/" class="chat-brand"><span class="brand-mark small">CA</span><strong>ChatAPI</strong></RouterLink><span>{{ t('chat.title') }}</span></header>
    <section v-if="loginRequired && !authenticated" class="chat-login"><p class="eyebrow">{{ t('chat.apiLogin') }}</p><h1>{{ t('chat.loginTitle') }}</h1><p class="muted">{{ t('chat.loginHint') }}</p><label>{{ t('login.username') }}<input v-model="username" /></label><label>{{ t('login.password') }}<input v-model="password" type="password" /></label><button class="primary-action" @click="login">{{ t('chat.login') }}</button></section>
    <section v-else class="chat-workspace">
      <aside class="chat-history">
        <div class="history-heading"><strong>{{ t('chat.history') }}</strong><button type="button" @click="startNewChat">{{ t('chat.newChat') }}</button></div>
        <p v-if="sessions.length === 0" class="history-empty">{{ t('chat.noHistory') }}</p>
        <button v-for="session in sessions" :key="session.id" type="button" :aria-label="session.title" :class="['history-item', { active: session.id === activeSessionId }]" @click="openSession(session)">
          <span>{{ session.title }}</span><small>{{ skills.find((skill) => skill.id === session.skillId)?.name || t('chat.unknownSkill') }}</small>
        </button>
      </aside>
      <div class="conversation"><div class="message-stream"><div v-if="messages.length === 0" class="chat-empty"><p class="eyebrow">{{ t('chat.eyebrow') }}</p><h1>{{ t('chat.emptyTitle') }}</h1><p>{{ t('chat.emptyHint') }}</p></div><article v-for="(message, index) in messages" :key="index" :class="['message', message.role]">{{ message.content }}</article><p v-if="errorMessage" class="chat-error" role="alert">{{ errorMessage }}</p></div>
        <div class="composer"><label class="sr-only" for="chat-input">{{ t('chat.message') }}</label><textarea id="chat-input" v-model="input" :placeholder="t('chat.placeholder')" rows="3" @keydown.ctrl.enter="send" /><button :disabled="sending" @click="send">{{ sending ? t('chat.sending') : t('chat.send') }}</button><div class="skill-dock"><label>{{ t('chat.skill') }}<select v-model="selectedSkill" @change="messages.length && startNewChat()"><option v-for="skill in skills" :key="skill.id" :value="skill.id">{{ skill.name }}</option></select></label><span>{{ t('chat.skillHint') }}</span></div></div>
      </div>
    </section>
  </main>
</template>
