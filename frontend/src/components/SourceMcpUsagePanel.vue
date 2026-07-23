<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ApiSourceSummary, ToolSummary } from '../api/contracts'

const props = defineProps<{ source: ApiSourceSummary; tools: ToolSummary[] }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const selectedToolId = ref<number | null>(null)
const copyFeedback = ref('')

const enabledTools = computed(() => props.tools.filter(
  (tool) => tool.api_source_id === props.source.id && tool.enabled,
))
const selectedTool = computed(() => enabledTools.value.find(
  (tool) => tool.id === selectedToolId.value,
) ?? enabledTools.value[0] ?? null)
const endpoint = computed(() => `${window.location.origin}/mcp/`)
const clientConfig = computed(() => JSON.stringify({
  mcpServers: {
    [`agent4api-${props.source.id}`]: {
      url: endpoint.value,
      transport: 'streamable-http',
    },
  },
}, null, 2))
const parameters = computed(() => {
  const schema = selectedTool.value?.input_schema
  if (!schema || typeof schema !== 'object') return []
  const properties = schema.properties
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return []
  const required = new Set(Array.isArray(schema.required) ? schema.required : [])
  return Object.entries(properties).map(([name, raw]) => {
    const field = raw && typeof raw === 'object' && !Array.isArray(raw)
      ? raw as Record<string, unknown>
      : {}
    return {
      name,
      type: typeof field.type === 'string' ? field.type : 'any',
      required: required.has(name),
      description: typeof field.description === 'string' ? field.description : '',
    }
  })
})
const exampleArguments = computed(() => Object.fromEntries(parameters.value.map((field) => [
  field.name,
  field.type === 'integer' || field.type === 'number'
    ? 0
    : field.type === 'boolean'
      ? false
      : field.type === 'array'
        ? []
        : `<${field.name}>`,
])))
const pythonExample = computed(() => [
  'import asyncio',
  'from fastmcp import Client',
  '',
  'async def main():',
  `    async with Client("${endpoint.value}") as client:`,
  '        tools = await client.list_tools()',
  selectedTool.value
    ? `        result = await client.call_tool("${selectedTool.value.name}", ${JSON.stringify(exampleArguments.value)})`
    : '        # Enable a Tool in this API source before calling it.',
  selectedTool.value ? '        print(result)' : '',
  '',
  'asyncio.run(main())',
].filter((line, index, lines) => line || lines[index - 1] !== '').join('\n'))

watch(enabledTools, (tools) => {
  if (!tools.some((tool) => tool.id === selectedToolId.value)) {
    selectedToolId.value = tools[0]?.id ?? null
  }
}, { immediate: true })

async function copy(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value)
    copyFeedback.value = t('sources.mcp.copySuccess')
  } catch {
    copyFeedback.value = t('sources.mcp.copyFailed')
  }
}
</script>

