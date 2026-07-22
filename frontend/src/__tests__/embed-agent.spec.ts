import { describe, expect, it } from 'vitest'

import { createEmbedAgent } from '../embed/agent'

describe('embedded AG-UI client', () => {
  it('uses the embed endpoint and in-memory bearer token', () => {
    const agent = createEmbedAgent({
      url: 'https://chat.example/api/embed/public-id/agent',
      agentId: 'agent-7',
      threadId: 'thread-1',
      token: 'embed-token',
    })

    expect(agent.url).toBe('https://chat.example/api/embed/public-id/agent')
    expect(agent.agentId).toBe('agent-7')
    expect(agent.threadId).toBe('thread-1')
    expect(agent.headers).toEqual({ Authorization: 'Bearer embed-token' })
  })
})
