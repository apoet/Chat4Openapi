import { defineStore } from 'pinia'
import { ref } from 'vue'

import { request } from '../api/client'
import type {
  ApiSourceSummary,
  SkillSummary,
  ToolSummary,
} from '../api/contracts'
import { useAuthStore } from './auth'

export const useSkillsStore = defineStore('skills', () => {
  const tools = ref<ToolSummary[]>([])
  const eligibleToolIds = ref(new Set<number>())
  const sources = ref<ApiSourceSummary[]>([])
  const skills = ref<SkillSummary[]>([])
  let toolEligibilityRequest: Promise<void> | null = null

  async function loadTools(): Promise<void> {
    eligibleToolIds.value = new Set()
    const currentRequest = (async () => {
      tools.value = await request<ToolSummary[]>('/api/admin/tools')
      try {
        const eligibleTools = await request<ToolSummary[]>('/api/admin/skills/eligible-tools')
        eligibleToolIds.value = new Set(eligibleTools.map((tool) => tool.id))
      } catch {
        eligibleToolIds.value = new Set()
      }
    })()
    toolEligibilityRequest = currentRequest
    try {
      await currentRequest
    } finally {
      if (toolEligibilityRequest === currentRequest) toolEligibilityRequest = null
    }
  }
  async function waitForToolEligibility(): Promise<void> {
    await toolEligibilityRequest
  }
  async function loadSources(): Promise<void> {
    sources.value = await request<ApiSourceSummary[]>('/api/admin/sources')
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
  return {
    tools,
    eligibleToolIds,
    sources,
    skills,
    loadTools,
    waitForToolEligibility,
    loadSources,
    loadSkills,
    save,
    setRunning,
    remove,
  }
})
