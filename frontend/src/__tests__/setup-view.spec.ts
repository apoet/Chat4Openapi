import { createPinia } from 'pinia'
import { fireEvent, render, screen } from '@testing-library/vue'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import SetupView from '../views/SetupView.vue'
import { i18n } from '../i18n'

describe('setup view', () => {
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
})
