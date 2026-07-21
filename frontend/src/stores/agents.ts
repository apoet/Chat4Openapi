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

export class AgentSavePartialError extends Error {
  constructor(public readonly agentId: number, public readonly cause: unknown) {
    super('agent_save_partial')
  }
}

export const useAgentsStore = defineStore('agents', () => {
  const agents = ref<AgentConfig[]>([])
  const providers = ref<LlmProviderSummary[]>([])
  const skills = ref<SkillSummary[]>([])
  const keysByAgent = ref<Record<number, AgentApiKey[]>>({})
  const keyLoadGenerations = new Map<number, number>()

  function upsertAgent(agent: AgentConfig): void {
    const index = agents.value.findIndex((item) => item.id === agent.id)
    if (index >= 0) agents.value[index] = agent
    else agents.value.push(agent)
  }

  function invalidateKeyLoads(agentId: number): number {
    const generation = (keyLoadGenerations.get(agentId) ?? 0) + 1
    keyLoadGenerations.set(agentId, generation)
    return generation
  }

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
    upsertAgent(agent)
    try {
      const updated = await request<AgentConfig>(`/api/admin/agents/${agent.id}/skills`, {
        method: 'PUT',
        body: JSON.stringify({ skill_ids: skillIds }),
      }, auth.csrfToken)
      upsertAgent(updated)
      return updated
    } catch (error) {
      try { await refreshAgents() } catch { /* Keep the authoritative metadata response. */ }
      upsertAgent(agent)
      throw new AgentSavePartialError(agent.id, error)
    }
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
    const generation = invalidateKeyLoads(agentId)
    const keys = await request<AgentApiKey[]>(`/api/admin/agents/${agentId}/keys`)
    if (keyLoadGenerations.get(agentId) === generation) keysByAgent.value[agentId] = keys
  }

  async function createKey(agentId: number, label: string, expiresAt: string | null): Promise<AgentApiKeyCreated> {
    const auth = useAuthStore()
    invalidateKeyLoads(agentId)
    const created = await request<AgentApiKeyCreated>(`/api/admin/agents/${agentId}/keys`, {
      method: 'POST',
      body: JSON.stringify({ label, expires_at: expiresAt }),
    }, auth.csrfToken)
    const { secret: _secret, ...metadata } = created
    keysByAgent.value[agentId] = [...(keysByAgent.value[agentId] ?? []), metadata]
    return created
  }

  async function updateKey(agentId: number, keyId: number, label: string, expiresAt: string | null): Promise<void> {
    const auth = useAuthStore()
    invalidateKeyLoads(agentId)
    const updated = await request<AgentApiKey>(`/api/admin/agents/${agentId}/keys/${keyId}`, {
      method: 'PATCH',
      body: JSON.stringify({ label, expires_at: expiresAt }),
    }, auth.csrfToken)
    keysByAgent.value[agentId] = (keysByAgent.value[agentId] ?? []).map((key) => key.id === keyId ? updated : key)
  }

  async function revokeKey(agentId: number, keyId: number): Promise<void> {
    const auth = useAuthStore()
    invalidateKeyLoads(agentId)
    const updated = await request<AgentApiKey>(`/api/admin/agents/${agentId}/keys/${keyId}/revoke`, {
      method: 'POST',
    }, auth.csrfToken)
    keysByAgent.value[agentId] = (keysByAgent.value[agentId] ?? []).map((key) => key.id === keyId ? updated : key)
  }

  async function deleteKey(agentId: number, keyId: number): Promise<void> {
    const auth = useAuthStore()
    invalidateKeyLoads(agentId)
    await request<void>(`/api/admin/agents/${agentId}/keys/${keyId}`, { method: 'DELETE' }, auth.csrfToken)
    keysByAgent.value[agentId] = (keysByAgent.value[agentId] ?? []).filter((key) => key.id !== keyId)
  }

  async function discardCreatedKey(agentId: number, keyId: number): Promise<void> {
    try {
      await deleteKey(agentId, keyId)
    } catch (deleteError) {
      try { await revokeKey(agentId, keyId) } catch { throw deleteError }
    }
  }

  return {
    agents, providers, skills, keysByAgent,
    load, refreshAgents, save, lifecycle, remove,
    loadKeys, createKey, updateKey, revokeKey, deleteKey, discardCreatedKey,
  }
})
