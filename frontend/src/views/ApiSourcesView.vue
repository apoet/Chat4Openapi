<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { routerKey } from 'vue-router'

import { ApiError, request } from '../api/client'
import type {
  ApiSourceSummary,
  OAuthConfigSummary,
  OAuthConfigWrite,
  OAuthTokenEndpointAuthMethod,
  ToolAuthConfig,
} from '../api/contracts'
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
const authMode = ref<'oauth' | 'tool'>('oauth')
const toolAuthConfig = ref<ToolAuthConfig>({
  enabled: false,
  login_tool_id: null,
  username_field: 'username',
  password_field: 'password',
  token_json_path: '$.access_token',
  expires_json_path: null,
  auth_type: 'bearer',
  auth_name: 'Authorization',
  auth_prefix: 'Bearer',
  idle_minutes: 30,
  absolute_hours: 8,
  request_parameters: {},
  request_headers: {},
})
const oauthSummary = ref<OAuthConfigSummary | null>(null)
const oauthEnabled = ref(true)
const oauthClientId = ref('')
const oauthClientSecret = ref('')
const oauthTokenAuthMethod = ref<OAuthTokenEndpointAuthMethod>('auto')
const oauthTokenHeaders = ref('{}')
const oauthTokenParams = ref('{}')
const toolRequestParameters = ref('{}')
const toolRequestHeaders = ref('{}')
const oauthConfigError = ref<string | null>(null)
const oauthAuthorizationUrl = ref('')
const oauthTokenUrl = ref('')
const oauthDeviceUrl = ref('')
const oauthRedirectUri = ref('')
const oauthScopes = ref('')
const oauthPending = ref(false)
const authTesting = ref(false)
const authTestResult = ref<string | null>(null)
const authTestSucceeded = ref(false)
const toolTestUsername = ref('')
const toolTestPassword = ref('')

onMounted(() => void store.loadSources())

function selectFile(event: Event): void {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function importFailureReason(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.params.reason === 'string' && error.params.reason.trim()) {
      return error.params.reason
    }
    if (Array.isArray(error.params.fields) && error.params.fields.length) {
      return `${error.code}: ${error.params.fields.join(', ')}`
    }
    if (typeof error.params.status === 'number') {
      return `${error.code} (HTTP ${error.params.status})`
    }
    return error.code
  }
  return error instanceof Error && error.message ? error.message : t('error.unknown')
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
  } catch (error) {
    window.alert(t('sources.importFailed', { reason: importFailureReason(error) }))
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
  oauthTokenAuthMethod.value = summary?.token_endpoint_auth_method ?? 'auto'
  oauthTokenHeaders.value = JSON.stringify(summary?.token_headers ?? {}, null, 2)
  oauthTokenParams.value = JSON.stringify(summary?.token_params ?? {}, null, 2)
  oauthConfigError.value = null
  oauthAuthorizationUrl.value = summary?.authorization_url ?? ''
  oauthTokenUrl.value = summary?.token_url ?? ''
  oauthDeviceUrl.value = summary?.device_authorization_url ?? ''
  oauthRedirectUri.value = summary?.redirect_uri ?? ''
  oauthScopes.value = summary?.scopes.join(' ') ?? ''
}

async function openOAuth(source: ApiSourceSummary): Promise<void> {
  oauthSource.value = source
  authMode.value = source.auth_mode === 'tool' ? 'tool' : 'oauth'
  if (store.tools.length === 0) await store.loadTools()
  toolAuthConfig.value = await request<ToolAuthConfig>(
    `/api/admin/sources/${source.id}/tool-auth`,
  )
  toolRequestParameters.value = JSON.stringify(
    toolAuthConfig.value.request_parameters ?? {},
    null,
    2,
  )
  toolRequestHeaders.value = JSON.stringify(
    toolAuthConfig.value.request_headers ?? {},
    null,
    2,
  )
  authTestResult.value = null
  toolTestUsername.value = ''
  toolTestPassword.value = ''
  try {
    fillOAuth(await request<OAuthConfigSummary>(`/api/admin/sources/${source.id}/oauth`))
  } catch (error) {
    if (!(error instanceof ApiError) || !['oauth.not_configured', 'http.404'].includes(error.code)) throw error
    fillOAuth(null)
  }
}

