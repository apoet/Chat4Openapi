// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { discoverWebMcpTools, executeWebMcpTool } from '../embed/webmcp'

type RegisteredTool = {
  name: string
  description: string
  inputSchema: string
}

function installContext(options: {
  tools?: RegisteredTool[]
  execute?: (name: string, args: unknown) => unknown | Promise<unknown>
  discoveryOnly?: boolean
}) {
  const getTools = vi.fn(async () => options.tools ?? [])
  const executeTool = options.discoveryOnly
    ? undefined
    : vi.fn(async (name: string, args: unknown) => options.execute?.(name, args))
  Object.defineProperty(document, 'modelContext', {
    configurable: true,
    value: { getTools, executeTool },
  })
  return { getTools, executeTool }
}

beforeEach(() => {
  Object.defineProperty(document, 'modelContext', {
    configurable: true,
    value: undefined,
  })
})

describe('WebMCP bridge', () => {
  it('silently returns no tools without both WebMCP capabilities', async () => {
    expect(await discoverWebMcpTools('https://host.example')).toEqual([])
    installContext({ discoveryOnly: true })
    expect(await discoverWebMcpTools('https://host.example')).toEqual([])
  })

  it('maps only valid host tools into the reserved web namespace', async () => {
    const context = installContext({
      tools: [
        {
          name: 'select-row',
          description: 'Select a row',
          inputSchema: '{"type":"object","properties":{"id":{"type":"string"}}}',
        },
        { name: 'bad name', description: 'Invalid name', inputSchema: '{"type":"object"}' },
        { name: 'broken', description: 'Broken schema', inputSchema: '{' },
      ],
    })

    const tools = await discoverWebMcpTools('https://host.example')

    expect(tools).toEqual([
      {
        name: 'web__select-row',
        description: 'Select a row',
        parameters: {
          type: 'object',
          properties: { id: { type: 'string' } },
        },
      },
    ])
    expect(context.getTools).toHaveBeenCalledWith({
      fromOrigins: ['https://host.example'],
    })
  })

  it('executes the original registered name and serializes results', async () => {
    const release: Array<() => void> = []
    let active = 0
    let maxActive = 0
    const context = installContext({
      tools: [
        { name: 'select-row', description: 'Select a row', inputSchema: '{"type":"object"}' },
      ],
      execute: async () => {
        active += 1
        maxActive = Math.max(maxActive, active)
        await new Promise<void>((resolve) => release.push(resolve))
        active -= 1
        return { selected: true }
      },
    })
    await discoverWebMcpTools('https://host.example')

    const first = executeWebMcpTool('web__select-row', { id: '41' })
    const second = executeWebMcpTool('web__select-row', { id: '42' })
    await vi.waitFor(() => expect(release).toHaveLength(1))
    release.shift()?.()
    await vi.waitFor(() => expect(release).toHaveLength(1))
    release.shift()?.()

    await expect(Promise.all([first, second])).resolves.toEqual([
      '{"selected":true}',
      '{"selected":true}',
    ])
    expect(maxActive).toBe(1)
    expect(context.executeTool).toHaveBeenNthCalledWith(1, 'select-row', { id: '41' })
    expect(context.executeTool).toHaveBeenNthCalledWith(2, 'select-row', { id: '42' })
  })

  it('does not fall back when a frontend tool is unavailable', async () => {
    await expect(executeWebMcpTool('web__removed', {})).rejects.toThrow(
      'frontend_tool_unavailable',
    )
  })
})
