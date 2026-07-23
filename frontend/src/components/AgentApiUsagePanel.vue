<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  agentId: number
  baseUrl?: string
}>()
const { t } = useI18n()
const protocol = ref<'openai' | 'anthropic'>('openai')
const copyFeedback = ref('')

const rootUrl = computed(() => (
  props.baseUrl?.trim() || window.location.origin
).replace(/\/+$/, ''))
const endpoint = computed(() => protocol.value === 'openai'
  ? `${rootUrl.value}/v1/chat/completions`
  : `${rootUrl.value}/v1/messages`)
const model = computed(() => `agent-${props.agentId}`)
const parameters = computed(() => [
  {
    name: 'model',
    required: true,
    description: t('agent.api.params.model', { model: model.value }),
  },
  {
    name: 'messages',
    required: true,
    description: t('agent.api.params.messages'),
  },
  ...(protocol.value === 'anthropic' ? [{
    name: 'max_tokens',
    required: true,
    description: t('agent.api.params.maxTokens'),
  }] : []),
  {
    name: 'stream',
    required: false,
    description: t('agent.api.params.stream'),
  },
  {
    name: 'conversation_id',
    required: false,
    description: t('agent.api.params.conversationId'),
  },
  {
    name: 'chat4openapi_skill_ids',
    required: false,
    description: t('agent.api.params.skillIds'),
  },
  {
    name: 'tool_session_id',
    required: false,
    description: t('agent.api.params.toolSessionId'),
  },
])
const requestBody = computed(() => protocol.value === 'openai'
  ? {
      model: model.value,
      messages: [{ role: 'user', content: t('agent.api.exampleQuestion') }],
      stream: false,
    }
  : {
      model: model.value,
      max_tokens: 1024,
      messages: [{ role: 'user', content: t('agent.api.exampleQuestion') }],
      stream: false,
    })
const curl = computed(() => {
  const headers = [
    `-H "Authorization: Bearer <AGENT_API_KEY>"`,
    `-H "Content-Type: application/json"`,
  ]
  if (protocol.value === 'anthropic') {
    headers.push(`-H "anthropic-version: 2023-06-01"`)
  }
  return [
    `curl "${endpoint.value}" \\`,
    ...headers.map((header) => `  ${header} \\`),
    `  -d '${JSON.stringify(requestBody.value, null, 2)}'`,
  ].join('\n')
})

function selectProtocol(next: 'openai' | 'anthropic'): void {
  protocol.value = next
  copyFeedback.value = ''
}

async function copyExample(): Promise<void> {
  try {
    await navigator.clipboard.writeText(curl.value)
    copyFeedback.value = t('agent.api.copySuccess')
  } catch {
    copyFeedback.value = t('agent.api.copyFailed')
  }
}
</script>

