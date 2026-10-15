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


// Scene starts, the same arithmetic as src/timeline.ts.
const plan = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/scenes.json'), 'utf8'))
const OVERLAP = plan.overlap
const voiceStart = []
plan.scenes.forEach((s, i) => {
  if (i === 0) voiceStart.push(plan.voiceAt[s.into.kind])
  else voiceStart.push(voiceStart[i - 1] + timing.scenes[plan.scenes[i - 1].id].duration + plan.breath + (s.pauseBefore ?? 0))
})
const starts = plan.scenes.map((s, i) => {
  const start = voiceStart[i] - plan.voiceAt[s.into.kind]
  const voiced = voiceStart[i]
  return { id: s.id, kind: s.into.kind, start, voiced, chunks: timing.scenes[s.id].chunks.map((c) => +(voiced + c.start).toFixed(2)) }
})
starts.forEach((s, i) => (s.dur = (starts[i + 1] ? starts[i + 1].start + OVERLAP[starts[i + 1].kind] : s.voiced + timing.scenes[s.id].duration + plan.hold) - s.start))
if (args.includes('--plan')) {
  for (const s of starts) console.log(s.id.padEnd(10), s.start.toFixed(2).padStart(7), s.dur.toFixed(2).padStart(6), s.chunks.join(' '))
  process.exit(0)
}

const serveUrl = await bundle({ entryPoint: path.join(ROOT, 'src/index.ts'), publicDir: path.join(ROOT, 'public') })
const browserExecutable = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const composition = await selectComposition({ serveUrl, id: 'CanonDemo', browserExecutable, chromeMode: 'chrome-for-testing' })

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
