import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAgentsStore } from '../stores/agents'
import { useAuthStore } from '../stores/auth'

function response(value: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(value), { status })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().csrfToken = 'csrf'
})

describe('Agents store request generations', () => {
  it('does not let an older key load overwrite metadata created later', async () => {
    const pendingLoad = deferred<Response>()
    const created = {
      id: 8, agent_id: 1, label: 'Production', key_prefix: 'c4o_prod', enabled: true,
      expires_at: null, last_used_at: null, created_at: '2026-07-22T08:00:00Z',
      updated_at: '2026-07-22T08:00:00Z', revoked_at: null, secret: 'c4o_secret_once',
    }
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1/keys' && init?.method === 'POST') return Promise.resolve(response(created, 201))
      if (input === '/api/admin/agents/1/keys') return pendingLoad.promise
      throw new Error(`Unexpected request ${String(input)}`)
    }))
    const store = useAgentsStore()

    const loading = store.loadKeys(1)
    await store.createKey(1, 'Production', null)
    pendingLoad.resolve(response([]))
    await loading

    expect(store.keysByAgent[1]).toHaveLength(1)
    expect(store.keysByAgent[1][0].label).toBe('Production')
    expect(JSON.stringify(store.$state)).not.toContain('c4o_secret_once')
  })
})
