import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../stores/auth'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('loads an uninitialized installation without requesting the admin', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ initialized: false, locale: null }))
    vi.stubGlobal('fetch', fetchMock)

    const store = useAuthStore()
    await store.loadState()

    expect(store.initialized).toBe(false)
    expect(store.admin).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retains the csrf token returned by login', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValueOnce(
        jsonResponse({
          admin: { username: 'admin', locale: 'en-US' },
          csrf_token: 'csrf-value',
        }),
      ),
    )

    const store = useAuthStore()
    await store.login('admin', 'StrongPass!123')

    expect(store.admin?.username).toBe('admin')
    expect(store.csrfToken).toBe('csrf-value')
  })
})
