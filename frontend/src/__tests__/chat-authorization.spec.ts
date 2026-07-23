// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatAuthorization from '../components/ChatAuthorization.vue'
import { i18n } from '../i18n'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
    response({ authorization_url: 'https://identity.example/authorize' }, 201),
  ))
})

describe('Chat authorization', () => {
  it('notifies Chat and closes the OAuth popup after authorization succeeds', async () => {
    const popup = { closed: false, close: vi.fn() } as unknown as Window
    vi.spyOn(window, 'open').mockReturnValue(popup)
    const wrapper = mount(ChatAuthorization, {
      props: {
        agentId: 3,
        source: {
          api_source_id: 9,
          api_source_name: 'Orders API',
          flows: ['pkce'],
        },
      },
      global: { plugins: [i18n] },
    })

    await wrapper.get('button').trigger('click')
    await flushPromises()
    window.dispatchEvent(new MessageEvent('message', {
      origin: window.location.origin,
      source: popup,
      data: {
        type: 'chat4openapi:auth-complete',
        api_source_id: 9,
      },
    }))
    await flushPromises()

    expect(popup.close).toHaveBeenCalledOnce()
    expect(wrapper.emitted('authorized')).toEqual([[9]])
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  })

  it('closes a denied OAuth popup and leaves authorization retryable', async () => {
    const popup = { closed: false, close: vi.fn() } as unknown as Window
    vi.spyOn(window, 'open').mockReturnValue(popup)
    const wrapper = mount(ChatAuthorization, {
      props: {
        agentId: 3,
        source: {
          api_source_id: 9,
          api_source_name: 'Orders API',
          flows: ['pkce'],
        },
      },
      global: { plugins: [i18n] },
    })

    await wrapper.get('button').trigger('click')
    await flushPromises()
    window.dispatchEvent(new MessageEvent('message', {
      origin: window.location.origin,
      source: popup,
      data: {
        type: 'chat4openapi:auth-error',
        api_source_id: 9,
        error: 'access_denied',
      },
    }))
    await flushPromises()

    expect(popup.close).toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('cancelled')
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
    expect(wrapper.emitted('authorized')).toBeUndefined()
  })
})
