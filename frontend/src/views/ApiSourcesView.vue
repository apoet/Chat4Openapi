<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { routerKey } from 'vue-router'

import { ApiError, request } from '../api/client'
import type { ApiSourceSummary, OAuthConfigSummary, OAuthConfigWrite } from '../api/contracts'
import { useAuthStore } from '../stores/auth'
import { useToolsStore } from '../stores/tools'

const store = useToolsStore()
const auth = useAuthStore()
const { t } = useI18n()
const router = inject(routerKey, null)
const name = ref('')
const baseUrl = ref('')
const importMode = ref<'file' | 'url'>('file')
const sourceUrl = ref('')
const file = ref<File | null>(null)
const allowPrivateNetworks = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)
const editName = ref('')
const editBaseUrl = ref('')
const editDocumentUrl = ref('')
const editAllowPrivateNetworks = ref(false)
const refreshingId = ref<number | null>(null)
const refreshNotice = ref<{ sourceId: number; message: string } | null>(null)
const oauthSource = ref<ApiSourceSummary | null>(null)
const oauthSummary = ref<OAuthConfigSummary | null>(null)
const oauthEnabled = ref(true)
const oauthClientId = ref('')
const oauthClientSecret = ref('')
const oauthAuthorizationUrl = ref('')
const oauthTokenUrl = ref('')
const oauthDeviceUrl = ref('')
const oauthRedirectUri = ref('')
const oauthScopes = ref('')
const oauthPending = ref(false)

onMounted(() => void store.loadSources())

