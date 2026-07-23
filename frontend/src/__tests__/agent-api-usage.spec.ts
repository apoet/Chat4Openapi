import { fireEvent, render, screen } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AgentApiUsagePanel from '../components/AgentApiUsagePanel.vue'
import { i18n } from '../i18n'

describe('AgentApiUsagePanel', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en-US'
  })

  it('shows accurate OpenAI and Anthropic endpoints, parameters, and copyable examples', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    render(AgentApiUsagePanel, {
      props: { agentId: 7, baseUrl: 'https://agent.example/' },
      global: { plugins: [i18n] },
    })

    expect(screen.getByText('https://agent.example/v1/chat/completions')).toBeTruthy()
    expect(screen.getByText('agent-7')).toBeTruthy()
    expect(screen.getByRole('cell', { name: 'messages' })).toBeTruthy()
    expect(screen.getByText(/chat4openapi_conversation_id/)).toBeTruthy()

    await fireEvent.click(screen.getByRole('tab', { name: 'Anthropic' }))

    expect(screen.getByText('https://agent.example/v1/messages')).toBeTruthy()
    expect(screen.getByRole('cell', { name: 'max_tokens' })).toBeTruthy()
    expect(screen.getByText(/anthropic-version: 2023-06-01/)).toBeTruthy()

    await fireEvent.click(screen.getByRole('button', { name: 'Copy example' }))
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('/v1/messages'))
    expect(await screen.findByRole('status')).toHaveProperty(
      'textContent',
      'Example copied.',
    )
  })
})
