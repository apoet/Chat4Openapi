import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiSourceSummary, SkillSummary, ToolSummary } from '../api/contracts'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import SkillsView from '../views/SkillsView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function source(id: number, name: string): ApiSourceSummary {
  return {
    id,
    name,
    source_type: 'openapi',
    base_url: `https://${name.toLocaleLowerCase().replaceAll(' ', '-')}.test`,
    document_url: null,
    allow_private_networks: false,
    enabled: true,
    created_at: '2026-07-22T00:00:00',
  }
}

function tool(
  id: number,
  overrides: Partial<ToolSummary> = {},
): ToolSummary {
  return {
    id,
    api_source_id: 1,
    operation_key: `GET /generic/${id}`,
    name: `generic_tool_${id}`,
    description: `Generic description ${id}`,
    input_schema: {},
    execution_schema: {},
    tags: ['General'],
    enabled: true,
    ...overrides,
  }
}

function skill(id: number, tools: ToolSummary[]): SkillSummary {
  return {
    id,
    name: 'Catalog skill',
    description: 'Catalog regression fixture',
    system_prompt: 'Use catalog Tools.',
    running: false,
    tools,
  }
}

function catalogFetch(
  tools: ToolSummary[],
  sources: ApiSourceSummary[],
  skills: SkillSummary[] = [],
) {
  return vi.fn((input: RequestInfo | URL) => {
    if (input === '/api/admin/tools') {
      return Promise.resolve(response(tools))
    }
    if (input === '/api/admin/sources') return Promise.resolve(response(sources))
    if (input === '/api/admin/skills') return Promise.resolve(response(skills))
    return Promise.resolve(response([]))
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf'
  localStorage.clear()
})

describe('scalable Skill Tool catalog', () => {
  it('searches 1,001 Tools completely by name, description, path, tag, and source before limiting rows', async () => {
    const tools = Array.from({ length: 1000 }, (_, index) => tool(index + 1))
    tools.push(tool(1001, {
      api_source_id: 2,
      operation_key: 'POST /genes/{symbol}',
      name: 'gene_lookup',
      description: 'Resolve an HGNC symbol',
      tags: ['Genomics'],
    }))
    vi.stubGlobal('fetch', catalogFetch(tools, [source(1, 'Generic API'), source(2, 'Varcards')]))

    render(SkillsView, { global: { plugins: [i18n] } })
    const search = await screen.findByRole('searchbox', { name: 'Search Tool catalog' })

    for (const query of ['gene_lookup', 'HGNC symbol', '/genes/{symbol}', 'Genomics', 'Varcards']) {
      await fireEvent.update(search, query)
      expect(await screen.findByText('gene_lookup')).toBeTruthy()
      expect(screen.queryByText('generic_tool_1')).toBeNull()
    }

    await fireEvent.update(search, '')
    await waitFor(() => expect(screen.getAllByTestId('catalog-tool-row').length).toBeLessThanOrEqual(100))
    expect(screen.getByText('Showing 100 of 1001 Tools')).toBeTruthy()
  })

  it('filters and collapses dense source/tag groups while keeping a disabled binding removable', async () => {
    const enabled = tool(1, {
      operation_key: 'GET /pets/{id}',
      name: 'get_pet',
      tags: ['Pets', 'Public'],
    })
    const disabled = tool(2, {
      api_source_id: 2,
      operation_key: 'DELETE /orders/{id}',
      name: 'delete_order',
      tags: ['Orders'],
      enabled: false,
    })
    vi.stubGlobal('fetch', catalogFetch(
      [enabled, disabled],
      [source(1, 'Pet API'), source(2, 'Order API')],
      [skill(7, [disabled])],
    ))

    const { container } = render(SkillsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))

    const disabledRow = screen.getByTestId('catalog-tool-2')
    expect(within(disabledRow).getByText('DELETE')).toBeTruthy()
    expect(within(disabledRow).getByText('/orders/{id}')).toBeTruthy()
    expect(within(disabledRow).getByText('Order API')).toBeTruthy()
    expect(within(disabledRow).getByText('Orders')).toBeTruthy()
    expect(within(disabledRow).getByText('Disabled')).toBeTruthy()
    const disabledBinding = within(disabledRow).getByRole('checkbox', { name: 'Bind delete_order' }) as HTMLInputElement
    expect(disabledBinding.checked).toBe(true)
    expect(disabledBinding.disabled).toBe(false)
    await fireEvent.click(disabledBinding)
    expect(screen.getByText('0 Tools bound')).toBeTruthy()
    expect(disabledBinding.disabled).toBe(true)

    await fireEvent.update(screen.getByRole('combobox', { name: 'Enabled state' }), 'enabled')
    expect(screen.queryByText('delete_order')).toBeNull()
    expect(screen.getByText('get_pet')).toBeTruthy()
    await fireEvent.update(screen.getByRole('combobox', { name: 'Enabled state' }), 'all')
    await fireEvent.update(screen.getByRole('combobox', { name: 'Swagger tag' }), 'Orders')
    expect(await screen.findByText('delete_order')).toBeTruthy()
    expect(screen.queryByText('get_pet')).toBeNull()
    await fireEvent.update(screen.getByRole('combobox', { name: 'Swagger tag' }), 'all')
    await fireEvent.update(screen.getByRole('combobox', { name: 'API source' }), '2')
    expect(await screen.findByText('delete_order')).toBeTruthy()
    expect(screen.queryByText('get_pet')).toBeNull()

    const sourceGroup = container.querySelector<HTMLDetailsElement>('details.catalog-source-group')
    expect(sourceGroup?.open).toBe(true)
    const tagGroup = sourceGroup?.querySelector<HTMLDetailsElement>('details.catalog-tag-group')
    expect(tagGroup?.open).toBe(true)
    await fireEvent.click(within(tagGroup as HTMLElement).getByRole('heading', { name: 'Orders' }))
    expect(tagGroup?.open).toBe(false)
    await fireEvent.click(within(sourceGroup as HTMLElement).getByRole('heading', { name: 'Order API' }))
    expect(sourceGroup?.open).toBe(false)
  })

  it('keeps an existing disabled binding visible beyond the ordinary row limit', async () => {
    const tools = Array.from({ length: 149 }, (_, index) => tool(index + 1))
    const disabled = tool(150, { name: 'legacy_disabled_binding', enabled: false })
    tools.push(disabled)
    vi.stubGlobal('fetch', catalogFetch(tools, [source(1, 'Legacy API')], [skill(9, [disabled])]))

    render(SkillsView, { global: { plugins: [i18n] } })
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))

    const checkbox = screen.getByRole('checkbox', { name: 'Bind legacy_disabled_binding' }) as HTMLInputElement
    expect(checkbox.checked).toBe(true)
    expect(checkbox.disabled).toBe(false)
  })

  it('uses the catalog search for categorized enabled-only mentions and keyboard insertion', async () => {
    const first = tool(1, { name: 'gene_lookup', tags: ['Genomics'], api_source_id: 2 })
    const second = tool(2, { name: 'gene_summary', tags: ['Genomics'], api_source_id: 2 })
    const disabled = tool(3, { name: 'gene_delete', tags: ['Genomics'], api_source_id: 2, enabled: false })
    vi.stubGlobal('fetch', catalogFetch(
      [first, second, disabled],
      [source(2, 'Varcards')],
    ))

    render(SkillsView, { global: { plugins: [i18n] } })
    const prompt = await screen.findByLabelText('System prompt') as HTMLTextAreaElement
    await fireEvent.update(prompt, 'Use @Genomics')
    const menu = await screen.findByRole('listbox', { name: 'Tool reference suggestions' })
    expect(within(menu).getByText('Varcards / Genomics')).toBeTruthy()
    expect(within(menu).queryByText('gene_delete')).toBeNull()

    await fireEvent.keyDown(prompt, { key: 'ArrowDown' })
    await fireEvent.keyDown(prompt, { key: 'ArrowUp' })
    await fireEvent.keyDown(prompt, { key: 'ArrowDown' })
    await fireEvent.keyDown(prompt, { key: 'Enter' })
    expect(prompt.value).toBe('Use {{tool:gene_summary}}')
    expect(screen.getByText('1 Tool bound')).toBeTruthy()

    await fireEvent.update(prompt, `${prompt.value} @gene`)
    expect(await screen.findByRole('listbox', { name: 'Tool reference suggestions' })).toBeTruthy()
    await fireEvent.keyDown(prompt, { key: 'Escape' })
    expect(screen.queryByRole('listbox', { name: 'Tool reference suggestions' })).toBeNull()
  })

  it('restores a bounded panel height and persists keyboard resizing', async () => {
    localStorage.setItem('chat4openapi.skill-tool-catalog-height', '780')
    vi.stubGlobal('fetch', catalogFetch([], []))

    render(SkillsView, { global: { plugins: [i18n] } })
    const panel = await screen.findByRole('region', { name: 'Tool catalog' })
    expect(panel.getAttribute('style')).toContain('height: 780px')
    await fireEvent.keyDown(screen.getByRole('separator', { name: 'Resize Tool catalog' }), { key: 'ArrowUp' })
    expect(panel.getAttribute('style')).toContain('height: 820px')
    expect(localStorage.getItem('chat4openapi.skill-tool-catalog-height')).toBe('820')
  })

  it('keeps editing usable when localStorage reads and writes fail', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    vi.stubGlobal('fetch', catalogFetch([], []))

    render(SkillsView, { global: { plugins: [i18n] } })
    const panel = await screen.findByRole('region', { name: 'Tool catalog' })
    await fireEvent.keyDown(screen.getByRole('separator', { name: 'Resize Tool catalog' }), { key: 'ArrowDown' })
    expect(panel.getAttribute('style')).toContain('height: 640px')
    await fireEvent.update(screen.getByLabelText('Skill name'), 'Still editable')
    expect((screen.getByLabelText('Skill name') as HTMLInputElement).value).toBe('Still editable')
  })
})
