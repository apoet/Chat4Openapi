// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'

import AutoAgentifyPanel from '../components/AutoAgentifyPanel.vue'
import ApiSourcesView from '../views/ApiSourcesView.vue'
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

const failedJob = {
  ...queuedJob,
  status: 'failed',
  phase: 'failed',
  progress: 44,
  error_code: 'auto_agentify.provider_failed',
  error_params: { status: 502 },
  completed_at: '2026-07-24T00:06:28',
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
  i18n.global.locale.value = 'en-US'
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  document.body.innerHTML = ''
})

it('opens the generator in the document overlay layer from the import action', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([]))
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response(null)))
  const wrapper = mount(ApiSourcesView, {
    attachTo: document.body,
    global: { plugins: [i18n] },
  })
  await flushPromises()

  await wrapper.get('[data-testid="open-auto-agentify"]').trigger('click')
  await flushPromises()

  expect(wrapper.find('.auto-agentify-backdrop').exists()).toBe(false)
  expect(document.body.querySelector('.auto-agentify-backdrop')).not.toBeNull()
  expect(document.body.querySelector('.modal-backdrop')).toBeNull()
  wrapper.unmount()
})

it('removes primary button top margin inside every row action group', () => {
  const styles = readFileSync('src/styles.css', 'utf8')
  expect(styles).toMatch(/\.row-actions \.primary-action\s*\{[^}]*margin:\s*0/)
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
    global: { plugins: [i18n], stubs: { teleport: true } },
  })
  await flushPromises()

  expect(wrapper.get('[data-testid="auto-provider"]').element.parentElement?.classList)
    .toContain('provider-select-shell')
  expect(wrapper.get('.provider-mark').attributes('aria-hidden')).toBe('true')
  expect(wrapper.get('[data-testid="auto-generation-notice"]').text())
    .toContain('20 Skills')
  expect(wrapper.get('[data-testid="capability-system-sensitive_data_security"]').text())
    .toContain('Sensitive information and security')
  expect(wrapper.get('[data-testid="capability-system-sensitive_data_security"]')
    .attributes('aria-pressed')).toBe('false')

  await wrapper.get('[data-testid="capability-system-file_management"]').trigger('click')
  await wrapper.get('[data-testid="custom-capability-input"]')
    .setValue('Clinical trial data capture')
  await wrapper.get('[data-testid="add-custom-capability"]').trigger('click')
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
    allowed_system_capabilities: ['file_management'],
    custom_capability_labels: ['Clinical trial data capture'],
    result_language: 'en-US',
  })
  expect(FakeEventSource.instances[0].url)
    .toBe('/api/admin/auto-agentify/jobs/job-1/events')

  FakeEventSource.instances[0].emit({
    sequence: 2,
    kind: 'body_schema_warning',
    phase: 'cataloging_operations',
    progress: 22,
    message_key: 'autoAgentify.events.bodySchemaWarning',
    params: {
      count: 1,
      issues: [{
        operation_key: 'POST /projects',
        reasons: ['missing_field_descriptions'],
      }],
      truncated: false,
    },
    capability: null,
    created_at: '2026-07-24T00:00:00',
  }, '2')
  FakeEventSource.instances[0].emit({
    sequence: 3,
    kind: 'capability_discovered',
    phase: 'analyzing_capabilities',
    progress: 42,
    message_key: 'autoAgentify.events.capabilityDiscovered',
    params: {},
    capability: {
      name: 'Project delivery insight',
      category: 'file_management',
      description: 'Summarizes delivery health and risk.',
      value: 'Reduces project review time.',
      workflow: ['List projects', 'Inspect risks'],
      operation_keys: ['GET /projects'],
      candidate_skills: ['Project Insights'],
      high_impact: true,
    },
    created_at: '2026-07-24T00:00:01',
  }, '3')
  await flushPromises()

  expect(wrapper.get('[data-testid="body-schema-warning"]').text())
    .toContain('POST /projects')
  expect(wrapper.get('[data-testid="body-schema-warning"]').text())
    .toContain('Insufficient field descriptions')
  expect(wrapper.text()).toContain('Project delivery insight')
  expect(wrapper.text()).toContain('Reduces project review time.')
  expect(wrapper.get('[data-testid="recognition-results"]').text())
    .toContain('File management')
  expect(wrapper.get('.analysis-process').text()).toContain('Analysis process')
  expect(wrapper.get('[data-testid="auto-progress"]').attributes('value')).toBe('42')
})

