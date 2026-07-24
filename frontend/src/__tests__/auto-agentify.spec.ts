// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'

import AutoAgentifyPanel from '../components/AutoAgentifyPanel.vue'
import ApiSourcesView from '../views/ApiSourcesView.vue'
import type { ApiSourceSummary } from '../api/contracts'
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
  public_id: 'job-1', provider_id: 7, source_id: 3, input_mode: 'url',
  source_name: 'Projects', status: 'queued', phase: 'queued', progress: 0,
  metrics: {}, result: null, error_code: null, error_params: null,
  created_at: '2026-07-24T00:00:00', started_at: null, completed_at: null,
}

const importedSource: ApiSourceSummary = {
  id: 3, name: 'Projects', source_type: 'openapi',
  base_url: 'https://api.example.test',
  document_url: 'https://api.example.test/openapi.json',
  allow_private_networks: false, auth_mode: 'none', enabled: true,
  created_at: '2026-07-24T00:00:00',
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

const completedJob = {
  ...queuedJob,
  status: 'completed',
  phase: 'completed',
  progress: 100,
  completed_at: '2026-07-24T00:06:28',
  result: {
    source: {
      id: 3, name: 'Projects', source_type: 'openapi',
      base_url: 'https://api.example.test', document_url: null,
      allow_private_networks: false, auth_mode: 'none', enabled: true,
      created_at: '2026-07-24T00:06:28',
    },
    imported_tool_count: 4,
    enabled_tool_count: 3,
    skills: [{
      id: 8, name: 'Project insight', description: 'Generated from Projects.',
      tool_ids: [1, 2], value: 'Summarizes delivery health.',
    }],
    agents: [{
      id: 9, name: 'Project analyst', description: 'Generated from Projects.',
      skill_ids: [8], mode: 'react', provider_id: 7,
      value: 'Turns project APIs into decisions.', use_cases: ['Review delivery risk'],
    }],
  },
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

it('shows source-specific generation actions and resumes only that source progress', async () => {
  const sourceWithProgress = {
    ...importedSource,
    auto_agentify_job: {
      public_id: queuedJob.public_id,
      status: 'running',
      phase: 'analyzing_capabilities',
      progress: 37,
      updated_at: '2026-07-24T00:01:00',
    },
  }
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([sourceWithProgress]))
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({ ...queuedJob, status: 'running', progress: 37 })))
  const wrapper = mount(ApiSourcesView, {
    attachTo: document.body,
    global: { plugins: [i18n] },
  })
  await flushPromises()

  const progressButton = wrapper.get('[data-testid="source-auto-agentify-3"]')
  expect(progressButton.text()).toContain('View progress 37%')
  expect(progressButton.classes()).toContain('secondary-action')
  expect(progressButton.find('.source-generate-icon').exists()).toBe(true)
  await progressButton.trigger('click')
  await flushPromises()

  expect(vi.mocked(fetch).mock.calls[2][0])
    .toBe('/api/admin/auto-agentify/jobs/job-1')
  expect(document.body.querySelector('.wizard-steps [aria-current="step"]')?.textContent)
    .toContain('Analyze & generate')
  wrapper.unmount()
})

it('updates API source generation progress from background events', async () => {
  const sourceWithProgress = {
    ...importedSource,
    auto_agentify_job: {
      public_id: queuedJob.public_id,
      status: 'running',
      phase: 'analyzing_capabilities',
      progress: 37,
      updated_at: '2026-07-24T00:01:00',
    },
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response([sourceWithProgress])))
  const wrapper = mount(ApiSourcesView, {
    attachTo: document.body,
    global: { plugins: [i18n] },
  })
  await flushPromises()

  expect(wrapper.get('[data-testid="source-auto-agentify-3"]').text())
    .toContain('View progress 37%')
  expect(FakeEventSource.instances).toHaveLength(1)

  FakeEventSource.instances[0].emit({
    sequence: 4,
    kind: 'capability_batch_started',
    phase: 'analyzing_capabilities',
    progress: 64,
    message_key: 'autoAgentify.events.capabilityBatchStarted',
    params: { batch: 2, total: 3 },
    capability: null,
    created_at: '2026-07-24T00:02:00',
  }, '4')
  await flushPromises()

  expect(wrapper.get('[data-testid="source-auto-agentify-3"]').text())
    .toContain('View progress 64%')
  wrapper.unmount()
  expect(FakeEventSource.instances[0].close).toHaveBeenCalled()
})

