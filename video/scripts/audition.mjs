// Short samples from a few voices, to choose a narrator: `node scripts/audition.mjs <model> <voiceId>...`.
// Writes .audition/<voice>.mp3 and reports whether the model returned timestamps. Plays nothing.
import fs from 'node:fs'
import path from 'node:path'
import { readKey } from './keys.mjs'

const key = readKey('ELEVENLABS_API_KEY')
const [model, ...voices] = process.argv.slice(2)
const text = 'Every company brain can find a page and cite it. None of them checks whether that page is still true.'
const dir = path.resolve(new URL('../.audition', import.meta.url).pathname)
fs.mkdirSync(dir, { recursive: true })
for (const v of voices) {
  const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${v}/with-timestamps?output_format=mp3_44100_192`, {
    method: 'POST',
    headers: { 'xi-api-key': key, 'content-type': 'application/json' },
    body: JSON.stringify({ text, model_id: model, voice_settings: { stability: 0.5, similarity_boost: 0.75, style: 0, speed: 0.95 }, next_text: 'PostHog’s handbook says the PostHog AI team owns the MCP server.' }),
  })
  if (!res.ok) {
    console.log(v, res.status, (await res.text()).slice(0, 300))
    continue
  }
  const body = await res.json()
  fs.writeFileSync(path.join(dir, `${model}_${v}.mp3`), Buffer.from(body.audio_base64, 'base64'))
  const a = body.alignment
  console.log(v, 'chars', a?.characters?.length, 'end', a?.character_end_times_seconds?.at(-1))
}
