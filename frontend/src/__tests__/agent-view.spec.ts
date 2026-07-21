import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import AdminLayout from '../layouts/AdminLayout.vue'
import { createAppRouter } from '../router'
import { useAuthStore } from '../stores/auth'
import AgentView from '../views/AgentView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const providers = [
  { id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true },
  { id: 2, name: 'Offline', provider_type: 'anthropic', base_url: 'https://offline.test', default_model: 'claude-test', enabled: false, has_api_key: true },
]
const skills = [
  { id: 10, name: 'Inventory', description: 'Stock lookup', system_prompt: 'inventory', running: true, tools: [] },
  { id: 11, name: 'Billing', description: 'Invoices', system_prompt: 'billing', running: false, tools: [] },
  { id: 12, name: 'Shipping', description: 'Shipments', system_prompt: 'shipping', running: true, tools: [] },
]
const agents = [
  {
    id: 1,
    name: 'Operations Agent',
    enabled: true,
    is_default: true,
    system_prompt: 'Route requests through bound Skills.',
    provider_id: 1,
    model: null,
    mode: 'human_in_loop',
    max_iterations: 8,
    created_at: '2026-07-20T08:00:00Z',
    updated_at: '2026-07-20T08:00:00Z',
    deleted_at: null,
    skill_ids: [10, 11],
  },
  {
    id: 2,
    name: 'Draft Agent',
    enabled: false,
    is_default: false,
    system_prompt: 'Draft prompt.',
    provider_id: null,
    model: null,
    mode: 'react',
    max_iterations: 4,
    created_at: '2026-07-21T08:00:00Z',
    updated_at: '2026-07-21T08:00:00Z',
    deleted_at: null,
    skill_ids: [],
  },
]

function adminGet(input: RequestInfo | URL): Promise<Response> {
  if (input === '/api/admin/agents') return Promise.resolve(response(agents))
  if (input === '/api/admin/providers') return Promise.resolve(response(providers))
  if (input === '/api/admin/skills') return Promise.resolve(response(skills))
  if (input === '/api/admin/agents/1/keys') return Promise.resolve(response([]))
  if (input === '/api/admin/agents/2/keys') return Promise.resolve(response([]))
  throw new Error(`Unexpected request: ${String(input)}`)
}

function renderView(pinia = createPinia()) {
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.admin = { username: 'admin', locale: 'en-US' }
  auth.csrfToken = 'csrf'
  return render(AgentView, { global: { plugins: [pinia, i18n] } })
}

