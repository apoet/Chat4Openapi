import { render, screen } from '@testing-library/vue'
import { describe, expect, it } from 'vitest'

import EmbedChatPanel from '../components/EmbedChatPanel.vue'
import { i18n } from '../i18n'

describe('EmbedChatPanel', () => {
  it('renders assistant Markdown tables while keeping user messages plain', () => {
    const { container } = render(EmbedChatPanel, {
      props: {
        agentName: 'Project Agent',
        messages: [
          {
            id: 'user',
            role: 'user',
            content: '**show projects**',
          },
          {
            id: 'assistant',
            role: 'assistant',
            content: [
              '| Project | Status |',
              '|---|---|',
              '| Apollo | Active |',
            ].join('\n'),
          },
        ],
        draft: '',
        ready: true,
        sending: false,
        error: '',
        canMaximize: false,
        maximized: false,
      },
      global: { plugins: [i18n] },
    })

    expect(screen.getByRole('table')).toBeTruthy()
    expect(screen.getByRole('cell', { name: 'Apollo' })).toBeTruthy()
    const userMessage = container.querySelector('.embed-message.is-user')
    expect(userMessage?.textContent).toContain('**show projects**')
    expect(userMessage?.querySelector('strong')).toBeNull()
  })

  it('shows an accessible loading animation while the Agent is working', () => {
    render(EmbedChatPanel, {
      props: {
        agentName: 'Project Agent',
        messages: [],
        draft: '',
        ready: true,
        sending: true,
        error: '',
        canMaximize: false,
        maximized: false,
      },
      global: { plugins: [i18n] },
    })

    const indicator = screen.getByRole('status', { name: 'Assistant is working…' })
    expect(indicator.querySelectorAll('.chat-loading-dot')).toHaveLength(3)
  })
})
