<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError, request } from '../api/client'
import type { SkillSummary } from '../api/contracts'

const { t } = useI18n()
const skills = ref<SkillSummary[]>([])
const selectedSkill = ref<number | null>(null)
const input = ref('')
const messages = ref<{ role: 'user' | 'assistant'; content: string }[]>([])
const conversationId = ref<string | null>(null)
const loginRequired = ref(false)
const authenticated = ref(false)
const username = ref('')
const password = ref('')
const sending = ref(false)

onMounted(async () => {
  const config = await request<{ enabled: boolean }>('/api/tool-session/config')
  loginRequired.value = config.enabled
  if (config.enabled) {
    try { await request('/api/tool-session/status'); authenticated.value = true } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
    }
  }
  skills.value = await request<SkillSummary[]>('/api/skills')
  selectedSkill.value = skills.value[0]?.id ?? null
})

async function login(): Promise<void> {
  await request('/api/tool-session/login', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) })
  authenticated.value = true
  password.value = ''
}

async function send(): Promise<void> {
  if (!input.value.trim() || !selectedSkill.value) return
  const content = input.value.trim(); messages.value.push({ role: 'user', content }); input.value = ''; sending.value = true
  try {
    const result = await request<{ choices: { message: { content: string } }[]; chatapi_conversation_id: string }>('/v1/chat/completions', {
      method: 'POST',
      body: JSON.stringify({ model: `skill-${selectedSkill.value}`, messages: [{ role: 'user', content }], conversation_id: conversationId.value }),
    })
    conversationId.value = result.chatapi_conversation_id
    messages.value.push({ role: 'assistant', content: result.choices[0].message.content })
  } finally { sending.value = false }
}
</script>

<template>
  <main class="chat-page">
    <header class="chat-header"><RouterLink to="/" class="chat-brand"><span class="brand-mark small">CA</span><strong>ChatAPI</strong></RouterLink><span>{{ t('chat.title') }}</span></header>
    <section v-if="loginRequired && !authenticated" class="chat-login"><p class="eyebrow">{{ t('chat.apiLogin') }}</p><h1>{{ t('chat.loginTitle') }}</h1><p class="muted">{{ t('chat.loginHint') }}</p><label>{{ t('login.username') }}<input v-model="username" /></label><label>{{ t('login.password') }}<input v-model="password" type="password" /></label><button class="primary-action" @click="login">{{ t('chat.login') }}</button></section>
    <section v-else class="conversation"><div class="message-stream"><div v-if="messages.length === 0" class="chat-empty"><p class="eyebrow">{{ t('chat.eyebrow') }}</p><h1>{{ t('chat.emptyTitle') }}</h1><p>{{ t('chat.emptyHint') }}</p></div><article v-for="(message, index) in messages" :key="index" :class="['message', message.role]">{{ message.content }}</article></div>
      <div class="composer"><label class="sr-only" for="chat-input">{{ t('chat.message') }}</label><textarea id="chat-input" v-model="input" :placeholder="t('chat.placeholder')" rows="3" @keydown.ctrl.enter="send" /><button :disabled="sending" @click="send">{{ t('chat.send') }}</button><div class="skill-dock"><label>{{ t('chat.skill') }}<select v-model="selectedSkill"><option v-for="skill in skills" :key="skill.id" :value="skill.id">{{ skill.name }}</option></select></label><span>{{ t('chat.skillHint') }}</span></div></div>
    </section>
  </main>
</template>
