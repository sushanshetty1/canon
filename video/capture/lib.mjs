// Headless capture: a CDP screencast of crisp 2x frames, and a log of every scripted interaction.
//
// Each take writes video/public/captures/<name>/
//   f00000.jpg ...     every frame Chrome painted (3200x1800 for a 1600x900 viewport)
//   take.json          { viewport, scale, duration, frames: [[file, t]], events: [...] }
// Times are seconds from the start of the take. Events are cursor samples, clicks, keys, scrolls and named marks
// (an element's rectangle in CSS pixels at a moment), which the composition uses for the cursor, zooms and rings.
//
// Headless only: no window opens and audio is muted.

import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const require = createRequire('/Users/sushan/Projects/open-source/diffcut/package.json')
const { chromium } = require('playwright')

export const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
export const OUT = path.resolve(new URL('../public/captures', import.meta.url).pathname)
export const PROD = 'https://canon.sushans.dev'
export const LOCAL = 'http://localhost:4198'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const rand = (a, b) => a + Math.random() * (b - a)
const easeInOut = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2)

/**
 * A browser whose screencast frames are device pixels. Chrome's screencast ignores emulated scale factors, so the
 * scale is forced on the whole browser and the window sized so the page gets exactly width x height.
 */
export async function open({ width = 1600, height = 900, scale = 2, mobile = false } = {}) {
  const browser = await chromium.launch({
    headless: true,
    executablePath: CHROME,
    args: ['--mute-audio', '--hide-scrollbars', `--force-device-scale-factor=${scale}`, `--window-size=${Math.max(width, 500)},${height + 87}`],
  })
  const ctx = await browser.newContext({ viewport: null })
  const page = await ctx.newPage()
  if (mobile) {
    // Chrome windows have a minimum width, so a phone is an emulated screen inside one.
    const emu = await ctx.newCDPSession(page)
    await emu.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile: true })
    await emu.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 })
    return { browser, ctx, page, width, height, scale, emu }
  }
  const inner = await page.evaluate(() => [innerWidth, innerHeight])
  if (inner[0] !== width || inner[1] !== height) {
    // The window frame differs: correct it once.
    const cdp = await ctx.newCDPSession(page)
    const { windowId } = await cdp.send('Browser.getWindowForTarget')
    await cdp.send('Browser.setWindowBounds', { windowId, bounds: { width: width + (width - inner[0]), height: height + 87 + (height - inner[1]) } })
    await sleep(200)
  }
  return { browser, ctx, page, width, height, scale }
}

export class Take {
  constructor(session, name) {
    this.s = session
    this.page = session.page
    this.name = name
    this.dir = path.join(OUT, name)
    this.events = []
    this.frames = []
    this.x = session.width * 0.62
    this.y = session.height * 0.72
  }

  now() {
    return Date.now() / 1000 - this.t0
  }

  log(type, data = {}) {
    this.events.push({ t: +this.now().toFixed(3), type, ...data })
  }

