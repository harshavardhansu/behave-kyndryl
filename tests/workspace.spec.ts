import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'

const routes = [
  ['/', 'Command centre'],
  ['/incidents', 'Issues & incidents'],
  ['/war-room', 'AI War Room'],
  ['/investigations', 'Root cause analysis'],
  ['/agents', 'Agent orchestration'],
  ['/repositories', 'Project & repositories'],
  ['/testing', 'Testing & validation'],
  ['/security', 'Security centre'],
  ['/changes', 'Change & release'],
  ['/observability', 'Observability & logs'],
  ['/knowledge', 'Knowledge centre'],
  ['/reports', 'Reports & analytics'],
  ['/audit', 'Audit trail'],
  ['/administration', 'Administration'],
] as const

async function openWorkspace(page: Page, path = '/') {
  await page.goto(path, { waitUntil: 'commit' })
  await expect(page.locator('.global-header')).toBeVisible()
}

async function navigate(page: Page, path: string) {
  if ((await page.viewportSize())!.width < 1100) {
    await page.getByRole('button', { name: 'Toggle navigation', exact: true }).click()
  }
  await page.locator(`.sidebar a[href="${path}"]`).click()
}

async function changeRole(page: Page, role: string) {
  await page.getByRole('button', { name: /^Profile:/ }).click()
  await page.getByRole('menuitem', { name: role, exact: true }).click()
  await expect(page.locator('.toast-stack')).toContainText(`(${role})`)
}

async function confirmAction(page: Page, trigger: string, confirmation: string) {
  await page.getByRole('button', { name: trigger, exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: confirmation, exact: true }).click()
  await expect(dialog).not.toBeVisible()
}

async function screenshotPixelSummary(page: Page, screenshot: Buffer) {
  return page.evaluate(async (encodedImage) => {
    const image = new Image()
    image.src = `data:image/png;base64,${encodedImage}`
    await image.decode()
    const probe = document.createElement('canvas')
    probe.width = image.width
    probe.height = image.height
    const context = probe.getContext('2d', { willReadFrequently: true })!
    context.drawImage(image, 0, 0)
    const pixels = context.getImageData(0, 0, image.width, image.height).data
    let redPixels = 0
    let nonBackgroundPixels = 0
    for (let offset = 0; offset < pixels.length; offset += 4) {
      const red = pixels[offset]
      const green = pixels[offset + 1]
      const blue = pixels[offset + 2]
      if (red > 130 && red > green * 1.35 && red > blue * 1.25) redPixels += 1
      // Background is the light workforce stage colour (#f4f6f6).
      if (Math.abs(red - 244) + Math.abs(green - 246) + Math.abs(blue - 246) > 45) nonBackgroundPixels += 1
    }
    return { width: image.width, height: image.height, redPixels, nonBackgroundPixels }
  }, screenshot.toString('base64'))
}

