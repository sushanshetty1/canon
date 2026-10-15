// The voiceover: one audio file per scene, and the timing the composition is cut to.
//
//   npm run voice            ElevenLabs when ELEVENLABS_API_KEY is set (env or ~/.zshrc), else macOS `say` drafts
//   npm run voice -- --draft macOS `say` drafts, whatever keys exist
//
// A scene is spoken in one text-to-speech request "with timestamps" (or in `parts`, a request each), so its prosody
// is whole, and the character alignment gives every caption chunk and word its start and end. Responses are cached
// in voice/cache by a hash of the voice, the settings and the text, so only text that changed is generated again
// (and paid for). A part whose exact text is already spoken inside an earlier cached take of the same scene is cut
// out of that take instead of being generated.
//
// Assembly reads as one continuous take: leading and trailing silence is trimmed, any pause between words longer
// than MAX_GAP is shortened to it (cut in the middle of the silence, with short fades so nothing clicks), parts are
// joined with a breath, and every scene is loudness-matched. The scenes themselves are butted together by the
// composition (src/timeline.ts) with a breath between them. Output: public/voice/<scene>.wav and src/timing.json.

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
const SILENT_DB = PACE.silent_db ?? -35 // a window with no sample this loud is silence (the listen-check's level)
const MAX_GAP = PACE.max_gap ?? 0.26 // longest pause kept between two phrases
const SHORT_GAP = PACE.short_gap ?? 0.12 // longest pause kept next to a single short word or a breath
const SHORT_WORD = 0.55 // sound shorter than this, between two pauses, is a short word or a breath
const BLIP = 0.12 // sound shorter than this, between two pauses, is a click: it becomes silence
const PAUSE = 0.15 // a silence this long is heard as a pause (the listen-check counts from here)
const PART_GAP = PACE.part_gap ?? 0.2 // silence put between parts of a scene before the pauses are evened out
const HEAD = 0.02 // kept before the first sound
const TAIL = 0.06 // kept after the last sound, for its release
const FADE = 0.006
fs.mkdirSync(CACHE, { recursive: true })
fs.mkdirSync(OUT, { recursive: true })

const draft = process.argv.includes('--draft')
const key = draft ? '' : readKey('ELEVENLABS_API_KEY')
const provider = key ? 'elevenlabs' : 'say'
console.log(`voice: ${provider === 'elevenlabs' ? `ElevenLabs ${script.voice.model_id}, ${script.voice.voice_name}` : `macOS say (${script.voice.draft_voice}), draft`}`)

const speakOf = (c) => c.speak ?? c.text
const partsOf = (s) => s.parts ?? [s.chunks.map((_, i) => i)]
const partText = (s, part) => part.map((i) => speakOf(s.chunks[i])).join(' ')
const sceneText = (s) => s.chunks.map(speakOf).join(' ')

function hashOf(text) {
  const v = script.voice
  const basis = provider === 'elevenlabs' ? [v.voice_id, v.model_id, v.output_format, JSON.stringify(v.settings)] : ['say', v.draft_voice]
  return crypto.createHash('sha1').update([...basis, text].join('\n')).digest('hex').slice(0, 12)
}

/** ElevenLabs, with the text around it as context so the delivery flows across requests. */
async function eleven(text, previous, next) {
  const v = script.voice
  const body = { text, model_id: v.model_id, voice_settings: v.settings, ...(previous ? { previous_text: previous } : {}), ...(next ? { next_text: next } : {}) }
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
    const err = await res.text()
    if (attempt < 3 && (res.status === 429 || res.status >= 500)) {
      await new Promise((r) => setTimeout(r, 4000 * attempt))
      continue
    }
    throw new Error(`ElevenLabs ${res.status}: ${err.slice(0, 300)}`)
  }
}

