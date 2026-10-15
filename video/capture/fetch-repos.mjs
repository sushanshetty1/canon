// The repository list the New workspace picker shows in the video: the owner's public GitHub repositories, plus
// the two private ones this project lives next to. Development sign-in has no GitHub token, so the take serves this
// list in place of GitHub's. Run once: node capture/fetch-repos.mjs
import fs from 'node:fs'

const login = 'sushanshetty1'
const res = await fetch(`https://api.github.com/users/${login}/repos?sort=pushed&per_page=100`, { headers: { 'User-Agent': 'canon-video' } })
const list = await res.json()
const skip = new Set(['sushanshetty1/Keylogger-Monitor-GUI', 'sushanshetty1/sushanshetty1'])
const rows = [
  { full_name: `${login}/canon`, name: 'canon', private: true, description: 'A company brain that checks its own answers.', pushed_at: '2026-10-15T08:10:00Z' },
  { full_name: `${login}/diffcut`, name: 'diffcut', private: true, description: '', pushed_at: '2026-10-12T17:40:00Z' },
  ...list
    .filter((r) => !skip.has(r.full_name) && !r.archived)
    .map((r) => ({ full_name: r.full_name, name: r.name, private: false, description: (r.description || '').slice(0, 200), pushed_at: r.pushed_at })),
].map((r) => ({ ...r, owner: login, owner_kind: 'user', archived: false }))
fs.writeFileSync(new URL('./repos.json', import.meta.url), JSON.stringify(rows, null, 2) + '\n')
console.log(rows.length, 'repositories')
