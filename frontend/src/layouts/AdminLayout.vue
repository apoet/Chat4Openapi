<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import logoUrl from '../../../logo.png'
import { ApiError } from '../api/client'
import { setLocale } from '../i18n'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { locale, t } = useI18n()
const initials = computed(() => auth.admin?.username.slice(0, 2).toUpperCase() ?? 'AD')
const accountMenuOpen = ref(false)
const passwordDialogOpen = ref(false)
const passwordDialog = ref<HTMLDialogElement | null>(null)
const passwordSaving = ref(false)
const passwordError = ref<string | null>(null)
const passwordForm = reactive({
  current: '',
  next: '',
  confirmation: '',
})
const passwordsDiffer = computed(
  () => passwordForm.confirmation.length > 0
    && passwordForm.next !== passwordForm.confirmation,
)
const canChangePassword = computed(
  () => passwordForm.current.length > 0
    && passwordForm.next.length >= 6
    && /[A-Za-z]/.test(passwordForm.next)
    && /[0-9]/.test(passwordForm.next)
    && passwordForm.confirmation === passwordForm.next
    && !passwordSaving.value,
)

function toggleLocale(): void {
  setLocale(locale.value === 'en-US' ? 'zh-CN' : 'en-US')
}

async function logout(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}

async function openPasswordDialog(): Promise<void> {
  accountMenuOpen.value = false
  passwordError.value = null
  Object.assign(passwordForm, { current: '', next: '', confirmation: '' })
  passwordDialogOpen.value = true
  await nextTick()
  if (typeof passwordDialog.value?.showModal === 'function') {
    passwordDialog.value.showModal()
  } else {
    passwordDialog.value?.setAttribute('open', '')
  }
}

function closePasswordDialog(): void {
  if (passwordDialog.value?.open && typeof passwordDialog.value.close === 'function') {
    passwordDialog.value.close()
  }
  passwordDialogOpen.value = false
}

async function changePassword(): Promise<void> {
  if (!canChangePassword.value) return
  passwordSaving.value = true
  passwordError.value = null
  try {
    await auth.changePassword(
      passwordForm.current,
      passwordForm.next,
      passwordForm.confirmation,
    )
    closePasswordDialog()
    await router.push({ name: 'login' })
  } catch (error) {
    passwordError.value = error instanceof ApiError ? error.code : 'unknown'
  } finally {
    passwordSaving.value = false
  }
}
</script>

<template>
  <div class="admin-shell">
    <aside class="sidebar">
      <div class="sidebar-brand"><span class="brand-mark brand-logo small"><img :src="logoUrl" alt="Agent4API" /></span><strong>Agent4API</strong></div>
      <nav>
        <RouterLink v-if="auth.admin?.role === 'admin'" to="/admin" class="nav-link">⌂ <span>{{ t('nav.overview') }}</span></RouterLink>
        <template v-if="auth.admin?.role === 'admin'">
          <span class="nav-section">{{ t('nav.system') }}</span>
          <RouterLink to="/admin/settings" class="nav-link">⚙ <span>{{ t('settings.nav') }}</span></RouterLink>
          <RouterLink to="/admin/users" class="nav-link">♙ <span>{{ t('users.nav') }}</span></RouterLink>
          <RouterLink to="/admin/providers" class="nav-link">◈ <span>{{ t('overview.providers') }}</span></RouterLink>
        </template>
        <span class="nav-section">{{ t('nav.build') }}</span>
        <RouterLink to="/admin/sources" class="nav-link">⇄ <span>{{ t('nav.apis') }}</span></RouterLink>
        <RouterLink to="/admin/tools" class="nav-link">⌁ <span>{{ t('overview.tools') }}</span></RouterLink>
        <RouterLink to="/admin/skills" class="nav-link">✦ <span>{{ t('overview.skills') }}</span></RouterLink>
        <RouterLink to="/admin/agent" class="nav-link">◉ <span>{{ t('agent.nav') }}</span></RouterLink>
        <RouterLink to="/chat" class="nav-link" target="_blank" rel="noopener">◫ <span>{{ t('chat.title') }}</span></RouterLink>
      </nav>
      <div class="sidebar-footer">
        <button class="text-button" @click="toggleLocale">◎ {{ t('nav.language') }}</button>
        <button class="text-button" @click="logout">↪ {{ t('nav.logout') }}</button>
      </div>
    </aside>
    <section class="admin-main">
      <header class="topbar">
        <div><span class="status-dot"></span> {{ t('status.ready') }}</div>
        <div class="account-menu">
          <button
            type="button"
            class="admin-identity"
            :aria-label="t('account.menu')"
            :aria-expanded="accountMenuOpen"
            @click="accountMenuOpen = !accountMenuOpen"
          >
            <span>{{ auth.admin?.username }}</span><b>{{ initials }}</b>
          </button>
          <div v-if="accountMenuOpen" class="account-dropdown">
            <button type="button" @click="openPasswordDialog">
              {{ t('account.changePassword') }}
            </button>
          </div>
        </div>
      </header>
      <RouterView />
    </section>
    <dialog
      v-if="passwordDialogOpen"
      ref="passwordDialog"
      class="confirmation-dialog password-dialog"
      aria-labelledby="change-password-title"
      @cancel.prevent="closePasswordDialog"
    >
      <form @submit.prevent="changePassword">
        <h2 id="change-password-title">{{ t('account.changePassword') }}</h2>
        <p>{{ t('account.changePasswordHint') }}</p>
        <label>
          {{ t('account.currentPassword') }}
          <input v-model="passwordForm.current" type="password" autocomplete="current-password" />
        </label>
        <label>
          {{ t('account.newPassword') }}
          <input v-model="passwordForm.next" type="password" autocomplete="new-password" />
        </label>
        <label>
          {{ t('account.confirmNewPassword') }}
          <input v-model="passwordForm.confirmation" type="password" autocomplete="new-password" />
        </label>
        <p v-if="passwordsDiffer" class="field-error">{{ t('setup.mismatch') }}</p>
        <p v-if="passwordError" class="form-error">{{ t(`error.${passwordError}`) }}</p>
        <div class="confirmation-actions">
          <button type="button" class="secondary-action" @click="closePasswordDialog">
            {{ t('users.cancel') }}
          </button>
          <button type="submit" class="primary-action" :disabled="!canChangePassword">
            {{ t('account.updatePassword') }}
          </button>
        </div>
      </form>
    </dialog>
  </div>
</template>
