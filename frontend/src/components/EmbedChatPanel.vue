<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import logoUrl from '../../../logo.png'

defineProps<{
  agentName: string
  messages: Array<{ id: string; role: 'user' | 'assistant'; content: string }>
  draft: string
  ready: boolean
  sending: boolean
  error: string
}>()

const emit = defineEmits<{
  'update:draft': [value: string]
  send: []
  cancel: []
  close: []
}>()
const { t } = useI18n()
</script>

<template>
  <section class="embed-chat-panel">
    <header class="embed-chat-header">
      <div class="embed-agent-identity">
        <img :src="logoUrl" alt="" />
        <div>
          <strong>{{ agentName || t('embed.starting') }}</strong>
          <span>{{ t('embed.subtitle') }}</span>
        </div>
      </div>
      <button class="embed-close" type="button" :aria-label="t('embed.close')" @click="emit('close')">
        ×
      </button>
    </header>

    <main class="embed-chat-messages" aria-live="polite">
      <div v-if="messages.length === 0" class="embed-empty">
        <img :src="logoUrl" alt="" />
        <strong>{{ t('embed.welcome', { agent: agentName || t('embed.assistant') }) }}</strong>
        <p>{{ t('embed.welcomeHint') }}</p>
        <div class="embed-suggestion">
          <span>{{ t('embed.suggestionLabel') }}</span>
          <button
            type="button"
            @click="emit('update:draft', t('embed.suggestionQuestion'))"
          >
            {{ t('embed.suggestionQuestion') }}
          </button>
        </div>
      </div>
      <article
        v-for="message in messages"
        :key="message.id"
        class="embed-message"
        :class="`is-${message.role}`"
      >
        <span>{{ message.role === 'user' ? t('embed.you') : agentName }}</span>
        <p>{{ message.content }}</p>
      </article>
      <p v-if="error" class="embed-error" role="alert">{{ error }}</p>
    </main>

    <form class="embed-composer" @submit.prevent="emit('send')">
      <textarea
        :value="draft"
        :placeholder="t('embed.placeholder')"
        :disabled="!ready || sending"
        rows="2"
        @input="emit('update:draft', ($event.target as HTMLTextAreaElement).value)"
        @keydown.enter.exact.prevent="emit('send')"
      />
      <button v-if="sending" type="button" class="embed-cancel" @click="emit('cancel')">
        {{ t('embed.cancel') }}
      </button>
      <button v-else type="submit" class="embed-send" :disabled="!ready || !draft.trim()">
        {{ t('embed.send') }}
      </button>
    </form>
  </section>
</template>

<style scoped>
.embed-chat-panel { height: 100dvh; min-height: 420px; display: grid; grid-template-rows: auto 1fr auto; overflow: hidden; color: #162033; background: #fbfaf7; }
.embed-chat-header { min-height: 70px; padding: 13px 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #e5e1d8; background: rgba(255,255,255,.86); }
.embed-agent-identity { min-width: 0; display: flex; align-items: center; gap: 11px; }
.embed-agent-identity img { width: 40px; height: 40px; object-fit: contain; }
.embed-agent-identity div { min-width: 0; display: grid; gap: 2px; }
.embed-agent-identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; }
.embed-agent-identity span { color: #778092; font-size: 11px; }
.embed-close { width: 34px; height: 34px; border: 0; border-radius: 50%; color: #5d6574; background: transparent; font-size: 25px; line-height: 1; }
.embed-close:hover { background: #f0eee8; }
.embed-chat-messages { min-height: 0; padding: 20px 16px; overflow-y: auto; background: radial-gradient(circle at 90% 0, rgba(101,88,232,.07), transparent 32%); }
.embed-empty { min-height: 100%; display: grid; place-content: center; justify-items: center; text-align: center; color: #626b7b; }
.embed-empty img { width: 68px; height: 68px; margin-bottom: 14px; object-fit: contain; }
.embed-empty strong { color: #1b2434; font-size: 17px; }
.embed-empty p { max-width: 260px; margin: 8px 0 0; font-size: 13px; line-height: 1.6; }
.embed-suggestion { max-width: 290px; margin-top: 20px; display: grid; justify-items: center; gap: 8px; }
.embed-suggestion span { color: #8b92a0; font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
.embed-suggestion button { max-width: 100%; padding: 8px 12px; overflow: hidden; border: 1px solid #d7d1f7; border-radius: 999px; color: #5146ad; background: #f6f4ff; text-overflow: ellipsis; white-space: nowrap; font: inherit; font-size: 12px; cursor: pointer; }
.embed-suggestion button:hover { border-color: #a89ff5; background: #eeebff; }
.embed-suggestion button:focus-visible { outline: 3px solid rgba(101,88,232,.22); outline-offset: 2px; }
.embed-message { max-width: 86%; margin: 0 0 16px; }
.embed-message > span { display: block; margin: 0 5px 5px; color: #858c98; font-size: 10px; }
.embed-message p { margin: 0; padding: 11px 13px; border-radius: 14px 14px 14px 4px; white-space: pre-wrap; line-height: 1.55; background: white; box-shadow: 0 2px 12px rgba(17,25,40,.07); }
.embed-message.is-user { margin-left: auto; }
.embed-message.is-user > span { text-align: right; }
.embed-message.is-user p { border-radius: 14px 14px 4px 14px; color: white; background: #6558e8; }
.embed-error { padding: 10px 12px; border-radius: 10px; color: #a52f45; background: #fff0f2; font-size: 12px; }
.embed-composer { padding: 12px; display: flex; align-items: flex-end; gap: 9px; border-top: 1px solid #e5e1d8; background: white; }
.embed-composer textarea { min-width: 0; flex: 1; resize: none; padding: 10px 11px; border: 1px solid #dcd8cf; border-radius: 11px; outline: none; color: inherit; background: #fbfaf7; line-height: 1.4; }
.embed-composer textarea:focus { border-color: #7569ed; box-shadow: 0 0 0 3px rgba(101,88,232,.1); }
.embed-send, .embed-cancel { min-width: 62px; height: 38px; border: 0; border-radius: 10px; font-weight: 700; }
.embed-send { color: white; background: #172033; }
.embed-cancel { color: #5e6674; background: #efede8; }
.embed-send:disabled { opacity: .4; cursor: default; }
</style>
