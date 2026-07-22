/// <reference types="vite/client" />

interface Document {
  modelContext?: EventTarget & {
    getTools?: (options: { fromOrigins: string[] }) => Promise<Array<{
      name: string
      description: string
      inputSchema: string
    }>>
    executeTool?: (name: string, args: unknown) => Promise<unknown>
  }
}
