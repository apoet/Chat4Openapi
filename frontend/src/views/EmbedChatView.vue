<script setup lang="ts">
import type { AgentSubscriber } from '@ag-ui/client'
import type { Message, Tool } from '@ag-ui/core'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import EmbedChatPanel from '../components/EmbedChatPanel.vue'
import { createEmbedAgent } from '../embed/agent'
import {
  discoverWebMcpTools,
  executeWebMcpTool,
  observeWebMcpToolChanges,
} from '../embed/webmcp'

type SessionResponse = {
  session_id: string
  token: string
  parent_origin: string
  agent: { id: number; name: string }
}

type DisplayMessage = { id: string; role: 'user' | 'assistant'; content: string }
type PendingTool = { id: string; name: string; args: Record<string, unknown> }

const route = useRoute()
const { t } = useI18n()
const publicId = String(route.params.publicId)
const agentName = ref('')
const draft = ref('')
const ready = ref(false)
const sending = ref(false)
const error = ref('')
const messages = ref<DisplayMessage[]>([])
let parentOrigin = ''
let agent: ReturnType<typeof createEmbedAgent> | null = null
let tools: Tool[] = []
let pendingTool: PendingTool | null = null
let stopObserving: () => void = () => undefined
let initializing = false

function id(): string {
  return globalThis.crypto?.randomUUID?.() ?? `embed-${Date.now()}-${Math.random()}`
}

function isSessionResponse(value: unknown): value is SessionResponse {
  if (!value || typeof value !== 'object') return false
  const data = value as Partial<SessionResponse>
  return typeof data.session_id === 'string'
    && typeof data.token === 'string'
    && typeof data.parent_origin === 'string'
    && !!data.agent
    && typeof data.agent.id === 'number'
    && typeof data.agent.name === 'string'
}

async function initialize(origin: string): Promise<void> {
  if (initializing || ready.value) return
  initializing = true
  try {
    const response = await fetch(`/api/embed/${encodeURIComponent(publicId)}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent_origin: origin }),
    })
    const body: unknown = await response.json()
    if (!response.ok || !isSessionResponse(body) || body.parent_origin !== origin) {
      throw new Error('embed.unavailable')
    }
    parentOrigin = origin
    agentName.value = body.agent.name
    sessionStorage.setItem(`chat4openapi.embed.${publicId}`, body.token)
    agent = createEmbedAgent({
      url: `/api/embed/${encodeURIComponent(publicId)}/agent`,
      agentId: String(body.agent.id),
      threadId: body.session_id,
      token: body.token,
    })
    tools = await discoverWebMcpTools(parentOrigin)
    stopObserving = observeWebMcpToolChanges(parentOrigin, (available) => { tools = available })
    ready.value = true
  } catch {
    error.value = t('embed.unavailable')
  } finally {
    initializing = false
  }
}

function handleParentMessage(event: MessageEvent): void {
  if (event.source !== window.parent || !event.data || typeof event.data !== 'object') return
  const data = event.data as { type?: unknown; parentOrigin?: unknown }
  if (
    data.type !== 'chat4openapi:init'
    || typeof data.parentOrigin !== 'string'
    || data.parentOrigin !== event.origin
  ) return
  void initialize(event.origin)
}

const subscriber: AgentSubscriber = {
  onTextMessageEndEvent({ textMessageBuffer }) {
    if (textMessageBuffer) {
      messages.value.push({ id: id(), role: 'assistant', content: textMessageBuffer })
    }
  },
  onToolCallEndEvent({ event, toolCallName, toolCallArgs }) {
    pendingTool = { id: event.toolCallId, name: toolCallName, args: toolCallArgs }
  },
  onCustomEvent({ event }) {
    if (
      event.name === 'chat4openapi:conversation'
      && event.value
      && typeof event.value === 'object'
      && typeof (event.value as { conversationId?: unknown }).conversationId === 'string'
      && agent
    ) {
      agent.setState({
        ...agent.state,
        conversationId: (event.value as { conversationId: string }).conversationId,
      })
    }
  },
  onRunErrorEvent() {
    error.value = t('embed.failed')
  },
}

function takePendingTool(): PendingTool | null {
  const selected = pendingTool
  pendingTool = null
  return selected
}

async function runUntilSettled(): Promise<void> {
  if (!agent) return
  for (let iteration = 0; iteration < 8; iteration += 1) {
    pendingTool = null
    tools = await discoverWebMcpTools(parentOrigin)
    await agent.runAgent({ tools }, subscriber)
    const selected = takePendingTool()
    if (!selected) return
    let content: string
    let toolError: string | undefined
    try {
      content = await executeWebMcpTool(selected.name, selected.args)
    } catch (caught) {
      toolError = caught instanceof Error ? caught.message : 'frontend_tool_failed'
      content = JSON.stringify({ error: toolError, tool: selected.name })
    }
    const toolMessage: Message = {
      id: id(),
      role: 'tool',
      toolCallId: selected.id,
      content,
      ...(toolError ? { error: toolError } : {}),
    }
    agent.addMessage(toolMessage)
  }
  throw new Error('frontend_tool_iteration_limit')
}

async function send(): Promise<void> {
  const content = draft.value.trim()
  if (!content || !agent || sending.value) return
  error.value = ''
  draft.value = ''
  messages.value.push({ id: id(), role: 'user', content })
  agent.addMessage({ id: id(), role: 'user', content })
  sending.value = true
  try {
    await runUntilSettled()
  } catch {
    error.value = t('embed.failed')
  } finally {
    sending.value = false
  }
}

function cancel(): void {
  agent?.abortRun()
  sending.value = false
}

function close(): void {
  if (parentOrigin) window.parent.postMessage({ type: 'chat4openapi:close' }, parentOrigin)
}

onMounted(() => window.addEventListener('message', handleParentMessage))
onBeforeUnmount(() => {
  window.removeEventListener('message', handleParentMessage)
  stopObserving()
  agent?.abortRun()
})
</script>

<template>
  <EmbedChatPanel
    v-model:draft="draft"
    :agent-name="agentName"
    :messages="messages"
    :ready="ready"
    :sending="sending"
    :error="error"
    @send="send"
    @cancel="cancel"
    @close="close"
  />
</template>
