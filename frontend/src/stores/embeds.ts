import { defineStore } from 'pinia'
import { ref } from 'vue'

import { request } from '../api/client'
import type { AgentEmbedConfig, AgentEmbedWrite } from '../api/contracts'
import { useAuthStore } from './auth'

export const useEmbedsStore = defineStore('embeds', () => {
  const byAgent = ref<Record<number, AgentEmbedConfig[]>>({})

  async function load(agentId: number): Promise<void> {
    byAgent.value[agentId] = await request<AgentEmbedConfig[]>(`/api/admin/agents/${agentId}/embeds`)
  }

  async function create(agentId: number, payload: AgentEmbedWrite): Promise<void> {
    const created = await request<AgentEmbedConfig>(`/api/admin/agents/${agentId}/embeds`, {
      method: 'POST', body: JSON.stringify(payload),
    }, useAuthStore().csrfToken)
    byAgent.value[agentId] = [...(byAgent.value[agentId] ?? []), created]
  }

  async function update(agentId: number, embedId: number, payload: AgentEmbedWrite): Promise<void> {
    const updated = await request<AgentEmbedConfig>(`/api/admin/agents/${agentId}/embeds/${embedId}`, {
      method: 'PUT', body: JSON.stringify(payload),
    }, useAuthStore().csrfToken)
    byAgent.value[agentId] = (byAgent.value[agentId] ?? []).map((item) => item.id === embedId ? updated : item)
  }

  async function remove(agentId: number, embedId: number): Promise<void> {
    await request<void>(`/api/admin/agents/${agentId}/embeds/${embedId}`, { method: 'DELETE' }, useAuthStore().csrfToken)
    byAgent.value[agentId] = (byAgent.value[agentId] ?? []).filter((item) => item.id !== embedId)
  }

  return { byAgent, load, create, update, remove }
})
