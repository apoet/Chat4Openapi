import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import AdminLayout from '../layouts/AdminLayout.vue'
import { createAppRouter } from '../router'
import { useAuthStore } from '../stores/auth'
import AgentView from '../views/AgentView.vue'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline })
  return { promise, resolve, reject }
}

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
const originalShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const originalDialogClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
let showModalSpy: ReturnType<typeof vi.fn>
let dialogCloseSpy: ReturnType<typeof vi.fn>

function adminGet(input: RequestInfo | URL): Promise<Response> {
  if (input === '/api/admin/agents') return Promise.resolve(response(agents))
  if (input === '/api/admin/build/providers') return Promise.resolve(response(providers))
  if (input === '/api/admin/skills') return Promise.resolve(response(skills))
  if (input === '/api/admin/agents/1/keys') return Promise.resolve(response([]))
  if (input === '/api/admin/agents/2/keys') return Promise.resolve(response([]))
  throw new Error(`Unexpected request: ${String(input)}`)
}

function renderView(pinia = createPinia()) {
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.admin = { username: 'admin', locale: 'en-US', role: 'admin' }
  auth.csrfToken = 'csrf'
  return render(AgentView, { global: { plugins: [pinia, i18n] } })
}

beforeEach(() => {
  vi.stubEnv('TZ', 'Asia/Shanghai')
  showModalSpy = vi.fn(function (this: HTMLDialogElement) { this.setAttribute('open', '') })
  dialogCloseSpy = vi.fn(function (this: HTMLDialogElement) { this.removeAttribute('open') })
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: showModalSpy })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: dialogCloseSpy })
  i18n.global.locale.value = 'en-US'
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.admin = { username: 'admin', locale: 'en-US', role: 'admin' }
  auth.csrfToken = 'csrf'
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  if (originalShowModal) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShowModal)
  else delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal
  if (originalDialogClose) Object.defineProperty(HTMLDialogElement.prototype, 'close', originalDialogClose)
  else delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).close
})