  async start() {
    fs.rmSync(this.dir, { recursive: true, force: true })
    fs.mkdirSync(this.dir, { recursive: true })
    this.cdp = await this.s.ctx.newCDPSession(this.page)
    let n = 0
    this.cdp.on('Page.screencastFrame', (f) => {
      const file = `f${String(n++).padStart(5, '0')}.jpg`
      fs.writeFileSync(path.join(this.dir, file), Buffer.from(f.data, 'base64'))
      this.frames.push([file, +(f.metadata.timestamp - this.t0).toFixed(4)])
      this.cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {})
    })
    this.t0 = Date.now() / 1000
    await this.cdp.send('Page.startScreencast', { format: 'jpeg', quality: 95, maxWidth: 4000, maxHeight: 4000, everyNthFrame: 1 })
    await this.page.mouse.move(this.x, this.y)
    this.log('move', { x: this.x, y: this.y })
    // Chrome sends frames only when something paints: nudge one paint so the take opens on a frame.
    await this.page.evaluate(() => {
      const d = document.createElement('div')
      d.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;opacity:0.01;pointer-events:none'
      document.body.appendChild(d)
      requestAnimationFrame(() => requestAnimationFrame(() => d.remove()))
    })
    await sleep(300)
  }

  async stop() {
    await sleep(400)
    await this.cdp.send('Page.stopScreencast')
    await sleep(200)
    const duration = +this.now().toFixed(3)
    const take = {
      name: this.name,
      viewport: { width: this.s.width, height: this.s.height },
      scale: this.s.scale,
      duration,
      frames: this.frames.filter(([, t]) => t >= 0),
      events: this.events,
    }
    if (!take.frames.length && this.frames.length) take.frames = [[this.frames.at(-1)[0], 0]]
    fs.writeFileSync(path.join(this.dir, 'take.json'), JSON.stringify(take))
    console.log(`${this.name}: ${take.frames.length} frames, ${duration.toFixed(1)}s, ${this.events.length} events`)
    return take
  }

  async wait(ms) {
    await sleep(ms)
  }

  /** A named rectangle (CSS px) at this moment: an element, or {x,y,w,h}. */
  async mark(name, target, extra = {}) {
    let rect = target
    if (target && typeof target.boundingBox === 'function') {
      const b = await target.boundingBox({ timeout: 5000 }).catch(() => null)
      if (!b) {
        console.warn(`mark ${name}: no box`)
        return null
      }
      rect = { x: b.x, y: b.y, w: b.width, h: b.height }
    }
    rect = { x: +rect.x.toFixed(1), y: +rect.y.toFixed(1), w: +rect.w.toFixed(1), h: +rect.h.toFixed(1) }
    this.log('mark', { name, rect, ...extra })
    return rect
  }

  /** Move the pointer along a gentle arc with ease in and out, logging each step. */
  async move(x, y, ms) {
    const x0 = this.x
    const y0 = this.y
    const dist = Math.hypot(x - x0, y - y0)
    if (dist < 1) return
    ms = ms ?? Math.min(900, 280 + dist * 0.55)
    // A slight bow, perpendicular to the path, as a hand would draw it.
    const bow = Math.min(60, dist * 0.12) * (Math.random() < 0.5 ? -1 : 1)
    const nx = -(y - y0) / dist
    const ny = (x - x0) / dist
    const start = Date.now()
    for (;;) {
      const p = Math.min(1, (Date.now() - start) / ms)
      const e = easeInOut(p)
      const arc = Math.sin(Math.PI * e) * bow
      const cx = x0 + (x - x0) * e + nx * arc
      const cy = y0 + (y - y0) * e + ny * arc
      await this.page.mouse.move(cx, cy)
      this.log('move', { x: +cx.toFixed(1), y: +cy.toFixed(1) })
      if (p >= 1) break
      await sleep(14)
    }
    this.x = x
    this.y = y
  }

  async center(target, { dx = 0, dy = 0, at = 0.5 } = {}) {
    const b = await target.boundingBox({ timeout: 5000 }).catch(() => null)
    if (!b) throw new Error('no box for target')
    return { x: b.x + b.width * at + dx, y: b.y + b.height / 2 + dy, box: b }
  }

  async hover(target, opts = {}) {
    const { x, y } = await this.center(target, opts)
    await this.move(x, y, opts.ms)
  }

  async click(target, opts = {}) {
    let x
    let y
    if (typeof target.x === 'number' && typeof target.boundingBox !== 'function') ({ x, y } = target)
    else ({ x, y } = await this.center(target, opts))
    await this.move(x, y, opts.ms)
    await sleep(opts.settle ?? rand(120, 220))
    this.log('down', { x, y })
    await this.page.mouse.down()
    await sleep(70)
    await this.page.mouse.up()
    this.log('click', { x, y, label: opts.label })
    await sleep(opts.after ?? 120)
  }

  /** Type with a person's rhythm: uneven gaps, a little longer after spaces and punctuation. */
  async type(text, { min = 45, max = 115 } = {}) {
    for (const ch of text) {
      await this.page.keyboard.type(ch)
      this.log('key', { ch })
      let gap = rand(min, max)
      if (ch === ' ') gap += rand(20, 70)
      if (/[,.?]/.test(ch)) gap += rand(80, 160)
      await sleep(gap)
    }
  }

  async press(key) {
    await this.page.keyboard.press(key)
    this.log('key', { ch: key })
  }

  /** Smoothly scroll whatever scrolls under (x, y) by dy CSS px over ms. */
  async scroll(dy, ms = 1200, at = null) {
    const px = at?.x ?? this.x
    const py = at?.y ?? this.y
    const sel = at?.el ?? null
    this.log('scroll', { dy, ms })
    await this.page.evaluate(
      ({ dy, ms, px, py, sel }) =>
        new Promise((res) => {
          let el = sel ? document.querySelector(sel) : document.elementFromPoint(px, py)
          const scrollable = (n) => {
            if (!n || n === document.body || n === document.documentElement) return false
            const s = getComputedStyle(n)
            return /(auto|scroll)/.test(s.overflowY) && n.scrollHeight > n.clientHeight + 2
          }
          if (!sel) while (el && !scrollable(el)) el = el.parentElement
          const target = el || document.scrollingElement
          const y0 = target.scrollTop
          const t0 = performance.now()
          const ease = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2)
          const step = (now) => {
            const p = Math.min(1, (now - t0) / ms)
            target.scrollTop = y0 + dy * ease(p)
            if (p < 1) requestAnimationFrame(step)
            else res()
          }
          requestAnimationFrame(step)
        }),
      { dy, ms, px, py, sel },
    )
  }

  /** Press, travel and release, for sliders and handles. */
  async drag(from, to, ms = 1400) {
    await this.move(from.x, from.y)
    await sleep(180)
    this.log('down', { x: from.x, y: from.y })
    await this.page.mouse.down()
    this.log('dragstart', { x: from.x, y: from.y })
    const start = Date.now()
    for (;;) {
      const p = Math.min(1, (Date.now() - start) / ms)
      const e = easeInOut(p)
      const cx = from.x + (to.x - from.x) * e
      const cy = from.y + (to.y - from.y) * e
      await this.page.mouse.move(cx, cy)
      this.log('move', { x: +cx.toFixed(1), y: +cy.toFixed(1) })
      if (p >= 1) break
      await sleep(14)
    }
    this.x = to.x
    this.y = to.y
    await sleep(120)
    await this.page.mouse.up()
    this.log('up', { x: to.x, y: to.y })
  }

  /** Wait until a locator is visible, quietly. */
  async until(locator, timeout = 60000) {
    await locator.waitFor({ state: 'visible', timeout })
  }
}

/** Sign in to the local stack (development sign-in) and choose the video's own workspace. */
export async function localSignIn(page, { login = 'sushanshetty1' } = {}) {
  await page.goto(`${LOCAL}/auth/dev-login?login=${login}&next=/app`, { waitUntil: 'load' })
  await page.evaluate(() => {
    localStorage.setItem(
      'canon-workspace',
      JSON.stringify({ slug: 'posthog-v', name: 'PostHog', label: 'PostHog', suggestions: [], own: true, repo: null, private: false, role: 'owner' }),
    )
  })
}

/** Production signs in with GitHub; the local stack uses development sign-in. Show the account as production does. */
export async function showAsGitHub(page) {
  await page.route('**/api/me', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    if (body.user) body.user.dev = false
    await route.fulfill({ response: res, json: body })
  })
}
