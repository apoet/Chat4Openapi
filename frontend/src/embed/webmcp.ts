import type { Tool } from '@ag-ui/core'

const MAX_TOOLS = 64
const MAX_VALUE_BYTES = 64 * 1024
const EXECUTION_TIMEOUT_MS = 30_000
const TOOL_NAME = /^[A-Za-z0-9_.-]{1,128}$/

type WebMcpTool = {
  name: string
  description: string
  inputSchema: string
}

type WebMcpContext = EventTarget & {
  getTools?: (options: { fromOrigins: string[] }) => Promise<WebMcpTool[]>
  executeTool?: (name: string, args: unknown) => Promise<unknown>
}

const originalNames = new Map<string, string>()
let executionQueue: Promise<void> = Promise.resolve()

function context(): WebMcpContext | undefined {
  return document.modelContext as WebMcpContext | undefined
}

function encodedSize(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength
}

export async function discoverWebMcpTools(parentOrigin: string): Promise<Tool[]> {
  const modelContext = context()
  if (
    !modelContext
    || typeof modelContext.getTools !== 'function'
    || typeof modelContext.executeTool !== 'function'
  ) {
    originalNames.clear()
    return []
  }

  let registered: WebMcpTool[]
  try {
    registered = await modelContext.getTools({ fromOrigins: [parentOrigin] })
  } catch {
    originalNames.clear()
    return []
  }

  const nextNames = new Map<string, string>()
  const tools: Tool[] = []
  for (const tool of registered.slice(0, MAX_TOOLS)) {
    if (
      !TOOL_NAME.test(tool.name)
      || typeof tool.description !== 'string'
      || tool.description.length < 1
      || tool.description.length > 4096
    ) continue
    try {
      const parameters = JSON.parse(tool.inputSchema) as unknown
      if (
        !parameters
        || typeof parameters !== 'object'
        || Array.isArray(parameters)
        || encodedSize(parameters) > MAX_VALUE_BYTES
      ) continue
      const name = `web__${tool.name}`
      nextNames.set(name, tool.name)
      tools.push({ name, description: tool.description, parameters })
    } catch {
      // Invalid host Tool definitions are ignored independently.
    }
  }
  originalNames.clear()
  for (const [name, original] of nextNames) originalNames.set(name, original)
  return tools
}

export function observeWebMcpToolChanges(
  parentOrigin: string,
  callback: (tools: Tool[]) => void,
): () => void {
  const modelContext = context()
  if (!modelContext || typeof modelContext.addEventListener !== 'function') return () => undefined
  const refresh = () => { void discoverWebMcpTools(parentOrigin).then(callback) }
  modelContext.addEventListener('toolchange', refresh)
  return () => modelContext.removeEventListener('toolchange', refresh)
}

export function executeWebMcpTool(
  name: string,
  args: unknown,
  signal?: AbortSignal,
): Promise<string> {
  const operation = executionQueue.then(async () => {
    const modelContext = context()
    const originalName = originalNames.get(name)
    if (!originalName || typeof modelContext?.executeTool !== 'function') {
      throw new Error('frontend_tool_unavailable')
    }
    if (encodedSize(args) > MAX_VALUE_BYTES) throw new Error('frontend_tool_arguments_too_large')
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')

    let timer: ReturnType<typeof setTimeout> | undefined
    let onAbort: (() => void) | undefined
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error('frontend_tool_timeout')), EXECUTION_TIMEOUT_MS)
      if (signal) {
        onAbort = () => reject(new DOMException('Aborted', 'AbortError'))
        signal.addEventListener('abort', onAbort, { once: true })
      }
    })
    try {
      const result = await Promise.race([modelContext.executeTool(originalName, args), timeout])
      if (encodedSize(result) > MAX_VALUE_BYTES) throw new Error('frontend_tool_result_too_large')
      return JSON.stringify(result ?? null)
    } finally {
      if (timer !== undefined) clearTimeout(timer)
      if (signal && onAbort) signal.removeEventListener('abort', onAbort)
    }
  })
  executionQueue = operation.then(() => undefined, () => undefined)
  return operation
}