/** macOS `say` (writes a file, plays nothing); characters are spread evenly over the speech. */
function say(text) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'canon-say-'))
  const aiff = path.join(tmp, 'a.aiff')
  const wav = path.join(tmp, 'a.wav')
  execFileSync('say', ['-v', script.voice.draft_voice, '-r', '172', '-o', aiff, text])
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', aiff, '-ar', String(RATE), '-ac', '1', wav])
  const d = Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', wav]).toString())
  const chars = [...text]
  const span = Math.max(0.1, d - 0.2)
  const alignment = {
    characters: chars,
    character_start_times_seconds: chars.map((_, k) => 0.05 + (span * k) / chars.length),
    character_end_times_seconds: chars.map((_, k) => 0.05 + (span * (k + 1)) / chars.length),
  }
  const audio = fs.readFileSync(wav)
  fs.rmSync(tmp, { recursive: true, force: true })
  return { audio, ext: 'wav', alignment }
}

function decode(file) {
  const raw = execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 'f32le', '-ac', '1', '-ar', String(RATE), '-'], { maxBuffer: 1 << 30 })
  return new Float32Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength))
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

/** The samples, loudness-matched (via a temporary file). */
function normalise(pcm) {
  const tmp = path.join(os.tmpdir(), `canon-voice-${process.pid}.wav`)
  fs.writeFileSync(tmp, wav16(pcm))
  loudnorm(tmp)
  const out = decode(tmp)
  fs.rmSync(tmp, { force: true })
  return out
}

/** A cached take of this scene that already speaks `text`: the slice of it, with its own alignment. */
function reuse(sceneId, text) {
  for (const f of fs.readdirSync(CACHE)) {
    if (!f.startsWith(`${sceneId}.${provider}.`) || !f.endsWith('.json')) continue
    const a = JSON.parse(fs.readFileSync(path.join(CACHE, f), 'utf8'))
    const spoken = a.characters.join('')
    const at = spoken.indexOf(text)
    if (at < 0) continue
    const base = path.join(CACHE, f.replace(/\.json$/, ''))
    const audioFile = ['mp3', 'wav'].map((e) => `${base}.${e}`).find((p) => fs.existsSync(p))
    const from = Math.max(0, a.character_start_times_seconds[at] - 0.05)
    // End in the silence after the text, before the next word of the old take starts to sound.
    const next = a.characters.findIndex((ch, k) => k >= at + text.length && /[\p{L}\p{N}]/u.test(ch))
    const lastEnd = a.character_end_times_seconds[at + text.length - 1]
    const to = next > 0 ? Math.min(lastEnd + 0.15, a.character_start_times_seconds[next] - 0.08) : lastEnd + 0.15
    const pcm = decode(audioFile).subarray(Math.round(from * RATE), Math.round(to * RATE))
    const slice = (arr) => arr.slice(at, at + text.length).map((x) => +(x - from).toFixed(4))
    return {
      audio: wav16(pcm),
      ext: 'wav',
      alignment: { characters: a.characters.slice(at, at + text.length), character_start_times_seconds: slice(a.character_start_times_seconds), character_end_times_seconds: slice(a.character_end_times_seconds) },
      from: f,
    }
  }
  return null
}

/** One part's audio and alignment: from the cache, cut from an earlier take, or generated. */
async function take(scene, part, previous, next) {
  const text = partText(scene, part)
  const base = path.join(CACHE, `${scene.id}.${provider}.${hashOf(text)}`)
  const ext = ['mp3', 'wav'].find((e) => fs.existsSync(`${base}.${e}`))
  if (ext && fs.existsSync(`${base}.json`)) return { file: `${base}.${ext}`, alignment: JSON.parse(fs.readFileSync(`${base}.json`, 'utf8')), how: 'cached' }
  let got = reuse(scene.id, text)
  const how = got ? `cut from ${got.from}` : 'generated'
  if (!got) got = provider === 'elevenlabs' ? await eleven(text, previous, next) : say(text)
  fs.writeFileSync(`${base}.${got.ext}`, got.audio)
  fs.writeFileSync(`${base}.json`, JSON.stringify(got.alignment))
  return { file: `${base}.${got.ext}`, alignment: got.alignment, how: `${how} (${text.length} characters)` }
}

