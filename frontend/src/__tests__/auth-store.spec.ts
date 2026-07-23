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

  it('reuses an in-flight setup status request', async () => {
    let resolveStatus!: (response: Response) => void
    const pendingStatus = new Promise<Response>((resolve) => {
      resolveStatus = resolve
    })
    const fetchMock = vi.fn<typeof fetch>().mockReturnValue(pendingStatus)
    vi.stubGlobal('fetch', fetchMock)
    const store = useAuthStore()

    const first = store.loadState()
    const second = store.loadState()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    resolveStatus(jsonResponse({ initialized: false, locale: null }))
    await Promise.all([first, second])
    expect(store.initialized).toBe(false)
  })

  it('retains the csrf token returned by login', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValueOnce(
        jsonResponse({
          admin: { username: 'admin', locale: 'en-US', role: 'admin' },
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
