import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { createAppRouter } from '../router'
import { useAuthStore } from '../stores/auth'

describe('router guards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('redirects an uninitialized installation to setup', async () => {
    const auth = useAuthStore()
    auth.initialized = false
    const router = createAppRouter()

    await router.push('/admin')

    expect(router.currentRoute.value.fullPath).toBe('/setup')
  })

  it('redirects an unauthenticated administrator to login', async () => {
    const auth = useAuthStore()
    auth.initialized = true
    auth.admin = null
    const router = createAppRouter()

    await router.push('/admin')

    expect(router.currentRoute.value.fullPath).toBe('/login?redirect=/admin')
  })

  it('allows an authenticated administrator into overview', async () => {
    const auth = useAuthStore()
    auth.initialized = true
    auth.admin = { username: 'admin', locale: 'en-US', role: 'admin' }
    const router = createAppRouter()

    await router.push('/admin')

    expect(router.currentRoute.value.fullPath).toBe('/admin')
  })

  it('redirects an ordinary user away from System routes', async () => {
    const auth = useAuthStore()
    auth.initialized = true
    auth.admin = { username: 'builder', locale: 'en-US', role: 'user' }
    const router = createAppRouter()

    await router.push('/admin/settings')

    expect(router.currentRoute.value.fullPath).toBe('/admin/sources')
  })

  it('keeps public Embed Chat outside setup and administrator guards', async () => {
    const auth = useAuthStore()
    auth.initialized = false
    const router = createAppRouter()

    await router.push('/embed/public-id')

    expect(router.currentRoute.value.fullPath).toBe('/embed/public-id')
  })
})
