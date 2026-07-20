import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/tools/4/enabled')
    expect((fetchMock.mock.calls[1][1] as RequestInit).headers).toEqual(
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
})
