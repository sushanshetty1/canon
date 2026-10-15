// Frames from the rendered video for review: node scripts/frames.mjs <seconds>:<name> ...
// Writes out/final-stills/<seconds>-<name>.jpg. Reads the mp4; renders nothing and plays nothing.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const ROOT = path.resolve(new URL('..', import.meta.url).pathname)
const video = path.join(ROOT, 'out/canon-demo.mp4')
const dir = path.join(ROOT, 'out/final-stills')
fs.mkdirSync(dir, { recursive: true })
for (const arg of process.argv.slice(2)) {
  const [sec, name] = arg.split(':')
  const file = path.join(dir, `${Number(sec).toFixed(2).padStart(6, '0')}-${name}.jpg`)
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-ss', sec, '-i', video, '-frames:v', '1', '-q:v', '2', file])
  console.log(file)
}