beforeEach(() => {
  i18n.global.locale.value = 'en-US'
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.admin = { username: 'admin', locale: 'en-US' }
  auth.csrfToken = 'csrf'
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Agent administration', () => {
  it('links to and registers the independent Agent administration route', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
    })
    render(AdminLayout, { global: { plugins: [i18n, router] } })
    expect((await screen.findByRole('link', { name: /Agents/ })).getAttribute('href')).toBe('/admin/agent')

    const auth = useAuthStore()
    auth.initialized = true
    const appRouter = createAppRouter()
    await appRouter.push('/admin/agent')
    expect(appRouter.currentRoute.value.name).toBe('agent')
  })

  it('loads a multi-Agent list and keeps a stopped bound Skill visible', async () => {
    vi.stubGlobal('fetch', vi.fn(adminGet))
    renderView()

    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeTruthy()
    expect(await screen.findByRole('button', { name: /Operations Agent/ })).toBeTruthy()
    expect(screen.getByText('Default')).toBeTruthy()
    expect(((await screen.findByLabelText('Provider')) as HTMLSelectElement).value).toBe('1')

    const bindings = screen.getByRole('region', { name: 'Bound Skills' })
    expect(within(bindings).getByText('Inventory')).toBeTruthy()
    expect(within(bindings).getByText('Billing')).toBeTruthy()
    expect(within(bindings).getByText('Stopped')).toBeTruthy()
    expect(within(bindings).getByRole('button', { name: 'Remove Billing' })).toBeTruthy()
  })

  it('creates disabled first and then writes ordered Skill bindings with CSRF', async () => {
    const created = { ...agents[1], id: 42, name: 'Support Agent', skill_ids: [] }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents' && init?.method === 'POST') return Promise.resolve(response(created, 201))
      if (input === '/api/admin/agents/42/skills') return Promise.resolve(response({ ...created, skill_ids: [12, 10] }))
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()
    await screen.findByRole('button', { name: /Operations Agent/ })

    await fireEvent.click(screen.getByRole('button', { name: 'New Agent' }))
    await fireEvent.update(screen.getByLabelText('Agent name'), 'Support Agent')
    await fireEvent.update(screen.getByLabelText('Provider'), '1')
    await fireEvent.update(screen.getByLabelText('System prompt'), 'Help support users.')
    await fireEvent.update(screen.getByLabelText('Search Skills'), 'ship')
    await fireEvent.click(screen.getByRole('button', { name: 'Add Shipping' }))
    await fireEvent.update(screen.getByLabelText('Search Skills'), 'inventory')
    await fireEvent.click(screen.getByRole('button', { name: 'Add Inventory' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Save Agent' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/42/skills', expect.anything()))
    const createCall = fetchMock.mock.calls.find(([url, init]) => url === '/api/admin/agents' && (init as RequestInit)?.method === 'POST')
    expect(JSON.parse((createCall?.[1] as RequestInit).body as string)).toMatchObject({
      name: 'Support Agent',
      enabled: false,
      provider_id: 1,
      system_prompt: 'Help support users.',
    })
    expect(((createCall?.[1] as RequestInit).headers as Headers).get('X-CSRF-Token')).toBe('csrf')
    const skillsCall = fetchMock.mock.calls.find(([url]) => url === '/api/admin/agents/42/skills')
    expect(JSON.parse((skillsCall?.[1] as RequestInit).body as string)).toEqual({ skill_ids: [12, 10] })
  })

  it('reorders Skills and saves every editable field', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1' && init?.method === 'PUT') return Promise.resolve(response({ ...agents[0], name: 'Ops Router' }))
      if (input === '/api/admin/agents/1/skills') return Promise.resolve(response({ ...agents[0], skill_ids: [11, 10] }))
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()
    await screen.findByDisplayValue('Operations Agent')

    await fireEvent.update(screen.getByLabelText('Agent name'), 'Ops Router')
    await fireEvent.update(screen.getByLabelText('Model override'), 'gpt-special')
    await fireEvent.update(screen.getByLabelText('Mode'), 'react')
    await fireEvent.update(screen.getByLabelText('Maximum iterations'), '12')
    await fireEvent.click(screen.getByRole('button', { name: 'Move Billing up' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Save Agent' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/skills', expect.anything()))
    const updateCall = fetchMock.mock.calls.find(([url]) => url === '/api/admin/agents/1')
    expect(JSON.parse((updateCall?.[1] as RequestInit).body as string)).toMatchObject({
      name: 'Ops Router', model: 'gpt-special', mode: 'react', max_iterations: 12, enabled: true,
    })
    const skillsCall = fetchMock.mock.calls.find(([url]) => url === '/api/admin/agents/1/skills')
    expect(JSON.parse((skillsCall?.[1] as RequestInit).body as string)).toEqual({ skill_ids: [11, 10] })
  })

  it('uses lifecycle endpoints and presents backend protection errors', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/2/enable' && init?.method === 'POST') {
        return Promise.resolve(response({ error: { code: 'agents.no_running_skills', params: {} } }, 409))
      }
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()
    await screen.findByRole('button', { name: /Draft Agent/ })
    await screen.findByLabelText('Provider')

    await fireEvent.click(screen.getByRole('button', { name: /Draft Agent/ }))
    await fireEvent.click(await screen.findByRole('button', { name: 'Enable Agent' }))

    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Bind at least one running Skill before enabling this Agent.')
    expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/2/enable', expect.objectContaining({ method: 'POST' }))
  })

  it('shows a created API key once, never persists the secret, and clears it on close', async () => {
    const pinia = createPinia()
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1/keys' && init?.method === 'POST') {
        return Promise.resolve(response({
          id: 8, agent_id: 1, label: 'Production', key_prefix: 'c4o_prod', enabled: true,
          expires_at: null, last_used_at: null, created_at: '2026-07-22T08:00:00Z',
          updated_at: '2026-07-22T08:00:00Z', revoked_at: null, secret: 'c4o_secret_once',
        }, 201))
      }
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView(pinia)
    await screen.findByRole('heading', { name: 'API keys' })

    await fireEvent.update(screen.getByLabelText('Key label'), 'Production')
    await fireEvent.click(screen.getByRole('button', { name: 'Create API key' }))

    expect(await screen.findByRole('dialog', { name: 'New API key' })).toHaveProperty('textContent', expect.stringContaining('c4o_secret_once'))
    expect(JSON.stringify(pinia.state.value)).not.toContain('c4o_secret_once')
    expect(setItem).not.toHaveBeenCalledWith(expect.any(String), expect.stringContaining('c4o_secret_once'))
    await fireEvent.click(screen.getByRole('button', { name: 'Close secret' }))
    expect(screen.queryByText('c4o_secret_once')).toBeNull()

    await fireEvent.update(screen.getByLabelText('Key label'), 'Rotation')
    await fireEvent.click(screen.getByRole('button', { name: 'Create API key' }))
    expect(await screen.findByText('c4o_secret_once')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: /Draft Agent/ }))
    await screen.findByRole('button', { name: 'Enable Agent' })
    expect(screen.queryByText('c4o_secret_once')).toBeNull()
  })

  it('lists key metadata and calls the supported revoke and delete actions', async () => {
    const key = {
      id: 7, agent_id: 1, label: 'Automation', key_prefix: 'c4o_auto', enabled: true,
      expires_at: '2027-01-01T00:00:00Z', last_used_at: '2026-07-22T05:00:00Z',
      created_at: '2026-07-20T08:00:00Z', updated_at: '2026-07-20T08:00:00Z', revoked_at: null,
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1/keys' && !init?.method) return Promise.resolve(response([key]))
      if (input === '/api/admin/agents/1/keys/7/revoke') return Promise.resolve(response({ ...key, enabled: false, revoked_at: '2026-07-22T08:00:00Z' }))
      if (input === '/api/admin/agents/1/keys/7' && init?.method === 'DELETE') return Promise.resolve(response(null, 204))
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()

    expect(await screen.findByText('c4o_auto')).toBeTruthy()
    expect(screen.getByText('Jan 1, 2027')).toBeTruthy()
    expect(screen.getByText('Jul 22, 2026')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Revoke Automation' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/keys/7/revoke', expect.objectContaining({ method: 'POST' })))
    await fireEvent.click(screen.getByRole('button', { name: 'Delete Automation' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/keys/7', expect.objectContaining({ method: 'DELETE' })))
  })
})
