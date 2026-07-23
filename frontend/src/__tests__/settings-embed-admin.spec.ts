// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AgentEmbedPanel from '../components/AgentEmbedPanel.vue'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import SettingsView from '../views/SettingsView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf-token'
  vi.restoreAllMocks()
})

describe('Embed administration', () => {
  it('loads, normalizes, and saves the system Base URL', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response({ base_url: 'https://chat.example' }))
      .mockResolvedValueOnce(response({ base_url: 'https://widget.example/base' })))
    const wrapper = mount(SettingsView, { global: { plugins: [i18n] } })
    await flushPromises()

    expect(wrapper.get('input[type="url"]').element).toHaveProperty(
      'value', 'https://chat.example',
    )
    expect(wrapper.text()).toContain('HTTP or HTTPS')
    await wrapper.get('input[type="url"]').setValue('https://widget.example/base/')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(vi.mocked(fetch)).toHaveBeenLastCalledWith(
      '/api/admin/settings',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ base_url: 'https://widget.example/base/' }),
      }),
    )
    expect(wrapper.text()).toContain('https://widget.example/base')
  })

  it('disables script copy until Base URL exists and creates multiple embeds', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(response([
        {
          id: 1, agent_id: 7, name: 'Docs', public_id: 'public-id', enabled: true,
          allowed_origins: ['https://docs.example'], position: 'bottom_right',
          created_at: '2026-07-22T00:00:00', updated_at: '2026-07-22T00:00:00',
          deleted_at: null, script: null,
        },
      ]))
      .mockResolvedValueOnce(response({
        id: 2, agent_id: 7, name: 'Portal', public_id: 'public-2', enabled: true,
        allowed_origins: [], position: 'bottom_left',
        created_at: '2026-07-22T00:00:00', updated_at: '2026-07-22T00:00:00',
        deleted_at: null, script: null,
      }, 201)))
    const wrapper = mount(AgentEmbedPanel, {
      props: { agentId: 7 },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="copy-script"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="embed-name"]').setValue('Portal')
    await wrapper.get('[data-testid="embed-position"]').setValue('bottom_left')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Docs')
    expect(wrapper.text()).toContain('Portal')
    expect(vi.mocked(fetch)).toHaveBeenLastCalledWith(
      '/api/admin/agents/7/embeds',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('copies an embed script when the Clipboard API is unavailable', async () => {
    const script = '<script src="http://chat.example/embed/public-id.js" async></script>'
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
    const execCommand = vi.fn(() => true)
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response([
      {
        id: 1, agent_id: 7, name: 'Docs', public_id: 'public-id', enabled: true,
        allowed_origins: [], position: 'bottom_right',
        created_at: '2026-07-22T00:00:00', updated_at: '2026-07-22T00:00:00',
        deleted_at: null, script,
      },
    ])))
    const wrapper = mount(AgentEmbedPanel, {
      props: { agentId: 7 },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    await wrapper.get('[data-testid="copy-script"]').trigger('click')
    await flushPromises()

    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(wrapper.get('[data-testid="copy-script"]').text()).toBe('Copied')
  })

  it('shows copy failure feedback when the browser blocks all copy methods', async () => {
    const script = '<script src="http://chat.example/embed/public-id.js" async></script>'
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('NotAllowedError')) },
    })
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn(() => { throw new Error('copy blocked') }),
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response([
      {
        id: 1, agent_id: 7, name: 'Docs', public_id: 'public-id', enabled: true,
        allowed_origins: [], position: 'bottom_right',
        created_at: '2026-07-22T00:00:00', updated_at: '2026-07-22T00:00:00',
        deleted_at: null, script,
      },
    ])))
    const wrapper = mount(AgentEmbedPanel, {
      props: { agentId: 7 },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    await wrapper.get('[data-testid="copy-script"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('Copy failed')
    expect(wrapper.get('[data-testid="embed-script-fallback"]').text()).toBe(script)
  })
})
