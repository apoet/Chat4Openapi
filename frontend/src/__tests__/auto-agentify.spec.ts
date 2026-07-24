// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'

import AutoAgentifyPanel from '../components/AutoAgentifyPanel.vue'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const provider = {
  id: 7, name: 'Primary', provider_type: 'openai',
  base_url: 'https://llm.example.test/v1', default_model: 'gpt-test',
  enabled: true, has_api_key: true,
}

const queuedJob = {
  public_id: 'job-1', provider_id: 7, input_mode: 'url',
  source_name: 'Projects', status: 'queued', phase: 'queued', progress: 0,
  metrics: {}, result: null, error_code: null, error_params: null,
  created_at: '2026-07-24T00:00:00', started_at: null, completed_at: null,
}

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  close = vi.fn()

  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }

  emit(value: unknown, lastEventId = '1'): void {
    this.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify(value),
        lastEventId,
      }),
    )
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf-token'
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

it('starts from the current URL import input and displays live capability analysis', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response(null))
    .mockResolvedValueOnce(response(queuedJob, 202)))
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      source: {
        mode: 'url',
        name: 'Projects',
        baseUrl: 'https://api.example.test',
        sourceUrl: 'https://api.example.test/openapi.json',
        file: null,
        allowPrivateNetworks: false,
      },
    },
    global: { plugins: [i18n] },
  })
  await flushPromises()

  await wrapper.get('[data-testid="auto-provider"]').setValue('7')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  const call = vi.mocked(fetch).mock.calls[2]
  expect(call[0]).toBe('/api/admin/auto-agentify/jobs/url')
  expect(JSON.parse(String(call[1]?.body))).toEqual({
    provider_id: 7,
    name: 'Projects',
    url: 'https://api.example.test/openapi.json',
    base_url: 'https://api.example.test',
    allow_private_networks: false,
  })
  expect(FakeEventSource.instances[0].url)
    .toBe('/api/admin/auto-agentify/jobs/job-1/events')

  FakeEventSource.instances[0].emit({
    sequence: 2,
    kind: 'capability_discovered',
    phase: 'analyzing_capabilities',
    progress: 42,
    message_key: 'autoAgentify.events.capabilityDiscovered',
    params: {},
    capability: {
      name: 'Project delivery insight',
      description: 'Summarizes delivery health and risk.',
      value: 'Reduces project review time.',
      workflow: ['List projects', 'Inspect risks'],
      operation_keys: ['GET /projects'],
      candidate_skills: ['Project Insights'],
      high_impact: true,
    },
    created_at: '2026-07-24T00:00:01',
  }, '2')
  await flushPromises()

  expect(wrapper.text()).toContain('Project delivery insight')
  expect(wrapper.text()).toContain('Reduces project review time.')
  expect(wrapper.get('[data-testid="auto-progress"]').attributes('value')).toBe('42')
})

it('uses the current file input and keeps the background job when closed', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response(null))
    .mockResolvedValueOnce(response(queuedJob, 202)))
  const file = new File(['openapi: 3.0.3'], 'openapi.yaml', {
    type: 'application/yaml',
  })
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      source: {
        mode: 'file',
        name: 'Pets',
        baseUrl: '',
        sourceUrl: '',
        file,
        allowPrivateNetworks: false,
      },
    },
    global: { plugins: [i18n] },
  })
  await flushPromises()

  await wrapper.get('[data-testid="auto-provider"]').setValue('7')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  const call = vi.mocked(fetch).mock.calls[2]
  expect(call[0]).toBe('/api/admin/auto-agentify/jobs/file')
  expect(call[1]?.body).toBeInstanceOf(FormData)
  expect((call[1]?.body as FormData).get('document')).toBe(file)

  await wrapper.get('[data-testid="auto-close"]').trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(1)
  expect(FakeEventSource.instances[0].close).not.toHaveBeenCalled()
})
