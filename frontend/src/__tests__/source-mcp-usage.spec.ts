import { fireEvent, render, screen } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SourceMcpUsagePanel from '../components/SourceMcpUsagePanel.vue'
import { i18n } from '../i18n'

describe('SourceMcpUsagePanel', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en-US'
  })

  it('shows the shared MCP endpoint and only this source Tool parameters', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    render(SourceMcpUsagePanel, {
      props: {
        source: {
          id: 9,
          name: 'Projects',
          source_type: 'openapi',
          base_url: 'https://projects.example',
          document_url: null,
          allow_private_networks: false,
          auth_mode: 'none',
          enabled: true,
          created_at: '2026-07-23T00:00:00Z',
        },
        tools: [
          {
            id: 21,
            api_source_id: 9,
            operation_key: 'GET /projects',
            name: 'getProjectPage',
            description: 'List projects',
            input_schema: {
              type: 'object',
              properties: {
                page: { type: 'integer', description: 'Page number' },
                keyword: { type: 'string', description: 'Search keyword' },
              },
              required: ['page'],
            },
            execution_schema: {},
            tags: [],
            needs_schema_review: false,
            enabled: true,
          },
          {
            id: 22,
            api_source_id: 10,
            operation_key: 'GET /orders',
            name: 'getOrders',
            description: null,
            input_schema: {},
            execution_schema: {},
            tags: [],
            needs_schema_review: false,
            enabled: true,
          },
        ],
      },
      global: { plugins: [i18n] },
    })

    expect(screen.getByRole('heading', { name: 'MCP usage for Projects' })).toBeTruthy()
    expect(screen.getAllByText(/\/mcp\//).length).toBeGreaterThanOrEqual(1)
    expect((screen.getByTestId('mcp-tool-select') as HTMLSelectElement).value).toBe('21')
    expect(screen.getByRole('cell', { name: 'page' })).toBeTruthy()
    expect(screen.getByRole('cell', { name: 'Page number' })).toBeTruthy()
    expect(screen.queryByText('getOrders')).toBeNull()
    expect(screen.getByText(/client\.call_tool\("getProjectPage"/)).toBeTruthy()

    await fireEvent.click(screen.getAllByRole('button', { name: 'Copy' })[0])
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('streamable-http'))
    expect(await screen.findByRole('status')).toHaveProperty(
      'textContent',
      'MCP example copied.',
    )
  })
})
