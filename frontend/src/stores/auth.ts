import { defineStore } from 'pinia'
import { ref } from 'vue'

import { ApiError, request } from '../api/client'
import type { AdminSummary, AuthResponse, Locale, SetupStatus } from '../api/contracts'

export const useAuthStore = defineStore('auth', () => {
  const initialized = ref<boolean | null>(null)
  const admin = ref<AdminSummary | null>(null)
  const csrfToken = ref<string | null>(null)

  async function loadState(): Promise<void> {
    const status = await request<SetupStatus>('/api/setup/status')
    initialized.value = status.initialized
    if (!status.initialized) {
      admin.value = null
      csrfToken.value = null
      return
    }
    try {
      const auth = await request<AuthResponse>('/api/admin/auth/me')
      admin.value = auth.admin
      csrfToken.value = auth.csrf_token
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
      admin.value = null
      csrfToken.value = null
    }
  }

  async function initialize(username: string, password: string, locale: Locale): Promise<void> {
    await request<SetupStatus>('/api/setup', {
      method: 'POST',
      body: JSON.stringify({ username, password, locale }),
    })
    initialized.value = true
  }

  async function login(username: string, password: string): Promise<void> {
    const auth = await request<AuthResponse>('/api/admin/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    admin.value = auth.admin
    csrfToken.value = auth.csrf_token
  }

  async function logout(): Promise<void> {
    await request<void>('/api/admin/auth/logout', { method: 'POST' }, csrfToken.value)
    admin.value = null
    csrfToken.value = null
  }

  return { initialized, admin, csrfToken, loadState, initialize, login, logout }
})
