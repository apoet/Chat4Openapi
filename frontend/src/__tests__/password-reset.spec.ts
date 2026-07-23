import { createPinia } from 'pinia'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import LoginView from '../views/LoginView.vue'
import ResetPasswordView from '../views/ResetPasswordView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  i18n.global.locale.value = 'en-US'
  sessionStorage.clear()
})

describe('Administrator password recovery', () => {
  it('requests a server-side key from login and opens the reset page', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      if (String(input).startsWith('https://api.github.com/')) {
        return Promise.resolve(response({ stargazers_count: 0 }))
      }
      return Promise.resolve(response({
        credential_path: 'C:\\private\\admin-password-reset.key',
        expires_at: '2026-07-23T08:15:00Z',
      }, 201))
    })
    vi.stubGlobal('fetch', fetchMock)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/login', name: 'login', component: LoginView },
        {
          path: '/reset-password',
          name: 'reset-password',
          component: { template: '<div>Reset page</div>' },
        },
      ],
    })
    await router.push('/login')
    await router.isReady()
    render(LoginView, { global: { plugins: [createPinia(), i18n, router] } })

    await fireEvent.click(screen.getByRole('button', { name: 'Request password reset' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/admin/auth/password-reset/request',
      expect.objectContaining({ method: 'POST' }),
    ))
    await waitFor(() => expect(router.currentRoute.value.name).toBe('reset-password'))
    expect(JSON.parse(
      sessionStorage.getItem('chat4openapi.admin-password-reset') ?? '{}',
    ).credential_path).toBe('C:\\private\\admin-password-reset.key')
  })

  it('shows the private server path and completes reset with confirmation', async () => {
    sessionStorage.setItem('chat4openapi.admin-password-reset', JSON.stringify({
      credential_path: '/srv/agent4api/data/password-reset/admin-password-reset.key',
      expires_at: '2026-07-23T08:15:00Z',
    }))
    const fetchMock = vi.fn().mockResolvedValue(response(null, 204))
    vi.stubGlobal('fetch', fetchMock)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/reset-password',
          name: 'reset-password',
          component: ResetPasswordView,
        },
        { path: '/login', name: 'login', component: LoginView },
      ],
    })
    await router.push('/reset-password')
    await router.isReady()
    render(ResetPasswordView, {
      global: { plugins: [createPinia(), i18n, router] },
    })

    expect(screen.getByText(
      '/srv/agent4api/data/password-reset/admin-password-reset.key',
    )).toBeTruthy()
    await fireEvent.update(screen.getByLabelText('Reset key'), 'server-file-key')
    await fireEvent.update(screen.getByLabelText('New password'), 'RecoveredPass456')
    await fireEvent.update(
      screen.getByLabelText('Confirm new password'),
      'RecoveredPass456',
    )
    await fireEvent.click(
      screen.getByRole('button', { name: 'Reset administrator password' }),
    )

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/admin/auth/password-reset/complete',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          key: 'server-file-key',
          new_password: 'RecoveredPass456',
          new_password_confirm: 'RecoveredPass456',
        }),
      }),
    ))
    await waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
    expect(sessionStorage.getItem('chat4openapi.admin-password-reset')).toBeNull()
  })
})
