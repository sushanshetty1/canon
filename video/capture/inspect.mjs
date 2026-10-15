// node capture/inspect.mjs <take> [t ...]: the take's marks and clicks, and the frame shown at each time t.
import fs from 'node:fs'
import path from 'node:path'
import { OUT } from './lib.mjs'

const [name, ...times] = process.argv.slice(2)
const take = JSON.parse(fs.readFileSync(path.join(OUT, name, 'take.json'), 'utf8'))
console.log(`${name}: ${take.duration}s, ${take.frames.length} frames, first frame at ${take.frames[0]?.[1]}`)
for (const e of take.events) if (e.type !== 'move' && e.type !== 'key') console.log(e.t.toFixed(2), e.type, e.name ?? e.label ?? '', e.rect ? JSON.stringify(e.rect) : '')
for (const t of times.map(Number)) {
  let f = take.frames[0]
  for (const fr of take.frames) if (fr[1] <= t) f = fr
  console.log(`t=${t}: ${path.join(OUT, name, f[0])}`)
}