test('all 14 modules navigate without runtime errors and keep the Kyndryl Bridge theme', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`) })
  await openWorkspace(page)
  await expect(page).toHaveTitle('BEHAVE KYNDRYL')
  await expect(page.getByRole('link', { name: 'BEHAVE KYNDRYL command centre', exact: true })).toHaveText('behave kyndryl')
  await expect(page.locator('.workspace-footer')).toContainText('BEHAVE KYNDRYL')
  const schema = await (await page.request.get('/api/openapi.json')).json()
  expect(schema.info.title).toBe('BEHAVE KYNDRYL API')
  await expect(page.locator('.global-header')).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(page.locator('.global-header .brand-kyndryl')).toHaveCSS('color', 'rgb(255, 70, 45)')
  for (const [path, title] of routes) {
    await navigate(page, path)
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `Horizontal overflow on ${path}`).toBe(true)
  }
  expect(errors).toEqual([])
})

test('graph nodes, edges, health filters, zoom and reset are interactive', async ({ page }) => {
  await openWorkspace(page, '/war-room')
  await page.getByRole('button', { name: /XY Flow/ }).click()
  await expect(page.locator('.react-flow__node')).toHaveCount(15)
  await page.locator('.react-flow__node[data-id="checkout-svc"]').click()
  await expect(page.locator('.inspector-identity h3')).toHaveText('checkout-svc')
  await page.locator('.react-flow__edge[data-id="DEP-EDGE-10"]').dispatchEvent('click')
  await expect(page.getByRole('tab', { name: 'Dependency', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.edge-endpoints')).toContainText('rds-proxy')
  const before = await page.locator('.react-flow__viewport').getAttribute('style')
  await page.getByRole('button', { name: 'Zoom In', exact: true }).click()
  await expect(page.locator('.react-flow__viewport')).not.toHaveAttribute('style', before!)
  await page.getByRole('button', { name: 'Graph filters', exact: true }).click()
  await page.getByRole('combobox', { name: 'Graph health filter' }).selectOption('Critical')
  await expect(page.locator('.react-flow__node')).toHaveCount(1)
  await page.getByRole('button', { name: 'Reset graph layout' }).click()
  await expect(page.locator('.react-flow__node')).toHaveCount(15)
  await page.getByRole('textbox', { name: 'Search graph services' }).fill('Redis')
  await page.getByRole('textbox', { name: 'Search graph services' }).press('Enter')
  await expect(page.locator('.inspector-identity h3')).toHaveText('Redis cache')
})

test('War Room agent mission forms a team and stops at every human decision', async ({ page }) => {
  await openWorkspace(page, '/war-room')
  await expect(page.getByRole('button', { name: 'Command view' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.cmd-hub .workforce-core-label')).toContainText('ORCHESTRATOR')
  await expect(page.locator('.workforce-truth-row')).toContainText('SIMULATED')
  await expect(page.locator('.cmd-squad')).toHaveCount(4)
  await expect(page.locator('.mission-empty')).toContainText('No agent mission yet')
  const stagePixels = await screenshotPixelSummary(page, await page.locator('.cmd-stage').screenshot({ animations: 'disabled' }))
  expect(stagePixels.width).toBeGreaterThan(600)
  expect(stagePixels.redPixels).toBeGreaterThan(0)

  await page.getByRole('button', { name: 'Start agent mission' }).click()
  const gate = page.locator('.mission-gate')
  await expect(gate).toContainText('Approve the team for iteration 1')
  const proposed = await page.locator('.cmd-member:not(.is-skipped)').count()
  expect(proposed).toBeGreaterThan(0)
  expect(proposed).toBeLessThan(13)
  await expect(page.locator('.cmd-member.is-skipped').first()).toBeVisible()
  await expect(page.locator('.cmd-hub .workforce-core-label')).toContainText('awaiting approval')
  await expect(page.locator('.mission-feed')).toContainText('Proposed a team of')

  await gate.getByRole('button', { name: 'Approve team' }).click()
  await expect(gate).toContainText('Approve the root cause', { timeout: 20_000 })
  await expect(page.locator('.cmd-state.is-done').first()).toBeVisible()
  await page.locator('.cmd-member').filter({ hasText: 'Log analysis' }).click()
  await expect(page.getByRole('tab', { name: 'Agent', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.workforce-agent-inspector')).toContainText('EVD-301')

  await gate.getByRole('button', { name: 'Approve root cause' }).click()
  await expect(gate).toContainText('Approve the fix for release', { timeout: 20_000 })
  await expect(page.locator('.mission-gate-blocked')).toContainText('Separation of duties')
  await expect(gate.getByRole('button', { name: 'Approve fix' })).toBeDisabled()

  await page.getByRole('button', { name: '2D list' }).click()
  await expect(page.locator('.workforce-list-agent')).toHaveCount(proposed + 1)
  await page.getByRole('button', { name: 'Cancel mission' }).click()
  await expect(page.locator('.mission-empty')).toContainText('Last mission cancelled')
})

test('War Room command search highlights matches and selects an agent', async ({ page }) => {
  await openWorkspace(page, '/war-room')
  await page.getByRole('button', { name: 'Start agent mission' }).click()
  await expect(page.locator('.mission-gate')).toContainText('Approve the team')
  const search = page.getByRole('textbox', { name: 'Search the workforce' })
  await search.fill('root')
  await expect(page.locator('.cmd-member:not(.is-skipped)').filter({ hasText: 'Log analysis' })).toHaveClass(/is-dim/)
  await expect(page.locator('.cmd-member').filter({ hasText: 'Root-cause analysis' })).not.toHaveClass(/is-dim/)
  await search.press('Enter')
  await expect(page.getByRole('tab', { name: 'Agent', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.workforce-agent-inspector')).toContainText('Root-cause analysis')
  await page.getByRole('combobox', { name: 'Filter workforce by status' }).selectOption('Completed')
  await search.fill('')
  await expect(page.locator('.cmd-member.is-dim').first()).toBeVisible()
  await page.getByRole('button', { name: 'Cancel mission' }).click()
  await expect(page.locator('.mission-empty')).toBeVisible()
})

test('incident intake validates input and uploads redacted evidence', async ({ page }) => {
  await openWorkspace(page, '/incidents')
  await page.getByRole('button', { name: 'Create incident', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Create incident', exact: true }).click()
  await expect(dialog).toBeVisible()
  await dialog.getByLabel(/Issue title/).fill('Browser test checkout incident')
  await dialog.getByLabel(/^Description/).fill('A synthetic browser-test report with enough context to investigate the observed checkout failure.')
  await dialog.getByLabel(/Business impact/).fill('Synthetic checkout transactions are blocked in this test.')
  await dialog.getByRole('button', { name: 'Create incident', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Browser test checkout incident' })).toBeVisible()
  await page.getByRole('button', { name: 'Add evidence', exact: true }).first().click()
  const evidenceDialog = page.getByRole('dialog')
  await evidenceDialog.getByLabel('Choose evidence file').setInputFiles({ name: 'unsafe.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('not an executable') })
  await expect(evidenceDialog).toContainText('Unsupported file type')
  await evidenceDialog.getByLabel('Choose evidence file').setInputFiles({ name: 'browser-evidence.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ timestamp: '2026-10-30T10:00:00Z', message: 'password=synthetic-sensitive-placeholder checkout connection timeout', level: 'ERROR', traceId: 'browser-trace' })) })
  await evidenceDialog.getByRole('button', { name: 'Attach evidence', exact: true }).click()
  await expect(evidenceDialog).not.toBeVisible()
  await page.getByRole('tab', { name: 'Evidence', exact: true }).click()
  await page.getByRole('button', { name: /Imported evidence: browser-evidence.json/ }).click()
  await expect(page.getByRole('dialog')).toContainText('[REDACTED]')
  await expect(page.getByRole('dialog')).not.toContainText('synthetic-sensitive-placeholder')
})

test('Payment API sandbox incidents create the bounded recovery proposal', async ({ page }) => {
  await openWorkspace(page, '/incidents')
  await page.getByRole('button', { name: 'Create incident', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(/Issue title/).fill('Browser test Payment API sandbox intake')
  await dialog.getByLabel(/^Description/).fill('Synthetic browser-test report for Payment API summary requests in the sandbox.')
  await dialog.getByLabel(/Business impact/).fill('Synthetic browser test creates a sandbox-only incident record.')
  await dialog.getByRole('combobox', { name: 'Incident environment' }).selectOption('Sandbox')
  await dialog.getByRole('combobox', { name: 'Affected service' }).selectOption('payment-api')
  await dialog.getByRole('button', { name: 'Create incident', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Browser test Payment API sandbox intake' })).toBeVisible()
  const snapshot = await (await page.request.get('/api/v1/workspace')).json()
  const incident = snapshot.incidents.find((item: { title: string }) => item.title === 'Browser test Payment API sandbox intake')
  const change = snapshot.changes.find((item: { incidentId: string }) => item.incidentId === incident.id)
  expect(incident.environment).toBe('Sandbox')
  expect(incident.service).toBe('payment-api')
  expect(change.sandboxAction).toEqual({ release: '3.8.1', pool_size: 20 })
})

test('checkout workflow pauses, resumes, validates, obtains separate approval and closes', async ({ page }) => {
  await openWorkspace(page, '/war-room')
  await page.getByRole('combobox', { name: 'Selected incident', exact: true }).selectOption('INC-1042')
  await confirmAction(page, 'Investigate incident', 'Start investigation')
  await navigate(page, '/agents')
  await confirmAction(page, 'Pause', 'Pause workflow')
  await expect(page.getByRole('button', { name: 'Resume', exact: true })).toBeEnabled()
  await confirmAction(page, 'Resume', 'Resume workflow')
  await expect.poll(async () => {
    const snapshot = await (await page.request.get('/api/v1/workspace')).json()
    return snapshot.incidents.find((incident: { id: string }) => incident.id === 'INC-1042').status
  }).toBe('Fix Proposed')
  await navigate(page, '/testing')
  await confirmAction(page, 'Replay validation', 'Replay validation')
  await expect(page.getByText('Checkout remediation validation', { exact: true })).toBeVisible()
  await navigate(page, '/changes')
  await confirmAction(page, 'Request approval', 'Request approval')
  await expect(page.getByRole('button', { name: 'Review approval', exact: true })).toBeDisabled()
  await changeRole(page, 'Change Approver')
  await page.getByRole('button', { name: 'Review approval', exact: true }).click()
  await page.getByRole('dialog').getByRole('checkbox').check()
  await page.getByRole('dialog').getByRole('button', { name: 'Approve change', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Simulate deployment', exact: true })).toBeDisabled()
  await changeRole(page, 'Incident Manager')
  await page.getByRole('button', { name: 'Simulate deployment', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Simulate deployment', exact: true })).toBeDisabled()
  await page.getByRole('dialog').getByLabel(/Type Production/).fill('Production')
  await page.getByRole('dialog').getByRole('button', { name: 'Simulate deployment', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await confirmAction(page, 'Verify recovery', 'Verify recovery')
  await page.getByRole('button', { name: 'Close incident', exact: true }).click()
  await page.getByRole('dialog').getByLabel('Verified outcome').fill('Synthetic recovery verified against the defined error and latency budgets; separate human review completed.')
  await page.getByRole('dialog').getByRole('button', { name: 'Close incident', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Reopen incident', exact: true })).toBeVisible()
  await navigate(page, '/knowledge')
  await page.getByRole('tab', { name: 'Drafts', exact: true }).click()
  await expect(page.getByRole('button', { name: /Resolution draft: Checkout failures/ })).toBeVisible()
  await navigate(page, '/audit')
  await page.getByRole('textbox', { name: 'Search identity, action, resource or correlation' }).fill('close')
  await expect(page.locator('tbody')).toContainText('INC-1042')
})

test('viewer authorization and environment confirmation are enforced', async ({ page }) => {
  await openWorkspace(page, '/incidents')
  await changeRole(page, 'Viewer')
  await expect(page.getByRole('button', { name: 'Create incident', exact: true })).toBeDisabled()
  const session = await (await page.request.get('/api/v1/auth/session')).json()
  const response = await page.request.post('/api/v1/incidents/INC-1042/actions', { data: { action: 'assign', owner: 'James Wilson' }, headers: { 'X-CSRF-Token': session.csrf, 'Idempotency-Key': crypto.randomUUID() } })
  expect(response.status()).toBe(403)
  expect((await response.json()).detail).toContain('Viewer')
  await page.getByRole('combobox', { name: 'Global environment' }).selectOption('Development')
  await expect(page.locator('select[aria-label="Global environment"]')).toHaveValue('Production')
  await page.getByRole('dialog').getByRole('button', { name: 'Change view' }).click()
  await expect(page.getByRole('combobox', { name: 'Global environment' })).toHaveValue('Development')
  await expect(page.getByRole('button', { name: 'Create incident', exact: true })).toBeDisabled()
})

test('search, table filters, export and explicit integration errors work', async ({ page }) => {
  await openWorkspace(page)
  await page.getByRole('button', { name: 'Search your workspace' }).click()
  await page.getByRole('textbox', { name: 'Search by name, incident ID or service' }).fill('INC-1041')
  await page.getByRole('dialog').getByRole('button', { name: /Elevated latency on payment authorization/ }).click()
  await expect(page.getByRole('heading', { name: 'Elevated latency on payment authorization' })).toBeVisible()
  await navigate(page, '/observability')
  await page.getByRole('combobox', { name: 'Log severity filter' }).selectOption('ERROR')
  await page.getByRole('textbox', { name: 'Search log messages, services or trace IDs' }).fill('no-such-record')
  await expect(page.getByRole('heading', { name: 'No matching log records' })).toBeVisible()
  await navigate(page, '/repositories')
  await page.getByRole('button', { name: 'Analyse project', exact: true }).click()
  await page.getByRole('dialog').getByRole('combobox', { name: 'Analysis source' }).selectOption('repository')
  await page.getByRole('dialog').getByLabel('Repository URL').fill('https://example.invalid/authorized-repo')
  await page.getByRole('dialog').getByRole('checkbox', { name: /I am authorized/ }).check()
  await page.getByRole('dialog').getByRole('button', { name: 'Analyse project', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Repository adapter not configured')
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await navigate(page, '/reports')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export environment records' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('BEHAVE KYNDRYL-workspace.json')
})

test('API failure is explicit and recoverable', async ({ page }) => {
  await page.route('**/api/v1/workspace', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Temporary API outage for the failure-state test.' }) }))
  await page.goto('/', { waitUntil: 'commit' })
  await expect(page.getByText('Workspace unavailable', { exact: true })).toBeVisible()
  await expect(page.locator('.loading-brand')).toHaveText('behave kyndryl')
  await expect(page.getByRole('button', { name: 'Retry connection' })).toBeVisible()
  await page.unroute('**/api/v1/workspace')
  await page.getByRole('button', { name: 'Retry connection' }).click()
  await expect(page.getByRole('heading', { name: 'Command centre' })).toBeVisible()
})

test('sign-in displays the behave kyndryl wordmark on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(() => sessionStorage.setItem('agentica-signed-out', 'true'))
  await page.goto('/', { waitUntil: 'commit' })
  await expect(page.getByRole('heading', { name: 'Workspace access' })).toBeVisible()
  await expect(page.locator('.loading-brand')).toHaveText('behave kyndryl')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
})

test('desktop, tablet and mobile layouts stay within the viewport', async ({ page }, testInfo) => {
  await openWorkspace(page)
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 820, height: 1180 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    for (const [path, title] of routes) {
      await navigate(page, path)
      await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible()
      if (path === '/war-room') {
        if (viewport.width <= 820) await expect(page.locator('.cmd-compact .cmd-card').first()).toBeVisible()
        else await expect(page.locator('.cmd-card')).toHaveCount(4)
        await expect(page.locator('.mission-panel')).toBeVisible()
        await expect(page.locator('.cmd-hub')).toBeVisible()
      }
      const overflow = await page.evaluate(() => ({
        width: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        elements: Array.from(document.querySelectorAll('main *')).filter(element => {
          const bounds = element.getBoundingClientRect()
          return bounds.right > innerWidth + 1 && !element.closest('.table-scroll, .react-flow, .workflow-steps, .tabs, .event-timeline-horizontal, .knowledge-list, .pipeline-sidebar ol')
        }).slice(0, 5).map(element => `${element.tagName}.${element.className}`),
      }))
      expect.soft(overflow.documentWidth <= viewport.width + 1, `Overflow at ${viewport.width}px on ${path}: ${JSON.stringify(overflow)}`).toBe(true)
      if (path === '/' || path === '/war-room') {
        await page.screenshot({ path: testInfo.outputPath(`${viewport.width}-${path === '/' ? 'command-centre' : 'war-room'}.png`), fullPage: true, animations: 'disabled' })
      }
    }
  }
})