it('stops an active generation job from the progress step', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({ ...queuedJob, status: 'running', progress: 37 }))
    .mockResolvedValueOnce(response({
      ...queuedJob,
      status: 'cancelled',
      phase: 'cancelled',
      progress: 37,
      completed_at: '2026-07-24T00:02:00',
    }))
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      sourceRecord: importedSource,
      resumeJobId: queuedJob.public_id,
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

  await wrapper.get('[data-testid="auto-stop"]').trigger('click')
  await flushPromises()

  expect(fetchMock.mock.calls[2][0])
    .toBe('/api/admin/auto-agentify/jobs/job-1/cancel')
  expect((fetchMock.mock.calls[2][1] as RequestInit).method).toBe('POST')
  expect(wrapper.text()).toContain('Generation stopped')
  expect(wrapper.emitted('stopped')).toHaveLength(1)
  expect(wrapper.find('[data-testid="auto-stop"]').exists()).toBe(false)
  expect(wrapper.get('[data-testid="auto-submit"]').text()).toContain('Retry')
  wrapper.unmount()
})

it('refreshes the API source row after stopping generation', async () => {
  const runningSource = {
    ...importedSource,
    auto_agentify_job: {
      public_id: queuedJob.public_id,
      status: 'running',
      phase: 'analyzing_capabilities',
      progress: 37,
      updated_at: '2026-07-24T00:01:00',
    },
  }
  const cancelledJob = {
    ...queuedJob,
    status: 'cancelled',
    phase: 'cancelled',
    progress: 37,
    completed_at: '2026-07-24T00:02:00',
  }
  const refreshedSource = {
    ...importedSource,
    auto_agentify_job: {
      public_id: queuedJob.public_id,
      status: 'cancelled',
      phase: 'cancelled',
      progress: 37,
      updated_at: '2026-07-24T00:02:00',
    },
  }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(response([runningSource]))
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({ ...queuedJob, status: 'running', progress: 37 }))
    .mockResolvedValueOnce(response(cancelledJob))
    .mockResolvedValueOnce(response([refreshedSource]))
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(ApiSourcesView, {
    attachTo: document.body,
    global: { plugins: [i18n] },
  })
  await flushPromises()

  await wrapper.get('[data-testid="source-auto-agentify-3"]').trigger('click')
  await flushPromises()
  const stopButton = document.body.querySelector<HTMLButtonElement>(
    '[data-testid="auto-stop"]',
  )
  expect(stopButton).not.toBeNull()
  stopButton?.click()
  await flushPromises()

  expect(fetchMock.mock.calls.filter(([url]) => url === '/api/admin/sources'))
    .toHaveLength(2)
  expect(wrapper.get('[data-testid="source-auto-agentify-3"]').text())
    .toContain('One-click generate')
  wrapper.unmount()
})

it('starts from the current URL import input and displays live capability analysis', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({ source: importedSource, tools: [] }, 201))
    .mockResolvedValueOnce(response([importedSource]))
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
  expect(wrapper.get('.wizard-steps').text()).toContain('Source & model')
  await wrapper.get('[data-testid="auto-provider"]').setValue('7')
  await wrapper.get('[data-testid="wizard-next"]').trigger('click')
  expect(wrapper.get('[data-testid="auto-generation-notice"]').text())
    .toContain('20 Skills')
  expect(wrapper.get('[data-testid="capability-system-sensitive_data_security"]').text())
    .toContain('Sensitive information and security')
  expect(wrapper.get('[data-testid="capability-system-sensitive_data_security"]')
    .attributes('aria-pressed')).toBe('false')
  expect(wrapper.findAll('[data-testid^="capability-system-"]')).toHaveLength(20)
  expect(wrapper.get('[data-testid="capability-system-order_query"]').text())
    .toContain('Order query')
  expect(wrapper.get('[data-testid="capability-system-public_services"]').text())
    .toContain('Public services')
  expect(wrapper.get('[data-testid="capability-system-intelligent_customer_service"]').text())
    .toContain('Intelligent customer service')

  await wrapper.get('[data-testid="capability-system-file_management"]').trigger('click')
  await wrapper.get('[data-testid="custom-capability-input"]')
    .setValue('Clinical trial data capture')
  await wrapper.get('[data-testid="add-custom-capability"]').trigger('click')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  const importCall = vi.mocked(fetch).mock.calls[1]
  expect(importCall[0]).toBe('/api/admin/sources/import-url')
  expect(JSON.parse(String(importCall[1]?.body))).toEqual({
    name: 'Projects',
    url: 'https://api.example.test/openapi.json',
    base_url: 'https://api.example.test',
    allow_private_networks: false,
  })
  const call = vi.mocked(fetch).mock.calls[3]
  expect(call[0]).toBe('/api/admin/auto-agentify/sources/3/jobs')
  expect(JSON.parse(String(call[1]?.body))).toEqual({
    provider_id: 7,
    allowed_system_capabilities: ['file_management'],
    custom_capability_labels: ['Clinical trial data capture'],
    result_language: 'en-US',
  })
  expect(FakeEventSource.instances[0].url)
    .toBe('/api/admin/auto-agentify/jobs/job-1/events')
  expect(wrapper.find('[data-testid="auto-analysis-loading"]').exists()).toBe(true)
  expect(wrapper.get('.activity-orbit').classes()).toContain('is-loading')

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
  expect(wrapper.text()).not.toContain('Project delivery insight')
  expect(wrapper.find('[data-testid="recognition-results"]').exists()).toBe(false)
  expect(wrapper.get('.analysis-process').text()).toContain('Analysis process')
  expect(wrapper.get('[data-testid="auto-progress"]').attributes('value')).toBe('42')
})

