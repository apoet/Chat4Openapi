import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import ChatView from '../views/ChatView.vue'
import ProvidersView from '../views/ProvidersView.vue'
import SkillsView from '../views/SkillsView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function deferred<T>(): {
  promise: Promise<T>
  resolve: (value: T) => void
} {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

const defaultAgent = {
  id: 1,
  name: 'Research Agent',
  is_default: true,
}

const CHAT_SUBJECT = 'test-browser-subject'
const CHAT_STORAGE_KEY = `chat4openapi.chat.sessions.v3.${CHAT_SUBJECT}`

function chatFetch(options: {
  agents?: unknown[]
  skills?: unknown[]
  turns?: Array<Response | Promise<Response>>
  subjectId?: string
} = {}) {
  const turns = [...(options.turns ?? [])]
  return vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    if (input === '/api/tool-session/config') return Promise.resolve(response({ enabled: false }))
    if (input === '/api/chat/bootstrap') return Promise.resolve(response({
      subject_id: options.subjectId ?? CHAT_SUBJECT,
      agents: options.agents ?? [defaultAgent],
    }))
    if (input === '/api/skills') return Promise.resolve(response(options.skills ?? []))
    if (input === '/api/chat/turns') {
      const next = turns.shift()
      if (!next) throw new Error('Unexpected Chat turn')
      return Promise.resolve(next)
    }
    return Promise.resolve(response([]))
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf'
  localStorage.clear()
})