<template>
  <section class="settings-panel agent-api-panel" :aria-label="t('agent.api.title')">
    <header class="panel-heading">
      <div>
        <p class="eyebrow">{{ t('agent.api.eyebrow') }}</p>
        <h2>{{ t('agent.api.title') }}</h2>
        <p class="muted">{{ t('agent.api.subtitle') }}</p>
      </div>
      <code class="agent-api-model">{{ model }}</code>
    </header>

    <div class="agent-api-tabs" role="tablist" :aria-label="t('agent.api.protocol')">
      <button
        id="agent-api-openai-tab"
        type="button"
        role="tab"
        :aria-selected="protocol === 'openai'"
        aria-controls="agent-api-panel"
        :class="{ active: protocol === 'openai' }"
        @click="selectProtocol('openai')"
      >OpenAI</button>
      <button
        id="agent-api-anthropic-tab"
        type="button"
        role="tab"
        :aria-selected="protocol === 'anthropic'"
        aria-controls="agent-api-panel"
        :class="{ active: protocol === 'anthropic' }"
        @click="selectProtocol('anthropic')"
      >Anthropic</button>
    </div>

    <div
      id="agent-api-panel"
      class="agent-api-content"
      role="tabpanel"
      :aria-labelledby="protocol === 'openai' ? 'agent-api-openai-tab' : 'agent-api-anthropic-tab'"
    >
      <dl class="agent-api-endpoint">
        <div><dt>{{ t('agent.api.endpoint') }}</dt><dd><code>{{ endpoint }}</code></dd></div>
        <div><dt>{{ t('agent.api.authentication') }}</dt><dd><code>Authorization: Bearer &lt;AGENT_API_KEY&gt;</code></dd></div>
      </dl>

      <h3>{{ t('agent.api.parameters') }}</h3>
      <div class="agent-api-table-wrap">
        <table>
          <thead>
            <tr>
              <th>{{ t('agent.api.parameter') }}</th>
              <th>{{ t('agent.api.requirement') }}</th>
              <th>{{ t('agent.api.description') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="parameter in parameters" :key="parameter.name">
              <td><code>{{ parameter.name }}</code></td>
              <td>{{ parameter.required ? t('agent.api.required') : t('agent.api.optional') }}</td>
              <td>{{ parameter.description }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="agent-api-example-heading">
        <h3>{{ t('agent.api.curlExample') }}</h3>
        <button type="button" class="secondary-action" @click="copyExample">
          {{ t('agent.api.copy') }}
        </button>
      </div>
      <pre><code>{{ curl }}</code></pre>
      <p v-if="copyFeedback" class="muted" role="status">{{ copyFeedback }}</p>
    </div>
  </section>
</template>

<style scoped>
.agent-api-panel { min-width: 0; }
.agent-api-panel .panel-heading { align-items: flex-start; }
.agent-api-panel .panel-heading .muted { max-width: 720px; margin: 5px 0 0; }
.agent-api-model { padding: 6px 9px; border-radius: 7px; color: #574bb5; background: #f0edff; font-weight: 800; }
.agent-api-tabs { width: fit-content; margin: 18px 0; padding: 4px; display: flex; gap: 3px; border-radius: 10px; background: #ece9e2; }
.agent-api-tabs button { min-width: 105px; height: 36px; padding: 0 14px; border: 0; border-radius: 7px; color: #626b7b; background: transparent; font-weight: 800; cursor: pointer; }
.agent-api-tabs button.active { color: #172033; background: white; box-shadow: 0 2px 8px rgba(20,28,45,.09); }
.agent-api-tabs button:focus-visible { outline: 3px solid rgba(101,88,232,.24); outline-offset: 2px; }
.agent-api-content { min-width: 0; }
.agent-api-content h3 { margin: 20px 0 9px; font-size: 14px; }
.agent-api-endpoint { margin: 0; display: grid; gap: 8px; }
.agent-api-endpoint div { min-width: 0; padding: 10px 12px; display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 12px; border: 1px solid #e1ddd4; border-radius: 9px; background: #f7f5f0; }
.agent-api-endpoint dt { color: #697283; font-size: 12px; font-weight: 800; }
.agent-api-endpoint dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.agent-api-table-wrap { max-width: 100%; overflow-x: auto; border: 1px solid #e1ddd4; border-radius: 10px; }
.agent-api-table-wrap table { width: 100%; border-collapse: collapse; font-size: 12px; }
.agent-api-table-wrap th, .agent-api-table-wrap td { padding: 9px 11px; border-bottom: 1px solid #e8e4dc; text-align: left; vertical-align: top; }
.agent-api-table-wrap th { color: #596272; background: #f4f2ed; font-size: 11px; }
.agent-api-table-wrap tbody tr:last-child td { border-bottom: 0; }
.agent-api-table-wrap td:nth-child(2) { width: 82px; white-space: nowrap; }
.agent-api-example-heading { margin-top: 20px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.agent-api-example-heading h3 { margin: 0; }
.agent-api-content pre { max-width: 100%; margin: 9px 0 0; padding: 15px; overflow: auto; border-radius: 10px; color: #edf1f7; background: #172033; font: 12px/1.55 ui-monospace, 'Cascadia Code', Consolas, monospace; }
.agent-api-content pre code { white-space: pre; }
@media (max-width: 720px) {
  .agent-api-panel .panel-heading { display: grid; gap: 12px; }
  .agent-api-endpoint div { grid-template-columns: 1fr; gap: 4px; }
}
</style>
