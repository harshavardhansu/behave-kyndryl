import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'

/**
 * The War Room draws whatever squads the backend publishes (workspace `missionSteps`), not a fixed four.
 * A real mission is started, then the workspace response is rewritten to a bigger engine: 6 squads,
 * 15 agents (one squad of 6) and one role that belongs to no squad.
 */
const BIG_ENGINE = [
  { id: 'investigate', name: 'Investigate', roles: ['intake', 'logs', 'observability', 'repository', 'triage', 'forensics'] },
  { id: 'diagnose', name: 'Diagnose', roles: ['knowledge', 'root-cause'] },
  { id: 'remediate', name: 'Remediate', roles: ['remediation', 'testing'] },
  { id: 'validate', name: 'Validate', roles: ['security', 'validation'] },
  { id: 'govern', name: 'Govern', roles: ['risk'] },
  { id: 'release', name: 'Release', roles: ['release', 'summary'] },
]
const EXTRA_NAMES: Record<string, string> = { triage: 'Triage', forensics: 'Forensics', 'chaos-monkey': 'Chaos monkey' }

async function startMissionWithTeam(page: Page) {
  // Use INC-1040 so this test never touches the incident the other War Room tests rely on (INC-1042).
  await page.addInitScript(() => localStorage.setItem('agentica-incident', 'INC-1040'))
  await page.goto('/war-room', { waitUntil: 'commit' })
  await expect(page.locator('.global-header')).toBeVisible()
  await page.getByRole('button', { name: 'Start agent mission' }).click()
  const gate = page.locator('.mission-gate')
  await expect(gate).toContainText('Approve the team for iteration 1')
  await gate.getByRole('button', { name: 'Approve team' }).click()
  await expect(gate).toContainText('Approve the root cause', { timeout: 20_000 })
}

async function useBigEngine(page: Page) {
  await page.route('**/api/v1/workspace', async (route) => {
    const response = await route.fetch()
    const workspace = await response.json()
    workspace.missionSteps = BIG_ENGINE
    const mission = [...workspace.missions].sort((a: { createdAt: string }, b: { createdAt: string }) => b.createdAt.localeCompare(a.createdAt))[0]
    const iteration = mission.iterations[mission.iterations.length - 1]
    const template = iteration.team[0]
    const roles = [...BIG_ENGINE.flatMap((step) => step.roles.map((role) => ({ role, step: step.id }))), { role: 'chaos-monkey', step: 'other' }]
    iteration.team = roles.map(({ role, step }, index) => {
      const existing = iteration.team.find((member: { role: string }) => member.role === role)
      return {
        ...template,
        ...(existing ?? {}),
        id: existing?.id ?? `${mission.id}-1-${role}`,
        role,
        step,
        name: existing?.name ?? EXTRA_NAMES[role] ?? role,
        status: existing?.status ?? (index % 3 === 0 ? 'Running' : 'Completed'),
      }
    })
    iteration.skipped = [] // every role is on this team now, so none is left out
    await route.fulfill({ response, json: workspace })
  })
  await page.reload({ waitUntil: 'commit' })
  await expect(page.locator('.global-header')).toBeVisible()
}

function overlaps(a: { x: number; y: number; width: number; height: number }, b: { x: number; y: number; width: number; height: number }) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

test('War Room lays out any number of squads without overlap', async ({ page }) => {
  await startMissionWithTeam(page)
  await expect(page.locator('.cmd-squad')).toHaveCount(4) // the real engine today
  await expect(page.locator('.cmd-squad-pill i')).toHaveText(['1', '2', '3', '4'])

  await useBigEngine(page)
  const squads = page.locator('.cmd-stage .cmd-squad')
  await expect(squads).toHaveCount(7) // 6 published squads + "Other specialists" for the unknown role
  await expect(page.locator('.cmd-squad-pill i')).toHaveText(['1', '2', '3', '4', '5', '6', '7'])
  await expect(page.locator('.cmd-card').filter({ hasText: 'Other specialists' })).toContainText('Chaos monkey')

  // Let the fly-in animations finish, then check geometry.
  const slots = page.locator('.cmd-card-slot')
  await expect(slots).toHaveCount(7)
  await expect.poll(async () => slots.last().evaluate((element) => getComputedStyle(element).opacity)).toBe('1')
  const stage = (await page.locator('.cmd-stage').boundingBox())!
  expect(stage.height).toBeGreaterThanOrEqual(900) // 4 rows on the left column: the stage grew instead of overlapping
  const boxes = await slots.evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect()
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  }))
  for (const [index, box] of boxes.entries()) {
    expect(box.y, `card ${index + 1} starts inside the stage`).toBeGreaterThanOrEqual(stage.y - 1)
    expect(box.y + box.height, `card ${index + 1} ends inside the stage`).toBeLessThanOrEqual(stage.y + stage.height + 1)
    for (const other of boxes.slice(index + 1)) expect(overlaps(box, other), `cards ${index + 1} overlap`).toBe(false)
  }
  const hub = (await page.locator('.cmd-hub').boundingBox())!
  for (const box of boxes) expect(overlaps(box, hub)).toBe(false)

  // A squad of 6 shows 3 agents and "+3 more"; expanding keeps the card's height budget (scrolls inside).
  const investigate = page.locator('.cmd-card').filter({ hasText: 'Detection & evidence' })
  await expect(investigate.getByRole('button', { name: /Show 3 more agents/ })).toBeVisible()
  const before = (await investigate.boundingBox())!.height
  await investigate.getByRole('button', { name: /Show 3 more agents/ }).click()
  await expect(investigate.locator('.cmd-member').filter({ hasText: 'Forensics' })).toBeAttached()
  expect((await investigate.boundingBox())!.height).toBeLessThan(before + 60)
  await page.locator('.cmd-stage').screenshot({ path: 'test-results/war-room-7-squads.png', animations: 'disabled' })

  // Phones get one row per squad, all 7 of them.
  await page.setViewportSize({ width: 390, height: 900 })
  await expect(page.locator('.cmd-compact-row')).toHaveCount(7)
  await page.locator('.cmd-stage').screenshot({ path: 'test-results/war-room-7-squads-mobile.png', animations: 'disabled' })

  // Leave the shared test workspace as we found it.
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: 'Cancel mission' }).click()
  await expect(page.locator('.toast-stack')).toContainText('Mission cancelled')
})