const timing = { provider, voice: provider === 'elevenlabs' ? `${script.voice.voice_name} (${script.voice.model_id})` : `say ${script.voice.draft_voice}`, rate: RATE, scenes: {} }
const used = new Set()

for (const [si, scene] of script.scenes.entries()) {
  const parts = partsOf(scene)
  // Each part, decoded, with its characters' times; parts are joined after trimming.
  let chars = []
  let starts = []
  let ends = []
  let pcm = new Float32Array(0)
  for (const [pi, part] of parts.entries()) {
    const prevText = pi > 0 ? partText(scene, parts[pi - 1]) : si > 0 ? sceneText(script.scenes[si - 1]) : ''
    const nextText = pi < parts.length - 1 ? partText(scene, parts[pi + 1]) : si < script.scenes.length - 1 ? sceneText(script.scenes[si + 1]) : ''
    const t = await take(scene, part, prevText, nextText)
    used.add(path.basename(t.file).replace(/\.(mp3|wav)$/, ''))
    console.log(`  ${scene.id}${parts.length > 1 ? ` part ${pi + 1}` : ''}: ${t.how}`)
    const audio = decode(t.file)
    const offset = pcm.length / RATE + (pi > 0 ? PART_GAP : 0)
    if (pi > 0) {
      const joined = new Float32Array(pcm.length + Math.round(PART_GAP * RATE) + audio.length)
      joined.set(pcm, 0)
      joined.set(audio, pcm.length + Math.round(PART_GAP * RATE))
      pcm = joined
      chars.push(' ')
      starts.push(offset - PART_GAP / 2)
      ends.push(offset - PART_GAP / 2)
    } else pcm = audio
    // Trim this part's own head and tail silence before joining the next one.
    const a = t.alignment
    chars = chars.concat(a.characters)
    starts = starts.concat(a.character_start_times_seconds.map((x) => x + offset))
    ends = ends.concat(a.character_end_times_seconds.map((x) => x + offset))
  }

  // Words, by character ranges of the spoken text.
  const spoken = chars.join('')
  const words = []
  const re = /\S+/g
  let m
  while ((m = re.exec(spoken))) {
    const a = m.index
    const b = a + m[0].length
    let s0 = starts[a]
    let e0 = ends[b - 1]
    // Punctuation carries the pause after it in the alignment, so a word spans its letters and digits only.
    for (let k = a; k < b; k++) if (/[\p{L}\p{N}]/u.test(chars[k])) { s0 = starts[k]; break }
    for (let k = b - 1; k >= a; k--) if (/[\p{L}\p{N}]/u.test(chars[k])) { e0 = ends[k]; break }
    words.push({ a, b, start: s0, end: e0, w: m[0].replace(/[^\w'-]/g, '') })
  }

  // Loudness first, so silence is judged at the level the viewer hears.
  pcm = normalise(pcm)

  // What to keep. Silence is found in the audio itself, since the alignment stretches a sentence's last letters
  // over the pause after it: a 10 ms window is silent when no sample in it reaches SILENT_DB (the level the
  // listen-check uses). Then, as an ear hears it:
  // - a burst shorter than BLIP between two silences (a breath, a click, the first sound of a cut-off word) is
  //   silence, so the two pauses around it become one;
  // - a pause is shortened to MAX_GAP, or to SHORT_GAP when the sound on either side of it is a single short word,
  //   so a quick "So," never sits between two full pauses;
  // - the speech starts HEAD before its first sound and ends TAIL after its last.
  const WIN = Math.round(0.01 * RATE)
  const floor = 10 ** (SILENT_DB / 20)
  const voiced = []
  for (let i = 0; i + WIN <= pcm.length; i += WIN) {
    let peak = 0
    for (let j = i; j < i + WIN; j++) peak = Math.max(peak, Math.abs(pcm[j]))
    voiced.push(peak >= floor)
  }
  // Runs of voiced and silent windows, in seconds.
  let runs = []
  for (let k = 0; k < voiced.length; k++) {
    const last = runs.at(-1)
    if (last && last.v === voiced[k]) last.b = (k + 1) * 0.01
    else runs.push({ v: voiced[k], a: k * 0.01, b: (k + 1) * 0.01 })
  }
  const merge = (rs) => rs.reduce((out, r) => {
    const last = out.at(-1)
    if (last && last.v === r.v) last.b = r.b
    else out.push({ ...r })
    return out
  }, [])
  runs = merge(runs.map((r, i) => (r.v && r.b - r.a < BLIP && i > 0 && i < runs.length - 1 ? { ...r, v: false } : r)))
  const firstV = runs.find((r) => r.v)
  const lastV = [...runs].reverse().find((r) => r.v)
  // Pauses are silences long enough to hear; the gaps inside a word (a stop, a breath of air) are left alone.
  const pauses = runs.filter((r) => !r.v && r.a >= firstV.b && r.b <= lastV.a && r.b - r.a >= PAUSE)
  const keep = []
  let from = Math.max(0, firstV.a - HEAD)
  pauses.forEach((r, i) => {
    const soundBefore = r.a - (i > 0 ? pauses[i - 1].b : firstV.a)
    const soundAfter = (i < pauses.length - 1 ? pauses[i + 1].a : lastV.b) - r.b
    const allowed = soundBefore < SHORT_WORD || soundAfter < SHORT_WORD ? SHORT_GAP : MAX_GAP
    if (r.b - r.a > allowed) {
      keep.push([from, r.a + allowed / 2])
      from = r.b - allowed / 2
    }
  })
  keep.push([from, Math.min(pcm.length / RATE, lastV.b + TAIL)])

  // Map a source time to the output time.
  const mapTime = (t) => {
    let out = 0
    for (const [a, b] of keep) {
      if (t <= a) return out
      if (t <= b) return out + (t - a)
      out += b - a
    }
    return out
  }

  const fadeN = Math.round(FADE * RATE)
  const pieces = keep.map(([a, b]) => {
    const seg = pcm.slice(Math.round(a * RATE), Math.round(b * RATE))
    for (let i = 0; i < Math.min(fadeN, seg.length); i++) {
      seg[i] *= i / fadeN
      seg[seg.length - 1 - i] *= i / fadeN
    }
    return seg
  })
  const total = pieces.reduce((n, p) => n + p.length, 0)
  const out = new Float32Array(total)
  let o = 0
  for (const p of pieces) {
    out.set(p, o)
    o += p.length
  }

  // Chunks: the spoken text of each caption, located in order.
  const chunks = []
  let at = 0
  for (const c of scene.chunks) {
    const s = speakOf(c)
    const idx = spoken.indexOf(s, at)
    const a = idx >= 0 ? idx : at
    const b = a + s.length
    at = b
    const inChunk = words.filter((w) => w.a >= a && w.b <= b)
    chunks.push({ text: c.text, start: +mapTime(inChunk[0].start).toFixed(3), end: +mapTime(inChunk.at(-1).end).toFixed(3) })
  }

  const file = path.join(OUT, `${scene.id}.wav`)
  fs.writeFileSync(file, wav16(out))
  timing.scenes[scene.id] = {
    file: `voice/${scene.id}.wav`,
    duration: +(total / RATE).toFixed(3),
    chunks,
    words: words.map((w) => ({ w: w.w, start: +mapTime(w.start).toFixed(3), end: +mapTime(w.end).toFixed(3) })),
  }
}

// Takes no part uses any more are dropped, so the cache holds exactly what the video speaks.
for (const f of fs.readdirSync(CACHE)) if (f.includes(`.${provider}.`) && !used.has(f.replace(/\.(mp3|wav|json)$/, ''))) fs.rmSync(path.join(CACHE, f))

timing.order = script.scenes.map((s) => s.id)
timing.total = +timing.order.reduce((n, id) => n + timing.scenes[id].duration, 0).toFixed(2)
fs.writeFileSync(path.join(ROOT, 'src/timing.json'), JSON.stringify(timing, null, 1) + '\n')
console.log(`speech: ${timing.total}s across ${timing.order.length} scenes -> src/timing.json`)
