import { describe, expect, it, vi } from 'vitest'

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

  it('consumes the backend lifecycle and text SSE with the official client', async () => {
    const events = [
      { type: 'RUN_STARTED', threadId: 'thread-1', runId: 'run-1' },
      { type: 'TEXT_MESSAGE_START', messageId: 'assistant-1', role: 'assistant' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'assistant-1', delta: 'Hello' },
      { type: 'TEXT_MESSAGE_END', messageId: 'assistant-1' },
      { type: 'RUN_FINISHED', threadId: 'thread-1', runId: 'run-1' },
    ]
    const fetch = vi.fn(async () => new Response(
      events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
      { headers: { 'Content-Type': 'text/event-stream' } },
    ))
    const agent = createEmbedAgent({
      url: '/api/embed/public-id/agent',
      agentId: 'agent-7',
      threadId: 'thread-1',
      token: 'embed-token',
      fetch,
    })
    agent.addMessage({ id: 'user-1', role: 'user', content: 'Hi' })

    const result = await agent.runAgent({ runId: 'run-1' })

    expect(result.newMessages).toEqual([
      { id: 'assistant-1', role: 'assistant', content: 'Hello' },
    ])
    expect(fetch).toHaveBeenCalledOnce()
  })
})