function selectFile(event: Event): void {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function submit(): Promise<void> {
  if (!name.value) return
  if (importMode.value === 'file' && !file.value) return
  if (importMode.value === 'url' && !sourceUrl.value) return
  submitting.value = true
  try {
    if (importMode.value === 'url') {
      await store.importUrl(
        name.value,
        sourceUrl.value,
        baseUrl.value || undefined,
        allowPrivateNetworks.value,
      )
    } else if (file.value) {
      await store.importFile(
        name.value,
        file.value,
        baseUrl.value || undefined,
        allowPrivateNetworks.value,
      )
    }
    name.value = ''
    baseUrl.value = ''
    sourceUrl.value = ''
    file.value = null
    allowPrivateNetworks.value = false
  } finally {
    submitting.value = false
  }
}

function startEdit(source: ApiSourceSummary): void {
  editingId.value = source.id
  editName.value = source.name
  editBaseUrl.value = source.base_url
  editDocumentUrl.value = source.document_url || ''
  editAllowPrivateNetworks.value = source.allow_private_networks
}

function cancelEdit(): void {
  editingId.value = null
}

async function saveEdit(source: ApiSourceSummary): Promise<void> {
  await store.updateSource(source, {
    name: editName.value,
    base_url: editBaseUrl.value,
    document_url: editDocumentUrl.value || null,
    allow_private_networks: editAllowPrivateNetworks.value,
  })
  editingId.value = null
}

function showRefreshResult(
  source: ApiSourceSummary,
  result: { created: number; updated: number; unchanged: number },
): void {
  refreshNotice.value = {
    sourceId: source.id,
    message: t('sources.refreshResult', result),
  }
}

async function refreshSource(source: ApiSourceSummary): Promise<void> {
  refreshingId.value = source.id
  try {
    showRefreshResult(source, await store.refreshSource(source))
  } finally {
    refreshingId.value = null
  }
}

async function refreshSourceFile(source: ApiSourceSummary, event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const selectedFile = input.files?.[0]
  if (!selectedFile) return
  refreshingId.value = source.id
  try {
    showRefreshResult(source, await store.refreshSourceFile(source, selectedFile))
  } finally {
    refreshingId.value = null
    input.value = ''
  }
}

function viewTools(source: ApiSourceSummary): void {
  void router?.push({
    name: 'tools',
    query: { source_id: String(source.id), source_name: source.name },
  })
}

function fillOAuth(summary: OAuthConfigSummary | null): void {
  oauthSummary.value = summary
  oauthEnabled.value = summary?.enabled ?? true
  oauthClientId.value = summary?.client_id ?? ''
  oauthClientSecret.value = ''
  oauthAuthorizationUrl.value = summary?.authorization_url ?? ''
  oauthTokenUrl.value = summary?.token_url ?? ''
  oauthDeviceUrl.value = summary?.device_authorization_url ?? ''
  oauthRedirectUri.value = summary?.redirect_uri ?? ''
  oauthScopes.value = summary?.scopes.join(' ') ?? ''
}

async function openOAuth(source: ApiSourceSummary): Promise<void> {
  oauthSource.value = source
  try {
    fillOAuth(await request<OAuthConfigSummary>(`/api/admin/sources/${source.id}/oauth`))
  } catch (error) {
    if (!(error instanceof ApiError) || !['oauth.not_configured', 'http.404'].includes(error.code)) throw error
    fillOAuth(null)
  }
}

async function saveOAuth(): Promise<void> {
  if (!oauthSource.value || oauthPending.value) return
  oauthPending.value = true
  const payload: OAuthConfigWrite = {
    enabled: oauthEnabled.value,
    client_id: oauthClientId.value.trim(),
    client_secret: oauthClientSecret.value.trim() || null,
    authorization_url: oauthAuthorizationUrl.value.trim() || null,
    token_url: oauthTokenUrl.value.trim(),
    device_authorization_url: oauthDeviceUrl.value.trim() || null,
    redirect_uri: oauthRedirectUri.value.trim() || null,
    scopes: oauthScopes.value.split(/[\s,]+/).filter(Boolean),
  }
  try {
    fillOAuth(await request<OAuthConfigSummary>(`/api/admin/sources/${oauthSource.value.id}/oauth`, {
      method: 'PUT', body: JSON.stringify(payload),
    }, auth.csrfToken))
  } finally { oauthPending.value = false }
}
</script>

<template>
  <main class="management-page">
    <header class="page-heading">
      <div><p class="eyebrow">{{ t('sources.eyebrow') }}</p><h1>{{ t('sources.title') }}</h1><p class="muted">{{ t('sources.subtitle') }}</p></div>
    </header>
    <section class="import-panel">
      <div class="segmented import-mode">
        <button type="button" :class="{ active: importMode === 'file' }" @click="importMode = 'file'">{{ t('sources.fileMode') }}</button>
        <button type="button" :class="{ active: importMode === 'url' }" @click="importMode = 'url'">{{ t('sources.urlMode') }}</button>
      </div>
      <div class="form-grid">
        <label>{{ t('sources.name') }}<input v-model="name" /></label>
        <label>{{ t('sources.baseUrl') }}<input v-model="baseUrl" placeholder="https://api.example.com" /></label>
        <label v-if="importMode === 'file'" class="file-field">{{ t('sources.document') }}<input type="file" accept=".json,.yaml,.yml,application/json,application/yaml" @change="selectFile" /></label>
        <label v-else>{{ t('sources.url') }}<input v-model="sourceUrl" type="url" placeholder="https://api.example.com/openapi.json" /></label>
      </div>
      <label class="checkbox-label import-private"><input v-model="allowPrivateNetworks" type="checkbox" />{{ t('sources.allowPrivate') }}</label>
      <button class="primary-action" :disabled="!name || (importMode === 'file' ? !file : !sourceUrl) || submitting" @click="submit">{{ submitting ? t('sources.importing') : importMode === 'url' ? t('sources.importUrl') : t('sources.import') }}</button>
    </section>
    <section class="resource-list">
      <div v-if="!store.loading && store.sources.length === 0" class="empty-state">{{ t('sources.empty') }}</div>
      <article v-for="source in store.sources" :key="source.id" class="resource-row">
        <span class="resource-icon">API</span>
        <div v-if="editingId === source.id" class="source-inline-editor">
          <label>{{ t('sources.editName') }}<input v-model="editName" /></label>
          <label>{{ t('sources.editBaseUrl') }}<input v-model="editBaseUrl" /></label>
          <label>{{ t('sources.editDocumentUrl') }}<input v-model="editDocumentUrl" /></label>
          <label class="checkbox-label"><input v-model="editAllowPrivateNetworks" type="checkbox" />{{ t('sources.allowPrivate') }}</label>
          <div class="row-actions editor-actions"><button class="primary-action" :disabled="!editName || !editBaseUrl" @click="saveEdit(source)">{{ t('sources.save') }}</button><button class="secondary-action" @click="cancelEdit">{{ t('skills.cancel') }}</button></div>
        </div>
        <template v-else>
          <div><strong>{{ source.name }}</strong><p>{{ source.base_url }}</p><p v-if="source.document_url">{{ source.document_url }}</p><p v-if="refreshNotice?.sourceId === source.id" class="refresh-notice">{{ refreshNotice.message }}</p></div>
          <span :class="['status-pill', source.enabled ? 'enabled' : 'disabled']">{{ source.enabled ? t('tools.enabled') : t('tools.disabled') }}</span>
          <footer class="row-actions"><button class="secondary-action" @click="viewTools(source)">{{ t('sources.viewTools') }}</button><button class="secondary-action" :data-testid="`source-oauth-${source.id}`" @click="openOAuth(source)">{{ t('sources.oauth.open') }}</button><button v-if="source.document_url" class="secondary-action" :disabled="refreshingId === source.id" @click="refreshSource(source)">{{ refreshingId === source.id ? t('sources.updating') : t('sources.update') }}</button><label v-else class="secondary-action source-refresh-file"><span>{{ t('sources.chooseUpdateFile') }}</span><input type="file" accept=".json,.yaml,.yml,application/json,application/yaml" :aria-label="t('sources.chooseUpdateFile')" :disabled="refreshingId === source.id" @change="refreshSourceFile(source, $event)" /></label><button class="secondary-action" @click="startEdit(source)">{{ t('skills.edit') }}</button><button class="secondary-action" @click="store.setSourceEnabled(source, !source.enabled)">{{ source.enabled ? t('tools.disable') : t('tools.enable') }}</button><button class="danger-action" @click="store.deleteSource(source)">{{ t('tools.delete') }}</button></footer>
        </template>
      </article>
    </section>
    <section v-if="oauthSource" class="import-panel oauth-panel">
      <div class="panel-heading"><div><p class="eyebrow">OAuth 2.0</p><h2>{{ t('sources.oauth.title', { name: oauthSource.name }) }}</h2></div><button type="button" class="text-button" @click="oauthSource = null">×</button></div>
      <form class="form-grid" @submit.prevent="saveOAuth">
        <label class="checkbox-label"><input v-model="oauthEnabled" type="checkbox" />{{ t('sources.oauth.enabled') }}</label>
        <label>{{ t('sources.oauth.clientId') }}<input v-model="oauthClientId" required /></label>
        <label>{{ t('sources.oauth.clientSecret') }}<input v-model="oauthClientSecret" type="password" :placeholder="oauthSummary?.has_client_secret ? t('sources.oauth.keepSecret') : ''" /></label>
        <label>{{ t('sources.oauth.authorizationUrl') }}<input v-model="oauthAuthorizationUrl" type="url" /><small v-if="oauthAuthorizationUrl" class="muted">{{ oauthAuthorizationUrl }}</small></label>
        <label>{{ t('sources.oauth.tokenUrl') }}<input v-model="oauthTokenUrl" type="url" required /></label>
        <label>{{ t('sources.oauth.deviceUrl') }}<input v-model="oauthDeviceUrl" type="url" /></label>
        <label>{{ t('sources.oauth.scopes') }}<input v-model="oauthScopes" /></label>
        <label>{{ t('sources.oauth.redirectOverride') }}<input v-model="oauthRedirectUri" type="url" /></label>
        <div class="oauth-callbacks"><p><strong>{{ t('sources.oauth.recommended') }}</strong> {{ oauthSummary?.recommended_redirect_uri || t('sources.oauth.baseUrlRequired') }}</p><p><strong>{{ t('sources.oauth.effective') }}</strong> {{ oauthSummary?.effective_redirect_uri || oauthRedirectUri || t('sources.oauth.baseUrlRequired') }}</p></div>
        <button class="primary-action" :disabled="oauthPending || !oauthClientId || !oauthTokenUrl">{{ t('sources.oauth.save') }}</button>
      </form>
    </section>
  </main>
</template>
