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
})
