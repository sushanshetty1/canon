// Stills for review, headless: node scripts/stills.mjs [seconds ...] | --scenes | --transitions
// Writes out/stills/<time>.jpg. With --scenes, three stills per scene; with --transitions, the middle of each
// transition.

import fs from 'node:fs'
import path from 'node:path'
import { bundle } from '@remotion/bundler'
import { renderStill, selectComposition } from '@remotion/renderer'

const ROOT = path.resolve(new URL('..', import.meta.url).pathname)
const OUT = path.join(ROOT, 'out/stills')
fs.mkdirSync(OUT, { recursive: true })
const args = process.argv.slice(2)

const timing = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/timing.json'), 'utf8'))
const tl = fs.readFileSync(path.join(ROOT, 'src/timeline.ts'), 'utf8')

const serveUrl = await bundle({ entryPoint: path.join(ROOT, 'src/index.ts'), publicDir: path.join(ROOT, 'public') })
const browserExecutable = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const composition = await selectComposition({ serveUrl, id: 'CanonDemo', browserExecutable, chromeMode: 'chrome-for-testing' })

// Scene starts, the same arithmetic as src/timeline.ts.
const OVERLAP = { none: 0, sweep: 0.8, lift: 0.8, stretch: 0.7, card: 0.55 }
const defs = [...tl.matchAll(/\{ id: '(\w+)', into: \{ kind: '(\w+)'[^}]*\}(?:, delay: ([\d.]+))?(?:, extra: ([\d.]+))? \}/g)].map((m) => ({
  id: m[1],
  kind: m[2],
  delay: Number(m[3] ?? 0),
  extra: Number(m[4] ?? 0),
}))
let t = 0
const starts = defs.map((d, i) => {
  if (i > 0) t -= OVERLAP[d.kind]
  const s = { ...d, start: t, dur: d.delay + timing.scenes[d.id].duration + d.extra }
  t += s.dur
  return s
})

let times = []
if (args.includes('--scenes')) for (const s of starts) times.push(s.start + s.dur * 0.3, s.start + s.dur * 0.62, s.start + s.dur * 0.92)
if (args.includes('--transitions')) for (const s of starts.slice(1)) times.push(s.start + (s.kind === 'card' ? 0.75 : OVERLAP[s.kind] * 0.5))
times.push(...args.filter((a) => !a.startsWith('--')).map(Number))

for (const sec of times) {
  const frame = Math.min(composition.durationInFrames - 1, Math.round(sec * 30))
  const scene = [...starts].reverse().find((s) => s.start <= sec)
  const file = path.join(OUT, `${sec.toFixed(2).padStart(6, '0')}-${scene?.id}.jpg`)
  await renderStill({ serveUrl, composition, frame, output: file, imageFormat: 'jpeg', jpegQuality: 90, browserExecutable, chromeMode: 'chrome-for-testing' })
  console.log(file)
}
