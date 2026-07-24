import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

import apiSourcesView from '../views/ApiSourcesView.vue?raw'
import providersView from '../views/ProvidersView.vue?raw'
import skillsView from '../views/SkillsView.vue?raw'
import usersView from '../views/UsersView.vue?raw'

it.each([
  ['Users', usersView],
  ['Providers', providersView],
  ['APIs', apiSourcesView],
])('%s uses the compact resource list heading layout', (_name, source) => {
  expect(source).toContain('resource-list compact-resource-list')
  expect(source).toContain('class="resource-copy"')
})

it('keeps the Skill list in the form column and gives remaining width to Tools', () => {
  const styles = readFileSync('src/styles.css', 'utf8')

  expect(skillsView).toMatch(
    /class="skill-primary-column"[\s\S]*class="settings-panel skill-editor"[\s\S]*class="skill-list"[\s\S]*<ToolCatalogPanel/,
  )
  expect(styles).toMatch(
    /\.skill-workbench\s*\{[^}]*grid-template-columns:\s*minmax\(340px,\s*38%\)\s+minmax\(0,\s*1fr\)/,
  )
  expect(styles).toMatch(
    /@media \(max-width:\s*1100px\)\s*\{[^}]*\.skill-workbench\s*\{[^}]*grid-template-columns:\s*1fr/,
  )
})
