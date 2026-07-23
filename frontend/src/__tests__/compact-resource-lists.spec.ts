import { expect, it } from 'vitest'

import apiSourcesView from '../views/ApiSourcesView.vue?raw'
import providersView from '../views/ProvidersView.vue?raw'
import usersView from '../views/UsersView.vue?raw'

it.each([
  ['Users', usersView],
  ['Providers', providersView],
  ['APIs', apiSourcesView],
])('%s uses the compact resource list heading layout', (_name, source) => {
  expect(source).toContain('resource-list compact-resource-list')
  expect(source).toContain('class="resource-copy"')
})