it('shows batch scope and a visible provider-specific retry state', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response(null))
    .mockResolvedValueOnce(response(queuedJob, 202))
    .mockResolvedValueOnce(response(failedJob)))
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      source: {
        mode: 'url',
        name: 'EDC',
        baseUrl: 'https://edc.example.test',
        sourceUrl: 'https://edc.example.test/openapi.json',
        file: null,
        allowPrivateNetworks: false,
      },
    },
    global: { plugins: [i18n], stubs: { teleport: true } },
  })
  await flushPromises()

  await wrapper.get('[data-testid="auto-provider"]').setValue('7')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  FakeEventSource.instances[0].emit({
    sequence: 2,
    kind: 'capability_batch_started',
    phase: 'analyzing_capabilities',
    progress: 24,
    message_key: 'autoAgentify.events.capabilityBatchStarted',
    params: { batch: 1, total: 3, operation_count: 200 },
    capability: null,
    created_at: '2026-07-24T00:00:01',
  }, '2')
  await flushPromises()
  expect(wrapper.get('[data-testid="auto-current-stage"]').text())
    .toContain('Batch 1 of 3')
  expect(wrapper.get('[data-testid="auto-current-stage"]').text())
    .toContain('200 API operations')

  FakeEventSource.instances[0].emit({
    sequence: 3,
    kind: 'failed',
    phase: 'failed',
    progress: 44,
    message_key: 'autoAgentify.events.failed',
    params: { code: 'auto_agentify.provider_failed', status: 502 },
    capability: null,
    created_at: '2026-07-24T00:06:28',
  }, '3')
  await flushPromises()

  expect(wrapper.get('[data-testid="auto-error"]').text())
    .toContain('provider could not complete')
  expect(wrapper.find('.event-list').text()).not.toContain('business capability batch')
  await wrapper.get('.activity-history-toggle').trigger('click')
  expect(wrapper.get('.event-list').text()).toContain('business capability batch')
  expect(wrapper.get('[data-testid="auto-submit"]').text()).toContain('Retry')
})

it('restores capability preferences with a recovered background job', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({
      ...failedJob,
      metrics: {
        allowed_system_capabilities: ['messaging_notifications'],
        custom_capability_labels: ['Clinical trial data capture'],
      },
    })))
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      source: {
        mode: 'url',
        name: 'EDC',
        baseUrl: 'https://edc.example.test',
        sourceUrl: 'https://edc.example.test/openapi.json',
        file: null,
        allowPrivateNetworks: false,
      },
    },
    global: { plugins: [i18n], stubs: { teleport: true } },
  })
  await flushPromises()

  expect(wrapper.get('[data-testid="capability-system-messaging_notifications"]')
    .attributes('aria-pressed')).toBe('true')
  expect(wrapper.text()).toContain('Clinical trial data capture')
})

it('uses the current file input and keeps the background job when closed', async () => {
  i18n.global.locale.value = 'zh-CN'
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
    global: { plugins: [i18n], stubs: { teleport: true } },
  })
  await flushPromises()

  await wrapper.get('[data-testid="auto-provider"]').setValue('7')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  const call = vi.mocked(fetch).mock.calls[2]
  expect(call[0]).toBe('/api/admin/auto-agentify/jobs/file')
  expect(call[1]?.body).toBeInstanceOf(FormData)
  expect((call[1]?.body as FormData).get('document')).toBe(file)
  expect((call[1]?.body as FormData).get('allowed_system_capabilities')).toBe('[]')
  expect((call[1]?.body as FormData).get('custom_capability_labels')).toBe('[]')
  expect((call[1]?.body as FormData).get('result_language')).toBe('zh-CN')

  await wrapper.get('[data-testid="auto-close"]').trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(1)
  expect(FakeEventSource.instances[0].close).not.toHaveBeenCalled()
})
