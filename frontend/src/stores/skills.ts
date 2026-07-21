import { defineStore } from 'pinia'
import { ref } from 'vue'

import { request } from '../api/client'
import type { LlmProviderSummary, SkillSummary, ToolSummary } from '../api/contracts'
import { useAuthStore } from './auth'

export const useSkillsStore = defineStore('skills', () => {
  const providers = ref<LlmProviderSummary[]>([])
  const tools = ref<ToolSummary[]>([])
  const skills = ref<SkillSummary[]>([])

  async function loadProviders(): Promise<void> {
    providers.value = await request<LlmProviderSummary[]>('/api/admin/providers')
  }
  async function loadTools(): Promise<void> {
    tools.value = await request<ToolSummary[]>('/api/admin/skills/eligible-tools')
  }
  async function loadSkills(): Promise<void> {
    skills.value = await request<SkillSummary[]>('/api/admin/skills')
  }
  async function save(payload: Record<string, unknown>, id?: number): Promise<void> {
    const auth = useAuthStore()
    await request<SkillSummary>(id ? `/api/admin/skills/${id}` : '/api/admin/skills', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(payload),
    }, auth.csrfToken)
    await loadSkills()
  }
  async function setRunning(skill: SkillSummary, running: boolean): Promise<void> {
    const auth = useAuthStore()
    await request<SkillSummary>(
      `/api/admin/skills/${skill.id}/${running ? 'start' : 'stop'}`,
      { method: 'POST' },
      auth.csrfToken,
    )
    await loadSkills()
  }
  async function remove(skill: SkillSummary): Promise<void> {
    const auth = useAuthStore()
    await request<void>(`/api/admin/skills/${skill.id}`, { method: 'DELETE' }, auth.csrfToken)
    await loadSkills()
  }
  return { providers, tools, skills, loadProviders, loadTools, loadSkills, save, setRunning, remove }
})