<template>
  <section class="import-panel source-mcp-panel" :aria-label="t('sources.mcp.title', { name: source.name })">
    <header class="panel-heading">
      <div>
        <p class="eyebrow">MCP</p>
        <h2>{{ t('sources.mcp.title', { name: source.name }) }}</h2>
        <p class="muted">{{ t('sources.mcp.subtitle') }}</p>
      </div>
      <button type="button" class="text-button" :aria-label="t('sources.mcp.close')" @click="emit('close')">×</button>
    </header>

    <dl class="mcp-connection-details">
      <div><dt>{{ t('sources.mcp.transport') }}</dt><dd>Streamable HTTP</dd></div>
      <div><dt>{{ t('sources.mcp.endpoint') }}</dt><dd><code>{{ endpoint }}</code></dd></div>
      <div><dt>{{ t('sources.mcp.listMethod') }}</dt><dd><code>tools/list</code></dd></div>
      <div><dt>{{ t('sources.mcp.callMethod') }}</dt><dd><code>tools/call</code> · <code>{ name, arguments }</code></dd></div>
    </dl>
    <p class="mcp-shared-note">{{ t('sources.mcp.sharedEndpoint', { name: source.name }) }}</p>
    <p v-if="source.auth_mode !== 'none'" class="mcp-auth-note">{{ t('sources.mcp.authNote') }}</p>

    <div class="mcp-code-heading">
      <h3>{{ t('sources.mcp.clientConfig') }}</h3>
      <button type="button" class="secondary-action" @click="copy(clientConfig)">{{ t('sources.mcp.copy') }}</button>
    </div>
    <pre><code>{{ clientConfig }}</code></pre>

    <div class="mcp-tool-heading">
      <h3>{{ t('sources.mcp.sourceTools') }}</h3>
      <label v-if="enabledTools.length">
        <span>{{ t('sources.mcp.tool') }}</span>
        <select v-model="selectedToolId" data-testid="mcp-tool-select">
          <option v-for="tool in enabledTools" :key="tool.id" :value="tool.id">
            {{ tool.name }} · {{ tool.operation_key }}
          </option>
        </select>
      </label>
    </div>
    <p v-if="enabledTools.length === 0" class="empty-inline">{{ t('sources.mcp.noTools') }}</p>
    <template v-else-if="selectedTool">
      <p v-if="selectedTool.description" class="muted">{{ selectedTool.description }}</p>
      <div class="mcp-parameter-table">
        <table>
          <thead><tr><th>{{ t('sources.mcp.parameter') }}</th><th>{{ t('sources.mcp.type') }}</th><th>{{ t('sources.mcp.requirement') }}</th><th>{{ t('sources.mcp.description') }}</th></tr></thead>
          <tbody>
            <tr v-for="parameter in parameters" :key="parameter.name">
              <td><code>{{ parameter.name }}</code></td>
              <td>{{ parameter.type }}</td>
              <td>{{ parameter.required ? t('sources.mcp.required') : t('sources.mcp.optional') }}</td>
              <td>{{ parameter.description || '—' }}</td>
            </tr>
            <tr v-if="parameters.length === 0"><td colspan="4">{{ t('sources.mcp.noParameters') }}</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <div class="mcp-code-heading">
      <h3>{{ t('sources.mcp.pythonExample') }}</h3>
      <button type="button" class="secondary-action" @click="copy(pythonExample)">{{ t('sources.mcp.copy') }}</button>
    </div>
    <pre><code>{{ pythonExample }}</code></pre>
    <p v-if="copyFeedback" class="muted" role="status">{{ copyFeedback }}</p>
  </section>
</template>

<style scoped>
.source-mcp-panel { margin-top: 20px; }
.source-mcp-panel .panel-heading { align-items: flex-start; }
.source-mcp-panel .panel-heading .muted { max-width: 760px; margin: 5px 0 0; }
.mcp-connection-details { margin: 18px 0 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.mcp-connection-details div { min-width: 0; padding: 11px 13px; border: 1px solid #e1ddd4; border-radius: 9px; background: #f7f5f0; }
.mcp-connection-details dt { margin-bottom: 5px; color: #697283; font-size: 11px; font-weight: 800; }
.mcp-connection-details dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.mcp-shared-note, .mcp-auth-note { margin: 12px 0 0; padding: 10px 12px; border-radius: 9px; color: #596272; background: #f0edff; font-size: 12px; line-height: 1.5; }
.mcp-auth-note { color: #805b16; background: #fff6df; }
.mcp-code-heading, .mcp-tool-heading { margin-top: 20px; display: flex; align-items: end; justify-content: space-between; gap: 14px; }
.mcp-code-heading h3, .mcp-tool-heading h3 { margin: 0; font-size: 14px; }
.mcp-tool-heading label { min-width: min(420px, 60%); display: grid; gap: 5px; color: #596272; font-size: 11px; font-weight: 800; }
.mcp-tool-heading select { min-width: 0; height: 38px; padding: 0 10px; border: 1px solid #d9d4ca; border-radius: 8px; background: white; }
.source-mcp-panel pre { max-width: 100%; margin: 9px 0 0; padding: 15px; overflow: auto; border-radius: 10px; color: #edf1f7; background: #172033; font: 12px/1.55 ui-monospace, 'Cascadia Code', Consolas, monospace; }
.source-mcp-panel pre code { white-space: pre; }
.mcp-parameter-table { max-width: 100%; margin-top: 10px; overflow-x: auto; border: 1px solid #e1ddd4; border-radius: 9px; }
.mcp-parameter-table table { width: 100%; border-collapse: collapse; font-size: 12px; }
.mcp-parameter-table th, .mcp-parameter-table td { padding: 9px 11px; border-bottom: 1px solid #e8e4dc; text-align: left; vertical-align: top; }
.mcp-parameter-table th { color: #596272; background: #f4f2ed; font-size: 11px; }
.mcp-parameter-table tbody tr:last-child td { border-bottom: 0; }
@media (max-width: 720px) {
  .mcp-connection-details { grid-template-columns: 1fr; }
  .mcp-tool-heading { align-items: stretch; flex-direction: column; }
  .mcp-tool-heading label { min-width: 0; width: 100%; }
}
</style>
