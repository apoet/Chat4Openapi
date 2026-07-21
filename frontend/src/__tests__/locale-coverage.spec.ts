import { describe, expect, it } from 'vitest'

import enUS from '../i18n/en-US'
import zhCN from '../i18n/zh-CN'

function flatten(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null) return [prefix]
  return Object.entries(value).flatMap(([key, child]) => flatten(child, prefix ? `${prefix}.${key}` : key))
}

describe('locale coverage', () => {
  it('keeps English and Chinese message keys identical', () => {
    expect(flatten(zhCN).sort()).toEqual(flatten(enUS).sort())
  })

  it('includes every administration-shell narrative key', () => {
    const keys = flatten(enUS)
    expect(keys).toEqual(
      expect.arrayContaining([
        'nav.build',
        'status.ready',
        'setup.identityNote',
        'login.quote',
        'overview.journey.eyebrow',
        'overview.journey.title',
        'overview.journey.description',
        'overview.journey.provider',
        'overview.journey.source',
        'overview.journey.tool',
        'overview.journey.skill',
        'agent.listTitle',
        'agent.newAgent',
        'agent.boundSkills',
        'agent.keys.title',
        'agent.keys.oneTimeWarning',
        'error.agents.default_cannot_disable',
        'error.agents.default_cannot_delete',
        'error.agents.provider_unavailable',
        'error.agents.no_running_skills',
      ]),
    )
  })
})
