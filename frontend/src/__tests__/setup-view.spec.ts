import { createPinia } from 'pinia'
import { fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import SetupView from '../views/SetupView.vue'
import { i18n } from '../i18n'

afterEach(() => vi.unstubAllGlobals())

describe('setup view', () => {
  it('allows a six-character password containing letters and numbers', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/setup', component: SetupView }],
    })
    await router.push('/setup')
    await router.isReady()
    render(SetupView, { global: { plugins: [createPinia(), i18n, router] } })

    await fireEvent.update(screen.getByLabelText('Username'), 'admin')
    await fireEvent.update(screen.getByLabelText('Password'), 'abc123')
    await fireEvent.update(screen.getByLabelText('Confirm password'), 'abc123')

    const submit = screen.getByRole('button', { name: 'Create administrator' })
    expect((submit as HTMLButtonElement).disabled).toBe(false)
  })

  it('blocks submission when password confirmation differs', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/setup', component: SetupView }],
    })
    await router.push('/setup')
    await router.isReady()
    render(SetupView, { global: { plugins: [createPinia(), i18n, router] } })

    await fireEvent.update(screen.getByLabelText('Username'), 'admin')
    await fireEvent.update(screen.getByLabelText('Password'), 'StrongPass!123')
    await fireEvent.update(screen.getByLabelText('Confirm password'), 'DifferentPass!123')

    expect(screen.getByText('Passwords do not match.')).toBeTruthy()
    const submit = screen.getByRole('button', { name: 'Create administrator' })
    expect((submit as HTMLButtonElement).disabled).toBe(true)
  })

  it('translates a setup conflict returned by the API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'setup.already_initialized', params: {} },
    }), { status: 409, headers: { 'content-type': 'application/json' } })))
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/setup', component: SetupView }],
    })
    await router.push('/setup')
    await router.isReady()
    render(SetupView, { global: { plugins: [createPinia(), i18n, router] } })
    await fireEvent.update(screen.getByLabelText('Username'), 'admin')
    await fireEvent.update(screen.getByLabelText('Password'), 'abc123')
    await fireEvent.update(screen.getByLabelText('Confirm password'), 'abc123')

    await fireEvent.click(screen.getByRole('button', { name: 'Create administrator' }))

    expect(await screen.findByText('This ChatAPI instance is already initialized.')).toBeTruthy()
  })
})
