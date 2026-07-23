import { defineStore } from 'pinia'
import { ref } from 'vue'

import { ApiError, request } from '../api/client'
import type { AdminSummary, AuthResponse, Locale, SetupStatus } from '../api/contracts'

export const useAuthStore = defineStore('auth', () => {
  const initialized = ref<boolean | null>(null)
  const admin = ref<AdminSummary | null>(null)
  const csrfToken = ref<string | null>(null)
  let pendingStateLoad: Promise<void> | null = null

  function loadState(): Promise<void> {
    if (pendingStateLoad) return pendingStateLoad
    pendingStateLoad = (async () => {
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
    })().finally(() => {
      pendingStateLoad = null
    })
    return pendingStateLoad
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

  async function changePassword(
    currentPassword: string,
    newPassword: string,
    newPasswordConfirm: string,
  ): Promise<void> {
    await request<void>('/api/admin/auth/password', {
      method: 'PUT',
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
        new_password_confirm: newPasswordConfirm,
      }),
    }, csrfToken.value)
    admin.value = null
    csrfToken.value = null
  }

  return {
    initialized,
    admin,
    csrfToken,
    loadState,
    initialize,
    login,
    logout,
    changePassword,
  }
})
