import { createPinia } from 'pinia'
import { render, screen, waitFor } from '@testing-library/vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import LoginView from '../views/LoginView.vue'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  i18n.global.locale.value = 'en-US'
})

describe('Login view', () => {
  it('links to the GitHub repository and displays its live star count', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      response({ stargazers_count: 42 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/login', name: 'login', component: LoginView }],
    })
    await router.push('/login')
    await router.isReady()

    render(LoginView, { global: { plugins: [createPinia(), i18n, router] } })

    const link = screen.getByRole('link', { name: 'View Agent4API on GitHub' })
    expect(link.getAttribute('href')).toBe('https://github.com/apoet/Agent4API')
    expect(link.getAttribute('target')).toBe('_blank')
    await waitFor(() => expect(link.textContent).toContain('42'))
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.github.com/repos/apoet/Agent4API',
      expect.objectContaining({
        headers: { Accept: 'application/vnd.github+json' },
      }),
    )
  })
})