async function saveToolAuth(): Promise<void> {
  if (!oauthSource.value || oauthPending.value) return
  try {
    toolAuthConfig.value.request_parameters = parseJsonObject(
      toolRequestParameters.value,
      false,
    )
    toolAuthConfig.value.request_headers = parseJsonObject(
      toolRequestHeaders.value,
      true,
    ) as Record<string, string>
  } catch {
    oauthConfigError.value = t('sources.auth.customJsonInvalid')
    return
  }
  oauthPending.value = true
  oauthConfigError.value = null
  try {
    toolAuthConfig.value = await request<ToolAuthConfig>(
      `/api/admin/sources/${oauthSource.value.id}/tool-auth`,
      {
        method: 'PUT',
        body: JSON.stringify({ ...toolAuthConfig.value, enabled: true }),
      },
      auth.csrfToken,
    )
    oauthSource.value.auth_mode = 'tool'
  } finally {
    oauthPending.value = false
  }
}

async function saveOAuth(): Promise<void> {
  if (!oauthSource.value || oauthPending.value) return
  let tokenHeaders: Record<string, string>
  let tokenParams: Record<string, string>
  try {
    tokenHeaders = parseJsonObject(
      oauthTokenHeaders.value,
      true,
    ) as Record<string, string>
    tokenParams = parseJsonObject(
      oauthTokenParams.value,
      true,
    ) as Record<string, string>
  } catch {
    oauthConfigError.value = t('sources.oauth.tokenHeadersInvalid')
    return
  }
  oauthPending.value = true
  oauthConfigError.value = null
  const payload: OAuthConfigWrite = {
    enabled: oauthEnabled.value,
    client_id: oauthClientId.value.trim(),
    client_secret: oauthClientSecret.value.trim() || null,
    token_endpoint_auth_method: oauthTokenAuthMethod.value,
    token_headers: tokenHeaders,
    token_params: tokenParams,
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
    oauthSource.value.auth_mode = 'oauth'
  } finally { oauthPending.value = false }
}

function parseJsonObject(
  value: string,
  stringValuesOnly: boolean,
): Record<string, unknown> {
  const parsed = JSON.parse(value || '{}') as unknown
  if (
    typeof parsed !== 'object'
    || parsed === null
    || Array.isArray(parsed)
    || (
      stringValuesOnly
      && Object.values(parsed).some((item) => typeof item !== 'string')
    )
  ) {
    throw new TypeError('invalid JSON object')
  }
  return parsed as Record<string, unknown>
}

function authTestFailure(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : t('error.unknown')
  }
  const parts: string[] = []
  if (typeof error.params.reason === 'string') parts.push(error.params.reason)
  if (typeof error.params.status === 'number') parts.push(`HTTP ${error.params.status}`)
  if (error.params.business_code !== null && error.params.business_code !== undefined) {
    parts.push(`code ${String(error.params.business_code)}`)
  }
  if (error.params.details !== null && error.params.details !== undefined) {
    parts.push(
      typeof error.params.details === 'string'
        ? error.params.details
        : JSON.stringify(error.params.details),
    )
  }
  return parts.length ? parts.join(' · ') : error.code
}

async function testOAuth(): Promise<void> {
  if (!oauthSource.value || authTesting.value) return
  authTesting.value = true
  authTestResult.value = null
  try {
    const result = await request<{ success: boolean; status: number }>(
      `/api/admin/sources/${oauthSource.value.id}/oauth/test`,
      { method: 'POST' },
      auth.csrfToken,
    )
    authTestSucceeded.value = true
    authTestResult.value = t('sources.auth.testSuccess', { status: result.status })
  } catch (error) {
    authTestSucceeded.value = false
    authTestResult.value = authTestFailure(error)
  } finally {
    authTesting.value = false
  }
}

async function testToolAuth(): Promise<void> {
  if (
    !oauthSource.value
    || authTesting.value
    || !toolTestUsername.value
    || !toolTestPassword.value
  ) return
  authTesting.value = true
  authTestResult.value = null
  try {
    const result = await request<{ success: boolean; status: number }>(
      `/api/admin/sources/${oauthSource.value.id}/tool-auth/test`,
      {
        method: 'POST',
        body: JSON.stringify({
          username: toolTestUsername.value,
          password: toolTestPassword.value,
        }),
      },
      auth.csrfToken,
    )
    authTestSucceeded.value = true
    authTestResult.value = t('sources.auth.testSuccess', { status: result.status })
  } catch (error) {
    authTestSucceeded.value = false
    authTestResult.value = authTestFailure(error)
  } finally {
    authTesting.value = false
  }
}

