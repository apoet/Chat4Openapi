// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import ApiSourcesView from '../views/ApiSourcesView.vue'

function response(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf-token'
})

it('configures OAuth on its API Source and displays the effective callback URI', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([{
      id: 9, name: 'Orders', source_type: 'openapi', base_url: 'https://api.example',
      document_url: null, allow_private_networks: false, enabled: true,
      created_at: '2026-07-22T00:00:00',
    }]))
    .mockResolvedValueOnce(response({
      api_source_id: 9, enabled: true, client_id: 'orders-client',
      has_client_secret: true, authorization_url: 'https://identity.example/authorize',
      token_url: 'https://identity.example/token', device_authorization_url: null,
      redirect_uri: 'https://override.example/callback', scopes: ['orders.read'],
      recommended_redirect_uri: 'https://chat.example/api/tool-sessions/oauth/pkce/callback',
      effective_redirect_uri: 'https://override.example/callback',
    })))
  const wrapper = mount(ApiSourcesView, { global: { plugins: [i18n] } })
  await flushPromises()

  await wrapper.get('[data-testid="source-oauth-9"]').trigger('click')
  await flushPromises()

  expect(wrapper.text()).toContain('https://identity.example/authorize')
  expect(wrapper.text()).toContain('https://override.example/callback')
  expect(wrapper.text()).toContain('https://chat.example/api/tool-sessions/oauth/pkce/callback')
})