it('shows actionable API authentication guidance without exposing the internal error code', async () => {
  i18n.global.locale.value = 'zh-CN'
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({
      error: { code: 'auth.session_invalid', params: {} },
    }, 401)))
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      sourceRecord: importedSource,
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

  await wrapper.get('[data-testid="wizard-next"]').trigger('click')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  const errorPanel = wrapper.get('[data-testid="auto-error"]')
  expect(errorPanel.text()).toContain('认证失败，修改 APIs 的认证配置')
  expect(errorPanel.text()).not.toContain('auth.session_invalid')
})

it('shows the backend reason when importing a source for generation fails', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({
      error: {
        code: 'tools.openapi_unsupported',
        params: { reason: 'Parameter file must define schema or content' },
      },
    }, 422)))
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

  await wrapper.get('[data-testid="wizard-next"]').trigger('click')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  expect(wrapper.get('[data-testid="auto-error"]').text())
    .toContain('Parameter file must define schema or content')
})

it('shows the backend reason when starting generation for an imported source fails', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({
      error: {
        code: 'auto_agentify.openapi_unsupported',
        params: { reason: 'No supported HTTP operations were found' },
      },
    }, 422)))
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      sourceRecord: importedSource,
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

  await wrapper.get('[data-testid="wizard-next"]').trigger('click')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  expect(wrapper.get('[data-testid="auto-error"]').text())
    .toContain('No supported HTTP operations were found')
})

it('shows analysis strategy, business domain, consolidation, and retry details', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response(queuedJob, 202))
    .mockResolvedValueOnce(response(failedJob)))
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      sourceRecord: importedSource,
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
  await wrapper.get('[data-testid="wizard-next"]').trigger('click')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  FakeEventSource.instances[0].emit({
    sequence: 2,
    kind: 'analysis_strategy_selected',
    phase: 'analyzing_capabilities',
    progress: 23,
    message_key: 'autoAgentify.events.analysisStrategySelected',
    params: {
      mode: 'domain_groups',
      operation_count: 600,
      domain_count: 3,
      estimated_chars: 120000,
    },
    capability: null,
    created_at: '2026-07-24T00:00:01',
  }, '2')
  await flushPromises()
  expect(wrapper.get('[data-testid="auto-current-stage"]').text())
    .toContain('600 operations')
  expect(wrapper.get('[data-testid="auto-current-stage"]').text())
    .toContain('3 business domains')

  FakeEventSource.instances[0].emit({
    sequence: 3,
    kind: 'capability_batch_started',
    phase: 'analyzing_capabilities',
    progress: 24,
    message_key: 'autoAgentify.events.capabilityBatchStarted',
    params: {
      batch: 1,
      total: 3,
      operation_count: 200,
      domain: 'Orders',
      mode: 'domain_groups',
    },
    capability: null,
    created_at: '2026-07-24T00:00:02',
  }, '3')
  await flushPromises()
  expect(wrapper.get('[data-testid="auto-current-stage"]').text())
    .toContain('Orders')
  expect(wrapper.get('[data-testid="auto-current-stage"]').text())
    .toContain('200 operations')

  FakeEventSource.instances[0].emit({
    sequence: 4,
    kind: 'capability_consolidation_completed',
    phase: 'analyzing_capabilities',
    progress: 60,
    message_key: 'autoAgentify.events.capabilityConsolidationCompleted',
    params: { input_count: 12, output_count: 7, merged_count: 5 },
    capability: null,
    created_at: '2026-07-24T00:00:03',
  }, '4')
  await flushPromises()
  expect(wrapper.get('[data-testid="auto-current-stage"]').text())
    .toContain('12 candidates into 7 capabilities')
  expect(wrapper.get('[data-testid="auto-current-stage"]').text())
    .toContain('merged or removed 5')

  FakeEventSource.instances[0].emit({
    sequence: 5,
    kind: 'failed',
    phase: 'failed',
    progress: 44,
    message_key: 'autoAgentify.events.failed',
    params: { code: 'auto_agentify.provider_failed', status: 502 },
    capability: null,
    created_at: '2026-07-24T00:06:28',
  }, '5')
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
      sourceRecord: importedSource,
      resumeJobId: failedJob.public_id,
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

  await wrapper.get('.wizard-actions .secondary-action').trigger('click')
  expect(wrapper.get('[data-testid="capability-system-messaging_notifications"]')
    .attributes('aria-pressed')).toBe('true')
  expect(wrapper.text()).toContain('Clinical trial data capture')
})

