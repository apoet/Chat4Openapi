import { createI18n } from 'vue-i18n'

import enUS from './en-US'
import zhCN from './zh-CN'

const savedLocale = localStorage.getItem('chatapi-locale')
const locale = savedLocale === 'zh-CN' ? 'zh-CN' : 'en-US'

export const i18n = createI18n({
  legacy: false,
  locale,
  fallbackLocale: 'en-US',
  messages: { 'en-US': enUS, 'zh-CN': zhCN },
})

export function setLocale(locale: 'en-US' | 'zh-CN'): void {
  i18n.global.locale.value = locale
  localStorage.setItem('chatapi-locale', locale)
  document.documentElement.lang = locale
}
