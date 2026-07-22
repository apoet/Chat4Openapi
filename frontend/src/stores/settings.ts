import { defineStore } from 'pinia'
import { ref } from 'vue'

import { request } from '../api/client'
import type { AppSettings } from '../api/contracts'
import { useAuthStore } from './auth'

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<AppSettings>({ base_url: null })

  async function load(): Promise<void> {
    settings.value = await request<AppSettings>('/api/admin/settings')
  }

  async function save(baseUrl: string | null): Promise<void> {
    settings.value = await request<AppSettings>('/api/admin/settings', {
      method: 'PUT',
      body: JSON.stringify({ base_url: baseUrl }),
    }, useAuthStore().csrfToken)
  }

  return { settings, load, save }
})
