import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf'
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

  it('quick-references only enabled Tools and inserts a stable prompt token', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          response([
            {
              id: 1,
              name: 'Primary',
              provider_type: 'openai',
              base_url: 'https://llm.test/v1',
              default_model: 'gpt-test',
              enabled: true,
              has_api_key: true,
            },
          ]),
        )
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
      .mockResolvedValueOnce(response([{ id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true }]))
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
      .mockResolvedValueOnce(response([{ id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true }]))
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
      .mockResolvedValueOnce(response([{ id: 1, name: 'Primary', provider_type: 'openai', base_url: 'https://llm.test/v1', default_model: 'gpt-test', enabled: true, has_api_key: true }]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response([{ id: 5, name: 'Pet helper', description: null, system_prompt: 'Help', provider_id: 1, model: null, running: false, tools: [] }]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(response([]))
    vi.stubGlobal('fetch', fetchMock)

    render(SkillsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6))
    expect(fetchMock.mock.calls[4][0]).toBe('/api/admin/skills/5')
  })

  it('places the running Skill selector below the input and renders a reply', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ enabled: false }))
      .mockResolvedValueOnce(
        response([
          {
            id: 5,
            name: 'Pet helper',
            description: null,
            system_prompt: 'Help',
            provider_id: 1,
            model: null,
            running: true,
            tools: [],
          },
        ]),
      )
      .mockResolvedValueOnce(
        response({
          choices: [{ message: { role: 'assistant', content: 'Milo is ready.' } }],
          chatapi_conversation_id: 'conversation-1',
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    const { container } = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    const input = await screen.findByLabelText('Message')
    const selector = screen.getByLabelText('Skill')
    await screen.findByRole('option', { name: 'Pet helper' })
    expect(
      input.compareDocumentPosition(selector) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    await fireEvent.update(selector, '5')
    await fireEvent.update(input, 'Find Milo')
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(await screen.findByText('Milo is ready.')).toBeTruthy()
    expect(container.querySelector('.skill-dock')).toBeTruthy()
  })
})
