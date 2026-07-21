import { defineStore } from 'pinia'
import { ref } from 'vue'

import { request } from '../api/client'
import type { AgentConfig, AgentConfigWrite, LlmProviderSummary } from '../api/contracts'
import { useAuthStore } from './auth'

export const useAgentStore = defineStore('agent', () => {
  const config = ref<AgentConfig | null>(null)
  const providers = ref<LlmProviderSummary[]>([])

  async function load(): Promise<void> {
    const [providerList, agentConfig] = await Promise.all([
      request<LlmProviderSummary[]>('/api/admin/providers'),
      request<AgentConfig>('/api/admin/agent'),
    ])
    providers.value = providerList
    config.value = agentConfig
  }

  async function save(payload: AgentConfigWrite): Promise<void> {
    const auth = useAuthStore()
    config.value = await request<AgentConfig>('/api/admin/agent', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }, auth.csrfToken)
  }

  async function reset(): Promise<void> {
    const auth = useAuthStore()
    config.value = await request<AgentConfig>(
      '/api/admin/agent/reset',
      { method: 'POST' },
      auth.csrfToken,
    )
  }

  return { config, providers, load, save, reset }
})