describe('Skills and chat', () => {
  it('loads the public browser bootstrap without requesting the admin Agent catalog', async () => {
    const fetchMock = chatFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/chat/bootstrap')).toBe(true))
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/admin/agents')).toBe(false)
    expect(await screen.findByRole('option', { name: 'Research Agent — Default' })).toBeTruthy()
  })

  it('starts a new Chat with the Agent requested in the route query', async () => {
    const fetchMock = chatFetch({
      agents: [defaultAgent, { id: 2, name: 'Operations Agent', is_default: false }],
    })
    vi.stubGlobal('fetch', fetchMock)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/chat', name: 'chat', component: ChatView },
      ],
    })
    await router.push('/chat?agent_id=2')
    await router.isReady()

    render(ChatView, { global: { plugins: [i18n, router] } })

    await waitFor(() => expect((screen.getByLabelText('Agent') as HTMLSelectElement).value).toBe('2'))
  })

  it('offers two prompts from the selected Agent Skills and sends with Enter', async () => {
    const skill = {
      id: 7,
      name: 'Varcards2-Gene',
      description: 'query variant locations by gene name',
      system_prompt: 'Query genes',
      running: true,
      tools: [],
    }
    const fetchMock = chatFetch({
      agents: [{ ...defaultAgent, skill_ids: [skill.id] }],
      skills: [skill],
      turns: [response({
        status: 'completed', conversation_id: 'conversation-1', agent_id: 1,
        agent_name: 'Research Agent', message: 'Done.', loaded_skill_ids: [skill.id], pending: null,
      })],
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    const taskPrompt = await screen.findByRole('button', {
      name: 'Help me with query variant locations by gene name.',
    })
    expect(screen.getByRole('button', { name: 'What can Varcards2-Gene help me with?' })).toBeTruthy()
    await fireEvent.click(taskPrompt)
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).value).toBe(
      'Help me with query variant locations by gene name.',
    )
    await fireEvent.keyDown(screen.getByLabelText('Message'), { key: 'Enter' })

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/chat/turns')).toBe(true))
    const call = fetchMock.mock.calls.find(([url]) => url === '/api/chat/turns')
    expect(JSON.parse((call?.[1] as RequestInit).body as string).message).toBe(
      'Help me with query variant locations by gene name.',
    )
  })

  it('loads history only from the current browser subject namespace', async () => {
    const session = (id: string, title: string) => ({
      version: 3, id, conversationId: `conversation-${id}`, title,
      agentId: 1, agentName: 'Research Agent', loadedSkillIds: [], status: 'completed', pending: null,
      messages: [{ role: 'user', content: title, kind: 'message' }], updatedAt: '2026-07-22T00:00:00.000Z',
    })
    const firstKey = 'chat4openapi.chat.sessions.v3.subject-a'
    const secondKey = 'chat4openapi.chat.sessions.v3.subject-b'
    localStorage.setItem(firstKey, JSON.stringify([session('a', 'Subject A history')]))
    localStorage.setItem(secondKey, JSON.stringify([session('b', 'Subject B history')]))
    vi.stubGlobal('fetch', chatFetch({ subjectId: 'subject-b' }))

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(await screen.findByRole('button', { name: 'Subject B history' })).toBeTruthy()
    expect(screen.queryByText('Subject A history')).toBeNull()
    expect(JSON.parse(localStorage.getItem(firstKey) ?? '[]')[0].title).toBe('Subject A history')
    expect(JSON.parse(localStorage.getItem(secondKey) ?? '[]')[0].title).toBe('Subject B history')
  })

  it('rebootstraps an expired in-page browser session without replaying the turn', async () => {
    const subjects = ['subject-a', 'subject-b']
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (input === '/api/tool-session/config') return Promise.resolve(response({ enabled: false }))
      if (input === '/api/skills') return Promise.resolve(response([]))
      if (input === '/api/chat/bootstrap') {
        return Promise.resolve(response({ subject_id: subjects.shift(), agents: [defaultAgent] }))
      }
      if (input === '/api/chat/turns') {
        return Promise.resolve(response({
          error: { code: 'chat.browser_session_expired', params: {} },
        }, 401))
      }
      return Promise.resolve(response([]))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Agent' }) as HTMLSelectElement).value).toBe('1'))

    await fireEvent.update(screen.getByLabelText('Message'), 'Create side effect once')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Your browser chat session changed. Start a New chat and send your message again.')).toBeTruthy()
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/chat/bootstrap')).toHaveLength(2)
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/chat/turns')).toHaveLength(1)
    expect(screen.queryByText('Create side effect once')).toBeNull()
    expect(localStorage.getItem('chat4openapi.chat.sessions.v3.subject-a')).toContain('Create side effect once')
    expect(JSON.parse(localStorage.getItem('chat4openapi.chat.sessions.v3.subject-b') ?? '[]')).toEqual([])
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('claims legacy global history once so a later subject cannot import it', async () => {
    localStorage.setItem('chat4openapi.chat.sessions.v1', JSON.stringify([{
      id: 'legacy-once', conversationId: 'legacy-conversation', title: 'Claim me once',
      messages: [{ role: 'user', content: 'Legacy message' }],
      updatedAt: '2026-07-21T00:00:00.000Z',
    }]))
    vi.stubGlobal('fetch', chatFetch({ subjectId: 'subject-a' }))
    const first = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await screen.findByRole('button', { name: 'Claim me once' })

    expect(localStorage.getItem('chat4openapi.chat.sessions.v1')).toBeNull()
    expect(localStorage.getItem('chat4openapi.chat.sessions.v3.subject-a')).toContain('Claim me once')
    first.unmount()

    vi.stubGlobal('fetch', chatFetch({ subjectId: 'subject-b' }))
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Agent' }) as HTMLSelectElement).value).toBe('1'))

    expect(screen.queryByRole('button', { name: 'Claim me once' })).toBeNull()
    expect(JSON.parse(localStorage.getItem('chat4openapi.chat.sessions.v3.subject-b') ?? '[]')).toEqual([])
  })

  it('keeps legacy global history when the namespaced claim cannot be written', async () => {
    const legacyKey = 'chat4openapi.chat.sessions.v1'
    const namespacedKey = 'chat4openapi.chat.sessions.v3.subject-a'
    localStorage.setItem(legacyKey, JSON.stringify([{
      id: 'legacy-retry', conversationId: 'legacy-conversation', title: 'Retry this claim',
      messages: [{ role: 'user', content: 'Legacy message' }],
      updatedAt: '2026-07-21T00:00:00.000Z',
    }]))
    const originalSetItem = Storage.prototype.setItem
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
      if (key === namespacedKey) throw new DOMException('Quota exceeded', 'QuotaExceededError')
      return originalSetItem.call(this, key, value)
    })
    vi.stubGlobal('fetch', chatFetch({ subjectId: 'subject-a' }))

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await screen.findByRole('button', { name: 'Retry this claim' })

    expect(localStorage.getItem(namespacedKey)).toBeNull()
    expect(localStorage.getItem(legacyKey)).toContain('Retry this claim')
  })

  it('isolates an unknown history version without rewriting or dropping its payload', async () => {
    const future = {
      version: 4,
      id: 'future-session',
      conversationId: 'future-conversation',
      title: 'Future history',
      messages: [{ role: 'user', content: 'future content', kind: 'hologram' }],
      futureSecretShape: { nested: [1, 2, 3] },
      updatedAt: '2027-01-01T00:00:00.000Z',
    }
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify([future]))
    vi.stubGlobal('fetch', chatFetch())

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    await screen.findByRole('combobox', { name: 'Agent' })
    expect(screen.queryByText('Future history')).toBeNull()
    expect(JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? '[]')).toEqual([future])
    expect(Object.keys(localStorage).some((key) => /cookie|token/i.test(key))).toBe(false)
  })
  it('tests an existing provider connection without exposing its API key', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response([{
        id: 1,
        name: 'Primary',
        provider_type: 'openai',
        base_url: 'https://llm.test/v1',
        default_model: 'gpt-test',
        enabled: true,
        has_api_key: true,
      }]))
      .mockResolvedValueOnce(response({ ok: true, model: 'gpt-test', response: 'OK' }))
    vi.stubGlobal('fetch', fetchMock)

    render(ProvidersView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Test' }))

    expect(await screen.findByText('Connection successful')).toBeTruthy()
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/providers/1/test')
  })

  it('saves a Skill as provider-free Tool and prompt orchestration', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/providers') {
        return Promise.resolve(response([{ id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true }]))
      }
      if (input === '/api/admin/tools' || input === '/api/admin/sources') {
        return Promise.resolve(response([]))
      }
      if (input === '/api/admin/skills' && init?.method === 'POST') {
        return Promise.resolve(response({ id: 7, name: 'Pet helper', description: null, system_prompt: 'Use pet Tools.', running: false, tools: [] }))
      }
      return Promise.resolve(response([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(SkillsView, { global: { plugins: [i18n] } })
    await fireEvent.update(screen.getByLabelText('Skill name'), 'Pet helper')
    await fireEvent.update(screen.getByLabelText('System prompt'), 'Use pet Tools.')
    const save = screen.getByRole('button', { name: 'Save Skill' }) as HTMLButtonElement
    await waitFor(() => expect(save.disabled).toBe(false))
    expect(screen.queryByLabelText('Provider')).toBeNull()
    expect(screen.queryByLabelText('Model override')).toBeNull()
    await fireEvent.click(save)

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true))
    const call = fetchMock.mock.calls.find(([input, init]) => input === '/api/admin/skills' && init?.method === 'POST')
    expect(JSON.parse(call?.[1]?.body as string)).toEqual({
      name: 'Pet helper',
      description: null,
      system_prompt: 'Use pet Tools.',
      tool_ids: [],
    })
  })

  it('quick-references only enabled Tools and inserts a stable prompt token', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          response([
            {
              id: 2,
              api_source_id: 1,
              operation_key: 'GET /pets/{id}',
              name: 'get_pet',
              description: 'Get pet',
              input_schema: { type: 'object' },
              enabled: true,
            },
            {
              id: 3,
              api_source_id: 1,
              operation_key: 'DELETE /pets/{id}',
              name: 'delete_pet',
              description: 'Delete pet',
              input_schema: { type: 'object' },
              enabled: false,
            },
          ]),
        )
        .mockResolvedValueOnce(response([
          { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', document_url: null, allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
        ]))
        .mockResolvedValueOnce(response([]))
        .mockResolvedValueOnce(response([
          { id: 2, api_source_id: 1, operation_key: 'GET /pets/{id}', name: 'get_pet', description: 'Get pet', input_schema: { type: 'object' }, enabled: true },
        ])),
    )

    render(SkillsView, { global: { plugins: [i18n] } })
    const quickTool = await screen.findByRole('button', { name: /get_pet/ }) as HTMLButtonElement
    await waitFor(() => expect(quickTool.disabled).toBe(false))
    const disabledTool = screen.getByText('delete_pet')
    expect(disabledTool).toBeTruthy()
    expect((screen.getByRole('checkbox', { name: 'Bind delete_pet' }) as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Reference delete_pet' }) as HTMLButtonElement).disabled).toBe(true)
    await fireEvent.click(quickTool)

    const prompt = screen.getByLabelText('System prompt') as HTMLTextAreaElement
    expect(prompt.value).toContain('{{tool:get_pet}}')
    expect(screen.getByText('1 Tool bound')).toBeTruthy()
  })

  it('offers enabled Tool mentions after typing @ in the prompt', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response([
        { id: 2, api_source_id: 1, operation_key: 'GET /pets/{id}', name: 'get_pet', description: 'Get pet', input_schema: {}, execution_schema: {}, tags: ['Pets'], enabled: true },
        { id: 3, api_source_id: 1, operation_key: 'GET /orders', name: 'list_orders', description: 'List orders', input_schema: {}, execution_schema: {}, tags: ['Orders'], enabled: true },
      ]))
      .mockResolvedValueOnce(response([{ id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', document_url: null, allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' }]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([
        { id: 2, api_source_id: 1, operation_key: 'GET /pets/{id}', name: 'get_pet', description: 'Get pet', input_schema: {}, execution_schema: {}, tags: ['Pets'], enabled: true },
        { id: 3, api_source_id: 1, operation_key: 'GET /orders', name: 'list_orders', description: 'List orders', input_schema: {}, execution_schema: {}, tags: ['Orders'], enabled: true },
      ])))

    render(SkillsView, { global: { plugins: [i18n] } })
    const prompt = await screen.findByLabelText('System prompt') as HTMLTextAreaElement
    await fireEvent.update(prompt, 'Use @get')
    await fireEvent.click(await screen.findByRole('option', { name: 'Mention get_pet' }))

    expect(prompt.value).toBe('Use {{tool:get_pet}}')
    expect(screen.getByText('1 Tool bound')).toBeTruthy()
    expect(screen.queryByRole('option', { name: 'Mention list_orders' })).toBeNull()
  })

  it('groups quick references by API source and Swagger tag', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response([
        { id: 2, api_source_id: 1, operation_key: 'GET /pets', name: 'list_pets', description: null, input_schema: {}, execution_schema: {}, tags: ['Pet operations'], enabled: true },
        { id: 3, api_source_id: 2, operation_key: 'GET /orders', name: 'list_orders', description: null, input_schema: {}, execution_schema: {}, tags: ['Order operations'], enabled: true },
      ]))
      .mockResolvedValueOnce(response([
        { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', document_url: null, allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
        { id: 2, name: 'Order API', source_type: 'openapi', base_url: 'https://orders.test', document_url: null, allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
      ]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([
        { id: 2, api_source_id: 1, operation_key: 'GET /pets', name: 'list_pets', description: null, input_schema: {}, execution_schema: {}, tags: ['Pet operations'], enabled: true },
        { id: 3, api_source_id: 2, operation_key: 'GET /orders', name: 'list_orders', description: null, input_schema: {}, execution_schema: {}, tags: ['Order operations'], enabled: true },
      ])))

    const { container } = render(SkillsView, { global: { plugins: [i18n] } })

    expect(await screen.findByRole('heading', { name: 'Pet API' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Order API' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Pet operations' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Order operations' })).toBeTruthy()
    expect(container.querySelectorAll('details.catalog-source-group')).toHaveLength(2)
  })

  it('deletes a managed Skill from its row actions', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([{ id: 5, name: 'Pet helper', description: null, system_prompt: 'Help', running: false, tools: [] }]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(response([]))
    vi.stubGlobal('fetch', fetchMock)

    render(SkillsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6))
    expect(fetchMock.mock.calls[4][0]).toBe('/api/admin/skills/5')
  })

  it('starts a managed Skill through its lifecycle endpoint', async () => {
    const stopped = { id: 5, name: 'Pet helper', description: null, system_prompt: 'Help', running: false, tools: [] }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([stopped]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response({ ...stopped, running: true }))
      .mockResolvedValueOnce(response([{ ...stopped, running: true }]))
    vi.stubGlobal('fetch', fetchMock)

    render(SkillsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Start' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6))
    expect(fetchMock.mock.calls[4][0]).toBe('/api/admin/skills/5/start')
    expect(fetchMock.mock.calls[4][1]).toMatchObject({ method: 'POST' })
  })

  it('selects the default Agent, sends it on creation, and locks while the turn is pending', async () => {
    const turn = deferred<Response>()
    const agents = [
      { id: 1, name: 'Operations', is_default: false },
      { id: 2, name: 'Research', is_default: true },
    ]
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      if (input === '/api/tool-session/config') return Promise.resolve(response({ enabled: false }))
      if (input === '/api/chat/bootstrap') return Promise.resolve(response({ subject_id: CHAT_SUBJECT, agents }))
      if (input === '/api/skills') return Promise.resolve(response([]))
      if (input === '/api/chat/turns') return turn.promise
      return Promise.resolve(response([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    const input = await screen.findByLabelText('Message')
    const selector = await screen.findByRole('combobox', { name: 'Agent' }) as HTMLSelectElement
    await waitFor(() => expect(selector.value).toBe('2'))
    expect(screen.queryByRole('option', { name: 'Stopped' })).toBeNull()
    expect(input.compareDocumentPosition(selector) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    await fireEvent.update(input, 'Find Milo')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(selector.disabled).toBe(true)
    const turnCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat/turns')
    expect(JSON.parse(turnCall?.[1]?.body as string)).toEqual({
      message: 'Find Milo',
      conversation_id: null,
      agent_id: 2,
    })
    turn.resolve(response({
      status: 'completed', conversation_id: 'conversation-1', agent_id: 2, agent_name: 'Research',
      message: 'Milo is ready.', loaded_skill_ids: [], pending: null,
    }))
    expect(await screen.findByText('Milo is ready.')).toBeTruthy()
    expect(selector.disabled).toBe(true)
  })

  it('prevents a new turn when no enabled Agent is available', async () => {
    const fetchMock = chatFetch({ agents: [] })
    vi.stubGlobal('fetch', fetchMock)
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/api/chat/bootstrap')).toBe(true))
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.queryByRole('option', { name: 'Stopped' })).toBeNull()
  })

  it('migrates legacy Skill history without guessing an Agent and backfills the server Agent on resume', async () => {
    localStorage.setItem('chat4openapi.chat.sessions.v1', JSON.stringify([
      {
        id: 'legacy-good',
        conversationId: 'conversation-abca4',
        skillId: 1,
        title: '查询ABCA4位点',
        messages: [
          { role: 'user', content: '查询ABCA4位点' },
          { role: 'assistant', content: 'ABCA4 variants found.' },
        ],
        updatedAt: '2026-07-21T00:00:00.000Z',
      },
      { id: 'broken', skillId: 'not-a-number', title: 42, messages: 'bad' },
    ]))
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      if (input === '/api/tool-session/config') return Promise.resolve(response({ enabled: false }))
      if (input === '/api/chat/bootstrap') return Promise.resolve(response({
        subject_id: CHAT_SUBJECT,
        agents: [{ id: 1, name: 'Current default', is_default: true }],
      }))
      if (input === '/api/skills') return Promise.resolve(response([]))
      if (input === '/api/chat/turns') return Promise.resolve(response({
        status: 'completed', conversation_id: 'conversation-abca4', agent_id: 9, agent_name: 'Retired research',
        message: 'Resumed safely.', loaded_skill_ids: [], pending: null,
      }))
      return Promise.resolve(response([]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(await screen.findByRole('button', { name: '查询ABCA4位点' })).toBeTruthy()
    expect(screen.getByText('ABCA4 variants found.')).toBeTruthy()
    const selector = await screen.findByRole('combobox', { name: 'Agent' }) as HTMLSelectElement
    expect(selector.disabled).toBe(true)
    expect(selector.value).toBe('')
    const stored = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? '[]')
    expect(stored).toHaveLength(1)
    expect(stored[0]).toMatchObject({
      version: 3,
      id: 'legacy-good',
      conversationId: 'conversation-abca4',
      agentId: null,
      agentName: null,
      loadedSkillIds: [],
      status: 'completed',
      pending: null,
    })
    expect(stored[0].skillId).toBeUndefined()
    expect(stored[0].skillIds).toBeUndefined()
    expect(stored[0].messages).toEqual([
      { role: 'user', content: '查询ABCA4位点', kind: 'message' },
      { role: 'assistant', content: 'ABCA4 variants found.', kind: 'message' },
    ])

    await fireEvent.update(screen.getByLabelText('Message'), 'Continue')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Resumed safely.')).toBeTruthy()
    const turnCall = fetchMock.mock.calls.find(([url]) => url === '/api/chat/turns')
    expect(JSON.parse(turnCall?.[1]?.body as string)).toEqual({
      message: 'Continue',
      conversation_id: 'conversation-abca4',
    })
    const resumed = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? '[]')[0]
    expect(resumed).toMatchObject({ agentId: 9, agentName: 'Retired research' })
    expect((screen.getByRole('combobox', { name: 'Agent' }) as HTMLSelectElement).value).toBe('9')
    expect(screen.getByRole('option', { name: 'Retired research' })).toBeTruthy()
  })

  it('safely restores pending v2 sessions whose messages predate explicit kinds', async () => {
    localStorage.setItem('chat4openapi.chat.sessions.v1', JSON.stringify([{
      version: 2,
      id: 'pending-v2',
      conversationId: 'conversation-pending',
      title: 'Pending question',
      skillIds: [],
      loadedSkillIds: [1],
      status: 'needs_input',
      pending: { fields: ['reference'] },
      messages: [
        { role: 'user', content: 'Find variants' },
        { role: 'assistant', content: 'Which reference genome?' },
      ],
      updatedAt: '2026-07-21T00:00:00.000Z',
    }]))
    vi.stubGlobal('fetch', chatFetch())

    const restored = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(await screen.findByText('Which reference genome?')).toBeTruthy()
    expect(restored.container.querySelector('.message.clarification')).toBeTruthy()
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).placeholder).toBe('Answer the clarification…')
    const stored = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? '[]')
    expect(stored[0]).toMatchObject({ version: 3, agentId: null, agentName: null })
    expect(stored[0].pending).toEqual({ fields: ['reference'] })
    expect(stored[0].messages).toEqual([
      { role: 'user', content: 'Find variants', kind: 'message' },
      { role: 'assistant', content: 'Which reference genome?', kind: 'clarification' },
    ])
  })

  it('persists clarification state and resumes the same Agent conversation', async () => {
    const skill = { id: 1, name: 'Varcards2-Gene', description: null, system_prompt: 'Query genes', running: true, tools: [] }
    const firstFetch = chatFetch({ skills: [skill], turns: [response({
        status: 'needs_input',
        conversation_id: 'conversation-abca4',
        agent_id: 1,
        agent_name: 'Research Agent',
        message: 'Which reference genome?',
        loaded_skill_ids: [1],
        pending: { fields: ['reference'], choices: ['GRCh37', 'GRCh38'] },
      })] })
    vi.stubGlobal('fetch', firstFetch)

    const first = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Agent' }) as HTMLSelectElement).value).toBe('1'))
    await fireEvent.update(await screen.findByLabelText('Message'), '查询一个基因')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Which reference genome?')).toBeTruthy()
    expect(screen.getByText('Clarification needed')).toBeTruthy()
    expect(await screen.findByText('Loaded: Varcards2-Gene')).toBeTruthy()

    let stored = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? '[]')
    expect(stored[0]).toMatchObject({
      version: 3,
      conversationId: 'conversation-abca4',
      agentId: 1,
      agentName: 'Research Agent',
      loadedSkillIds: [1],
      status: 'needs_input',
      pending: { fields: ['reference'], choices: ['GRCh37', 'GRCh38'] },
    })
    first.unmount()

    const resumedFetch = chatFetch({ skills: [skill], turns: [response({
        status: 'completed',
        conversation_id: 'conversation-abca4',
        agent_id: 1,
        agent_name: 'Research Agent',
        message: 'Using GRCh38.',
        loaded_skill_ids: [1],
        pending: null,
      })] })
    vi.stubGlobal('fetch', resumedFetch)
    const restored = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(await screen.findByText('Which reference genome?')).toBeTruthy()
    expect(restored.container.querySelector('.message.clarification')).toBeTruthy()
    expect(await screen.findByText('Loaded: Varcards2-Gene')).toBeTruthy()
    await fireEvent.update(screen.getByLabelText('Message'), 'GRCh38')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Using GRCh38.')).toBeTruthy()
    const clarification = screen.getByText('Which reference genome?').closest('article')
    expect(clarification?.classList.contains('clarification')).toBe(true)
    const resumedTurn = resumedFetch.mock.calls.find(([url]) => url === '/api/chat/turns')
    expect(JSON.parse(resumedTurn?.[1]?.body as string)).toEqual({
      message: 'GRCh38',
      conversation_id: 'conversation-abca4',
    })
    stored = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? '[]')
    expect(stored[0]).toMatchObject({ status: 'completed', pending: null })
    expect(stored[0].messages.map((message: { kind: string }) => message.kind)).toEqual([
      'message', 'clarification', 'message', 'message',
    ])

    restored.unmount()
    vi.stubGlobal('fetch', chatFetch({ skills: [skill] }))
    const completedReload = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(await screen.findByText('Using GRCh38.')).toBeTruthy()
    expect(screen.getByText('Which reference genome?').closest('article')?.classList.contains('clarification')).toBe(true)
    expect(completedReload.container.querySelectorAll('.message.clarification')).toHaveLength(1)
  })

  it('writes a deferred response only to the local session that started the turn', async () => {
    const turn = deferred<Response>()
    const fetchMock = chatFetch({ turns: [turn.promise] })
    vi.stubGlobal('fetch', fetchMock)
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Agent' }) as HTMLSelectElement).value).toBe('1'))

    await fireEvent.update(screen.getByLabelText('Message'), 'Find Milo')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
    turn.resolve(response({
      status: 'completed', conversation_id: 'conversation-1', agent_id: 1, agent_name: 'Research Agent',
      message: 'Milo is ready.', loaded_skill_ids: [1], pending: null,
    }))

    await waitFor(() => expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false))
    expect(screen.queryByText('Milo is ready.')).toBeNull()
    expect(screen.getByText('What can your APIs do?')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Find Milo' }))
    expect(await screen.findByText('Milo is ready.')).toBeTruthy()
    const stored = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? '[]')
    expect(stored.find((session: { title: string }) => session.title === 'Find Milo')).toMatchObject({
      conversationId: 'conversation-1',
      messages: [
        { role: 'user', content: 'Find Milo', kind: 'message' },
        { role: 'assistant', content: 'Milo is ready.', kind: 'message' },
      ],
    })
  })

  it('attributes a deferred request error to its originating history session', async () => {
    localStorage.setItem('chat4openapi.chat.sessions.v1', JSON.stringify([
      {
        version: 2, id: 'origin', conversationId: 'conversation-origin', title: 'Origin', skillIds: [], loadedSkillIds: [],
        status: 'completed', pending: null, messages: [{ role: 'user', content: 'Earlier origin message' }], updatedAt: '2026-07-21T00:00:01.000Z',
      },
      {
        version: 2, id: 'other', conversationId: 'conversation-other', title: 'Other', skillIds: [], loadedSkillIds: [],
        status: 'completed', pending: null, messages: [{ role: 'user', content: 'Other message' }], updatedAt: '2026-07-21T00:00:00.000Z',
      },
    ]))
    const turn = deferred<Response>()
    const fetchMock = chatFetch({ turns: [turn.promise] })
    vi.stubGlobal('fetch', fetchMock)
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await screen.findByRole('button', { name: 'Other' })

    await fireEvent.update(screen.getByLabelText('Message'), 'Fail this turn')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Other' }))
    turn.resolve(response({ error: { code: 'agent.unavailable', params: {} } }, 409))

    await waitFor(() => expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByText('Other message')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Origin' }))
    expect((await screen.findByRole('alert')).textContent).toBe("This conversation's Agent is no longer available.")
  })

  it('unlocks New Chat and reselects the current default Agent', async () => {
    const agents = [
      { id: 1, name: 'Operations', is_default: false },
      { id: 2, name: 'Research', is_default: true },
    ]
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      if (input === '/api/tool-session/config') return Promise.resolve(response({ enabled: false }))
      if (input === '/api/chat/bootstrap') return Promise.resolve(response({ subject_id: CHAT_SUBJECT, agents }))
      if (input === '/api/skills') return Promise.resolve(response([]))
      if (input === '/api/chat/turns') return Promise.resolve(response({
        status: 'completed', conversation_id: 'conversation-1', agent_id: 1, agent_name: 'Operations',
        message: 'Done', loaded_skill_ids: [], pending: null,
      }))
      return Promise.resolve(response([]))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    const selector = await screen.findByRole('combobox', { name: 'Agent' }) as HTMLSelectElement
    await waitFor(() => expect(selector.value).toBe('2'))
    await fireEvent.update(selector, '1')
    await fireEvent.update(screen.getByLabelText('Message'), 'Find Milo')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Done')
    expect(selector.disabled).toBe(true)

    await fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
    expect(selector.disabled).toBe(false)
    expect(selector.value).toBe('2')
  })

  it('keeps an inactive Agent snapshot visible and locked after refresh', async () => {
    localStorage.setItem('chat4openapi.chat.sessions.v1', JSON.stringify([{
      version: 3, id: 'inactive', conversationId: 'conversation-inactive', title: 'Archived work',
      agentId: 9, agentName: 'Stopped research', loadedSkillIds: [], status: 'completed', pending: null,
      messages: [{ role: 'user', content: 'Earlier work', kind: 'message' }], updatedAt: '2026-07-22T00:00:00.000Z',
    }]))
    vi.stubGlobal('fetch', chatFetch())

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    await screen.findByRole('button', { name: 'Archived work' })
    const selector = screen.getByRole('combobox', { name: 'Agent' }) as HTMLSelectElement
    expect(selector.value).toBe('9')
    expect(selector.disabled).toBe(true)
    expect(screen.getByRole('option', { name: 'Stopped research' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Archived work' }).textContent).toContain('Stopped research')
  })
})
