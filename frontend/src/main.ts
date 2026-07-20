import { createPinia } from 'pinia'
import { createApp } from 'vue'

import './styles.css'
import App from './App.vue'
import { i18n } from './i18n'
import { createAppRouter } from './router'

const app = createApp(App)
app.use(createPinia())
app.use(i18n)
app.use(createAppRouter())
app.mount('#app')
