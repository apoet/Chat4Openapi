import { HttpAgent } from '@ag-ui/client'

export type EmbedAgentConfig = {
  url: string
  agentId: string
  threadId: string
  token: string
}

export function createEmbedAgent(config: EmbedAgentConfig): HttpAgent {
  return new HttpAgent({
    url: config.url,
    agentId: config.agentId,
    threadId: config.threadId,
    headers: { Authorization: `Bearer ${config.token}` },
  })
}
