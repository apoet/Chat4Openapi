import { defineStore } from 'pinia'
import { ref } from 'vue'

import { request } from '../api/client'
import type {
  ApiSourceSummary,
  SourceImportResponse,
  SourceRefreshResult,
  ToolAuthConfig,
  ToolBatchAction,
  ToolBatchResponse,
  ToolParameterOverrideWrite,
  ToolSummary,
} from '../api/contracts'
import { useAuthStore } from './auth'

const defaultAuthConfig = (): ToolAuthConfig => ({
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

export const useToolsStore = defineStore('tools', () => {
  const sources = ref<ApiSourceSummary[]>([])
  const tools = ref<ToolSummary[]>([])
  const authConfig = ref<ToolAuthConfig>(defaultAuthConfig())
  const loading = ref(false)
  const errorCode = ref<string | null>(null)

  async function perform<T>(work: () => Promise<T>): Promise<T> {
    loading.value = true
    errorCode.value = null
    try {
      return await work()
    } catch (error) {
      errorCode.value = error instanceof Error ? error.message : 'unknown'
      throw error
    } finally {
      loading.value = false
    }
  }

  async function loadSources(): Promise<void> {
    sources.value = await perform(() => request<ApiSourceSummary[]>('/api/admin/sources'))
  }

  async function loadTools(sourceId?: number): Promise<void> {
    const query = sourceId === undefined
      ? ''
      : `?source_id=${encodeURIComponent(sourceId)}`
    tools.value = await perform(() => request<ToolSummary[]>(`/api/admin/tools${query}`))
  }

  async function loadAuthConfig(): Promise<void> {
    authConfig.value = await perform(() =>
      request<ToolAuthConfig>('/api/admin/tool-auth'),
    )
  }

  async function importFile(
    name: string,
    file: File,
    baseUrl?: string,
    allowPrivateNetworks = false,
  ): Promise<ApiSourceSummary> {
    const form = new FormData()
    form.set('name', name)
    form.set('document', file)
    if (baseUrl) form.set('base_url', baseUrl)
    form.set('allow_private_networks', String(allowPrivateNetworks))
    const auth = useAuthStore()
    const imported = await perform(() =>
      request<SourceImportResponse>(
        '/api/admin/sources/import-file',
        { method: 'POST', body: form },
        auth.csrfToken,
      ),
    )
    await loadSources()
    return imported.source
  }

  async function importUrl(
    name: string,
    url: string,
    baseUrl?: string,
    allowPrivateNetworks = false,
  ): Promise<ApiSourceSummary> {
    const auth = useAuthStore()
    const imported = await perform(() =>
      request<SourceImportResponse>(
        '/api/admin/sources/import-url',
        {
          method: 'POST',
          body: JSON.stringify({
            name,
            url,
            base_url: baseUrl || null,
            allow_private_networks: allowPrivateNetworks,
          }),
        },
        auth.csrfToken,
      ),
    )
    await loadSources()
    return imported.source
  }

  async function updateSource(
    source: ApiSourceSummary,
    payload: {
      name: string
      base_url: string
      document_url?: string | null
      allow_private_networks: boolean
    },
  ): Promise<void> {
    const auth = useAuthStore()
    const updated = await perform(() =>
      request<ApiSourceSummary>(
        `/api/admin/sources/${source.id}`,
        { method: 'PUT', body: JSON.stringify(payload) },
        auth.csrfToken,
      ),
    )
    const index = sources.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) sources.value[index] = updated
  }

  async function setSourceEnabled(source: ApiSourceSummary, enabled: boolean): Promise<void> {
    const auth = useAuthStore()
    const updated = await perform(() =>
      request<ApiSourceSummary>(
        `/api/admin/sources/${source.id}/enabled`,
        { method: 'PATCH', body: JSON.stringify({ enabled }) },
        auth.csrfToken,
      ),
    )
    const index = sources.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) sources.value[index] = updated
  }

  async function refreshSource(source: ApiSourceSummary): Promise<SourceRefreshResult> {
    const auth = useAuthStore()
    return perform(() =>
      request<SourceRefreshResult>(
        `/api/admin/sources/${source.id}/refresh`,
        { method: 'POST' },
        auth.csrfToken,
      ),
    )
  }

  async function refreshSourceFile(
    source: ApiSourceSummary,
    file: File,
  ): Promise<SourceRefreshResult> {
    const form = new FormData()
    form.set('document', file)
    const auth = useAuthStore()
    return perform(() =>
      request<SourceRefreshResult>(
        `/api/admin/sources/${source.id}/refresh-file`,
        { method: 'POST', body: form },
        auth.csrfToken,
      ),
    )
  }

  async function deleteSource(source: ApiSourceSummary): Promise<void> {
    const auth = useAuthStore()
    await perform(() =>
      request<void>(`/api/admin/sources/${source.id}`, { method: 'DELETE' }, auth.csrfToken),
    )
    sources.value = sources.value.filter((item) => item.id !== source.id)
  }

  async function setEnabled(tool: ToolSummary, enabled: boolean): Promise<void> {
    const auth = useAuthStore()
    const updated = await perform(() =>
      request<ToolSummary>(
        `/api/admin/tools/${tool.id}/enabled`,
        { method: 'PATCH', body: JSON.stringify({ enabled }) },
        auth.csrfToken,
      ),
    )
    const index = tools.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) tools.value[index] = updated
  }

  async function updateToolDescription(tool: ToolSummary, description: string): Promise<void> {
    const auth = useAuthStore()
    const updated = await perform(() =>
      request<ToolSummary>(
        `/api/admin/tools/${tool.id}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ description: description.trim() || null }),
        },
        auth.csrfToken,
      ),
    )
    const index = tools.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) tools.value[index] = updated
  }

  async function updateToolParameter(
    tool: ToolSummary,
    parameterName: string,
    payload: ToolParameterOverrideWrite,
  ): Promise<void> {
    const auth = useAuthStore()
    const updated = await perform(() =>
      request<ToolSummary>(
        `/api/admin/tools/${tool.id}/parameters/${encodeURIComponent(parameterName)}`,
        { method: 'PUT', body: JSON.stringify(payload) },
        auth.csrfToken,
      ),
    )
    const index = tools.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) tools.value[index] = updated
  }

  async function deleteTool(tool: ToolSummary): Promise<void> {
    const auth = useAuthStore()
    await perform(() =>
      request<void>(`/api/admin/tools/${tool.id}`, { method: 'DELETE' }, auth.csrfToken),
    )
    tools.value = tools.value.filter((item) => item.id !== tool.id)
  }

  async function batchTools(
    action: ToolBatchAction,
    toolIds: number[],
  ): Promise<ToolBatchResponse> {
    const auth = useAuthStore()
    const result = await perform(() =>
      request<ToolBatchResponse>(
        '/api/admin/tools/batch',
        {
          method: 'POST',
          body: JSON.stringify({ action, tool_ids: toolIds }),
        },
        auth.csrfToken,
      ),
    )
    const statuses = new Map(result.succeeded.map((item) => [item.tool_id, item.status]))
    tools.value = tools.value
      .filter((tool) => statuses.get(tool.id) !== 'deleted')
      .map((tool) => {
        const status = statuses.get(tool.id)
        if (status === 'enabled') return { ...tool, enabled: true }
        if (status === 'disabled') return { ...tool, enabled: false }
        return tool
      })
    return result
  }

  async function saveAuthConfig(config: ToolAuthConfig): Promise<void> {
    const auth = useAuthStore()
    authConfig.value = await perform(() =>
      request<ToolAuthConfig>(
        '/api/admin/tool-auth',
        { method: 'PUT', body: JSON.stringify(config) },
        auth.csrfToken,
      ),
    )
  }

  return {
    sources,
    tools,
    authConfig,
    loading,
    errorCode,
    loadSources,
    loadTools,
    loadAuthConfig,
    importFile,
    importUrl,
    updateSource,
    refreshSource,
    refreshSourceFile,
    setSourceEnabled,
    deleteSource,
    setEnabled,
    updateToolDescription,
    updateToolParameter,
    deleteTool,
    batchTools,
    saveAuthConfig,
  }
})
