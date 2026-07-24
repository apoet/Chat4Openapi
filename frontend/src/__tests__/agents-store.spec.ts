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
  it('keeps refreshed server state after Skill binding fails instead of restoring stale metadata', async () => {
    const metadata = {
      id: 1, name: 'Submitted name', description: null, enabled: true, is_default: true,
      system_prompt: 'Submitted prompt', provider_id: 1, model: null,
      mode: 'human_in_loop' as const, max_iterations: 8,
      created_at: '2026-07-20T08:00:00Z', updated_at: '2026-07-22T08:00:00Z',
      deleted_at: null, skill_ids: [10],
    }
    const refreshed = { ...metadata, name: 'Server normalized name', updated_at: '2026-07-22T08:00:01Z' }
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/admin/agents/1' && init?.method === 'PUT') return Promise.resolve(response(metadata))
      if (input === '/api/admin/agents/1/skills' && init?.method === 'PUT') return Promise.resolve(response({ error: { code: 'agents.skill_unavailable' } }, 409))
      if (input === '/api/admin/agents') return Promise.resolve(response([refreshed]))
      throw new Error(`Unexpected request ${String(input)}`)
    }))
    const store = useAgentsStore()

    await expect(store.save({
      name: metadata.name, description: null, enabled: true, system_prompt: metadata.system_prompt,
      provider_id: 1, model: null, mode: 'human_in_loop', max_iterations: 8,
    }, [10], 1)).rejects.toMatchObject({ agentId: 1 })

    expect(store.agents[0].name).toBe('Server normalized name')
    expect(store.agents[0].updated_at).toBe('2026-07-22T08:00:01Z')
  })

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
