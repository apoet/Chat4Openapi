import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import SkillMultiSelect from '../components/SkillMultiSelect.vue'
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

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf'
  localStorage.clear()
})

describe('Skills and chat', () => {
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
      if (input === '/api/admin/skills/eligible-tools' || input === '/api/admin/sources') {
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
        .mockResolvedValueOnce(response([])),
    )

    render(SkillsView, { global: { plugins: [i18n] } })
    const quickTool = await screen.findByRole('button', { name: /get_pet/ })
    expect(screen.queryByText('delete_pet')).toBeNull()
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
      .mockResolvedValueOnce(response([])))

    render(SkillsView, { global: { plugins: [i18n] } })
    const prompt = await screen.findByLabelText('System prompt') as HTMLTextAreaElement
    await fireEvent.update(prompt, 'Use @get')
    await fireEvent.click(await screen.findByRole('button', { name: 'Mention get_pet' }))

    expect(prompt.value).toBe('Use {{tool:get_pet}}')
    expect(screen.getByText('1 Tool bound')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Mention list_orders' })).toBeNull()
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
      .mockResolvedValueOnce(response([])))

    const { container } = render(SkillsView, { global: { plugins: [i18n] } })

    expect(await screen.findByRole('heading', { name: 'Pet API' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Order API' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Pet operations' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Order operations' })).toBeTruthy()
    expect(container.querySelectorAll('details.reference-source-group')).toHaveLength(2)
  })

  it('deletes a managed Skill from its row actions', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([{ id: 5, name: 'Pet helper', description: null, system_prompt: 'Help', running: false, tools: [] }]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(response([]))
    vi.stubGlobal('fetch', fetchMock)

    render(SkillsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5))
    expect(fetchMock.mock.calls[3][0]).toBe('/api/admin/skills/5')
  })

  it('auto-routes with an empty selection and sends multiple candidate Skills', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([
        { id: 1, name: 'Pet helper', description: null, system_prompt: 'Help', running: true, tools: [] },
        { id: 2, name: 'Order helper', description: null, system_prompt: 'Help', running: true, tools: [] },
      ]))
      .mockResolvedValueOnce(response({
        status: 'completed',
        conversation_id: 'conversation-1',
        message: 'Milo is ready.',
        loaded_skill_ids: [1],
        pending: null,
      }))
    vi.stubGlobal('fetch', fetchMock)

    const { container } = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    const input = await screen.findByLabelText('Message')
    const selector = screen.getByRole('button', { name: 'Select candidate Skills' })
    expect(screen.getByText('Agent auto-select')).toBeTruthy()
    expect(input.compareDocumentPosition(selector) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    await fireEvent.click(selector)
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Pet helper' }))
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Order helper' }))
    await fireEvent.update(input, 'Find Milo')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(fetchMock.mock.calls[2][0]).toBe('/api/chat/turns')
    expect(JSON.parse(fetchMock.mock.calls[2][1]?.body as string)).toEqual({
      message: 'Find Milo',
      conversation_id: null,
      candidate_skill_ids: [1, 2],
    })
    expect(await screen.findByText('Milo is ready.')).toBeTruthy()
    expect(container.querySelector('.skill-dock')).toBeTruthy()
  })

  it('migrates legacy single-Skill history and ignores malformed records', async () => {
    localStorage.setItem('chatapi.chat.sessions.v1', JSON.stringify([
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
    const skill = { id: 1, name: 'Varcards2-Gene', description: null, system_prompt: 'Query genes', running: true, tools: [] }
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([skill])))

    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(await screen.findByRole('button', { name: '查询ABCA4位点' })).toBeTruthy()
    expect(screen.getByText('ABCA4 variants found.')).toBeTruthy()
    expect(await screen.findByRole('button', { name: 'Remove Varcards2-Gene' })).toBeTruthy()
    const stored = JSON.parse(localStorage.getItem('chatapi.chat.sessions.v1') ?? '[]')
    expect(stored).toHaveLength(1)
    expect(stored[0]).toMatchObject({
      version: 2,
      id: 'legacy-good',
      conversationId: 'conversation-abca4',
      skillIds: [1],
      loadedSkillIds: [],
      status: 'completed',
      pending: null,
    })
    expect(stored[0].skillId).toBeUndefined()
    expect(stored[0].messages).toEqual([
      { role: 'user', content: '查询ABCA4位点', kind: 'message' },
      { role: 'assistant', content: 'ABCA4 variants found.', kind: 'message' },
    ])
  })

  it('safely restores pending v2 sessions whose messages predate explicit kinds', async () => {
    localStorage.setItem('chatapi.chat.sessions.v1', JSON.stringify([{
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
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([])))

    const restored = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(await screen.findByText('Which reference genome?')).toBeTruthy()
    expect(restored.container.querySelector('.message.clarification')).toBeTruthy()
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).placeholder).toBe('Answer the clarification…')
    const stored = JSON.parse(localStorage.getItem('chatapi.chat.sessions.v1') ?? '[]')
    expect(stored[0].pending).toEqual({ fields: ['reference'] })
    expect(stored[0].messages).toEqual([
      { role: 'user', content: 'Find variants', kind: 'message' },
      { role: 'assistant', content: 'Which reference genome?', kind: 'clarification' },
    ])
  })

  it('persists clarification state and resumes the same Agent conversation', async () => {
    const skill = { id: 1, name: 'Varcards2-Gene', description: null, system_prompt: 'Query genes', running: true, tools: [] }
    const firstFetch = vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([skill]))
      .mockResolvedValueOnce(response({
        status: 'needs_input',
        conversation_id: 'conversation-abca4',
        message: 'Which reference genome?',
        loaded_skill_ids: [1],
        pending: { fields: ['reference'], choices: ['GRCh37', 'GRCh38'] },
      }))
    vi.stubGlobal('fetch', firstFetch)

    const first = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await waitFor(() => expect(firstFetch).toHaveBeenCalledTimes(2))
    await fireEvent.update(await screen.findByLabelText('Message'), '查询一个基因')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Which reference genome?')).toBeTruthy()
    expect(screen.getByText('Clarification needed')).toBeTruthy()
    expect(await screen.findByText('Loaded: Varcards2-Gene')).toBeTruthy()

    let stored = JSON.parse(localStorage.getItem('chatapi.chat.sessions.v1') ?? '[]')
    expect(stored[0]).toMatchObject({
      version: 2,
      conversationId: 'conversation-abca4',
      skillIds: [],
      loadedSkillIds: [1],
      status: 'needs_input',
      pending: { fields: ['reference'], choices: ['GRCh37', 'GRCh38'] },
    })
    first.unmount()

    const resumedFetch = vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([skill]))
      .mockResolvedValueOnce(response({
        status: 'completed',
        conversation_id: 'conversation-abca4',
        message: 'Using GRCh38.',
        loaded_skill_ids: [1],
        pending: null,
      }))
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
    expect(JSON.parse(resumedFetch.mock.calls[2][1]?.body as string)).toEqual({
      message: 'GRCh38',
      conversation_id: 'conversation-abca4',
      candidate_skill_ids: [],
    })
    stored = JSON.parse(localStorage.getItem('chatapi.chat.sessions.v1') ?? '[]')
    expect(stored[0]).toMatchObject({ status: 'completed', pending: null })
    expect(stored[0].messages.map((message: { kind: string }) => message.kind)).toEqual([
      'message', 'clarification', 'message', 'message',
    ])

    restored.unmount()
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([skill])))
    const completedReload = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    expect(await screen.findByText('Using GRCh38.')).toBeTruthy()
    expect(screen.getByText('Which reference genome?').closest('article')?.classList.contains('clarification')).toBe(true)
    expect(completedReload.container.querySelectorAll('.message.clarification')).toHaveLength(1)
  })

  it('writes a deferred response only to the local session that started the turn', async () => {
    const turn = deferred<Response>()
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([]))
      .mockImplementationOnce(() => turn.promise)
    vi.stubGlobal('fetch', fetchMock)
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    await fireEvent.update(screen.getByLabelText('Message'), 'Find Milo')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
    turn.resolve(response({
      status: 'completed', conversation_id: 'conversation-1', message: 'Milo is ready.', loaded_skill_ids: [1], pending: null,
    }))

    await waitFor(() => expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false))
    expect(screen.queryByText('Milo is ready.')).toBeNull()
    expect(screen.getByText('What can your APIs do?')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Find Milo' }))
    expect(await screen.findByText('Milo is ready.')).toBeTruthy()
    const stored = JSON.parse(localStorage.getItem('chatapi.chat.sessions.v1') ?? '[]')
    expect(stored.find((session: { title: string }) => session.title === 'Find Milo')).toMatchObject({
      conversationId: 'conversation-1',
      messages: [
        { role: 'user', content: 'Find Milo', kind: 'message' },
        { role: 'assistant', content: 'Milo is ready.', kind: 'message' },
      ],
    })
  })

  it('attributes a deferred request error to its originating history session', async () => {
    localStorage.setItem('chatapi.chat.sessions.v1', JSON.stringify([
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
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([]))
      .mockImplementationOnce(() => turn.promise)
    vi.stubGlobal('fetch', fetchMock)
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    await fireEvent.update(screen.getByLabelText('Message'), 'Fail this turn')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Other' }))
    turn.resolve(response({ error: { code: 'turn_failed', params: { reason: 'Origin failed' } } }, 500))

    await waitFor(() => expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByText('Other message')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Origin' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Origin failed')
  })

  it('locks candidate Skills after the first turn and copies them into a new chat', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(response([
        { id: 1, name: 'Pet helper', description: null, system_prompt: 'Help', running: true, tools: [] },
      ]))
      .mockResolvedValueOnce(response({
        status: 'completed', conversation_id: 'conversation-1', message: 'Done', loaded_skill_ids: [1], pending: null,
      }))
    vi.stubGlobal('fetch', fetchMock)
    render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const selector = await screen.findByRole('button', { name: 'Select candidate Skills' })
    await fireEvent.click(selector)
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Pet helper' }))
    await fireEvent.update(screen.getByLabelText('Message'), 'Find Milo')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(screen.queryByRole('listbox', { name: 'Candidate Skills' })).toBeNull()
    await screen.findByText('Done')
    expect((screen.getByRole('button', { name: 'Select candidate Skills' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Remove Pet helper' }) as HTMLButtonElement).disabled).toBe(true)

    await fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
    expect((screen.getByRole('button', { name: 'Select candidate Skills' }) as HTMLButtonElement).disabled).toBe(false)
    expect(screen.getByRole('button', { name: 'Remove Pet helper' })).toBeTruthy()
  })

  it('exposes true disabled state for choices at the selection limit', async () => {
    render(SkillMultiSelect, {
      props: {
        modelValue: [1],
        max: 1,
        skills: [
          { id: 1, name: 'Pet helper', description: null, system_prompt: 'Help', running: true, tools: [] },
          { id: 2, name: 'Order helper', description: null, system_prompt: 'Help', running: true, tools: [] },
        ],
      },
      global: { plugins: [i18n] },
    })
    await fireEvent.click(screen.getByRole('button', { name: 'Select candidate Skills' }))

    expect((screen.getByRole('checkbox', { name: 'Order helper' }) as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByRole('checkbox', { name: 'Order helper' }).closest('[role="option"]')?.getAttribute('aria-disabled')).toBe('true')
    expect((screen.getByRole('checkbox', { name: 'Pet helper' }) as HTMLInputElement).disabled).toBe(false)
  })
})