it('shows the stored backend reason when a background generation job fails', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({
      ...failedJob,
      error_code: 'auto_agentify.openapi_unsupported',
      error_params: { reason: 'No supported HTTP operations were found' },
    })))
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      sourceRecord: importedSource,
      resumeJobId: failedJob.public_id,
      source: {
        mode: 'url',
        name: 'Projects',
        baseUrl: 'https://api.example.test',
        sourceUrl: 'https://api.example.test/openapi.json',
        file: null,
        allowPrivateNetworks: false,
      },
    },
    global: { plugins: [i18n], stubs: { teleport: true, RouterLink: true } },
  })
  await flushPromises()

  expect(wrapper.get('[data-testid="auto-error"]').text())
    .toContain('No supported HTTP operations were found')
})

it('restores completed work directly into a separate results step', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response(completedJob)))
  const wrapper = mount(AutoAgentifyPanel, {
    props: {
      sourceRecord: importedSource,
      resumeJobId: completedJob.public_id,
      source: {
        mode: 'url',
        name: 'Projects',
        baseUrl: 'https://api.example.test',
        sourceUrl: 'https://api.example.test/openapi.json',
        file: null,
        allowPrivateNetworks: false,
      },
    },
    global: { plugins: [i18n], stubs: { teleport: true, RouterLink: true } },
  })
  await flushPromises()

  expect(wrapper.get('.wizard-steps [aria-current="step"]').text())
    .toContain('Generated results')
  expect(wrapper.get('[data-testid="auto-result"]').text()).toContain('Project analyst')
  expect(wrapper.find('.analysis-process').exists()).toBe(false)
  expect(wrapper.get('[data-testid="result-footer-left"]').findAll('button')).toHaveLength(2)
  expect(wrapper.get('[data-testid="auto-complete"]').text()).toContain('Done')
  await wrapper.get('[data-testid="auto-complete"]').trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(1)

  await wrapper.get('.result-footer .secondary-action').trigger('click')
  expect(wrapper.get('.analysis-process').text()).toContain('Analysis process')
  expect(wrapper.find('[data-testid="recognition-results"]').exists()).toBe(false)
})

it('uses the current file input and keeps the background job when closed', async () => {
  i18n.global.locale.value = 'zh-CN'
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({
      source: { ...importedSource, name: 'Pets', document_url: null },
      tools: [],
    }, 201))
    .mockResolvedValueOnce(response([
      { ...importedSource, name: 'Pets', document_url: null },
    ]))
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
  await wrapper.get('[data-testid="wizard-next"]').trigger('click')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  const importCall = vi.mocked(fetch).mock.calls[1]
  expect(importCall[0]).toBe('/api/admin/sources/import-file')
  expect(importCall[1]?.body).toBeInstanceOf(FormData)
  expect((importCall[1]?.body as FormData).get('document')).toBe(file)
  const call = vi.mocked(fetch).mock.calls[3]
  expect(call[0]).toBe('/api/admin/auto-agentify/sources/3/jobs')
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    allowed_system_capabilities: [],
    custom_capability_labels: [],
    result_language: 'zh-CN',
  })

  await wrapper.get('[data-testid="auto-close"]').trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(1)
  expect(FakeEventSource.instances[0].close).not.toHaveBeenCalled()
})
