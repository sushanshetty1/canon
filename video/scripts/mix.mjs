// The narration track alone, placed exactly as the composition places it: out/voice-mix.wav.
// For checking pacing without a render: node scripts/mix.mjs && node scripts/breaks.mjs out/voice-mix.wav
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const ROOT = path.resolve(new URL('..', import.meta.url).pathname)
const RATE = 48000
const timing = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/timing.json'), 'utf8'))
const plan = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/scenes.json'), 'utf8'))

const starts = []
plan.scenes.forEach((s, i) => {
  if (i === 0) starts.push(plan.voiceAt[s.into.kind])
  else starts.push(starts[i - 1] + timing.scenes[plan.scenes[i - 1].id].duration + plan.breath + (s.pauseBefore ?? 0))
})
const last = plan.scenes.at(-1).id
const total = starts.at(-1) + timing.scenes[last].duration + plan.hold
const out = new Float32Array(Math.ceil(total * RATE))
plan.scenes.forEach((s, i) => {
  const raw = execFileSync('ffmpeg', ['-v', 'error', '-i', path.join(ROOT, 'public', timing.scenes[s.id].file), '-f', 'f32le', '-ac', '1', '-ar', String(RATE), '-'], { maxBuffer: 1 << 30 })
  const pcm = new Float32Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength))
  out.set(pcm.subarray(0, Math.max(0, out.length - Math.round(starts[i] * RATE))), Math.round(starts[i] * RATE))
})
const buf = Buffer.alloc(44 + out.length * 2)
buf.write('RIFF', 0)
buf.writeUInt32LE(36 + out.length * 2, 4)
buf.write('WAVEfmt ', 8)
buf.writeUInt32LE(16, 16)
buf.writeUInt16LE(1, 20)
buf.writeUInt16LE(1, 22)
buf.writeUInt32LE(RATE, 24)
buf.writeUInt32LE(RATE * 2, 28)
buf.writeUInt16LE(2, 32)
buf.writeUInt16LE(16, 34)
buf.write('data', 36)
buf.writeUInt32LE(out.length * 2, 40)
for (let i = 0; i < out.length; i++) buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, out[i])) * 32767), 44 + i * 2)
fs.mkdirSync(path.join(ROOT, 'out'), { recursive: true })
fs.writeFileSync(path.join(ROOT, 'out/voice-mix.wav'), buf)
console.log(`out/voice-mix.wav: ${total.toFixed(2)}s`)