const sourceLoginTools = () => store.tools.filter(
  (tool) => tool.api_source_id === oauthSource.value?.id && tool.enabled,
)
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
    <section class="resource-list compact-resource-list">
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
          <div class="resource-copy"><strong>{{ source.name }}</strong><p>{{ source.base_url }}</p><p v-if="source.document_url">{{ source.document_url }}</p><p v-if="refreshNotice?.sourceId === source.id" class="refresh-notice">{{ refreshNotice.message }}</p></div>
          <span :class="['status-pill', source.enabled ? 'enabled' : 'disabled']">{{ source.enabled ? t('tools.enabled') : t('tools.disabled') }}</span>
          <footer class="row-actions"><button class="secondary-action" @click="viewTools(source)">{{ t('sources.viewTools') }}</button><button class="secondary-action" :data-testid="`source-oauth-${source.id}`" @click="openOAuth(source)">{{ t('sources.auth.open') }}</button><button v-if="source.document_url" class="secondary-action" :disabled="refreshingId === source.id" @click="refreshSource(source)">{{ refreshingId === source.id ? t('sources.updating') : t('sources.update') }}</button><label v-else class="secondary-action source-refresh-file"><span>{{ t('sources.chooseUpdateFile') }}</span><input type="file" accept=".json,.yaml,.yml,application/json,application/yaml" :aria-label="t('sources.chooseUpdateFile')" :disabled="refreshingId === source.id" @change="refreshSourceFile(source, $event)" /></label><button class="secondary-action" @click="startEdit(source)">{{ t('skills.edit') }}</button><button class="secondary-action" @click="store.setSourceEnabled(source, !source.enabled)">{{ source.enabled ? t('tools.disable') : t('tools.enable') }}</button><button class="danger-action" @click="store.deleteSource(source)">{{ t('tools.delete') }}</button></footer>
        </template>
      </article>
    </section>
    <section v-if="oauthSource" class="import-panel oauth-panel">
      <div class="panel-heading"><div><p class="eyebrow">{{ t('sources.auth.eyebrow') }}</p><h2>{{ t('sources.auth.title', { name: oauthSource.name }) }}</h2></div><button type="button" class="text-button" @click="oauthSource = null">×</button></div>
      <div class="segmented">
        <button type="button" :class="{ active: authMode === 'oauth' }" @click="authMode = 'oauth'">OAuth 2.0</button>
        <button type="button" data-testid="auth-mode-tool" :class="{ active: authMode === 'tool' }" @click="authMode = 'tool'">{{ t('sources.auth.tool') }}</button>
      </div>
      <form v-if="authMode === 'oauth'" class="form-grid" @submit.prevent="saveOAuth">
        <label>{{ t('sources.oauth.clientId') }}<input v-model="oauthClientId" required /></label>
        <label>{{ t('sources.oauth.clientSecret') }}<input v-model="oauthClientSecret" type="password" :placeholder="oauthSummary?.has_client_secret ? t('sources.oauth.keepSecret') : ''" /></label>
        <label>{{ t('sources.oauth.tokenAuthMethod') }}<select v-model="oauthTokenAuthMethod" data-testid="oauth-token-auth-method"><option value="auto">{{ t('sources.oauth.tokenAuthAuto') }}</option><option value="client_secret_basic">client_secret_basic</option><option value="client_secret_post">client_secret_post</option><option value="none">{{ t('sources.oauth.tokenAuthNone') }}</option></select></label>
        <label>{{ t('sources.oauth.tokenHeaders') }}<textarea v-model="oauthTokenHeaders" data-testid="oauth-token-headers" spellcheck="false"></textarea><small class="muted">{{ t('sources.oauth.tokenHeadersHint') }}</small></label>
        <label>{{ t('sources.oauth.tokenParams') }}<textarea v-model="oauthTokenParams" data-testid="oauth-token-params" spellcheck="false"></textarea><small class="muted">{{ t('sources.oauth.tokenParamsHint') }}</small></label>
        <label>{{ t('sources.oauth.authorizationUrl') }}<input v-model="oauthAuthorizationUrl" type="url" /><small v-if="oauthAuthorizationUrl" class="muted">{{ oauthAuthorizationUrl }}</small></label>
        <label>{{ t('sources.oauth.tokenUrl') }}<input v-model="oauthTokenUrl" type="url" required /></label>
        <label>{{ t('sources.oauth.deviceUrl') }}<input v-model="oauthDeviceUrl" type="url" /></label>
        <label>{{ t('sources.oauth.scopes') }}<input v-model="oauthScopes" /></label>
        <label>{{ t('sources.oauth.redirectOverride') }}<input v-model="oauthRedirectUri" type="url" /></label>
        <div class="oauth-callbacks"><p><strong>{{ t('sources.oauth.recommended') }}</strong> {{ oauthSummary?.recommended_redirect_uri || t('sources.oauth.baseUrlRequired') }}</p><p><strong>{{ t('sources.oauth.effective') }}</strong> {{ oauthSummary?.effective_redirect_uri || oauthRedirectUri || t('sources.oauth.baseUrlRequired') }}</p></div>
        <p v-if="oauthConfigError" class="form-error">{{ oauthConfigError }}</p>
        <div class="form-actions auth-form-actions">
          <button type="submit" class="primary-action" :disabled="oauthPending || !oauthClientId || !oauthTokenUrl">{{ t('sources.oauth.save') }}</button>
          <button type="button" class="secondary-action" data-testid="oauth-test" :disabled="authTesting || !oauthSummary" @click="testOAuth">{{ authTesting ? t('sources.auth.testing') : t('sources.auth.test') }}</button>
        </div>
      </form>
      <form v-else class="form-grid" @submit.prevent="saveToolAuth">
        <label>{{ t('toolAuth.loginTool') }}<select v-model="toolAuthConfig.login_tool_id" required><option :value="null">{{ t('toolAuth.selectTool') }}</option><option v-for="tool in sourceLoginTools()" :key="tool.id" :value="tool.id">{{ tool.name }} · {{ tool.operation_key }}</option></select></label>
        <label>{{ t('toolAuth.tokenPath') }}<input v-model="toolAuthConfig.token_json_path" required /></label>
        <label>{{ t('toolAuth.usernameField') }}<input v-model="toolAuthConfig.username_field" required /></label>
        <label>{{ t('toolAuth.passwordField') }}<input v-model="toolAuthConfig.password_field" required /></label>
        <label>{{ t('toolAuth.requestParameters') }}<textarea v-model="toolRequestParameters" data-testid="tool-auth-request-parameters" spellcheck="false"></textarea><small class="muted">{{ t('toolAuth.requestParametersHint') }}</small></label>
        <label>{{ t('toolAuth.requestHeaders') }}<textarea v-model="toolRequestHeaders" data-testid="tool-auth-request-headers" spellcheck="false"></textarea></label>
        <label>{{ t('toolAuth.idle') }}<input v-model.number="toolAuthConfig.idle_minutes" type="number" min="1" /></label>
        <label>{{ t('toolAuth.absolute') }}<input v-model.number="toolAuthConfig.absolute_hours" type="number" min="1" /></label>
        <fieldset class="auth-test-fields">
          <legend>{{ t('sources.auth.testCredentials') }}</legend>
          <label>{{ t('toolAuth.testUsername') }}<input v-model="toolTestUsername" data-testid="tool-auth-test-username" autocomplete="username" /></label>
          <label>{{ t('toolAuth.testPassword') }}<input v-model="toolTestPassword" data-testid="tool-auth-test-password" type="password" autocomplete="current-password" /></label>
        </fieldset>
        <div class="form-actions auth-form-actions">
          <button type="submit" class="primary-action" :disabled="oauthPending || !toolAuthConfig.login_tool_id || !toolAuthConfig.token_json_path">{{ t('toolAuth.save') }}</button>
          <button type="button" class="secondary-action" data-testid="tool-auth-test" :disabled="authTesting || !toolAuthConfig.login_tool_id || !toolTestUsername || !toolTestPassword" @click="testToolAuth">{{ authTesting ? t('sources.auth.testing') : t('sources.auth.test') }}</button>
        </div>
      </form>
      <p
        v-if="authTestResult"
        data-testid="auth-test-result"
        :class="authTestSucceeded ? 'auth-test-success' : 'form-error'"
        role="status"
        aria-live="polite"
      >{{ authTestResult }}</p>
    </section>
  </main>
</template>
