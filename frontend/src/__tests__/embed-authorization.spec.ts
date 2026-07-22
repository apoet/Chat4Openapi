// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EmbedAuthorization from '../components/EmbedAuthorization.vue'
import { i18n } from '../i18n'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mountAuthorization() {
  return mount(EmbedAuthorization, {
    props: {
      sessionId: 'embed-session',
      token: 'embed-token',
      chatOrigin: 'https://chat.example',
      source: {
        api_source_id: 9,
        api_source_name: 'Orders API',
        flows: ['pkce'],
      },
    },
    global: { plugins: [i18n] },
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response({ authorization_url: 'https://chat.example/oauth/start' }, 201))
    .mockResolvedValueOnce(response({ status: 'ready', api_source_id: 9 })))
})

describe('Embed authorization', () => {
  it('opens authorization only from the user button', async () => {
    const popup = { closed: false, close: vi.fn() } as unknown as Window
    const open = vi.spyOn(window, 'open').mockReturnValue(popup)
    const wrapper = mountAuthorization()

    expect(open).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="authorize"]').trigger('click')
    await flushPromises()

    expect(open).toHaveBeenCalledWith(
      'https://chat.example/oauth/start',
      'chat4openapi-auth',
      'popup,width=520,height=720',
    )
  })

  it('ignores grants from another origin or window and exchanges the exact popup grant', async () => {
    const popup = { closed: false, close: vi.fn() } as unknown as Window
    vi.spyOn(window, 'open').mockReturnValue(popup)
    const wrapper = mountAuthorization()
    await wrapper.get('[data-testid="authorize"]').trigger('click')
    await flushPromises()
    const fetch = vi.mocked(globalThis.fetch)

    window.dispatchEvent(new MessageEvent('message', {
      origin: 'https://evil.example', source: popup,
      data: { type: 'chat4openapi:auth-grant', grant: 'evil-grant' },
    }))
    window.dispatchEvent(new MessageEvent('message', {
      origin: 'https://chat.example', source: window,
      data: { type: 'chat4openapi:auth-grant', grant: 'wrong-window' },
    }))
    await flushPromises()
    expect(fetch).toHaveBeenCalledTimes(1)

    window.dispatchEvent(new MessageEvent('message', {
      origin: 'https://chat.example', source: popup,
      data: { type: 'chat4openapi:auth-grant', grant: 'one-time-grant' },
    }))
    await flushPromises()

    expect(fetch).toHaveBeenLastCalledWith(
      '/api/embed/sessions/embed-session/auth/exchange',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer embed-token' }),
        body: JSON.stringify({ grant: 'one-time-grant' }),
      }),
    )
    expect(wrapper.emitted('authorized')).toEqual([[9]])
  })

  it('shows a retryable message when the popup is blocked', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    const wrapper = mountAuthorization()

    await wrapper.get('[data-testid="authorize"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('popup')
  })
})
