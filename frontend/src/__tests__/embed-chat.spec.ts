// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '../i18n'
import EmbedChatView from '../views/EmbedChatView.vue'

const mocks = vi.hoisted(() => ({
  runAgent: vi.fn(async () => ({ result: null, newMessages: [] })),
  addMessage: vi.fn(),
  abortRun: vi.fn(),
  discoverWebMcpTools: vi.fn(async () => []),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { publicId: 'public-id' } }),
}))

vi.mock('../embed/agent', () => ({
  createEmbedAgent: () => ({
    state: {},
    messages: [],
    runAgent: mocks.runAgent,
    addMessage: mocks.addMessage,
    abortRun: mocks.abortRun,
  }),
}))

vi.mock('../embed/webmcp', () => ({
  discoverWebMcpTools: mocks.discoverWebMcpTools,
  executeWebMcpTool: vi.fn(),
  observeWebMcpToolChanges: () => () => undefined,
}))

function sessionResponse(): Response {
  return new Response(JSON.stringify({
    session_id: 'session-id',
    token: 'embed-token',
    parent_origin: 'https://host.example',
    agent: { id: 7, name: 'Site Assistant' },
  }), { status: 201, headers: { 'Content-Type': 'application/json' } })
}

async function mountEmbed() {
  const wrapper = mount(EmbedChatView, { global: { plugins: [i18n] } })
  window.dispatchEvent(new MessageEvent('message', {
    origin: 'https://host.example',
    source: window,
    data: { type: 'chat4openapi:init', parentOrigin: 'https://host.example' },
  }))
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  mocks.runAgent.mockClear()
  mocks.addMessage.mockClear()
  mocks.abortRun.mockClear()
  mocks.discoverWebMcpTools.mockClear()
  sessionStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async () => sessionResponse()))
})

describe('embedded Agent Chat', () => {
  it('renders the bound Agent without an Agent selector', async () => {
    const wrapper = await mountEmbed()

    expect(wrapper.text()).toContain('Site Assistant')
    expect(wrapper.find('[data-testid="agent-select"]').exists()).toBe(false)
    expect(sessionStorage.getItem('chat4openapi.embed.public-id')).toBe('embed-token')
  })

  it('stays silent when WebMCP is unavailable', async () => {
    const wrapper = await mountEmbed()

    expect(mocks.discoverWebMcpTools).toHaveBeenCalledWith('https://host.example')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('sends a message through the fixed embedded Agent', async () => {
    const wrapper = await mountEmbed()
    await wrapper.get('textarea').setValue('Show order 42')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.addMessage).toHaveBeenCalledWith(expect.objectContaining({
      role: 'user',
      content: 'Show order 42',
    }))
    expect(mocks.runAgent).toHaveBeenCalledWith(
      { tools: [] },
      expect.objectContaining({ onTextMessageEndEvent: expect.any(Function) }),
    )
  })
})
