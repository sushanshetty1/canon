// Every take the video uses, scripted. Run: node capture/run.mjs <take> [<take> ...]   (or `all`)
//
// Public takes record https://canon.sushans.dev. Signed-in takes record the local stack (see video/README.md):
// the API on :8798 with development sign-in and a copy of the PostHog graph as the workspace `posthog-v`, and Vite
// on :4198.

import fs from 'node:fs'
import path from 'node:path'
import { LOCAL, PROD, Take, localSignIn, open, showAsGitHub } from './lib.mjs'

const settle = (page, ms = 600) => page.waitForTimeout(ms)

/** Wait until an answer has every verdict: the summary line under it appears. */
async function answered(page, timeout = 90000) {
  await page.getByText(/Checked:|verified|disputed|removed/).last().waitFor({ timeout }).catch(() => {})
  await page.waitForFunction(() => /Checked:/.test(document.body.innerText) || /\d+ verified/.test(document.body.innerText), null, { timeout })
}

export const TAKES = {
  /** The landing page: the hero's knowledge timeline, then the sections below it. */
  async landing() {
    const s = await open()
    const { page } = s
    await page.goto('about:blank')
    await page.evaluate(() => (document.body.style.background = '#e8e9ec'))
    const t = new Take(s, 'landing')
    await t.start()
    t.log('hide-cursor')
    await page.goto(PROD + '/', { waitUntil: 'load' })
    t.log('loaded')
    await t.mark('headline', page.locator('h1'))
    await t.wait(5200)
    await t.mark('timeline', page.getByText('Who owns session replay').locator('xpath=ancestor::div[contains(@class,"relative")][2]'))
    await t.wait(800)
    // What Canon reads
    const reads = page.getByRole('heading', { name: /What Canon reads/ })
    const y1 = await reads.evaluate((el) => el.getBoundingClientRect().top + scrollY - 90)
    await t.scroll(y1, 2200, { x: 800, y: 450 })
    t.log('section', { name: 'reads' })
    await t.wait(4500)
    const check = page.getByRole('heading', { name: /One sentence/ })
    const y2 = await check.evaluate((el) => el.getBoundingClientRect().top + scrollY - 70)
    await t.scroll(y2 - (await page.evaluate(() => scrollY)), 2200, { x: 800, y: 450 })
    t.log('section', { name: 'check' })
    await t.wait(7500)
    const product = page.getByRole('heading', { name: /What a team asks/ })
    const y3 = await product.evaluate((el) => el.getBoundingClientRect().top + scrollY - 70)
    await t.scroll(y3 - (await page.evaluate(() => scrollY)), 2200, { x: 800, y: 450 })
    t.log('section', { name: 'product' })
    await t.wait(3500)
    await t.stop()
    await s.browser.close()
  },

  /** Ask: a verified answer, its source and the fact's history, and the sentence the check removed. */
  async ask() {
    const s = await open()
    const { page } = s
    await page.goto(PROD + '/app', { waitUntil: 'load' })
    await settle(page, 2500)
    const t = new Take(s, 'ask')
    await t.start()
    await t.wait(900)
    const suggestion = page.getByRole('button', { name: 'Which team owns the MCP server?' })
    await t.mark('suggestions', page.getByText('Try', { exact: true }).locator('xpath=..'))
    await t.click(suggestion, { label: 'suggestion' })
    t.log('asked')
    await answered(page)
    t.log('answered')
    await t.wait(1400)
    const first = page.locator('[role=button]').filter({ hasText: 'owns the MCP server' }).first()
    await t.mark('answer', page.locator('h1').locator('xpath=..').locator('xpath=..'))
    await t.mark('sentence1', first)
    await t.wait(600)
    await t.click(first, { at: 0.35, label: 'sentence' })
    await t.wait(1600)
    const panel = page.locator('aside[aria-labelledby="panel-title"]').first()
    await t.mark('panel', panel)
    await t.wait(2200)
    const history = page.locator('section[aria-labelledby="fact-history"]')
    if (await history.count()) {
      await t.move(1300, 600)
      const top = await history.evaluate((el) => el.getBoundingClientRect().top)
      await t.scroll(top - 120, 1600, { el: 'aside[aria-labelledby="panel-title"]' })
      await t.wait(400)
      await t.mark('history', history)
    }
    await t.wait(4200)
    await t.click(page.getByRole('button', { name: 'Close sources' }), { label: 'close' })
    await t.wait(1000)
    const removed = page.getByRole('button', { name: /removed: nothing in the graph backs it/ })
    if (await removed.count()) {
      await t.mark('removedLine', removed)
      await t.click(removed, { at: 0.3, label: 'removed' })
      await t.wait(800)
      await t.mark('removed', removed.locator('xpath=..'))
    }
    await t.wait(3500)
    await t.stop()
    await s.browser.close()
  },

  /** A dispute: two current handbook pages disagree, and Canon shows both. */
  async dispute() {
    const s = await open()
    const { page } = s
    await page.goto(PROD + '/app', { waitUntil: 'load' })
    await settle(page, 2500)
    const t = new Take(s, 'dispute')
    await t.start()
    await t.wait(600)
    const input = page.locator('textarea, input[type=text]').first()
    await t.click(input, { at: 0.2, label: 'input' })
    await t.type('How often are growth reviews held?')
    await t.wait(350)
    await t.press('Enter')
    t.log('asked')
    await answered(page)
    t.log('answered')
    await t.wait(1500)
    const disputed = page.locator('[role=button]').filter({ hasText: 'every four weeks' }).first()
    await t.mark('answer', page.locator('h1').locator('xpath=..').locator('xpath=..'))
    await t.mark('disputed', disputed)
    await t.wait(800)
    await t.click(disputed, { at: 0.3, label: 'sentence' })
    await t.wait(1500)
    await t.mark('panel', page.locator('aside[aria-labelledby="panel-title"]').first())
    await t.wait(2500)
    await t.move(1300, 620)
    await t.scroll(320, 1600, { el: 'aside[aria-labelledby="panel-title"]' })
    await t.wait(400)
    await t.mark('panel2', page.locator('aside[aria-labelledby="panel-title"]').first())
    await t.wait(3500)
    await t.stop()
    await s.browser.close()
  },

  /** The fix queue, signed in on the local stack, approving one fix in dry run. */
  async fix() {
    const s = await open()
    const { page } = s
    await showAsGitHub(page)
    await localSignIn(page)
    await page.goto(LOCAL + '/app/fixes', { waitUntil: 'load' })
    await settle(page, 3000)
    await page.evaluate(() => localStorage.removeItem('canon-fix-repo'))
    const t = new Take(s, 'fix')
    await t.start()
    await t.wait(1000)
    await t.mark('header', page.getByRole('heading', { name: 'Fix queue' }).locator('xpath=..'))
    await t.mark('legend', page.getByText('is what the page says').locator('xpath=../..'))
    await t.wait(1800)
    await t.move(900, 640)
    await t.scroll(318, 1700, { x: 900, y: 640 })
    await t.wait(300)
    await t.mark('card', page.getByRole('heading', { name: 'AI Gateway' }).locator('xpath=ancestor::section[1]'))
    const struck = page.getByText(/The team owns the gateway service/).first()
    await t.mark('struck', struck)
    await t.hover(struck, { at: 0.4 })
    await t.wait(1500)
    const correction = page.getByText('The Agent Infrastructure team owns the AI gateway.').first()
    await t.mark('correction', correction)
    await t.hover(correction, { at: 0.6 })
    await t.wait(1400)
    await t.mark('holds', page.getByText('AI gateway is owned by the Agent Infrastructure team.').first().locator('xpath=..'))
    await t.wait(1200)
    const team = page.getByText('Agent Infrastructure', { exact: true }).first()
    await t.mark('goesto', team.locator('xpath=..'))
    await t.hover(team)
    await t.wait(1600)
    await t.click(page.getByRole('button', { name: 'Approve and file' }).first(), { label: 'approve' })
    await t.wait(700)
    const repo = page.getByPlaceholder('owner/repository').first()
    await t.mark('repoform', repo.locator('xpath=ancestor::form[1]'))
    await t.click(repo, { at: 0.3, label: 'repo' })
    await t.type('sushanshetty1/canon')
    await t.wait(500)
    await t.click(page.getByRole('button', { name: /Show the issue|File the issue/ }).first(), { label: 'file' })
    await page.getByText(/Approved, dry run|Filed/).first().waitFor({ timeout: 15000 })
    await t.wait(900)
    await t.mark('filed', page.getByText(/Approved, dry run|Filed/).first().locator('xpath=..'))
    await t.wait(1400)
    await t.move(900, 700)
    const issue = page.getByText(/The issue Canon would file in|Filed in/).first()
    const top = await issue.evaluate((el) => el.getBoundingClientRect().top)
    await t.scroll(top - 120, 1800, { x: 900, y: 700 })
    await t.wait(500)
    await t.mark('issue', issue.locator('xpath=ancestor::div[2]'))
    await t.wait(3500)
    await t.stop()
    await s.browser.close()
  },

  /** Who knows: an area's people from their evidence, then one person's evidence. */
  async whoknows() {
    const s = await open()
    const { page } = s
    await page.goto(PROD + '/app/who-knows', { waitUntil: 'load' })
    await settle(page, 3000)
    const close = page.getByRole('button', { name: 'Close' })
    if (await close.count()) await close.first().click().catch(() => {})
    await settle(page, 1200)
    const t = new Take(s, 'whoknows')
    await t.start()
    await t.wait(1200)
    await t.mark('graph', page.locator('svg[role=img]').first())
    await t.wait(800)
    const node = page.locator('[aria-label^="gilbert09:"]').first()
    await t.hover(node)
    await t.wait(900)
    await t.click(node, { label: 'person' })
    await t.wait(1500)
    await t.mark('person', page.locator('[aria-labelledby="person-title"]').first())
    await t.wait(2000)
    await t.move(1370, 640)
    await t.scroll(380, 2000, { x: 1370, y: 640 })
    await t.wait(400)
    await t.mark('evidence', page.locator('[aria-labelledby="person-title"]').first())
    await t.wait(3000)
    await t.stop()
    await s.browser.close()
  },

  /** Bus factor: areas that rest on one person, each with its flow network and the cut. */
  async busfactor() {
    const s = await open()
    const { page } = s
    await page.goto('about:blank')
    await page.evaluate(() => (document.body.style.background = '#e8e9ec'))
    const t = new Take(s, 'busfactor')
    await t.start()
    await page.goto(PROD + '/app/bus-factor', { waitUntil: 'load' })
    t.log('loaded')
    await page.getByText('Pipeline sources').first().waitFor()
    await t.wait(2500)
    await t.mark('headline', page.locator('h1').first())
    await t.mark('distribution', page.getByText('rest on one person').first().locator('xpath=../..'))
    const row = page.getByText('Pipeline sources').first().locator('xpath=ancestor::li[1]')
    await t.mark('row1', row)
    await t.move(1180, 480)
    await t.wait(1500)
    await t.hover(page.getByText('gilbert09').first())
    await t.wait(2200)
    await t.move(900, 700)
    await t.scroll(500, 2200, { x: 900, y: 700 })
    await t.wait(2500)
    await t.stop()
    await s.browser.close()
  },

  /** Decisions: every RFC on a timeline, and one opened. */
  async decisions() {
    const s = await open()
    const { page } = s
    await page.goto(PROD + '/app/decisions', { waitUntil: 'load' })
    await settle(page, 3000)
    const t = new Take(s, 'decisions')
    await t.start()
    await t.wait(1200)
    await t.mark('chart', page.getByRole('list', { name: /Decisions, oldest/ }))
    await t.move(1000, 560)
    await t.scroll(260, 1800, { x: 1000, y: 560 })
    await t.wait(900)
    const replaced = page.locator('ul[aria-label^="Decisions"] li').filter({ has: page.locator('.line-through') }).first()
    const target = (await replaced.count()) ? replaced : page.locator('ul[aria-label^="Decisions"] li').nth(2)
    await t.mark('row', target)
    await t.click(target.locator('button').first(), { at: 0.2, label: 'decision' })
    await t.wait(1600)
    const panel = page.getByRole('dialog').first()
    if (await panel.count()) await t.mark('panel', panel)
    await t.wait(3800)
    await t.stop()
    await s.browser.close()
  },

  /** Catch me up: drag back to when you left, and the checked brief. */
  async catchup() {
    const s = await open()
    const { page } = s
    await page.goto(PROD + '/app/catch-up', { waitUntil: 'load' })
    await settle(page, 2500)
    await page.getByRole('button', { name: 'A week' }).click()
    await settle(page, 2500)
    const t = new Take(s, 'catchup')
    await t.start()
    await t.wait(1000)
    const handle = page.getByRole('slider', { name: 'Since you left' })
    await t.mark('lanes', page.locator('section[aria-labelledby^="lane-"]').first().locator('xpath=..'))
    const hb = await handle.boundingBox()
    const sep = page.getByText('Sep', { exact: true }).first()
    const sb = await sep.boundingBox()
    const from = { x: hb.x + hb.width / 2, y: hb.y + hb.height / 2 }
    const to = { x: sb.x + 1, y: from.y }
    await t.drag(from, to, 1900)
    t.log('dragged')
    await t.wait(1200)
    await t.mark('lanes2', page.locator('section[aria-labelledby^="lane-"]').first().locator('xpath=..'))
    await t.move(800, 760)
    await t.wait(1500)
    await t.scroll(420, 2000, { x: 800, y: 700 })
    await page.waitForFunction(() => /Written from \d+ facts/.test(document.body.innerText), null, { timeout: 60000 }).catch(() => {})
    t.log('brief')
    await t.wait(4000)
    await t.mark('brief', page.locator('#brief-title').locator('xpath=ancestor::section[1]'))
    await t.wait(2500)
    await t.stop()
    await s.browser.close()
  },

  /** Sources: what the workspace reads, and how much each kind gives. */
  async sources() {
    const s = await open()
    const { page } = s
    await page.goto('about:blank')
    await page.evaluate(() => (document.body.style.background = '#e8e9ec'))
    const t = new Take(s, 'sources')
    await t.start()
    await page.goto(PROD + '/app/sources', { waitUntil: 'load' })
    t.log('loaded')
    await page.getByText('3,275 facts').first().waitFor().catch(() => {})
    await t.wait(3500)
    await t.mark('flow', page.getByText('Docs', { exact: true }).first().locator('xpath=ancestor::section[1]'))
    await t.hover(page.getByText('Tickets', { exact: true }).first())
    await t.wait(1500)
    await t.hover(page.getByText('Chats', { exact: true }).first())
    await t.wait(1500)
    await t.stop()
    await s.browser.close()
  },

  /** Connect a source, signed in on the local stack. */
  async connect() {
    const s = await open()
    const { page } = s
    await showAsGitHub(page)
    await localSignIn(page)
    await page.goto(LOCAL + '/app/connect?ws=posthog-v', { waitUntil: 'load' })
    await settle(page, 2500)
    const t = new Take(s, 'connect')
    await t.start()
    await t.wait(1000)
    await t.mark('list', page.getByText('Slack', { exact: true }).first().locator('xpath=ancestor::ul[1]'))
    for (const name of ['Notion', 'Linear', 'Jira', 'Confluence', 'Files']) {
      await t.click(page.getByText(name, { exact: true }).first(), { label: name })
      await t.wait(1100)
    }
    await t.wait(1200)
    await t.stop()
    await s.browser.close()
  },

  /** New workspace: the repository picker, then a repository being read. */
  async newws() {
    const s = await open()
    const { page } = s
    await showAsGitHub(page)
    await routeRepos(page)
    await localSignIn(page)
    await page.goto(LOCAL + '/app/new', { waitUntil: 'load' })
    await settle(page, 2500)
    const t = new Take(s, 'newws')
    await t.start()
    await t.wait(1000)
    await t.mark('picker', page.getByRole('heading', { name: 'Your repositories' }).locator('xpath=ancestor::section[1]'))
    await t.move(900, 700)
    await t.scroll(330, 1600, { x: 900, y: 700 })
    await t.wait(900)
    const search = page.getByPlaceholder('Search')
    await t.click(search, { at: 0.3, label: 'search' })
    await t.type('cachet')
    await t.wait(1200)
    const repo = page.getByText('cachet-cli', { exact: false }).first()
    await t.mark('repo', repo.locator('xpath=ancestor::li[1]'))
    await t.click(repo, { at: 0.3, label: 'repo' })
    t.log('picked')
    await t.wait(1500)
    await t.move(1400, 820)
    await t.wait(42000)
    await t.stop()
    await s.browser.close()
  },

  /** Members of a workspace: invite a teammate by GitHub handle. */
  async members() {
    const s = await open()
    const { page } = s
    await showAsGitHub(page)
    await localSignIn(page)
    await page.goto(LOCAL + '/app', { waitUntil: 'load' })
    await settle(page, 2500)
    const t = new Take(s, 'members')
    await t.start()
    await t.wait(800)
    await t.click(page.getByRole('button', { name: 'Members', exact: true }).first(), { label: 'members' })
    await t.wait(1200)
    await t.mark('sheet', page.getByRole('dialog').first())
    const handle = page.getByPlaceholder('GitHub handle')
    await t.click(handle, { at: 0.3, label: 'handle' })
    await t.type('octocat')
    await t.wait(400)
    await t.click(page.getByRole('button', { name: /^Invite/ }).first(), { label: 'invite' })
    await t.wait(2200)
    await t.mark('sheet2', page.getByRole('dialog').first())
    await t.wait(2000)
    await t.stop()
    await s.browser.close()
  },

  /** A phone: the same answer at phone width. */
  async phone() {
    const s = await open({ width: 390, height: 844, scale: 3, mobile: true })
    const { page } = s
    await page.goto(PROD + '/app', { waitUntil: 'load' })
    await settle(page, 2500)
    const t = new Take(s, 'phone')
    await t.start()
    t.log('hide-cursor')
    await t.wait(800)
    await page.getByRole('button', { name: 'Which team owns the MCP server?' }).click()
    t.log('asked')
    await answered(page)
    await t.wait(1500)
    await t.scroll(260, 1500, { x: 200, y: 600 })
    await t.wait(1200)
    await page.locator('[role=button]').filter({ hasText: 'owns the MCP server' }).first().click()
    t.log('sentence')
    await t.wait(2600)
    await t.scroll(360, 1600, { x: 200, y: 600 })
    await t.wait(2200)
    await t.stop()
    await s.browser.close()
  },
}

