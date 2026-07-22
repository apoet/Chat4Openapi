import { expect, test, type BrowserContext, type Route } from '@playwright/test'

const chatOrigin = 'http://127.0.0.1:4173'
const hostOrigin = 'http://127.0.0.1:4174'

function loader(publicId: string): string {
  return `(() => {
    const chatOrigin = ${JSON.stringify(chatOrigin)};
    const host = document.createElement('div'); host.dataset.chat4openapi = ${JSON.stringify(publicId)};
    const root = host.attachShadow({mode:'open'});
    const button = document.createElement('button'); button.type='button'; button.setAttribute('aria-label','Open Agent4API'); button.textContent='Chat';
    const frame = document.createElement('iframe'); frame.title='Agent4API'; frame.allow='tools'; frame.hidden=true; frame.src=chatOrigin+'/embed/${publicId}';
    button.addEventListener('click',()=>{ frame.hidden=!frame.hidden });
    const initializeFrame=()=>frame.contentWindow?.postMessage({type:'chat4openapi:init',parentOrigin:location.origin},chatOrigin);
    frame.addEventListener('load',initializeFrame);
    window.addEventListener('message',event=>{ if(event.origin!==chatOrigin || event.source!==frame.contentWindow) return; if(event.data?.type==='chat4openapi:ready') initializeFrame(); if(event.data?.type==='chat4openapi:close') frame.hidden=true });
    root.append(button,frame); document.body.append(host);
  })()`
}

function sse(events: object[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
}

function assistantEvents(text: string, run = 'run-1'): object[] {
  return [
    { type: 'RUN_STARTED', threadId: 'session-1', runId: run },
    { type: 'TEXT_MESSAGE_START', messageId: `assistant-${run}`, role: 'assistant' },
    { type: 'TEXT_MESSAGE_CONTENT', messageId: `assistant-${run}`, delta: text },
    { type: 'TEXT_MESSAGE_END', messageId: `assistant-${run}` },
    { type: 'RUN_FINISHED', threadId: 'session-1', runId: run },
  ]
}

async function mockEmbed(context: BrowserContext, publicId: string, agentHandler: (route: Route) => Promise<void>): Promise<void> {
  await context.route(`${chatOrigin}/embed/${publicId}.js`, route => route.fulfill({ contentType: 'text/javascript', body: loader(publicId) }))
  await context.route(`${chatOrigin}/api/embed/${publicId}/sessions`, route => route.fulfill({
    status: 201,
    contentType: 'application/json',
    body: JSON.stringify({ session_id: 'session-1', token: 'embed-token', parent_origin: hostOrigin, agent: { id: 7, name: 'Site Assistant' } }),
  }))
  await context.route(`${chatOrigin}/api/embed/${publicId}/agent`, agentHandler)
}

test('opens the iframe and completes a basic AG-UI conversation without WebMCP noise', async ({ context, page }) => {
  await mockEmbed(context, 'public-basic', async route => {
    await route.fulfill({ contentType: 'text/event-stream', body: sse(assistantEvents('Order 42 is ready.')) })
  })
  await page.goto('/embed-host-basic.html')
  await page.getByRole('button', { name: 'Open Agent4API' }).click()
  const widget = page.frameLocator('iframe[title="Agent4API"]')
  await expect(widget.getByText('Chat with Site Assistant')).toBeVisible()
  await widget.getByRole('textbox').fill('Show order 42')
  await widget.getByRole('button', { name: 'Send' }).click()
  await expect(widget.getByText('Order 42 is ready.')).toBeVisible()
  await expect(widget.getByText(/WebMCP.*unavailable/i)).toHaveCount(0)
})

test('exchanges a one-time popup grant and resumes the same embedded conversation', async ({ context, page }) => {
  let runs = 0
  await mockEmbed(context, 'public-basic', async route => {
    runs += 1
    const events = runs === 1 ? [
      { type: 'RUN_STARTED', threadId: 'session-1', runId: 'run-auth' },
      { type: 'CUSTOM', name: 'authorization_required', value: { api_source_id: 9, api_source_name: 'Orders', flows: ['pkce'] } },
      { type: 'RUN_FINISHED', threadId: 'session-1', runId: 'run-auth' },
    ] : assistantEvents('Authorized order details.', 'run-resumed')
    await route.fulfill({ contentType: 'text/event-stream', body: sse(events) })
  })
  await context.route(`${chatOrigin}/api/embed/sessions/session-1/auth/start`, route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({ authorization_url: `${chatOrigin}/e2e-auth-popup` }),
  }))
  await context.route(`${chatOrigin}/e2e-auth-popup`, route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><script>window.opener.postMessage({type:'chat4openapi:auth-grant',grant:'one-time-grant'},${JSON.stringify(chatOrigin)});window.close()</script>`,
  }))
  await context.route(`${chatOrigin}/api/embed/sessions/session-1/auth/exchange`, route => route.fulfill({ status: 204, body: '' }))

  await page.goto('/embed-host-basic.html')
  await page.getByRole('button', { name: 'Open Agent4API' }).click()
  const widget = page.frameLocator('iframe[title="Agent4API"]')
  await widget.getByRole('textbox').fill('Show protected order')
  await widget.getByRole('button', { name: 'Send' }).click()
  await expect(widget.getByTestId('authorize')).toBeVisible()
  await widget.getByTestId('authorize').click()
  await expect(widget.getByText('Authorized order details.')).toBeVisible()
  expect(runs).toBe(2)
})

test('executes a host WebMCP Tool when the browser exposes the draft capability', async ({ context, page }) => {
  await mockEmbed(context, 'public-webmcp', async route => {
    const body = route.request().postDataJSON() as { messages?: Array<{ role?: string }> }
    const hasResult = body.messages?.some(message => message.role === 'tool')
    const events = hasResult ? assistantEvents('Selected order 42.', 'run-result') : [
      { type: 'RUN_STARTED', threadId: 'session-1', runId: 'run-tool' },
      { type: 'TOOL_CALL_START', toolCallId: 'tool-1', toolCallName: 'web__select-order' },
      { type: 'TOOL_CALL_ARGS', toolCallId: 'tool-1', delta: '{"id":"42"}' },
      { type: 'TOOL_CALL_END', toolCallId: 'tool-1' },
      { type: 'RUN_FINISHED', threadId: 'session-1', runId: 'run-tool' },
    ]
    await route.fulfill({ contentType: 'text/event-stream', body: sse(events) })
  })
  await page.goto('/embed-host-webmcp.html')
  const supported = await page.evaluate(() => (window as Window & { webMcpRegistration?: Promise<boolean> }).webMcpRegistration)
  test.skip(!supported, 'Bundled Chromium does not expose the draft WebMCP API')
  await page.getByRole('button', { name: 'Open Agent4API' }).click()
  const widget = page.frameLocator('iframe[title="Agent4API"]')
  await widget.getByRole('textbox').fill('Select order 42')
  await widget.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('#selected-order')).toHaveText('42')
})
