import { computed, toValue, type ComputedRef, type MaybeRefOrGetter } from 'vue'

import type { ApiSourceSummary, ToolSummary } from '../api/contracts'

export type ToolCatalogState = 'all' | 'enabled' | 'disabled'

export interface ToolCatalogFilters {
  query?: string
  sourceId?: number | null
  tag?: string | null
  state?: ToolCatalogState
  pinnedIds?: readonly number[]
}

export interface IndexedTool extends ToolSummary {
  sourceName: string
  method: string
  path: string
  primaryTag: string
  available: boolean
  searchableText: string
}

export interface ToolCatalogTagGroup {
  name: string
  tools: IndexedTool[]
}

export interface ToolCatalogSourceGroup {
  id: number
  name: string
  toolCount: number
  tags: ToolCatalogTagGroup[]
}

export interface ToolCatalogIndex {
  tools: IndexedTool[]
  sources: Array<{ id: number, name: string }>
  tags: string[]
}

export interface ToolCatalogResult {
  tools: IndexedTool[]
  groups: ToolCatalogSourceGroup[]
  total: number
  shown: number
}

export interface ToolCatalog {
  index: ComputedRef<ToolCatalogIndex>
  query: (filters?: ToolCatalogFilters, limit?: number) => ToolCatalogResult
}

export function searchableText(tool: ToolSummary, sourceName: string): string {
  const path = tool.operation_key.replace(/^\S+\s+/, '')
  return [tool.name, tool.description, path, ...(tool.tags || []), sourceName]
    .filter(Boolean)
    .join('\n')
    .toLocaleLowerCase()
}

function operationParts(operationKey: string): { method: string, path: string } {
  const match = operationKey.trim().match(/^(\S+)\s+(.+)$/)
  return match ? { method: match[1].toLocaleUpperCase(), path: match[2] } : {
    method: operationKey,
    path: '',
  }
}

function buildIndex(tools: ToolSummary[], sources: ApiSourceSummary[]): ToolCatalogIndex {
  const sourceById = new Map(sources.map((source) => [source.id, source]))
  const indexed = tools.map((tool) => {
    const source = sourceById.get(tool.api_source_id)
    const sourceName = source?.name || `#${tool.api_source_id}`
    const tags = tool.tags || []
    return {
      ...tool,
      tags,
      ...operationParts(tool.operation_key),
      sourceName,
      primaryTag: tags[0] || '',
      available: tool.enabled && (source?.enabled ?? true),
      searchableText: searchableText(tool, sourceName),
    }
  })
  return {
    tools: indexed,
    sources: [...new Map(indexed.map((tool) => [
      tool.api_source_id,
      { id: tool.api_source_id, name: tool.sourceName },
    ])).values()],
    tags: [...new Set(indexed.flatMap((tool) => tool.tags))].sort((a, b) => a.localeCompare(b)),
  }
}

function groupTools(
  tools: IndexedTool[],
  selectedTag: string | null,
): ToolCatalogSourceGroup[] {
  const sources = new Map<number, {
    id: number
    name: string
    toolCount: number
    tags: Map<string, ToolCatalogTagGroup>
  }>()
  for (const tool of tools) {
    let source = sources.get(tool.api_source_id)
    if (!source) {
      source = {
        id: tool.api_source_id,
        name: tool.sourceName,
        toolCount: 0,
        tags: new Map(),
      }
      sources.set(tool.api_source_id, source)
    }
    const tagName = selectedTag && tool.tags.includes(selectedTag)
      ? selectedTag
      : tool.primaryTag
    let tag = source.tags.get(tagName)
    if (!tag) {
      tag = { name: tagName, tools: [] }
      source.tags.set(tagName, tag)
    }
    tag.tools.push(tool)
    source.toolCount += 1
  }
  return [...sources.values()].map((source) => ({
    id: source.id,
    name: source.name,
    toolCount: source.toolCount,
    tags: [...source.tags.values()],
  }))
}

export function useToolCatalog(
  tools: MaybeRefOrGetter<ToolSummary[]>,
  sources: MaybeRefOrGetter<ApiSourceSummary[]>,
): ToolCatalog {
  const index = computed(() => buildIndex(toValue(tools), toValue(sources)))
  return {
    index,
    query(filters = {}, limit = Number.POSITIVE_INFINITY): ToolCatalogResult {
      const normalizedQuery = filters.query?.trim().toLocaleLowerCase() || ''
      const selectedTag = filters.tag || null
      const matches = index.value.tools.filter((tool) => (
        (!normalizedQuery || tool.searchableText.includes(normalizedQuery))
        && (!filters.sourceId || tool.api_source_id === filters.sourceId)
        && (!selectedTag || tool.tags.includes(selectedTag))
        && (!filters.state || filters.state === 'all'
          || tool.available === (filters.state === 'enabled'))
      ))
      const pinnedIds = new Set(filters.pinnedIds || [])
      const pinned = matches.filter((tool) => pinnedIds.has(tool.id))
      const unpinned = matches.filter((tool) => !pinnedIds.has(tool.id))
      const visible = Number.isFinite(limit)
        ? [...pinned, ...unpinned.slice(0, Math.max(0, limit - pinned.length))]
        : matches
      return {
        tools: visible,
        groups: groupTools(visible, selectedTag),
        total: matches.length,
        shown: visible.length,
      }
    },
  }
}
