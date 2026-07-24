import { computed, ref } from 'vue'

import { ApiError, request } from '../api/client'
import type {
  AutoAgentifyCapability,
  AutoAgentifyJob,
  AutoAgentifyJobEvent,
} from '../api/contracts'
import { useAuthStore } from '../stores/auth'

export interface AutoAgentifySourceInput {
  mode: 'url' | 'file'
  name: string
  baseUrl: string
  sourceUrl: string
  file: File | null
  allowPrivateNetworks: boolean
}

export interface AutoAgentifyPreferences {
  allowedSystemCapabilities: string[]
  customCapabilityLabels: string[]
  resultLanguage: 'zh-CN' | 'en-US'
}

export function useAutoAgentifyJob() {
  const auth = useAuthStore()
  const job = ref<AutoAgentifyJob | null>(null)
  const events = ref<AutoAgentifyJobEvent[]>([])
  const capabilities = ref<AutoAgentifyCapability[]>([])
  const starting = ref(false)
  const errorCode = ref<string | null>(null)
  let stream: EventSource | null = null
  let lastSequence = 0

  const active = computed(
    () => job.value?.status === 'queued' || job.value?.status === 'running',
  )

  function applyEvent(event: AutoAgentifyJobEvent): void {
    if (events.value.some((item) => item.sequence === event.sequence)) return
    events.value.push(event)
    lastSequence = Math.max(lastSequence, event.sequence)
    if (job.value) {
      job.value.phase = event.phase
      job.value.progress = event.progress
    }
    if (
      event.capability
      && !capabilities.value.some((item) => item.name === event.capability?.name)
    ) {
      capabilities.value.push(event.capability)
    }
    if (event.kind === 'completed' || event.kind === 'failed') {
      stream?.close()
      void refreshUntilTerminal()
    }
  }

  function connect(publicId: string): void {
    stream?.close()
    const suffix = lastSequence ? `?after=${lastSequence}` : ''
    stream = new EventSource(
      `/api/admin/auto-agentify/jobs/${encodeURIComponent(publicId)}/events${suffix}`,
    )
    stream.onmessage = (message) => {
      applyEvent(JSON.parse(message.data) as AutoAgentifyJobEvent)
    }
  }

  async function refreshUntilTerminal(): Promise<void> {
    if (!job.value) return
    const publicId = job.value.public_id
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const current: AutoAgentifyJob = await request<AutoAgentifyJob>(
        `/api/admin/auto-agentify/jobs/${encodeURIComponent(publicId)}`,
      )
      job.value = current
      if (current.status === 'completed' || current.status === 'failed') return
      await new Promise((resolve) => window.setTimeout(resolve, 100))
    }
  }

  function reset(): void {
    stream?.close()
    stream = null
    job.value = null
    events.value = []
    capabilities.value = []
    errorCode.value = null
    lastSequence = 0
  }

  async function load(publicId: string): Promise<void> {
    reset()
    const current = await request<AutoAgentifyJob>(
      `/api/admin/auto-agentify/jobs/${encodeURIComponent(publicId)}`,
    )
    job.value = current
    if (current.status === 'queued' || current.status === 'running') {
      connect(current.public_id)
    }
  }

  async function start(
    sourceId: number,
    providerId: number,
    preferences: AutoAgentifyPreferences,
  ): Promise<void> {
    starting.value = true
    errorCode.value = null
    events.value = []
    capabilities.value = []
    lastSequence = 0
    try {
      job.value = await request<AutoAgentifyJob>(
        `/api/admin/auto-agentify/sources/${sourceId}/jobs`,
        {
          method: 'POST',
          body: JSON.stringify({
            provider_id: providerId,
            allowed_system_capabilities: preferences.allowedSystemCapabilities,
            custom_capability_labels: preferences.customCapabilityLabels,
            result_language: preferences.resultLanguage,
          }),
        },
        auth.csrfToken,
      )
      connect(job.value.public_id)
    } catch (error) {
      errorCode.value = error instanceof ApiError ? error.code : 'unknown'
    } finally {
      starting.value = false
    }
  }

  return {
    job,
    events,
    capabilities,
    starting,
    active,
    errorCode,
    load,
    reset,
    start,
  }
}