describe('Agent administration', () => {
  it('links to and registers the independent Agent administration route', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
    })
    render(AdminLayout, { global: { plugins: [i18n, router] } })
    expect((await screen.findByRole('link', { name: /Agents/ })).getAttribute('href')).toBe('/admin/agent')
    const chatLink = await screen.findByRole('link', { name: /Chat/ })
    expect(chatLink.getAttribute('href')).toBe('/chat')
    expect(chatLink.getAttribute('target')).toBe('_blank')
    expect(chatLink.getAttribute('rel')).toContain('noopener')

    const auth = useAuthStore()
    auth.initialized = true
    const appRouter = createAppRouter()
    await appRouter.push('/admin/agent')
    expect(appRouter.currentRoute.value.name).toBe('agent')
  })

  it('opens the account menu and changes the signed-in user password', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(null, 204))
    vi.stubGlobal('fetch', fetchMock)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/admin', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: { template: '<div>Login</div>' } },
      ],
    })
    await router.push('/admin')
    await router.isReady()
    render(AdminLayout, { global: { plugins: [i18n, router] } })

    await fireEvent.click(screen.getByRole('button', { name: 'Account menu' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    await fireEvent.update(screen.getByLabelText('Current password'), 'StrongPass!123')
    await fireEvent.update(screen.getByLabelText('New password'), 'ChangedPass456')
    await fireEvent.update(screen.getByLabelText('Confirm new password'), 'ChangedPass456')
    await fireEvent.click(screen.getByRole('button', { name: 'Update password' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/admin/auth/password',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          current_password: 'StrongPass!123',
          new_password: 'ChangedPass456',
          new_password_confirm: 'ChangedPass456',
        }),
        credentials: 'include',
      }),
    ))
    await waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
  })

  it('opens Chat for an enabled Agent in a new window', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.admin = { username: 'admin', locale: 'en-US', role: 'admin' }
    auth.csrfToken = 'csrf'
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/admin/agent', name: 'agent', component: AgentView },
        { path: '/chat', name: 'chat', component: { template: '<div>Chat page</div>' } },
      ],
    })
    await router.push('/admin/agent')
    await router.isReady()
    vi.stubGlobal('fetch', vi.fn(adminGet))
    render(AgentView, { global: { plugins: [pinia, i18n, router] } })

    const chatLinks = await screen.findAllByRole('link', { name: 'Chat' })
    expect(chatLinks[0].getAttribute('href')).toBe('/chat?agent_id=1')
    expect(chatLinks[0].getAttribute('target')).toBe('_blank')
    expect(chatLinks[0].getAttribute('rel')).toContain('noopener')
    expect(router.currentRoute.value.name).toBe('agent')
  })

  it('loads a multi-Agent list and keeps a stopped bound Skill visible', async () => {
    vi.stubGlobal('fetch', vi.fn(adminGet))
    renderView()

    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeTruthy()
    const selected = await screen.findByRole('button', { name: /Operations Agent/ })
    await waitFor(() => expect(selected.getAttribute('aria-current')).toBe('true'))
    expect(selected.querySelector('.agent-avatar')?.getAttribute('aria-hidden')).toBe('true')
    expect(screen.getByText('Default')).toBeTruthy()
    expect(((await screen.findByLabelText('Provider')) as HTMLSelectElement).value).toBe('1')

    const bindings = screen.getByRole('region', { name: 'Bound Skills' })
    expect(within(bindings).getByText('Inventory')).toBeTruthy()
    expect(within(bindings).getByText('Billing')).toBeTruthy()
    expect(within(bindings).getByText('Stopped')).toBeTruthy()
    expect(within(bindings).getByRole('button', { name: 'Remove Billing' })).toBeTruthy()
  })

  it('keeps a missing bound Skill visible so removing it repairs the saved bindings', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents') return Promise.resolve(response([{ ...agents[0], skill_ids: [10, 99] }]))
      if (input === '/api/admin/agents/1' && init?.method === 'PUT') return Promise.resolve(response({ ...agents[0], skill_ids: [10, 99] }))
      if (input === '/api/admin/agents/1/skills' && init?.method === 'PUT') return Promise.resolve(response({ ...agents[0], skill_ids: [10] }))
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()

    const bindings = await screen.findByRole('region', { name: 'Bound Skills' })
    expect(within(bindings).getByText('Unavailable Skill #99')).toBeTruthy()
    await fireEvent.click(within(bindings).getByRole('button', { name: 'Remove Unavailable Skill #99' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Save Agent' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/skills', expect.anything()))
    const bindingCall = fetchMock.mock.calls.find(([url]) => url === '/api/admin/agents/1/skills')
    expect(JSON.parse((bindingCall?.[1] as RequestInit).body as string)).toEqual({ skill_ids: [10] })
  })

  it('creates safely, writes ordered Skill bindings, and then starts the Agent', async () => {
    const created = { ...agents[1], id: 42, name: 'Support Agent', skill_ids: [] }
    const bound = { ...created, skill_ids: [12, 10] }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents' && init?.method === 'POST') return Promise.resolve(response(created, 201))
      if (input === '/api/admin/agents/42/skills') return Promise.resolve(response(bound))
      if (input === '/api/admin/agents/42/enable') return Promise.resolve(response({ ...bound, enabled: true }))
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

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/42/enable', expect.objectContaining({ method: 'POST' })))
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
    const enableCall = fetchMock.mock.calls.find(([url]) => url === '/api/admin/agents/42/enable')
    expect(((enableCall?.[1] as RequestInit).headers as Headers).get('X-CSRF-Token')).toBe('csrf')
  })

  it('reconciles a partially created Agent and prevents duplicate saves', async () => {
    const created = { ...agents[1], id: 42, name: 'Partial Agent', skill_ids: [] }
    const binding = deferred<Response>()
    let listCalls = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents' && init?.method === 'POST') return Promise.resolve(response(created, 201))
      if (input === '/api/admin/agents/42/skills') return binding.promise
      if (input === '/api/admin/agents') {
        listCalls += 1
        return Promise.resolve(response(listCalls === 1 ? agents : [...agents, created]))
      }
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()
    await screen.findByLabelText('Provider')

    await fireEvent.click(screen.getByRole('button', { name: 'New Agent' }))
    await fireEvent.update(screen.getByLabelText('Agent name'), 'Partial Agent')
    await fireEvent.update(screen.getByLabelText('System prompt'), 'Partial prompt.')
    const save = screen.getByRole('button', { name: 'Save Agent' })
    await fireEvent.click(save)
    await fireEvent.click(save)
    expect((save as HTMLButtonElement).disabled).toBe(true)
    expect(fetchMock.mock.calls.filter(([url, init]) => url === '/api/admin/agents' && (init as RequestInit)?.method === 'POST')).toHaveLength(1)

    binding.resolve(response({ error: { code: 'agents.skill_unavailable', params: { skill_id: 99 } } }, 409))
    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      'Agent details were saved, but Skill bindings were not. Review the current Agent and retry.',
    )
    expect(await screen.findByDisplayValue('Partial Agent')).toBeTruthy()
    expect(screen.getByRole('button', { name: /Partial Agent/ }).getAttribute('aria-current')).toBe('true')
    expect((screen.getByRole('button', { name: 'Save Agent' }) as HTMLButtonElement).disabled).toBe(false)
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

  it('uses set-default, disable, and soft-delete lifecycle endpoints', async () => {
    let current = agents.map((agent) => ({ ...agent }))
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents') return Promise.resolve(response(current))
      if (input === '/api/admin/agents/2/set-default') {
        current = current.map((agent) => ({ ...agent, is_default: agent.id === 2, enabled: agent.id === 2 ? true : agent.enabled }))
        return Promise.resolve(response(current[1]))
      }
      if (input === '/api/admin/agents/1/disable') {
        current = current.map((agent) => agent.id === 1 ? { ...agent, enabled: false } : agent)
        return Promise.resolve(response(current[0]))
      }
      if (input === '/api/admin/agents/1' && init?.method === 'DELETE') {
        current = current.filter((agent) => agent.id !== 1)
        return Promise.resolve(response(null, 204))
      }
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()
    await screen.findByLabelText('Provider')

    await fireEvent.click(screen.getByRole('button', { name: /Draft Agent/ }))
    await fireEvent.click(await screen.findByRole('button', { name: 'Set as default' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/2/set-default', expect.anything()))
    const operations = screen.getByRole('button', { name: /Operations Agent/ }) as HTMLButtonElement
    await waitFor(() => expect(operations.disabled).toBe(false))
    await fireEvent.click(operations)
    await fireEvent.click(await screen.findByRole('button', { name: 'Disable Agent' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/disable', expect.anything()))
    const remove = await screen.findByRole('button', { name: 'Delete Agent' }) as HTMLButtonElement
    await waitFor(() => expect(remove.disabled).toBe(false))
    await fireEvent.click(remove)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1', expect.objectContaining({ method: 'DELETE' })))
    for (const url of ['/api/admin/agents/2/set-default', '/api/admin/agents/1/disable', '/api/admin/agents/1']) {
      const call = fetchMock.mock.calls.find(([called]) => called === url)
      expect(((call?.[1] as RequestInit).headers as Headers).get('X-CSRF-Token')).toBe('csrf')
    }
  })

  it('shows a created API key once with focus, copy feedback, and Escape cleanup', async () => {
    const pinia = createPinia()
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
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
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('Asia/Shanghai')
    await fireEvent.update(screen.getByLabelText('Key expiry (Asia/Shanghai)'), '2027-02-02T09:30')
    await fireEvent.click(screen.getByRole('button', { name: 'Create API key' }))

    const dialog = await screen.findByRole('dialog', { name: 'New API key' })
    expect(dialog).toHaveProperty('textContent', expect.stringContaining('c4o_secret_once'))
    expect(showModalSpy).toHaveBeenCalledTimes(1)
    const createCall = fetchMock.mock.calls.find(([url, init]) => url === '/api/admin/agents/1/keys' && (init as RequestInit)?.method === 'POST')
    expect(JSON.parse((createCall?.[1] as RequestInit).body as string)).toEqual({ label: 'Production', expires_at: '2027-02-02T01:30:00.000Z' })
    expect(JSON.stringify(pinia.state.value)).not.toContain('c4o_secret_once')
    expect(setItem).not.toHaveBeenCalledWith(expect.any(String), expect.stringContaining('c4o_secret_once'))
    expect((screen.getByRole('button', { name: 'Create API key' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('Agent name') as HTMLInputElement).disabled).toBe(true)
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Copy secret' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Copy secret' }))
    expect(writeText).toHaveBeenCalledWith('c4o_secret_once')
    expect(await screen.findByText('Secret copied.')).toBeTruthy()
    await fireEvent(screen.getByRole('dialog', { name: 'New API key' }), new Event('cancel', { cancelable: true }))
    expect(dialogCloseSpy).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('c4o_secret_once')).toBeNull()
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText('Key label')))
  })

  it('locks key creation and Agent selection while a secret request is pending, then discards a late unmounted key', async () => {
    const pending = deferred<Response>()
    const created = {
      id: 88, agent_id: 1, label: 'Late', key_prefix: 'c4o_late', enabled: true,
      expires_at: null, last_used_at: null, created_at: '2026-07-22T08:00:00Z',
      updated_at: '2026-07-22T08:00:00Z', revoked_at: null, secret: 'c4o_late_secret',
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1/keys' && init?.method === 'POST') return pending.promise
      if (input === '/api/admin/agents/1/keys/88' && init?.method === 'DELETE') return Promise.resolve(response(null, 204))
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    const view = renderView()
    await screen.findByRole('heading', { name: 'API keys' })
    await fireEvent.update(screen.getByLabelText('Key label'), 'Late')
    const create = screen.getByRole('button', { name: 'Create API key' })
    await fireEvent.click(create)

    expect((create as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: /Draft Agent/ }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('Agent name') as HTMLInputElement).disabled).toBe(true)
    expect(fetchMock.mock.calls.filter(([url, init]) => url === '/api/admin/agents/1/keys' && (init as RequestInit)?.method === 'POST')).toHaveLength(1)
    view.unmount()
    pending.resolve(response(created, 201))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/keys/88', expect.objectContaining({ method: 'DELETE' })))
    expect(document.body.textContent).not.toContain('c4o_late_secret')
  })

  it('revokes a late created key when automatic deletion fails', async () => {
    const pending = deferred<Response>()
    const created = {
      id: 89, agent_id: 1, label: 'Late fallback', key_prefix: 'c4o_late', enabled: true,
      expires_at: null, last_used_at: null, created_at: '2026-07-22T08:00:00Z',
      updated_at: '2026-07-22T08:00:00Z', revoked_at: null, secret: 'c4o_late_fallback_secret',
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1/keys' && init?.method === 'POST') return pending.promise
      if (input === '/api/admin/agents/1/keys/89' && init?.method === 'DELETE') return Promise.resolve(response({ error: { code: 'http.500' } }, 500))
      if (input === '/api/admin/agents/1/keys/89/revoke' && init?.method === 'POST') return Promise.resolve(response({ ...created, secret: undefined, enabled: false, revoked_at: '2026-07-22T08:05:00Z' }))
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    const view = renderView()
    await screen.findByRole('heading', { name: 'API keys' })
    await fireEvent.update(screen.getByLabelText('Key label'), 'Late fallback')
    await fireEvent.click(screen.getByRole('button', { name: 'Create API key' }))
    view.unmount()
    pending.resolve(response(created, 201))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/keys/89/revoke', expect.objectContaining({ method: 'POST' })))
    expect(document.body.textContent).not.toContain('c4o_late_fallback_secret')
  })

  it('edits key label and expiry, shows precise metadata, and supports revoke/delete', async () => {
    const key = {
      id: 7, agent_id: 1, label: 'Automation', key_prefix: 'c4o_auto', enabled: true,
      expires_at: '2027-01-01T00:00:00Z', last_used_at: '2026-07-22T05:00:00Z',
      created_at: '2026-07-20T08:00:00Z', updated_at: '2026-07-20T08:00:00Z', revoked_at: null,
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1/keys' && !init?.method) return Promise.resolve(response([key]))
      if (input === '/api/admin/agents/1/keys/7' && init?.method === 'PATCH') return Promise.resolve(response({ ...key, label: 'Deployments', expires_at: '2027-02-02T09:30:00Z' }))
      if (input === '/api/admin/agents/1/keys/7/revoke') return Promise.resolve(response({ ...key, label: 'Deployments', expires_at: '2027-02-02T09:30:00Z', enabled: false, revoked_at: '2026-07-22T08:00:00Z' }))
      if (input === '/api/admin/agents/1/keys/7' && init?.method === 'DELETE') return Promise.resolve(response(null, 204))
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()

    expect(await screen.findByText('c4o_auto')).toBeTruthy()
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('Asia/Shanghai')
    expect(screen.getByText('Jan 1, 2027, 8:00 AM')).toBeTruthy()
    expect(screen.getByText('Jul 22, 2026, 1:00 PM')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Edit Automation' }))
    await fireEvent.update(screen.getByLabelText('Edit key label'), 'Deployments')
    await fireEvent.update(screen.getByLabelText('Edit key expiry (Asia/Shanghai)'), '2027-02-02T09:30')
    await fireEvent.click(screen.getByRole('button', { name: 'Save Automation' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/keys/7', expect.objectContaining({ method: 'PATCH' })))
    const patchCall = fetchMock.mock.calls.find(([url, init]) => url === '/api/admin/agents/1/keys/7' && (init as RequestInit)?.method === 'PATCH')
    expect(JSON.parse((patchCall?.[1] as RequestInit).body as string)).toEqual({ label: 'Deployments', expires_at: '2027-02-02T01:30:00.000Z' })
    expect(((patchCall?.[1] as RequestInit).headers as Headers).get('X-CSRF-Token')).toBe('csrf')
    await fireEvent.click(await screen.findByRole('button', { name: 'Revoke Deployments' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/keys/7/revoke', expect.objectContaining({ method: 'POST' })))
    await fireEvent.click(screen.getByRole('button', { name: 'Delete Deployments' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/admin/agents/1/keys/7', expect.objectContaining({ method: 'DELETE' })))
  })

  it.each(['patch', 'revoke', 'delete'] as const)('ignores a late %s failure after the Agent prop switches', async (operation) => {
    const pending = deferred<Response>()
    const key = {
      id: 7, agent_id: 1, label: 'Automation', key_prefix: 'c4o_auto', enabled: true,
      expires_at: null, last_used_at: null, created_at: '2026-07-20T08:00:00Z',
      updated_at: '2026-07-20T08:00:00Z', revoked_at: null,
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1/keys' && !init?.method) return Promise.resolve(response([key]))
      if (input === '/api/admin/agents/2/keys' && !init?.method) return Promise.resolve(response([]))
      if (operation === 'patch' && input === '/api/admin/agents/1/keys/7' && init?.method === 'PATCH') return pending.promise
      if (operation === 'revoke' && input === '/api/admin/agents/1/keys/7/revoke' && init?.method === 'POST') return pending.promise
      if (operation === 'delete' && input === '/api/admin/agents/1/keys/7' && init?.method === 'DELETE') return pending.promise
      return adminGet(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderView()
    await screen.findByText('c4o_auto')

    if (operation === 'patch') {
      await fireEvent.click(screen.getByRole('button', { name: 'Edit Automation' }))
      await fireEvent.click(screen.getByRole('button', { name: 'Save Automation' }))
    } else if (operation === 'revoke') {
      await fireEvent.click(screen.getByRole('button', { name: 'Revoke Automation' }))
    } else {
      await fireEvent.click(screen.getByRole('button', { name: 'Delete Automation' }))
    }
    await fireEvent.click(screen.getByRole('button', { name: /Draft Agent/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Draft Agent/ }).getAttribute('aria-current')).toBe('true'))
    pending.resolve(response({ error: { code: 'agent_keys.not_found', params: {} } }, 404))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByText('c4o_auto')).toBeNull()
  })
})
