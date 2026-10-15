// Lists the ElevenLabs voices this account can use: `node scripts/voices.mjs`.
import { readKey } from './keys.mjs'

const key = readKey('ELEVENLABS_API_KEY')
if (!key) throw new Error('ELEVENLABS_API_KEY is not set')
const res = await fetch('https://api.elevenlabs.io/v2/voices?page_size=100', { headers: { 'xi-api-key': key } })
const body = await res.json()
for (const v of body.voices ?? []) {
  const l = v.labels ?? {}
  console.log([v.voice_id, v.name, v.category, l.gender, l.age, l.accent, l.descriptive ?? l.description, l.use_case].join(' | '))
}
const sub = await fetch('https://api.elevenlabs.io/v1/user/subscription', { headers: { 'xi-api-key': key } })
const s = await sub.json()
console.log('characters', s.character_count, 'of', s.character_limit, s.tier)
