import { HttpAgent, type HttpAgentFetchFn } from '@ag-ui/client'

export type EmbedAgentConfig = {
  url: string
  agentId: string
  threadId: string
  token: string
  fetch?: HttpAgentFetchFn
}

export function createEmbedAgent(config: EmbedAgentConfig): HttpAgent {
  return new HttpAgent({
    url: config.url,
    agentId: config.agentId,
    threadId: config.threadId,
    headers: { Authorization: `Bearer ${config.token}` },
    fetch: config.fetch,
  })
}
