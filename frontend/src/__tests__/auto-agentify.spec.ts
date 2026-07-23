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
  id: 7,
  name: 'Primary',
  provider_type: 'openai',
  base_url: 'https://llm.example.test/v1',
  default_model: 'gpt-test',
  enabled: true,
  has_api_key: true,
}

const result = {
  source: {
    id: 11,
    name: 'Projects',
    source_type: 'openapi',
    base_url: 'https://api.example.test',
    document_url: 'https://api.example.test/openapi.json',
    allow_private_networks: false,
    auth_mode: 'none',
    enabled: true,
    created_at: '2026-07-24T00:00:00',
  },
  imported_tool_count: 8,
  enabled_tool_count: 5,
  skills: [{
    id: 21,
    name: 'Project Insights',
    tool_ids: [31, 32],
    value: 'Makes project delivery state understandable.',
  }],
  agents: [{
    id: 41,
    name: 'Project Operator',
    skill_ids: [21],
    mode: 'react',
    provider_id: 7,
    value: 'Coordinates project delivery workflows.',
    use_cases: ['Summarize project risk'],
  }],
}

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf-token'
})

it('submits URL generation and renders generated business value', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response(result, 201)))
  const wrapper = mount(AutoAgentifyPanel, { global: { plugins: [i18n] } })
  await flushPromises()

  await wrapper.get('[data-testid="auto-provider"]').setValue('7')
  await wrapper.get('[data-testid="auto-name"]').setValue('Projects')
  await wrapper.get('[data-testid="auto-url"]').setValue(
    'https://api.example.test/openapi.json',
  )
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  const call = vi.mocked(fetch).mock.calls[1]
  expect(call[0]).toBe('/api/admin/auto-agentify/url')
  expect(call[1]?.headers).toBeInstanceOf(Headers)
  expect((call[1]?.headers as Headers).get('X-CSRF-Token')).toBe('csrf-token')
  expect(JSON.parse(String(call[1]?.body))).toEqual({
    provider_id: 7,
    name: 'Projects',
    url: 'https://api.example.test/openapi.json',
    base_url: null,
    allow_private_networks: false,
  })
  expect(wrapper.text()).toContain('Project Insights')
  expect(wrapper.text()).toContain('Project Operator')
  expect(wrapper.text()).toContain('Coordinates project delivery workflows.')
  expect(wrapper.text()).toContain('Summarize project risk')
  expect(wrapper.emitted('generated')?.[0]).toEqual([result])
})


it('uses multipart file input and retains fields after a retryable failure', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([provider]))
    .mockResolvedValueOnce(response({
      error: { code: 'auto_agentify.plan_invalid', params: {} },
    }, 422)))
  const wrapper = mount(AutoAgentifyPanel, { global: { plugins: [i18n] } })
  await flushPromises()

  await wrapper.get('[data-testid="auto-mode-file"]').trigger('click')
  await wrapper.get('[data-testid="auto-provider"]').setValue('7')
  await wrapper.get('[data-testid="auto-name"]').setValue('Pets')
  const file = new File(['openapi: 3.0.3'], 'openapi.yaml', {
    type: 'application/yaml',
  })
  Object.defineProperty(
    wrapper.get('[data-testid="auto-file"]').element,
    'files',
    { value: [file] },
  )
  await wrapper.get('[data-testid="auto-file"]').trigger('change')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  await flushPromises()

  const call = vi.mocked(fetch).mock.calls[1]
  expect(call[0]).toBe('/api/admin/auto-agentify/file')
  expect(call[1]?.body).toBeInstanceOf(FormData)
  expect((call[1]?.body as FormData).get('document')).toBe(file)
  expect(wrapper.get<HTMLInputElement>('[data-testid="auto-name"]').element.value)
    .toBe('Pets')
  expect(wrapper.get('[data-testid="auto-error"]').text()).toContain(
    'could not produce a valid plan',
  )
})
