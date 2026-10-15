// node scripts/levels.mjs <file> <from> <to>: 20 ms RMS levels in dBFS, to see what sits in a pause.
import { execFileSync } from 'node:child_process'

const [file, from, to] = process.argv.slice(2)
const raw = execFileSync('ffmpeg', ['-v', 'error', '-ss', from, '-to', to, '-i', file, '-f', 'f32le', '-ac', '1', '-ar', '48000', '-'], { maxBuffer: 1 << 28 })
const pcm = new Float32Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength))
const W = 960
let line = ''
for (let i = 0; i + W <= pcm.length; i += W) {
  let s = 0
  for (let j = i; j < i + W; j++) s += pcm[j] * pcm[j]
  const db = 10 * Math.log10(s / W + 1e-12)
  line += `${(Number(from) + i / 48000).toFixed(2)} ${db.toFixed(0)} ${'#'.repeat(Math.max(0, Math.round((db + 70) / 2)))}\n`
}
console.log(line)
