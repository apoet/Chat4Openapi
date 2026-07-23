// @vitest-environment jsdom

import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import ApiSourcesView from '../views/ApiSourcesView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
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
      document_url: null, allow_private_networks: false, auth_mode: 'oauth', enabled: true,
      created_at: '2026-07-22T00:00:00',
    }]))
    .mockResolvedValueOnce(response([]))
    .mockResolvedValueOnce(response({
      api_source_id: 9, enabled: false, login_tool_id: null,
      username_field: 'username', password_field: 'password',
      token_json_path: '$.access_token', expires_json_path: null,
      auth_type: 'bearer', auth_name: 'Authorization', auth_prefix: 'Bearer',
      idle_minutes: 30, absolute_hours: 8,
    }))
    .mockResolvedValueOnce(response({
      api_source_id: 9, enabled: true, client_id: 'orders-client',
      has_client_secret: true, authorization_url: 'https://identity.example/authorize',
      token_endpoint_auth_method: 'client_secret_basic',
      token_headers: { 'tenant-id': '1' },
      token_params: { audience: 'orders' },
      token_url: 'https://identity.example/token', device_authorization_url: null,
      redirect_uri: 'https://override.example/callback', scopes: ['orders.read'],
      recommended_redirect_uri: 'https://chat.example/api/tool-sessions/oauth/pkce/callback',
      effective_redirect_uri: 'https://override.example/callback',
    }))
    .mockResolvedValueOnce(response({
      api_source_id: 9, enabled: true, client_id: 'orders-client',
      has_client_secret: true, authorization_url: 'https://identity.example/authorize',
      token_endpoint_auth_method: 'client_secret_basic',
      token_headers: { 'tenant-id': '2' },
      token_params: { audience: 'invoices' },
      token_url: 'https://identity.example/token', device_authorization_url: null,
      redirect_uri: 'https://override.example/callback', scopes: ['orders.read'],
      recommended_redirect_uri: 'https://chat.example/api/tool-sessions/oauth/pkce/callback',
      effective_redirect_uri: 'https://override.example/callback',
    })))
  const wrapper = mount(ApiSourcesView, { global: { plugins: [i18n] } })
  await flushPromises()

  await wrapper.get('[data-testid="source-oauth-9"]').trigger('click')
  await flushPromises()

  expect(wrapper.text()).toContain('Authentication for Orders')
  expect(wrapper.text()).toContain('Login Tool')
  expect(wrapper.text()).toContain('https://identity.example/authorize')
  expect(wrapper.text()).toContain('https://override.example/callback')
  expect(wrapper.text()).toContain('https://chat.example/api/tool-sessions/oauth/pkce/callback')
  expect(wrapper.get('[data-testid="oauth-token-auth-method"]').element).toHaveProperty(
    'value',
    'client_secret_basic',
  )
  expect(wrapper.get('[data-testid="oauth-token-headers"]').element).toHaveProperty(
    'value',
    '{\n  "tenant-id": "1"\n}',
  )
  expect(wrapper.get('[data-testid="oauth-token-params"]').element).toHaveProperty(
    'value',
    '{\n  "audience": "orders"\n}',
  )

  await wrapper.get('[data-testid="oauth-token-headers"]').setValue(
    '{ "tenant-id": "2" }',
  )
  await wrapper.get('[data-testid="oauth-token-params"]').setValue(
    '{ "audience": "invoices" }',
  )
  await wrapper.get('.oauth-panel form').trigger('submit')
  await flushPromises()

  const fetchMock = vi.mocked(fetch)
  const saveRequest = fetchMock.mock.calls.at(-1)
  expect(saveRequest?.[0]).toBe('/api/admin/sources/9/oauth')
  expect(JSON.parse(String(saveRequest?.[1]?.body))).toMatchObject({
    token_headers: { 'tenant-id': '2' },
    token_params: { audience: 'invoices' },
  })
})

it('tests OAuth and Tool authentication and displays detailed failures', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response([{
      id: 9, name: 'Orders', source_type: 'openapi', base_url: 'https://api.example',
      document_url: null, allow_private_networks: false, auth_mode: 'oauth', enabled: true,
      created_at: '2026-07-22T00:00:00',
    }]))
    .mockResolvedValueOnce(response([{
      id: 21, api_source_id: 9, operation_key: 'POST /login', name: 'Login',
      description: null, input_schema: {}, execution_schema: {}, tags: [], enabled: true,
    }]))
    .mockResolvedValueOnce(response({
      api_source_id: 9, enabled: false, login_tool_id: 21,
      username_field: 'username', password_field: 'password',
      token_json_path: '$.access_token', expires_json_path: null,
      auth_type: 'bearer', auth_name: 'Authorization', auth_prefix: 'Bearer',
      idle_minutes: 30, absolute_hours: 8,
      request_parameters: { tenant: 'north' },
      request_headers: { 'x-tenant': 'one' },
    }))
    .mockResolvedValueOnce(response({
      api_source_id: 9, enabled: true, client_id: 'orders-client',
      has_client_secret: true, authorization_url: 'https://identity.example/authorize',
      token_endpoint_auth_method: 'client_secret_basic',
      token_headers: { 'tenant-id': '1' },
      token_params: { audience: 'orders' },
      token_url: 'https://identity.example/token', device_authorization_url: null,
      redirect_uri: null, scopes: [],
      recommended_redirect_uri: null, effective_redirect_uri: null,
    }))
    .mockResolvedValueOnce(response({ success: true, status: 200 }))
    .mockResolvedValueOnce(response({
      error: {
        code: 'tools.auth_test_failed',
        params: {
          status: 401,
          reason: 'Upstream API returned HTTP 401',
          details: { message: 'invalid username or password' },
        },
      },
    }, 400)))

  const wrapper = mount(ApiSourcesView, { global: { plugins: [i18n] } })
  await flushPromises()
  await wrapper.get('[data-testid="source-oauth-9"]').trigger('click')
  await flushPromises()

  await wrapper.get('[data-testid="oauth-test"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[data-testid="auth-test-result"]').text()).toContain('200')

  await wrapper.get('[data-testid="auth-mode-tool"]').trigger('click')
  await wrapper.get('[data-testid="tool-auth-test-username"]').setValue('alice')
  await wrapper.get('[data-testid="tool-auth-test-password"]').setValue('wrong')
  await wrapper.get('[data-testid="tool-auth-test"]').trigger('click')
  await flushPromises()

  expect(wrapper.get('[data-testid="auth-test-result"]').text()).toContain(
    'invalid username or password',
  )
})
