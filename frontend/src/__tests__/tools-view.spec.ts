import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/vue'
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

function deferred<T>(): { promise: Promise<T>, resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

function apiSource(id = 1, name = 'Test API') {
  return {
    id,
    name,
    source_type: 'openapi',
    base_url: 'https://api.test',
    allow_private_networks: false,
    enabled: true,
    created_at: '2026-07-21T00:00:00',
  }
}

beforeEach(() => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.csrfToken = 'csrf-token'
  vi.stubGlobal('confirm', vi.fn(() => true))
})

describe('Tool administration views', () => {
  it('presents a prominent Tool description and parameter documentation', async () => {
    const tools = [
      {
        id: 1,
        api_source_id: 1,
        operation_key: 'GET /pets/{petId}',
        name: 'getPet',
        description: 'Get a pet',
        input_schema: {
          type: 'object',
          properties: {
            petId: { type: 'string', description: 'Unique pet identifier' },
            tenantId: { type: 'integer', format: 'int64', description: 'Tenant identifier' },
          },
          required: ['petId'],
        },
        execution_schema: {
          parameters: [
            { name: 'petId', in: 'path', required: true, argument: 'petId' },
            { name: 'tenant-id', in: 'header', required: false, argument: 'tenantId' },
          ],
        },
        tags: ['Pets', 'Public'],
        enabled: false,
      },
    ]
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    render(ToolsView, { global: { plugins: [i18n] } })

    expect(await screen.findByRole('heading', { name: 'Pets' })).toBeTruthy()
    expect(screen.getByText('Get a pet').classList.contains('tool-card-description')).toBe(true)
    expect(screen.queryByText('Public')).toBeNull()
    expect(screen.getByText('Unique pet identifier')).toBeTruthy()
    expect(screen.getByText('Tenant identifier')).toBeTruthy()
    expect(screen.getByText('Path')).toBeTruthy()
    expect(screen.getByText('Header')).toBeTruthy()
    expect(screen.getByText('Required')).toBeTruthy()
    expect(screen.getByText('Optional')).toBeTruthy()
  })

  it('shows the selected API source name above its Tools', async () => {
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
    expect(screen.queryByRole('heading', { name: 'Orders API' })).toBeNull()
    expect(screen.getByRole('option', { name: 'Orders API' })).toBeTruthy()
  })

  it('loads Tools only for the selected API source', async () => {
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
      { id: 2, name: 'Orders API', source_type: 'openapi', base_url: 'https://orders.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    const tools = {
      1: [{ id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Pets'], enabled: false }],
      2: [{ id: 2, api_source_id: 2, operation_key: 'GET /orders', name: 'listOrders', description: null, input_schema: {}, execution_schema: {}, tags: ['Orders'], enabled: false }],
    }
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse(sources))
      const selectedSourceId = Number(new URL(path, 'https://agent4api.test').searchParams.get('source_id'))
      return Promise.resolve(jsonResponse(tools[selectedSourceId as keyof typeof tools] ?? []))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })

    const sourceSelect = await screen.findByRole('combobox', { name: 'API source' })
    expect(await screen.findByText('listPets')).toBeTruthy()
    expect(screen.queryByText('listOrders')).toBeNull()
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/admin/tools?source_id=1')).toBe(true)

    await fireEvent.update(sourceSelect, '2')

    expect(await screen.findByText('listOrders')).toBeTruthy()
    expect(screen.queryByText('listPets')).toBeNull()
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/admin/tools?source_id=2')).toBe(true)
  })

  it('searches Tools by interface name or description', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: 'Browse the pet catalog', input_schema: {}, execution_schema: {}, tags: ['Pets'], enabled: false },
      { id: 2, api_source_id: 1, operation_key: 'GET /orders', name: 'listOrders', description: 'Find customer purchases', input_schema: {}, execution_schema: {}, tags: ['Orders'], enabled: false },
    ]
    const sources = [
      { id: 1, name: 'Commerce API', source_type: 'openapi', base_url: 'https://api.test', document_url: null, allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    render(ToolsView, { global: { plugins: [i18n] } })
    const search = await screen.findByLabelText('Search Tools')
    await fireEvent.update(search, 'CUSTOMER')
    expect(await screen.findByText('listOrders')).toBeTruthy()
    expect(screen.queryByText('listPets')).toBeNull()

    await fireEvent.update(search, 'listpets')
    expect(await screen.findByText('listPets')).toBeTruthy()
    expect(screen.queryByText('listOrders')).toBeNull()
  })

  it('quickly filters Tools whose parameter schemas need review', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'POST /pets', name: 'createPet', description: 'Create a pet', input_schema: {}, execution_schema: {}, tags: ['Pets'], needs_schema_review: true, enabled: false },
      { id: 2, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: 'List pets', input_schema: {}, execution_schema: {}, tags: ['Pets'], needs_schema_review: false, enabled: true },
    ]
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://api.test', document_url: null, allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    render(ToolsView, { global: { plugins: [i18n] } })
    await screen.findByText('createPet')
    await fireEvent.click(screen.getByRole('button', { name: 'Needs review' }))

    expect(screen.getByText('createPet')).toBeTruthy()
    expect(screen.queryByText('listPets')).toBeNull()
  })

  it('preserves Swagger tag groups inside each API source', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Pet operations', 'Public'], enabled: false },
      { id: 2, api_source_id: 1, operation_key: 'GET /orders', name: 'listOrders', description: null, input_schema: {}, execution_schema: {}, tags: ['Order operations'], enabled: false },
    ]
    const sources = [
      { id: 1, name: 'Commerce API', source_type: 'openapi', base_url: 'https://api.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    const { container } = render(ToolsView, { global: { plugins: [i18n] } })

    expect(await screen.findByRole('heading', { name: 'Pet operations' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Order operations' })).toBeTruthy()
    expect(container.querySelectorAll('details.tool-tag-group')).toHaveLength(2)
  })

  it('selects only visible Tools and keeps selection across search changes', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: 'Pet catalog', input_schema: {}, execution_schema: {}, tags: ['Pets'], enabled: true },
      { id: 2, api_source_id: 1, operation_key: 'GET /orders', name: 'listOrders', description: 'Order catalog', input_schema: {}, execution_schema: {}, tags: ['Orders'], enabled: false },
      { id: 3, api_source_id: 1, operation_key: 'GET /genes', name: 'listGenes', description: 'Gene catalog', input_schema: {}, execution_schema: {}, tags: ['Genes'], enabled: true },
    ]
    const sources = [
      { id: 1, name: 'Commerce API', source_type: 'openapi', base_url: 'https://commerce.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
      { id: 2, name: 'Gene API', source_type: 'openapi', base_url: 'https://genes.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    render(ToolsView, { global: { plugins: [i18n] } })
    await screen.findByText('listPets')
    const search = await screen.findByLabelText('Search Tools')
    await fireEvent.update(search, 'pet')
    await fireEvent.click(screen.getByRole('button', { name: 'Select visible' }))
    expect(screen.getByRole('checkbox', { name: 'Select listPets' })).toHaveProperty('checked', true)

    await fireEvent.update(search, 'order')
    await fireEvent.click(screen.getByRole('button', { name: 'Select visible' }))
    await fireEvent.update(search, '')
    await fireEvent.click(screen.getByRole('button', { name: 'Disabled' }))
    expect(screen.queryByRole('checkbox', { name: 'Select listPets' })).toBeNull()
    expect(screen.getByText('2 Tools selected')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Select visible' }))
    await fireEvent.click(screen.getByRole('button', { name: 'All' }))

    expect(screen.getByRole('checkbox', { name: 'Select listPets' })).toHaveProperty('checked', true)
    expect(screen.getByRole('checkbox', { name: 'Select listOrders' })).toHaveProperty('checked', true)
    expect(screen.getByRole('checkbox', { name: 'Select listGenes' })).toHaveProperty('checked', false)
    expect(screen.getByText('2 Tools selected')).toBeTruthy()
  })

  it('select visible excludes Tools hidden by a collapsed tag group', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Pets'], enabled: false },
      { id: 2, api_source_id: 1, operation_key: 'GET /orders', name: 'listOrders', description: null, input_schema: {}, execution_schema: {}, tags: ['Orders'], enabled: false },
      { id: 3, api_source_id: 1, operation_key: 'GET /private', name: 'listPrivateOrders', description: null, input_schema: {}, execution_schema: {}, tags: ['Private'], enabled: false },
    ]
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
      { id: 2, name: 'Orders API', source_type: 'openapi', base_url: 'https://orders.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    render(ToolsView, { global: { plugins: [i18n] } })
    await screen.findByRole('heading', { name: 'Pet API' })
    const privateTag = screen.getByRole('heading', { name: 'Private' }).closest('details') as HTMLDetailsElement
    await fireEvent.click(privateTag.querySelector(':scope > summary') as HTMLElement)
    expect(privateTag.open).toBe(false)

    await fireEvent.click(screen.getByRole('button', { name: 'Select visible' }))

    expect(screen.getByRole('checkbox', { name: 'Select listPets' })).toHaveProperty('checked', true)
    expect(screen.getByRole('checkbox', { name: 'Select listOrders' })).toHaveProperty('checked', true)
    expect(screen.getByRole('checkbox', { name: 'Select listPrivateOrders' })).toHaveProperty('checked', false)
    expect(screen.getByText('2 Tools selected')).toBeTruthy()
  })

  it('rejects selection above 200 without truncation', async () => {
    const tools = Array.from({ length: 201 }, (_, index) => ({
      id: index + 1,
      api_source_id: 1,
      operation_key: `GET /tools/${index + 1}`,
      name: index < 200 ? `allowedTool${index + 1}` : 'overflowTool',
      description: null,
      input_schema: {},
      execution_schema: {},
      tags: ['Catalog'],
      enabled: false,
    }))
    const sources = [
      { id: 1, name: 'Large API', source_type: 'openapi', base_url: 'https://large.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    const { container } = render(ToolsView, { global: { plugins: [i18n] } })
    await screen.findByText('overflowTool')
    const button = (label: string) => screen.getByText(label).closest('button') as HTMLButtonElement
    await fireEvent.click(button('Select visible'))

    expect(container.querySelector('[role="alert"]')?.textContent).toContain('You can select up to 200 Tools')
    expect(screen.getByText('0 Tools selected')).toBeTruthy()
  }, 15_000)

  it('selects and clears exactly 200 visible Tools', async () => {
    const tools = Array.from({ length: 200 }, (_, index) => ({
      id: index + 1,
      api_source_id: 1,
      operation_key: `GET /tools/${index + 1}`,
      name: `allowedTool${index + 1}`,
      description: null,
      input_schema: {},
      execution_schema: {},
      tags: ['Catalog'],
      enabled: false,
    }))
    const sources = [
      { id: 1, name: 'Large API', source_type: 'openapi', base_url: 'https://large.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    render(ToolsView, { global: { plugins: [i18n] } })
    await screen.findByText('allowedTool200')
    const button = (label: string) => screen.getByText(label).closest('button') as HTMLButtonElement
    await fireEvent.click(button('Select visible'))
    expect(screen.getByText('200 Tools selected')).toBeTruthy()

    await fireEvent.click(button('Clear selection'))
    expect(screen.getByText('0 Tools selected')).toBeTruthy()
  }, 15_000)

  it('reconciles partial bulk disable results with CSRF and localized safe errors', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: true },
      { id: 2, api_source_id: 1, operation_key: 'GET /orders', name: 'listOrders', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: true },
    ]
    const sources = [
      { id: 1, name: 'Commerce API', source_type: 'openapi', base_url: 'https://commerce.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse(sources))
      if (path.endsWith('/batch')) {
        return Promise.resolve(jsonResponse({
          request_count: 2,
          succeeded: [{ tool_id: 1, action: 'disable', status: 'disabled' }],
          failed: [{
            tool_id: 2,
            action: 'disable',
            code: 'tools.batch_item_failed',
            params: { internal: 'secret database detail' },
          }],
        }))
      }
      return Promise.resolve(jsonResponse(tools))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Select listPets' }))
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Select listOrders' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Disable selected' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const batchCall = fetchMock.mock.calls[2]
    expect(batchCall[0]).toBe('/api/admin/tools/batch')
    expect(JSON.parse((batchCall[1] as RequestInit).body as string)).toEqual({
      action: 'disable',
      tool_ids: [1, 2],
    })
    expect(((batchCall[1] as RequestInit).headers as Headers).get('X-CSRF-Token')).toBe('csrf-token')
    expect(await screen.findByText('Disabled 1 of 2 Tools. 1 failed.')).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: 'Select listPets' })).toHaveProperty('checked', false)
    expect(screen.getByRole('checkbox', { name: 'Select listOrders' })).toHaveProperty('checked', true)
    expect(within(screen.getByText('listPets').closest('article') as HTMLElement).getByText('Disabled')).toBeTruthy()
    expect(screen.getByText('listOrders: Unable to update this Tool. Try again.')).toBeTruthy()
    expect(document.body.textContent).not.toContain('secret database detail')
  })

  it('removes single-deleted Tools from bulk counts, confirmation, and request snapshots', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false },
      { id: 2, api_source_id: 1, operation_key: 'GET /genes', name: 'listGenes', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false },
    ]
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
      { id: 2, name: 'Gene API', source_type: 'openapi', base_url: 'https://genes.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse(sources))
      if (path.endsWith('/tools/1') && init?.method === 'DELETE') return Promise.resolve(jsonResponse(null))
      if (path.endsWith('/batch')) {
        return Promise.resolve(jsonResponse({
          request_count: 1,
          succeeded: [{ tool_id: 2, action: 'delete', status: 'deleted' }],
          failed: [],
        }))
      }
      return Promise.resolve(jsonResponse(tools))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Select listPets' }))
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Select listGenes' }))
    const petCard = screen.getByText('listPets').closest('article') as HTMLElement
    await fireEvent.click(within(petCard).getByRole('button', { name: 'Delete' }))
    const singleDeleteDialog = await screen.findByRole('dialog', { name: 'Delete Tool?' })
    await fireEvent.click(within(singleDeleteDialog).getByRole('button', { name: 'Delete Tool' }))

    await waitFor(() => expect(screen.queryByText('listPets')).toBeNull())
    expect(screen.getByText('1 Tools selected')).toBeTruthy()
    await fireEvent.click(screen.getByRole('button', { name: 'Delete selected' }))
    expect(screen.getByRole('dialog').textContent).toContain('Delete 1 Tools from 1 API sources?')
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm delete Tools' }))

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/batch'))).toHaveLength(1))
    const batchCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/batch'))
    expect(JSON.parse((batchCall?.[1] as RequestInit).body as string).tool_ids).toEqual([2])
  })

  it('requires confirmation before deleting a Tool referenced by a Skill', async () => {
    const tool = { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false }
    const source = { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' }
    const skill = { id: 5, name: 'Pet helper', description: null, system_prompt: 'Help', running: true, tools: [tool] }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse([source]))
      if (path.endsWith('/skills')) return Promise.resolve(jsonResponse([skill]))
      if (path.endsWith('/tools/1') && init?.method === 'DELETE') {
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(jsonResponse([tool]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    const deleteButton = within((await screen.findByText('listPets')).closest('article') as HTMLElement)
      .getByRole('button', { name: 'Delete' })
    await fireEvent.click(deleteButton)

    const cancelDialog = await screen.findByRole('dialog', { name: 'Delete Tool?' })
    expect(cancelDialog.textContent).toContain('Tool “listPets” is referenced by these Skills: Pet helper. Delete it anyway?')
    await fireEvent.click(within(cancelDialog).getByRole('button', { name: 'Cancel' }))
    expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).endsWith('/tools/1') && (init as RequestInit)?.method === 'DELETE'
    ))).toBe(false)

    await fireEvent.click(deleteButton)
    const confirmDialog = await screen.findByRole('dialog', { name: 'Delete Tool?' })
    await fireEvent.click(within(confirmDialog).getByRole('button', { name: 'Delete Tool' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => (
      String(url).endsWith('/tools/1') && (init as RequestInit)?.method === 'DELETE'
    ))).toBe(true))
  })

  it('confirms bulk delete with Tool and source counts while cancel sends no request', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false },
      { id: 2, api_source_id: 1, operation_key: 'GET /genes', name: 'listGenes', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false },
    ]
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
      { id: 2, name: 'Gene API', source_type: 'openapi', base_url: 'https://genes.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse(sources))
      if (path.endsWith('/batch')) {
        return Promise.resolve(jsonResponse({
          request_count: 2,
          succeeded: [
            { tool_id: 1, action: 'delete', status: 'deleted' },
            { tool_id: 2, action: 'delete', status: 'deleted' },
          ],
          failed: [],
        }))
      }
      return Promise.resolve(jsonResponse(tools))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Select listPets' }))
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Select listGenes' }))
    const deleteTrigger = screen.getByRole('button', { name: 'Delete selected' })
    await fireEvent.click(deleteTrigger)

    const dialog = screen.getByRole('dialog', { name: 'Delete selected Tools' })
    expect(dialog.textContent).toContain('Delete 2 Tools from 1 API sources?')
    const cancelButton = screen.getByRole('button', { name: 'Cancel bulk delete' })
    const confirmButton = screen.getByRole('button', { name: 'Confirm delete Tools' })
    expect(document.querySelector('main')?.hasAttribute('inert')).toBe(true)
    expect(document.activeElement).toBe(cancelButton)
    await fireEvent.keyDown(cancelButton, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(confirmButton)
    await fireEvent.keyDown(confirmButton, { key: 'Tab' })
    expect(document.activeElement).toBe(cancelButton)
    await fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Delete selected Tools' })).toBeNull()
    expect(document.activeElement).toBe(deleteTrigger)

    await fireEvent.click(screen.getByRole('button', { name: 'Delete selected' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Cancel bulk delete' }))
    expect(screen.queryByRole('dialog', { name: 'Delete selected Tools' })).toBeNull()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/batch'))).toHaveLength(0)

    await fireEvent.click(screen.getByRole('button', { name: 'Delete selected' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm delete Tools' }))

    expect(await screen.findByText('Deleted 2 of 2 Tools. 0 failed.')).toBeTruthy()
    expect(screen.queryByText('listPets')).toBeNull()
    expect(screen.queryByText('listGenes')).toBeNull()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/batch'))).toHaveLength(1)
  })

  it('keeps the native delete dialog modal and non-dismissible while confirmation is pending', async () => {
    const tool = { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false }
    const batch = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse([apiSource()]))
      if (path.endsWith('/batch')) return batch.promise
      if (path.endsWith('/tools/1') && init?.method === 'DELETE') return Promise.resolve(jsonResponse(null))
      return Promise.resolve(jsonResponse([tool]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Select listPets' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Delete selected' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete selected Tools' })
    const backgroundDelete = within(screen.getByText('listPets').closest('article') as HTMLElement)
      .getByRole('button', { name: 'Delete' })
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm delete Tools' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/batch'))).toHaveLength(1))

    expect(screen.getByRole('dialog', { name: 'Delete selected Tools' })).toBe(dialog)
    expect(screen.getByRole('button', { name: 'Cancel bulk delete' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Confirm delete Tools' })).toHaveProperty('disabled', true)
    expect(document.querySelector('main')?.hasAttribute('inert')).toBe(true)
    expect(backgroundDelete).toHaveProperty('disabled', true)
    await fireEvent.click(backgroundDelete)
    await fireEvent.keyDown(dialog, { key: 'Escape' })
    await fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(screen.getByRole('dialog', { name: 'Delete selected Tools' })).toBe(dialog)
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/tools/1'))).toHaveLength(0)

    batch.resolve(jsonResponse({
      request_count: 1,
      succeeded: [{ tool_id: 1, action: 'delete', status: 'deleted' }],
      failed: [],
    }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Delete selected Tools' })).toBeNull())
    expect(screen.queryByText('listPets')).toBeNull()
    expect(document.querySelector('main')?.hasAttribute('inert')).toBe(false)
  })

  it('locks the request snapshot while pending and preserves later unrelated selection', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false },
      { id: 2, api_source_id: 1, operation_key: 'GET /orders', name: 'listOrders', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false },
      { id: 3, api_source_id: 1, operation_key: 'GET /genes', name: 'listGenes', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false },
    ]
    const batch = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse([apiSource()]))
      if (path.endsWith('/batch')) return batch.promise
      return Promise.resolve(jsonResponse(tools))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Select listPets' }))
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Select listOrders' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Enable selected' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/batch'))).toHaveLength(1))

    expect(screen.getByRole('button', { name: 'Enable selected' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('checkbox', { name: 'Select listPets' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('checkbox', { name: 'Select listOrders' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('checkbox', { name: 'Select listGenes' })).toHaveProperty('disabled', false)
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Select listGenes' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Enable selected' }))
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/batch'))).toHaveLength(1)

    batch.resolve(jsonResponse({
      request_count: 2,
      succeeded: [{ tool_id: 1, action: 'enable', status: 'enabled' }],
      failed: [{ tool_id: 2, action: 'enable', code: 'tools.source_unavailable', params: { source_id: 1 } }],
    }))
    expect(await screen.findByText('Enabled 1 of 2 Tools. 1 failed.')).toBeTruthy()

    expect(screen.getByRole('checkbox', { name: 'Select listPets' })).toHaveProperty('checked', false)
    expect(screen.getByRole('checkbox', { name: 'Select listOrders' })).toHaveProperty('checked', true)
    expect(screen.getByRole('checkbox', { name: 'Select listGenes' })).toHaveProperty('checked', true)
    const batchCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/batch'))
    expect(JSON.parse((batchCall?.[1] as RequestInit).body as string).tool_ids).toEqual([1, 2])
  })

  it('blocks single-Tool mutations for pending batch IDs while unrelated Tools stay operable', async () => {
    const tools = [
      {
        id: 1,
        api_source_id: 1,
        operation_key: 'GET /pets/{petId}',
        name: 'getPet',
        description: 'Get a pet',
        input_schema: { type: 'object', properties: { petId: { type: 'string' } }, required: ['petId'] },
        execution_schema: { parameters: [{ name: 'petId', in: 'path', required: true, argument: 'petId' }] },
        tags: ['Catalog'],
        enabled: false,
      },
      { id: 2, api_source_id: 1, operation_key: 'GET /genes', name: 'listGenes', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: false },
    ]
    const batch = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse([apiSource()]))
      if (path.endsWith('/batch')) return batch.promise
      if (path.endsWith('/tools/2/enabled') && init?.method === 'PATCH') {
        return Promise.resolve(jsonResponse({ ...tools[1], enabled: true }))
      }
      return Promise.resolve(jsonResponse(tools))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Select getPet' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Enable selected' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/batch'))).toHaveLength(1))

    const petCard = screen.getByText('getPet').closest('article') as HTMLElement
    const geneCard = screen.getByText('listGenes').closest('article') as HTMLElement
    const pendingActions = [
      within(petCard).getByRole('button', { name: 'Edit description' }),
      within(petCard).getByRole('button', { name: 'Edit parameter' }),
      within(petCard).getByRole('button', { name: 'Enable' }),
      within(petCard).getByRole('button', { name: 'Delete' }),
    ]
    for (const action of pendingActions) {
      expect(action).toHaveProperty('disabled', true)
      await fireEvent.click(action)
    }
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/tools/1'))).toHaveLength(0)

    expect(within(geneCard).getByRole('button', { name: 'Edit description' })).toHaveProperty('disabled', false)
    expect(within(geneCard).getByRole('button', { name: 'Enable' })).toHaveProperty('disabled', false)
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Select listGenes' }))
    await fireEvent.click(within(geneCard).getByRole('button', { name: 'Enable' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/tools/2/enabled'))).toHaveLength(1))
    expect(screen.getByRole('checkbox', { name: 'Select listGenes' })).toHaveProperty('checked', true)
  })

  it('keeps the request selection retryable when the batch endpoint fails', async () => {
    const tool = { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: ['Catalog'], enabled: true }
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse([apiSource()]))
      if (path.endsWith('/batch')) {
        return Promise.resolve(jsonResponse({
          error: { code: 'tools.batch_item_failed', params: { internal: 'secret transaction detail' } },
        }, 500))
      }
      return Promise.resolve(jsonResponse([tool]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Select listPets' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Disable selected' }))

    expect(await screen.findByText('The bulk action could not be completed. Try again.')).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: 'Select listPets' })).toHaveProperty('checked', true)
    expect(screen.getByRole('button', { name: 'Disable selected' })).toHaveProperty('disabled', false)
    expect(document.body.textContent).not.toContain('secret transaction detail')
  })

  it('edits a Tool description', async () => {
    const tool = { id: 4, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: 'List pets', input_schema: {}, execution_schema: {}, tags: ['Pets'], enabled: false }
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://api.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse(sources))
      if (init?.method === 'PATCH') return Promise.resolve(jsonResponse({ ...tool, description: 'Search all pets' }))
      return Promise.resolve(jsonResponse([tool]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit description' }))
    await fireEvent.update(screen.getByLabelText('Tool description'), 'Search all pets')
    await fireEvent.click(screen.getByRole('button', { name: 'Save description' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(fetchMock.mock.calls[2][0]).toBe('/api/admin/tools/4')
    expect(JSON.parse((fetchMock.mock.calls[2][1] as RequestInit).body as string)).toEqual({ description: 'Search all pets' })
    expect(await screen.findByText('Search all pets')).toBeTruthy()
  })

  it('edits parameter guidance while keeping Swagger structure read-only', async () => {
    const tool = {
      id: 8,
      api_source_id: 1,
      operation_key: 'GET /genes/{geneSymbol}',
      name: 'getGene',
      description: 'Get a gene',
      input_schema: {
        type: 'object',
        properties: {
          geneSymbol: {
            type: 'string',
            description: 'Swagger gene symbol',
            example: 'BRCA1',
          },
        },
        required: ['geneSymbol'],
      },
      execution_schema: {
        parameters: [
          { name: 'geneSymbol', in: 'path', required: true, argument: 'geneSymbol' },
        ],
      },
      tags: ['Genes'],
      enabled: true,
    }
    const sources = [
      { id: 1, name: 'Gene API', source_type: 'openapi', base_url: 'https://api.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse(sources))
      if (init?.method === 'PUT') {
        return Promise.resolve(jsonResponse({
          ...tool,
          input_schema: {
            ...tool.input_schema,
            properties: {
              geneSymbol: {
                type: 'string',
                description: 'HGNC gene symbol',
                example: 'ABCA4',
              },
            },
          },
        }))
      }
      return Promise.resolve(jsonResponse([tool]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    const parameterName = await screen.findByText('geneSymbol')
    const parameterRow = parameterName.closest('.parameter-row') as HTMLElement
    const structuralFields = parameterRow.querySelector('.parameter-heading') as HTMLElement
    expect(structuralFields.textContent).toContain('Path')
    expect(structuralFields.textContent).toContain('string')
    expect(structuralFields.textContent).toContain('Required')
    expect(structuralFields.querySelector('input, textarea, select')).toBeNull()
    expect(screen.getByText('Swagger gene symbol')).toBeTruthy()
    expect(screen.getByText('BRCA1')).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: 'Edit parameter' }))
    await fireEvent.update(screen.getByLabelText('Parameter description'), 'HGNC gene symbol')
    await fireEvent.update(screen.getByLabelText('Example (JSON or text)'), '"ABCA4"')
    await fireEvent.click(screen.getByRole('button', { name: 'Save parameter' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const overrideCall = fetchMock.mock.calls.find(([input]) => String(input).includes('/parameters/'))
    expect(overrideCall?.[0]).toBe('/api/admin/tools/8/parameters/geneSymbol')
    expect(overrideCall?.[1]).toEqual(expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ description: 'HGNC gene symbol', example: 'ABCA4' }),
    }))
    expect(await screen.findByText('HGNC gene symbol')).toBeTruthy()
    expect(screen.getByText('ABCA4')).toBeTruthy()
    expect(screen.getByText('Parameter guidance saved.')).toBeTruthy()
  })

  it.each([
    ['numeric-looking string', '123', '"123"'],
    ['boolean-looking string', 'true', '"true"'],
    ['null-looking string', 'null', '"null"'],
    ['object-looking string', '{"key":"value"}', '"{\\"key\\":\\"value\\"}"'],
    ['number', 123, '123'],
    ['boolean', true, 'true'],
    ['object', { key: 'value' }, '{"key":"value"}'],
    ['array', [1, true], '[1,true]'],
  ])('preserves an unchanged Swagger %s example', async (_label, example, expectedDraft) => {
    const tool = {
      id: 8,
      api_source_id: 1,
      operation_key: 'GET /genes',
      name: 'getGene',
      description: 'Get a gene',
      input_schema: {
        type: 'object',
        properties: {
          exampleValue: { type: 'string', example },
        },
      },
      execution_schema: {},
      tags: ['Genes'],
      enabled: true,
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/sources')) return Promise.resolve(jsonResponse([apiSource()]))
      if (init?.method === 'PUT') return Promise.resolve(jsonResponse(tool))
      return Promise.resolve(jsonResponse([tool]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit parameter' }))
    const exampleInput = screen.getByLabelText('Example (JSON or text)') as HTMLTextAreaElement
    expect(exampleInput.value).toBe(expectedDraft)
    await fireEvent.click(screen.getByRole('button', { name: 'Save parameter' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const overrideCall = fetchMock.mock.calls.find(([input]) => String(input).includes('/parameters/'))
    expect(JSON.parse((overrideCall?.[1] as RequestInit).body as string)).toEqual({
      description: null,
      example,
    })
  })

  it('clears overrides to restore Swagger guidance', async () => {
    const tool = {
      id: 8,
      api_source_id: 1,
      operation_key: 'GET /genes/{geneSymbol}',
      name: 'getGene',
      description: 'Get a gene',
      input_schema: {
        type: 'object',
        properties: {
          geneSymbol: {
            type: 'string',
            description: 'HGNC gene symbol',
            example: 'ABCA4',
          },
        },
        required: ['geneSymbol'],
      },
      execution_schema: { parameters: [{ in: 'path', argument: 'geneSymbol' }] },
      tags: ['Genes'],
      enabled: true,
    }
    const swaggerTool = {
      ...tool,
      input_schema: {
        ...tool.input_schema,
        properties: {
          geneSymbol: {
            type: 'string',
            description: 'Swagger gene symbol',
            example: 'BRCA1',
          },
        },
      },
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse([apiSource()]))
      if (init?.method === 'PUT') return Promise.resolve(jsonResponse(swaggerTool))
      return Promise.resolve(jsonResponse([tool]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit parameter' }))
    await fireEvent.update(screen.getByLabelText('Parameter description'), '')
    await fireEvent.update(screen.getByLabelText('Example (JSON or text)'), '')
    await fireEvent.click(screen.getByRole('button', { name: 'Save parameter' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const overrideCall = fetchMock.mock.calls.find(([input]) => String(input).includes('/parameters/'))
    expect(JSON.parse((overrideCall?.[1] as RequestInit).body as string)).toEqual({
      description: null,
      example: null,
    })
    expect(await screen.findByText('Swagger gene symbol')).toBeTruthy()
    expect(screen.getByText('BRCA1')).toBeTruthy()
  })

  it('keeps the parameter editor open and reports save errors', async () => {
    const tool = {
      id: 8,
      api_source_id: 1,
      operation_key: 'GET /genes',
      name: 'getGene',
      description: null,
      input_schema: {
        type: 'object',
        properties: { geneSymbol: { type: 'string' } },
      },
      execution_schema: {},
      tags: ['Genes'],
      enabled: true,
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/sources')) return Promise.resolve(jsonResponse([apiSource()]))
      if (init?.method === 'PUT') {
        return Promise.resolve(jsonResponse({ error: { code: 'unknown', params: {} } }, 500))
      }
      return Promise.resolve(jsonResponse([tool]))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(ToolsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit parameter' }))
    await fireEvent.update(screen.getByLabelText('Parameter description'), 'HGNC gene symbol')
    await fireEvent.click(screen.getByRole('button', { name: 'Save parameter' }))

    expect(await screen.findByText('Unable to save parameter guidance. Try again.')).toBeTruthy()
    expect((screen.getByLabelText('Parameter description') as HTMLTextAreaElement).value).toBe('HGNC gene symbol')
  })

  it('allows each API source group to collapse and expand', async () => {
    const tools = [
      { id: 1, api_source_id: 1, operation_key: 'GET /pets', name: 'listPets', description: null, input_schema: {}, execution_schema: {}, tags: [], enabled: false },
    ]
    const sources = [
      { id: 1, name: 'Pet API', source_type: 'openapi', base_url: 'https://pets.test', allow_private_networks: false, enabled: true, created_at: '2026-07-21T00:00:00' },
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).endsWith('/sources') ? sources : tools),
    )))

    const { container } = render(ToolsView, { global: { plugins: [i18n] } })
    await screen.findByRole('heading', { name: 'Pet API' })
    const group = container.querySelector('details.tool-source-group') as HTMLDetailsElement

    expect(group.open).toBe(true)
    await fireEvent.click(group.querySelector('summary') as HTMLElement)
    expect(group.open).toBe(false)
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
    const deleteDialog = screen.getByRole('dialog', { name: 'Delete source?' })
    expect(deleteDialog.textContent).toContain(
      'Delete source “Pet API v2”? All Tools in this source will be deleted and Skills that reference them may be affected.',
    )
    await fireEvent.click(within(deleteDialog).getByRole('button', { name: 'Delete source' }))
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

  it('refreshes a URL-based API source manually', async () => {
    const source = {
      id: 3,
      name: 'Remote API',
      source_type: 'openapi',
      base_url: 'http://localhost:48080',
      document_url: 'http://localhost:48080/v2/api-docs',
      allow_private_networks: true,
      enabled: true,
      created_at: '2026-07-21T00:00:00',
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([source]))
      .mockResolvedValueOnce(jsonResponse({ created: 1, updated: 2, unchanged: 5 }))
    vi.stubGlobal('fetch', fetchMock)

    render(ApiSourcesView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Update' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/sources/3/refresh')
    expect(await screen.findByText('1 added, 2 updated, 5 unchanged')).toBeTruthy()
  })

  it('refreshes a file-based API source with a new document', async () => {
    const source = {
      id: 4,
      name: 'Uploaded API',
      source_type: 'openapi',
      base_url: 'https://api.test',
      document_url: null,
      allow_private_networks: false,
      enabled: true,
      created_at: '2026-07-21T00:00:00',
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([source]))
      .mockResolvedValueOnce(jsonResponse({ created: 0, updated: 1, unchanged: 2 }))
    vi.stubGlobal('fetch', fetchMock)

    render(ApiSourcesView, { global: { plugins: [i18n] } })
    const input = await screen.findByLabelText('Choose update file')
    const file = new File(['openapi: 3.0.3'], 'openapi.yaml')
    await fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/sources/4/refresh-file')
    expect((fetchMock.mock.calls[1][1] as RequestInit).body).toBeInstanceOf(FormData)
  })

  it('lists default-disabled Tools and enables one', async () => {
    const tool = {
      id: 4,
      api_source_id: 1,
      operation_key: 'GET /pets',
      name: 'listPets',
      description: 'List pets',
      input_schema: { type: 'object' },
      enabled: false,
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/sources')) return Promise.resolve(jsonResponse([apiSource(1, 'Pet API')]))
      if (path.endsWith('/tools/4/enabled') && init?.method === 'PATCH') {
        return Promise.resolve(jsonResponse({ ...tool, enabled: true }))
      }
      return Promise.resolve(jsonResponse([tool]))
    })
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
    await fireEvent.click(screen.getByRole('button', { name: 'File upload' }))
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
    expect(
      screen.getByRole('button', { name: 'URL import' }).classList.contains('active'),
    ).toBe(true)
    expect(screen.getByLabelText('OpenAPI URL')).toBeTruthy()
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

  it('alerts with the backend reason when an OpenAPI import fails', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({
        error: {
          code: 'tools.openapi_invalid',
          params: { reason: 'Parameter file must define schema or content' },
        },
      }, 422))
    const alertMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('alert', alertMock)

    render(ApiSourcesView, { global: { plugins: [i18n] } })
    await screen.findByText('No API sources imported yet.')
    await fireEvent.update(screen.getByLabelText('Source name'), 'Broken API')
    await fireEvent.update(screen.getByLabelText('OpenAPI URL'), 'https://api.test/openapi.json')
    await fireEvent.click(screen.getByRole('button', { name: 'Import from URL' }))

    await waitFor(() => expect(alertMock).toHaveBeenCalledWith(
      'Import failed: Parameter file must define schema or content',
    ))
  })
})
