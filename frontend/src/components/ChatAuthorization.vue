<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

export type ChatAuthorizationSource = {
  api_source_id: number
  api_source_name: string
  flows: Array<'pkce' | 'swagger'>
}

const props = defineProps<{
  agentId: number
  source: ChatAuthorizationSource
}>()
const emit = defineEmits<{
  authorized: [apiSourceId: number]
}>()
const { t } = useI18n()
const busy = ref(false)
const error = ref('')
let popup: Window | null = null

async function authorize(): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const flow = props.source.flows[0]
    if (!flow) throw new Error('authorization_unavailable')
    const response = await fetch('/api/chat/oauth/pkce/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_source_id: props.source.api_source_id,
        agent_id: props.agentId,
        flow,
      }),
    })
    const body = await response.json() as { authorization_url?: unknown }
    if (!response.ok || typeof body.authorization_url !== 'string') {
      throw new Error('authorization_start_failed')
    }
    popup = window.open(
      body.authorization_url,
      'chat4openapi-auth',
      'popup,width=520,height=720',
    )
    if (!popup) {
      error.value = t('embed.popupBlocked')
      busy.value = false
    }
  } catch {
    error.value = t('embed.authorizationFailed')
    busy.value = false
  }
}

function onComplete(event: MessageEvent): void {
  if (event.origin !== window.location.origin || event.source !== popup) return
  if (!event.data || typeof event.data !== 'object') return
  const data = event.data as { type?: unknown; api_source_id?: unknown }
  if (
    data.type !== 'chat4openapi:auth-complete'
    || data.api_source_id !== props.source.api_source_id
  ) return
  popup?.close()
  popup = null
  busy.value = false
  emit('authorized', props.source.api_source_id)
}

function onFocus(): void {
  if (popup?.closed) {
    popup = null
    busy.value = false
    error.value = t('embed.authorizationCancelled')
  }
}

onMounted(() => {
  window.addEventListener('message', onComplete)
  window.addEventListener('focus', onFocus)
})
onBeforeUnmount(() => {
  window.removeEventListener('message', onComplete)
  window.removeEventListener('focus', onFocus)
  popup?.close()
})
</script>

<template>
  <aside class="chat-authorization">
    <strong>{{ t('embed.authorizationTitle', { source: source.api_source_name }) }}</strong>
    <p>{{ t('embed.authorizationHint') }}</p>
    <button type="button" :disabled="busy" @click="authorize">
      {{ busy ? t('embed.authorizing') : t('embed.authorize') }}
    </button>
    <p v-if="error" role="alert">{{ error }}</p>
  </aside>
</template>

<style scoped>
.chat-authorization { margin: 12px 0; padding: 15px; border: 1px solid #ded9cf; border-radius: 14px; background: #fff; box-shadow: 0 8px 24px rgba(20,28,45,.1); }
.chat-authorization p { margin: 6px 0 12px; color: #697283; font-size: 13px; }
.chat-authorization button { min-height: 36px; padding: 0 13px; border: 0; border-radius: 9px; color: white; background: #172033; font-weight: 700; }
.chat-authorization button:disabled { opacity: .5; }
.chat-authorization [role='alert'] { margin-bottom: 0; color: #aa3349; }
</style>