/** The repository list as the owner's GitHub account shows it (their public repositories), served to the picker. */
async function routeRepos(page) {
  const file = path.resolve(new URL('./repos.json', import.meta.url).pathname)
  const rows = JSON.parse(fs.readFileSync(file, 'utf8'))
  const login = 'sushanshetty1'
  await page.route('**/api/github/repos**', async (route) => {
    const u = new URL(route.request().url())
    const q = (u.searchParams.get('q') || '').toLowerCase().split(/\s+/).filter(Boolean)
    const owner = u.searchParams.get('owner') || ''
    const pageNo = Number(u.searchParams.get('page') || 1)
    const seen = new Map()
    for (const r of rows) {
      const o = seen.get(r.owner) || { login: r.owner, kind: r.owner_kind, count: 0 }
      o.count += 1
      seen.set(r.owner, o)
    }
    const owners = [...seen.values()].sort((a, b) => (a.login === login ? 0 : a.kind === 'org' ? 1 : 2) - (b.login === login ? 0 : b.kind === 'org' ? 1 : 2))
    const found = rows.filter((r) => (!owner || r.owner === owner) && q.every((w) => `${r.full_name} ${r.description}`.toLowerCase().includes(w)))
    const size = 15
    const pages = Math.max(1, Math.ceil(found.length / size))
    const shown = found.slice((pageNo - 1) * size, pageNo * size)
    const groups = []
    for (const r of shown) {
      if (!groups.length || groups.at(-1).owner !== r.owner) groups.push({ owner: r.owner, kind: r.owner_kind, you: r.owner === login, repos: [] })
      groups.at(-1).repos.push(r)
    }
    await route.fulfill({
      json: { connected: true, private: true, login, truncated: false, owners, groups, page: pageNo, pages, total: found.length, size },
    })
  })
}
