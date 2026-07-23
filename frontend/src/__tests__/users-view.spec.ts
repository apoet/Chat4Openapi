import { createPinia, setActivePinia } from 'pinia'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import UsersView from '../views/UsersView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  i18n.global.locale.value = 'en-US'
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.admin = { username: 'admin', locale: 'en-US', role: 'admin' }
  auth.csrfToken = 'csrf'
})

describe('User administration', () => {
  it('requires and submits password confirmation when creating a user', async () => {
    const created = {
      id: 2,
      username: 'builder',
      role: 'user',
      locale: 'en-US',
      enabled: true,
      created_at: '2026-07-23T00:00:00Z',
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response(created, 201))
      .mockResolvedValueOnce(response([created]))
    vi.stubGlobal('fetch', fetchMock)
    render(UsersView, { global: { plugins: [i18n] } })

    await fireEvent.update(screen.getByLabelText('Username'), 'builder')
    await fireEvent.update(screen.getByLabelText('Password'), 'Builder123')
    expect((screen.getByRole('button', { name: 'Create user' }) as HTMLButtonElement).disabled)
      .toBe(true)
    await fireEvent.update(screen.getByLabelText('Confirm password'), 'Builder123')
    await fireEvent.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(
      ([path, init]) => path === '/api/admin/users' && init?.method === 'POST',
    )).toBe(true))
    const createCall = fetchMock.mock.calls.find(
      ([path, init]) => path === '/api/admin/users' && init?.method === 'POST',
    )
    expect(JSON.parse(createCall?.[1]?.body as string)).toEqual({
      username: 'builder',
      password: 'Builder123',
      password_confirm: 'Builder123',
      locale: 'en-US',
      enabled: true,
    })
  })

  it('lets an administrator reset a user password with confirmation', async () => {
    const user = {
      id: 2,
      username: 'builder',
      role: 'user',
      locale: 'en-US',
      enabled: true,
      created_at: '2026-07-23T00:00:00Z',
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response([user]))
      .mockResolvedValueOnce(response(null, 204))
      .mockResolvedValueOnce(response([user]))
    vi.stubGlobal('fetch', fetchMock)
    render(UsersView, { global: { plugins: [i18n] } })

    await fireEvent.click(await screen.findByRole('button', { name: 'Reset password' }))
    await fireEvent.update(screen.getByLabelText('New password'), 'ResetPass456')
    await fireEvent.update(screen.getByLabelText('Confirm new password'), 'ResetPass456')
    await fireEvent.click(screen.getByRole('button', { name: 'Reset user password' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(
      ([path, init]) => path === '/api/admin/users/2/password' && init?.method === 'PUT',
    )).toBe(true))
    const resetCall = fetchMock.mock.calls.find(
      ([path, init]) => path === '/api/admin/users/2/password' && init?.method === 'PUT',
    )
    expect(JSON.parse(resetCall?.[1]?.body as string)).toEqual({
      new_password: 'ResetPass456',
      new_password_confirm: 'ResetPass456',
    })
  })
})
