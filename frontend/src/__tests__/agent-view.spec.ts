import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import { createAppRouter } from '../router'
import { useAuthStore } from '../stores/auth'
import AdminLayout from '../layouts/AdminLayout.vue'
import AgentView from '../views/AgentView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.admin = { username: 'admin', locale: 'en-US' }
  auth.csrfToken = 'csrf'
})

describe('Agent administration', () => {
  it('links to the independent Agent configuration from administration', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
    })

    render(AdminLayout, { global: { plugins: [i18n, router] } })

    expect((await screen.findByRole('link', { name: /Agent/ })).getAttribute('href')).toBe(
      '/admin/agent',
    )
  })

  it('registers the Agent configuration as an administrator route', async () => {
    const auth = useAuthStore()
    auth.initialized = true
    const router = createAppRouter()

    await router.push('/admin/agent')

    expect(router.currentRoute.value.name).toBe('agent')
  })

  it('loads enabled providers and the Agent configuration with Human-in-loop selected', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (input === '/api/admin/providers') {
        return Promise.resolve(response([
          { id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true },
          { id: 2, name: 'Disabled', provider_type: 'openai', base_url: 'https://disabled.test/v1', default_model: 'gpt-disabled', enabled: false, has_api_key: true },
        ]))
      }
      return Promise.resolve(response({
        id: 1,
        name: 'Chat4Openapi Agent',
        enabled: true,
        system_prompt: 'Use Skills and Tools.',
        provider_id: 1,
        model: null,
        mode: 'human_in_loop',
        max_iterations: 8,
      }))
    }))

    render(AgentView, { global: { plugins: [i18n] } })

    await waitFor(() => expect((screen.getByLabelText('Agent name') as HTMLInputElement).value).toBe('Chat4Openapi Agent'))
    expect((screen.getByLabelText('Provider') as HTMLSelectElement).value).toBe('1')
    expect(screen.getByRole('option', { name: /Primary/ })).toBeTruthy()
    expect(screen.queryByRole('option', { name: /Disabled/ })).toBeNull()
    expect((screen.getByLabelText('Mode') as HTMLSelectElement).value).toBe('human_in_loop')
    expect(screen.getByRole('option', { name: 'Human-in-loop' })).toBeTruthy()
    expect(screen.getByText('Tool calls run without approval.')).toBeTruthy()
  })

  it('disables saving while no enabled provider is selected', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response({
        id: 1,
        name: 'Chat4Openapi Agent',
        enabled: true,
        system_prompt: 'Use Skills and Tools.',
        provider_id: null,
        model: null,
        mode: 'human_in_loop',
        max_iterations: 8,
      })))

    render(AgentView, { global: { plugins: [i18n] } })

    await waitFor(() => expect((screen.getByLabelText('Agent name') as HTMLInputElement).value).toBe('Chat4Openapi Agent'))
    expect((screen.getByRole('button', { name: 'Save Agent' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('saves every Agent configuration field with administrator CSRF', async () => {
    const initial = {
      id: 1 as const,
      name: 'Chat4Openapi Agent',
      enabled: true,
      system_prompt: 'Original prompt',
      provider_id: 1,
      model: null,
      mode: 'human_in_loop',
      max_iterations: 8,
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response([{ id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true }]))
      .mockResolvedValueOnce(response(initial))
      .mockResolvedValueOnce(response({ ...initial, name: 'Operations Agent' }))
    vi.stubGlobal('fetch', fetchMock)

    render(AgentView, { global: { plugins: [i18n] } })
    await waitFor(() => expect((screen.getByLabelText('Agent name') as HTMLInputElement).value).toBe('Chat4Openapi Agent'))

    await fireEvent.update(screen.getByLabelText('Agent name'), 'Operations Agent')
    await fireEvent.click(screen.getByRole('checkbox', { name: /Enabled/ }))
    await fireEvent.update(screen.getByLabelText('System prompt'), 'Route through declared Skills.')
    await fireEvent.update(screen.getByLabelText('Model override'), 'gpt-special')
    await fireEvent.update(screen.getByLabelText('Mode'), 'react')
    await fireEvent.update(screen.getByLabelText('Maximum iterations'), '12')
    await fireEvent.click(screen.getByRole('button', { name: 'Save Agent' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(fetchMock.mock.calls[2][0]).toBe('/api/admin/agent')
    const init = fetchMock.mock.calls[2][1] as RequestInit
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body as string)).toEqual({
      name: 'Operations Agent',
      enabled: false,
      system_prompt: 'Route through declared Skills.',
      provider_id: 1,
      model: 'gpt-special',
      mode: 'react',
      max_iterations: 12,
    })
    expect((init.headers as Headers).get('X-CSRF-Token')).toBe('csrf')
  })

  it('restores Agent defaults through the reset route', async () => {
    const initial = {
      id: 1 as const,
      name: 'Operations Agent',
      enabled: false,
      system_prompt: 'Custom prompt',
      provider_id: 1,
      model: 'gpt-special',
      mode: 'react',
      max_iterations: 12,
    }
    const defaults = {
      ...initial,
      name: 'Chat4Openapi Agent',
      enabled: true,
      system_prompt: 'Built-in prompt',
      model: null,
      mode: 'human_in_loop',
      max_iterations: 8,
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response([{ id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true }]))
      .mockResolvedValueOnce(response(initial))
      .mockResolvedValueOnce(response(defaults))
    vi.stubGlobal('fetch', fetchMock)

    render(AgentView, { global: { plugins: [i18n] } })
    await waitFor(() => expect((screen.getByLabelText('Agent name') as HTMLInputElement).value).toBe('Operations Agent'))
    await fireEvent.click(screen.getByRole('button', { name: 'Restore defaults' }))

    await waitFor(() => expect((screen.getByLabelText('Agent name') as HTMLInputElement).value).toBe('Chat4Openapi Agent'))
    expect(fetchMock.mock.calls[2][0]).toBe('/api/admin/agent/reset')
    const init = fetchMock.mock.calls[2][1] as RequestInit
    expect(init.method).toBe('POST')
    expect((init.headers as Headers).get('X-CSRF-Token')).toBe('csrf')
    expect((screen.getByLabelText('Mode') as HTMLSelectElement).value).toBe('human_in_loop')
  })

  it('shows a localized Agent error when the selected provider becomes unavailable', async () => {
    const initial = {
      id: 1 as const,
      name: 'Chat4Openapi Agent',
      enabled: true,
      system_prompt: 'Built-in prompt',
      provider_id: 1,
      model: null,
      mode: 'human_in_loop',
      max_iterations: 8,
    }
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response([{ id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true }]))
      .mockResolvedValueOnce(response(initial))
      .mockResolvedValueOnce(response({ error: { code: 'agent.provider_unavailable', params: {} } }, 409)))

    render(AgentView, { global: { plugins: [i18n] } })
    await waitFor(() => expect((screen.getByLabelText('Agent name') as HTMLInputElement).value).toBe('Chat4Openapi Agent'))
    await fireEvent.click(screen.getByRole('button', { name: 'Save Agent' }))

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Choose an enabled provider before saving the Agent.',
    )
  })
})
