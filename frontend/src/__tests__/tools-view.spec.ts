import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import ApiSourcesView from '../views/ApiSourcesView.vue'
import ToolsView from '../views/ToolsView.vue'

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.csrfToken = 'csrf-token'
})

describe('Tool administration views', () => {
  it('groups Tools by API source name', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, enabled: false },
      { id: 2, api_source_id: 2, operation_key: 'GET /orders', name: 'listOrders', description: null, input_schema: {}, enabled: false },
    ]
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
      { id: 2, name: 'Orders API', source_type: 'openapi', base_url: 'https://orders.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      return Promise.resolve(jsonResponse(path.endsWith('/sources') ? sources : tools))
    }))

    render(ToolsView, { global: { plugins: [i18n] } })

    expect(await screen.findByRole('heading', { name: 'Pet API' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Orders API' })).toBeTruthy()
  })

  it('jumps from an API source to its Tools', async () => {
    const source = {
      id: 7,
      name: 'Pet API',
      source_type: 'openapi',
      base_url: 'https://api.test',
      allow_private_networks: false,
      enabled: true,
      created_at: '2026-07-21T00:00:00',
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([source])))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/admin/sources', component: ApiSourcesView },
        { path: '/admin/tools', name: 'tools', component: ToolsView },
      ],
    })
    await router.push('/admin/sources')
    await router.isReady()

    render(ApiSourcesView, { global: { plugins: [i18n, router] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'View Tools' }))

    await waitFor(() => expect(router.currentRoute.value.name).toBe('tools'))
    expect(router.currentRoute.value.query).toEqual({
      source_id: '7',
      source_name: 'Pet API',
    })
  })

  it('shows only Tools from the API source in the route query', async () => {
    const tools = [
      {
        id: 1,
        api_source_id: 1,
        operation_key: 'GET /pets',
        name: 'listPets',
        description: null,
        input_schema: {},
        enabled: false,
      },
      {
        id: 2,
        api_source_id: 2,
        operation_key: 'GET /orders',
        name: 'listOrders',
        description: null,
        input_schema: {},
        enabled: false,
      },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => Promise.resolve(
        jsonResponse(String(input).endsWith('/sources') ? [] : tools),
      )),
    )
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/admin/tools', name: 'tools', component: ToolsView }],
    })
    await router.push('/admin/tools?source_id=2&source_name=Orders%20API')
    await router.isReady()

    render(ToolsView, { global: { plugins: [i18n, router] } })

    expect(await screen.findByText('listOrders')).toBeTruthy()
    expect(screen.queryByText('listPets')).toBeNull()
  })

  it('edits and deletes an API source', async () => {
    const source = {
      id: 1,
      name: 'Pet API',
      source_type: 'openapi',
      base_url: 'https://api.test',
      allow_private_networks: false,
      enabled: true,
      created_at: '2026-07-21T00:00:00',
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([source]))
      .mockResolvedValueOnce(jsonResponse({ ...source, name: 'Pet API v2', base_url: 'https://v2.api.test' }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    render(ApiSourcesView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await fireEvent.update(screen.getByLabelText('Edit source name'), 'Pet API v2')
    await fireEvent.update(screen.getByLabelText('Edit base URL'), 'https://v2.api.test')
    await fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/sources/1')
    await screen.findByText('Pet API v2')
    await fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(fetchMock.mock.calls[2][0]).toBe('/api/admin/sources/1')
    await waitFor(() => expect(screen.queryByText('Pet API v2')).toBeNull())
  })

  it('disables an enabled API source', async () => {
    const source = {
      id: 2,
      name: 'Orders API',
      source_type: 'openapi',
      base_url: 'https://orders.test',
      allow_private_networks: false,
      enabled: true,
      created_at: '2026-07-21T00:00:00',
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([source]))
      .mockResolvedValueOnce(jsonResponse({ ...source, enabled: false }))
    vi.stubGlobal('fetch', fetchMock)

    render(ApiSourcesView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Disable' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/sources/2/enabled')
    expect(await screen.findByText('Disabled')).toBeTruthy()
  })

  it('lists default-disabled Tools and enables one', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: 4,
            api_source_id: 1,
            operation_key: 'GET /pets',
            name: 'listPets',
            description: 'List pets',
            input_schema: { type: 'object' },
            enabled: false,
          },
        ]),
      )
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: 1,
            name: 'Pet API',
            source_type: 'openapi',
            base_url: 'https://api.test',
            allow_private_networks: false,
            enabled: true,
            created_at: '2026-07-21T00:00:00',
          },
        ]),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: 4,
          api_source_id: 1,
          operation_key: 'GET /pets',
          name: 'listPets',
          description: 'List pets',
          input_schema: { type: 'object' },
          enabled: true,
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    expect(await screen.findByText('listPets')).toBeTruthy()
    expect(screen.getAllByText('Disabled')).toHaveLength(2)
    await fireEvent.click(screen.getByRole('button', { name: 'Enable' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(fetchMock.mock.calls[2][0]).toBe('/api/admin/tools/4/enabled')
    expect((fetchMock.mock.calls[2][1] as RequestInit).headers).toEqual(
      expect.objectContaining({}),
    )
  })

  it('uploads an OpenAPI JSON or YAML document as multipart data', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          source: {
            id: 1,
            name: 'Pet API',
            source_type: 'openapi',
            base_url: 'https://api.test',
            allow_private_networks: false,
            enabled: true,
            created_at: '2026-07-21T00:00:00',
          },
          tools: [],
        }, 201),
      )
      .mockResolvedValueOnce(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    const { container } = render(ApiSourcesView, { global: { plugins: [i18n] } })
    await screen.findByText('No API sources imported yet.')
    await fireEvent.update(screen.getByLabelText('Source name'), 'Pet API')
    const file = new File(['openapi: 3.0.3'], 'openapi.yaml', { type: 'application/yaml' })
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await fireEvent.change(input, { target: { files: [file] } })
    await fireEvent.click(screen.getByRole('button', { name: 'Import source' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const request = fetchMock.mock.calls[1][1] as RequestInit
    expect(request.body).toBeInstanceOf(FormData)
  })

  it('imports an OpenAPI document from a URL', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          source: {
            id: 2,
            name: 'Remote API',
            source_type: 'openapi',
            base_url: 'https://api.test',
            allow_private_networks: true,
            enabled: true,
            created_at: '2026-07-21T00:00:00',
          },
          tools: [],
        }, 201),
      )
      .mockResolvedValueOnce(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    render(ApiSourcesView, { global: { plugins: [i18n] } })
    await screen.findByText('No API sources imported yet.')
    await fireEvent.click(screen.getByRole('button', { name: 'URL import' }))
    await fireEvent.update(screen.getByLabelText('Source name'), 'Remote API')
    await fireEvent.update(screen.getByLabelText('OpenAPI URL'), 'https://api.test/openapi.json')
    await fireEvent.click(screen.getByLabelText('Allow private network targets'))
    await fireEvent.click(screen.getByRole('button', { name: 'Import from URL' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/sources/import-url')
    const request = fetchMock.mock.calls[1][1] as RequestInit
    expect(JSON.parse(request.body as string)).toEqual({
      name: 'Remote API',
      url: 'https://api.test/openapi.json',
      base_url: null,
      allow_private_networks: true,
    })
  })
})
