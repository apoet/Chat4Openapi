import { render, screen, waitFor } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MarkdownMessage from '../components/MarkdownMessage.vue'
import { i18n } from '../i18n'
import ChatView from '../views/ChatView.vue'

function response(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  localStorage.clear()
})

describe('MarkdownMessage', () => {
  it('renders common GFM safely and hardens external links', () => {
    const content = [
      '# Gene result',
      '',
      '| Field | Result |',
      '|---|---|',
      '| Gene | ABCA4 |',
      '',
      '- first item',
      '- second item',
      '',
      '> source note',
      '',
      '`inline`',
      '',
      '```json',
      '{"chromosome":"1"}',
      '```',
      '',
      '[safe](https://example.test/result)',
      '[bad](javascript:alert(1))',
      '<img src=x onerror="alert(1)">',
      '<script>alert(1)</script>',
    ].join('\n')

    const { container } = render(MarkdownMessage, { props: { content } })

    expect(screen.getByRole('heading', { name: 'Gene result' })).toBeTruthy()
    expect(screen.getByRole('table')).toBeTruthy()
    expect(container.querySelector('thead')).toBeTruthy()
    expect(screen.getByRole('cell', { name: 'ABCA4' })).toBeTruthy()
    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(container.querySelector('blockquote')).toBeTruthy()
    expect(container.querySelector('code')).toBeTruthy()
    const safe = screen.getByRole('link', { name: 'safe' })
    expect(safe.getAttribute('target')).toBe('_blank')
    expect(safe.getAttribute('rel')).toBe('noopener noreferrer')
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('[onerror]')).toBeNull()
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull()
  })

  it('keeps user content plain while rendering assistant and clarification Markdown', async () => {
    localStorage.setItem('chat4openapi.chat.sessions.v1', JSON.stringify([{
      version: 3,
      id: 'markdown-history',
      conversationId: 'conversation-markdown',
      title: 'Markdown history',
      agentId: 7,
      agentName: 'Research Agent',
      loadedSkillIds: [],
      status: 'needs_input',
      pending: { fields: ['reference'] },
      messages: [
        { role: 'user', content: '**not bold** <img src=x onerror="alert(1)">', kind: 'message' },
        { role: 'assistant', content: '| Field | Result |\n|---|---|\n| Gene | ABCA4 |', kind: 'message' },
        { role: 'assistant', content: 'Choose **GRCh38**.', kind: 'clarification' },
      ],
      updatedAt: '2026-07-21T00:00:00.000Z',
    }]))
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (input === '/api/tool-session/config') return Promise.resolve(response({ enabled: false }))
      if (input === '/api/admin/agents') return Promise.resolve(response([]))
      return Promise.resolve(response([]))
    }))

    const { container } = render(ChatView, {
      global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    await waitFor(() => expect(screen.getByText('ABCA4')).toBeTruthy())
    const user = container.querySelector('.message.user')
    expect(user?.textContent).toContain('**not bold** <img')
    expect(user?.querySelector('strong')).toBeNull()
    expect(user?.querySelector('img')).toBeNull()
    expect(container.querySelector('.message.assistant:not(.clarification) table')).toBeTruthy()
    expect(container.querySelector('.message.clarification .markdown-body strong')?.textContent).toBe('GRCh38')
  })
})
