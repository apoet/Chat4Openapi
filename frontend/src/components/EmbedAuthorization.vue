<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

export type EmbedAuthorizationSource = {
  api_source_id: number
  api_source_name: string
  flows: Array<'pkce' | 'swagger'>
}

const props = defineProps<{
  sessionId: string
  token: string
  chatOrigin: string
  source: EmbedAuthorizationSource
}>()
const emit = defineEmits<{
  authorized: [apiSourceId: number]
  revoked: [apiSourceId: number]
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
    const response = await fetch(
      `/api/embed/sessions/${encodeURIComponent(props.sessionId)}/auth/start`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${props.token}`,
        },
        body: JSON.stringify({ api_source_id: props.source.api_source_id, flow }),
      },
    )
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

async function exchange(grant: string): Promise<void> {
  try {
    const response = await fetch(
      `/api/embed/sessions/${encodeURIComponent(props.sessionId)}/auth/exchange`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${props.token}`,
        },
        body: JSON.stringify({ grant }),
      },
    )
    if (!response.ok) throw new Error('authorization_exchange_failed')
    popup?.close()
    popup = null
    busy.value = false
    emit('authorized', props.source.api_source_id)
  } catch {
    error.value = t('embed.authorizationFailed')
    busy.value = false
  }
}

function onGrant(event: MessageEvent): void {
  if (event.origin !== props.chatOrigin || event.source !== popup) return
  if (!event.data || typeof event.data !== 'object') return
  const data = event.data as {
    type?: unknown
    grant?: unknown
    api_source_id?: unknown
    error?: unknown
  }
  if (
    data.type === 'chat4openapi:auth-error'
    && data.api_source_id === props.source.api_source_id
  ) {
    popup?.close()
    popup = null
    busy.value = false
    error.value = data.error === 'access_denied'
      ? t('embed.authorizationCancelled')
      : t('embed.authorizationFailed')
    return
  }
  if (data.type !== 'chat4openapi:auth-grant' || typeof data.grant !== 'string') return
  void exchange(data.grant)
}

function onFocus(): void {
  if (popup?.closed) {
    popup = null
    busy.value = false
    error.value = t('embed.authorizationCancelled')
  }
}

async function logout(): Promise<void> {
  const response = await fetch(
    `/api/embed/sessions/${encodeURIComponent(props.sessionId)}/auth/${props.source.api_source_id}`,
    { method: 'DELETE', headers: { Authorization: `Bearer ${props.token}` } },
  )
  if (response.ok) emit('revoked', props.source.api_source_id)
  else error.value = t('embed.authorizationFailed')
}

onMounted(() => {
  window.addEventListener('message', onGrant)
  window.addEventListener('focus', onFocus)
})
onBeforeUnmount(() => {
  window.removeEventListener('message', onGrant)
  window.removeEventListener('focus', onFocus)
  popup?.close()
})
</script>

<template>
  <aside class="embed-authorization">
    <strong>{{ t('embed.authorizationTitle', { source: source.api_source_name }) }}</strong>
    <p>{{ t('embed.authorizationHint') }}</p>
    <div>
      <button data-testid="authorize" type="button" :disabled="busy" @click="authorize">
        {{ busy ? t('embed.authorizing') : t('embed.authorize') }}
      </button>
      <button class="embed-auth-logout" type="button" @click="logout">
        {{ t('embed.logout') }}
      </button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
  </aside>
</template>

<style scoped>
.embed-authorization { position: absolute; z-index: 3; right: 14px; bottom: 80px; left: 14px; padding: 15px; border: 1px solid #ded9cf; border-radius: 14px; background: rgba(255,255,255,.98); box-shadow: 0 12px 36px rgba(20,28,45,.18); }
.embed-authorization strong { font-size: 14px; }
.embed-authorization p { margin: 6px 0 12px; color: #697283; font-size: 12px; line-height: 1.5; }
.embed-authorization div { display: flex; gap: 8px; }
.embed-authorization button { min-height: 36px; padding: 0 13px; border: 0; border-radius: 9px; color: white; background: #172033; font-weight: 700; }
.embed-authorization button:disabled { opacity: .5; }
.embed-authorization .embed-auth-logout { color: #596272; background: #efede8; }
.embed-authorization [role='alert'] { margin-bottom: 0; color: #aa3349; }
</style>
