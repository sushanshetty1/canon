// The voiceover: one audio file per scene, and the timing the composition is cut to.
//
//   npm run voice            ElevenLabs when ELEVENLABS_API_KEY is set (env or ~/.zshrc), else macOS `say` drafts
//   npm run voice -- --draft macOS `say` drafts, whatever keys exist
//
// Each scene is one text-to-speech request "with timestamps", so its prosody is whole, and the character alignment
// gives every caption chunk its start and end. Responses are cached under voice/cache by a hash of the voice, the
// settings and the scene's text, so only scenes whose text changed are generated again (and paid for).
// The scene audio is then assembled: a lead-in of silence, the speech cut at each chunk boundary with the chunk's
// pause added, loudness-matched, written to public/voice/<scene>.wav. Timing goes to src/timing.json.

import { execFileSync, spawnSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { readKey } from './keys.mjs'

const ROOT = path.resolve(new URL('..', import.meta.url).pathname)
const script = JSON.parse(fs.readFileSync(path.join(ROOT, 'narration/script.json'), 'utf8'))
const CACHE = path.join(ROOT, 'voice/cache')
const OUT = path.join(ROOT, 'public/voice')
const RATE = 48000
const PACE = script.pace ?? {}
const TAIL = PACE.tail ?? 0.35
fs.mkdirSync(CACHE, { recursive: true })
fs.mkdirSync(OUT, { recursive: true })

const draft = process.argv.includes('--draft')
const only = process.argv.filter((a) => !a.startsWith('--')).slice(2)
const key = draft ? '' : readKey('ELEVENLABS_API_KEY')
const provider = key ? 'elevenlabs' : 'say'
console.log(`voice: ${provider === 'elevenlabs' ? `ElevenLabs ${script.voice.model_id}, ${script.voice.voice_name}` : `macOS say (${script.voice.draft_voice}), draft`}`)

const speakOf = (c) => c.speak ?? c.text
const sceneText = (s) => s.chunks.map(speakOf).join(' ')

function hashOf(scene) {
  const v = script.voice
  const basis = provider === 'elevenlabs' ? [v.voice_id, v.model_id, v.output_format, JSON.stringify(v.settings)] : ['say', v.draft_voice]
  return crypto.createHash('sha1').update([...basis, sceneText(scene)].join('\n')).digest('hex').slice(0, 12)
}

/** ElevenLabs, with the neighbouring scenes' text as context so the delivery flows across files. */
async function eleven(scene, i) {
  const v = script.voice
  const prev = script.scenes[i - 1]
  const next = script.scenes[i + 1]
  const body = {
    text: sceneText(scene),
    model_id: v.model_id,
    voice_settings: v.settings,
    ...(prev ? { previous_text: sceneText(prev) } : {}),
    ...(next ? { next_text: sceneText(next) } : {}),
  }
  for (let attempt = 1; ; attempt++) {
    const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${v.voice_id}/with-timestamps?output_format=${v.output_format}`, {
      method: 'POST',
      headers: { 'xi-api-key': key, 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (res.ok) {
      const out = await res.json()
      return { audio: Buffer.from(out.audio_base64, 'base64'), ext: 'mp3', alignment: out.alignment }
    }
    const text = await res.text()
    if (attempt < 3 && (res.status === 429 || res.status >= 500)) {
      await new Promise((r) => setTimeout(r, 4000 * attempt))
      continue
    }
    throw new Error(`ElevenLabs ${res.status}: ${text.slice(0, 300)}`)
  }
}

/** macOS `say`, one file per chunk, joined; characters are spread evenly over each chunk's speech. Plays nothing. */
function say(scene) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'canon-say-'))
  const characters = []
  const starts = []
  const ends = []
  const parts = []
  let t = 0
  scene.chunks.forEach((c, i) => {
    const text = speakOf(c) + (i < scene.chunks.length - 1 ? ' ' : '')
    const aiff = path.join(tmp, `${i}.aiff`)
    execFileSync('say', ['-v', script.voice.draft_voice, '-r', '172', '-o', aiff, speakOf(c)])
    const wav = path.join(tmp, `${i}.wav`)
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', aiff, '-ar', String(RATE), '-ac', '1', wav])
    const d = Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', wav]).toString())
    const lead = 0.05
    const span = Math.max(0.1, d - 0.15)
    ;[...text].forEach((ch, k) => {
      characters.push(ch)
      starts.push(t + lead + (span * k) / text.length)
      ends.push(t + lead + (span * (k + 1)) / text.length)
    })
    parts.push(wav)
    t += d
  })
  const list = path.join(tmp, 'list.txt')
  fs.writeFileSync(list, parts.map((p) => `file '${p}'`).join('\n'))
  const joined = path.join(tmp, 'joined.wav')
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', joined])
  const audio = fs.readFileSync(joined)
  fs.rmSync(tmp, { recursive: true, force: true })
  return { audio, ext: 'wav', alignment: { characters, character_start_times_seconds: starts, character_end_times_seconds: ends } }
}

function decode(file) {
  const raw = execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 'f32le', '-ac', '1', '-ar', String(RATE), '-'], { maxBuffer: 1 << 30 })
  return new Float32Array(raw.buffer, raw.byteOffset, raw.byteLength / 4)
}

function wav16(samples) {
  const buf = Buffer.alloc(44 + samples.length * 2)
  buf.write('RIFF', 0)
  buf.writeUInt32LE(36 + samples.length * 2, 4)
  buf.write('WAVEfmt ', 8)
  buf.writeUInt32LE(16, 16)
  buf.writeUInt16LE(1, 20)
  buf.writeUInt16LE(1, 22)
  buf.writeUInt32LE(RATE, 24)
  buf.writeUInt32LE(RATE * 2, 28)
  buf.writeUInt16LE(2, 32)
  buf.writeUInt16LE(16, 34)
  buf.write('data', 36)
  buf.writeUInt32LE(samples.length * 2, 40)
  for (let i = 0; i < samples.length; i++) buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767), 44 + i * 2)
  return buf
}

/** Two-pass EBU R128 to -16 LUFS, linear, so every scene sits at the same level. */
function loudnorm(file) {
  const pass = spawnSync('ffmpeg', ['-hide_banner', '-i', file, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
  const err = pass.stderr.toString()
  const stats = JSON.parse(err.slice(err.lastIndexOf('{'), err.lastIndexOf('}') + 1))
  const tmp = file.replace(/\.wav$/, '.norm.wav')
  const af = `loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=${stats.input_i}:measured_TP=${stats.input_tp}:measured_LRA=${stats.input_lra}:measured_thresh=${stats.input_thresh}:offset=${stats.target_offset}:linear=true`
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', file, '-af', af, '-ar', String(RATE), '-ac', '1', '-c:a', 'pcm_s16le', tmp])
  fs.renameSync(tmp, file)
}

const timing = { provider, voice: provider === 'elevenlabs' ? `${script.voice.voice_name} (${script.voice.model_id})` : `say ${script.voice.draft_voice}`, rate: RATE, scenes: {} }
const previous = fs.existsSync(path.join(ROOT, 'src/timing.json')) ? JSON.parse(fs.readFileSync(path.join(ROOT, 'src/timing.json'), 'utf8')) : null

for (const [i, scene] of script.scenes.entries()) {
  if (only.length && !only.includes(scene.id) && previous?.scenes?.[scene.id]) {
    timing.scenes[scene.id] = previous.scenes[scene.id]
    continue
  }
  const h = hashOf(scene)
  const base = path.join(CACHE, `${scene.id}.${provider}.${h}`)
  let src
  let alignment
  const cachedExt = ['mp3', 'wav'].find((e) => fs.existsSync(`${base}.${e}`))
  if (cachedExt && fs.existsSync(`${base}.json`)) {
    src = `${base}.${cachedExt}`
    alignment = JSON.parse(fs.readFileSync(`${base}.json`, 'utf8'))
    console.log(`  ${scene.id}: cached`)
  } else {
    const got = provider === 'elevenlabs' ? await eleven(scene, i) : say(scene)
    src = `${base}.${got.ext}`
    fs.writeFileSync(src, got.audio)
    fs.writeFileSync(`${base}.json`, JSON.stringify(got.alignment))
    alignment = got.alignment
    // Older takes of this scene from the same provider are no longer needed.
    for (const f of fs.readdirSync(CACHE)) if (f.startsWith(`${scene.id}.${provider}.`) && !f.startsWith(`${scene.id}.${provider}.${h}`)) fs.rmSync(path.join(CACHE, f))
    console.log(`  ${scene.id}: generated (${sceneText(scene).length} characters)`)
  }

  // Chunk character ranges in the spoken text, and their times.
  const chars = alignment.characters
  const st = alignment.character_start_times_seconds
  const en = alignment.character_end_times_seconds
  const spoken = chars.join('')
  const ranges = []
  let at = 0
  for (const c of scene.chunks) {
    const s = speakOf(c)
    const idx = spoken.indexOf(s, at)
    const from = idx >= 0 ? idx : at
    ranges.push([from, from + s.length])
    at = from + s.length
  }
  const firstTime = (a, b) => {
    for (let k = a; k < b; k++) if (chars[k] && chars[k].trim()) return st[k]
    return st[a] ?? 0
  }
  const lastTime = (a, b) => {
    for (let k = b - 1; k >= a; k--) if (chars[k] && chars[k].trim()) return en[k]
    return en[b - 1] ?? 0
  }

  const pcm = decode(src)
  const total = pcm.length / RATE
  const lead = Math.min(scene.lead ?? 0.4, PACE.max_lead ?? 9)
  const pieces = [new Float32Array(Math.round(lead * RATE))]
  const chunks = []
  const words = []
  let cursor = 0 // time in the source
  let shift = lead // what the source time is offset by in the output
  scene.chunks.forEach((c, k) => {
    const [a, b] = ranges[k]
    const start = firstTime(a, b)
    const end = lastTime(a, b)
    const nextStart = k < scene.chunks.length - 1 ? firstTime(...ranges[k + 1]) : total
    // Cut in the silence between this chunk and the next, a little after this one ends.
    const cut = k < scene.chunks.length - 1 ? Math.min(nextStart - 0.02, Math.max(end + 0.04, (end + nextStart) / 2)) : total
    const seg = pcm.subarray(Math.round(cursor * RATE), Math.round(cut * RATE))
    pieces.push(seg)
    chunks.push({ text: c.text, start: +(start + shift).toFixed(3), end: +(end + shift).toFixed(3) })
    // Words of the spoken text inside this chunk.
    const re = /\S+/g
    const s = spoken.slice(a, b)
    let m
    while ((m = re.exec(s))) {
      const ws = a + m.index
      const we = ws + m[0].length
      words.push({ w: m[0].replace(/[^\w'-]/g, ''), start: +(firstTime(ws, we) + shift).toFixed(3), end: +(lastTime(ws, we) + shift).toFixed(3) })
    }
    const pause = k < scene.chunks.length - 1 ? (c.pause ?? 0.2) * (PACE.pause_scale ?? 1) : 0
    if (pause > 0) pieces.push(new Float32Array(Math.round(pause * RATE)))
    shift += pause
    cursor = cut
  })
  pieces.push(new Float32Array(Math.round(TAIL * RATE)))
  const length = pieces.reduce((n, p) => n + p.length, 0)
  const out = new Float32Array(length)
  let o = 0
  for (const p of pieces) {
    out.set(p, o)
    o += p.length
  }
  const file = path.join(OUT, `${scene.id}.wav`)
  fs.writeFileSync(file, wav16(out))
  loudnorm(file)
  const duration = +(length / RATE).toFixed(3)
  timing.scenes[scene.id] = { file: `voice/${scene.id}.wav`, duration, lead, chunks, words }
}

const order = script.scenes.map((s) => s.id)
timing.order = order
timing.total = +order.reduce((n, id) => n + timing.scenes[id].duration, 0).toFixed(2)
fs.writeFileSync(path.join(ROOT, 'src/timing.json'), JSON.stringify(timing, null, 1) + '\n')
console.log(`speech: ${timing.total}s across ${order.length} scenes -> src/timing.json`)
