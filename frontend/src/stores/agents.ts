import { defineStore } from 'pinia'
import { ref } from 'vue'

import { request } from '../api/client'
import type {
  AgentApiKey,
  AgentApiKeyCreated,
  AgentConfig,
  AgentConfigWrite,
  LlmProviderSummary,
  SkillSummary,
} from '../api/contracts'
import { useAuthStore } from './auth'

export const useAgentsStore = defineStore('agents', () => {
  const agents = ref<AgentConfig[]>([])
  const providers = ref<LlmProviderSummary[]>([])
  const skills = ref<SkillSummary[]>([])
  const keysByAgent = ref<Record<number, AgentApiKey[]>>({})

  async function load(): Promise<void> {
    const [agentList, providerList, skillList] = await Promise.all([
      request<AgentConfig[]>('/api/admin/agents'),
      request<LlmProviderSummary[]>('/api/admin/providers'),
      request<SkillSummary[]>('/api/admin/skills'),
    ])
    agents.value = agentList
    providers.value = providerList
    skills.value = skillList
  }

  async function refreshAgents(): Promise<void> {
    agents.value = await request<AgentConfig[]>('/api/admin/agents')
  }

  async function save(payload: AgentConfigWrite, skillIds: number[], id?: number): Promise<AgentConfig> {
    const auth = useAuthStore()
    const agent = await request<AgentConfig>(id ? `/api/admin/agents/${id}` : '/api/admin/agents', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(id ? payload : { ...payload, enabled: false }),
    }, auth.csrfToken)
    const updated = await request<AgentConfig>(`/api/admin/agents/${agent.id}/skills`, {
      method: 'PUT',
      body: JSON.stringify({ skill_ids: skillIds }),
    }, auth.csrfToken)
    const index = agents.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) agents.value[index] = updated
    else agents.value.push(updated)
    return updated
  }

  async function lifecycle(agent: AgentConfig, action: 'enable' | 'disable' | 'set-default'): Promise<AgentConfig> {
    const auth = useAuthStore()
    const updated = await request<AgentConfig>(`/api/admin/agents/${agent.id}/${action}`, {
      method: 'POST',
    }, auth.csrfToken)
    await refreshAgents()
    return agents.value.find((item) => item.id === updated.id) ?? updated
  }

  async function remove(agent: AgentConfig): Promise<void> {
    const auth = useAuthStore()
    await request<void>(`/api/admin/agents/${agent.id}`, { method: 'DELETE' }, auth.csrfToken)
    delete keysByAgent.value[agent.id]
    await refreshAgents()
  }

  async function loadKeys(agentId: number): Promise<void> {
    keysByAgent.value[agentId] = await request<AgentApiKey[]>(`/api/admin/agents/${agentId}/keys`)
  }

  async function createKey(agentId: number, label: string, expiresAt: string | null): Promise<AgentApiKeyCreated> {
    const auth = useAuthStore()
    const created = await request<AgentApiKeyCreated>(`/api/admin/agents/${agentId}/keys`, {
      method: 'POST',
      body: JSON.stringify({ label, expires_at: expiresAt }),
    }, auth.csrfToken)
    const { secret: _secret, ...metadata } = created
    keysByAgent.value[agentId] = [...(keysByAgent.value[agentId] ?? []), metadata]
    return created
  }

  async function revokeKey(agentId: number, keyId: number): Promise<void> {
    const auth = useAuthStore()
    const updated = await request<AgentApiKey>(`/api/admin/agents/${agentId}/keys/${keyId}/revoke`, {
      method: 'POST',
    }, auth.csrfToken)
    keysByAgent.value[agentId] = (keysByAgent.value[agentId] ?? []).map((key) => key.id === keyId ? updated : key)
  }

  async function deleteKey(agentId: number, keyId: number): Promise<void> {
    const auth = useAuthStore()
    await request<void>(`/api/admin/agents/${agentId}/keys/${keyId}`, { method: 'DELETE' }, auth.csrfToken)
    keysByAgent.value[agentId] = (keysByAgent.value[agentId] ?? []).filter((key) => key.id !== keyId)
  }

  return {
    agents, providers, skills, keysByAgent,
    load, refreshAgents, save, lifecycle, remove,
    loadKeys, createKey, revokeKey, deleteKey,
  }
})
