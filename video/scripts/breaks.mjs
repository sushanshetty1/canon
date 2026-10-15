// The stricter listen-check: breaks a listener hears, not just long silences.
//   node scripts/breaks.mjs <file> [--n=-35] [--d=0.15] [--near=0.5] [--max=0.4]
// Finds every silence of at least d seconds below n dB, groups silences closer than `near` seconds to each other
// (a breath or a click between two pauses is still one break to the ear), and reports every group of two or more,
// and every group whose silence adds up to more than `max` seconds.
import { spawnSync } from 'node:child_process'

const args = process.argv.slice(2)
const opt = (k, d) => Number(args.find((a) => a.startsWith(`--${k}=`))?.split('=')[1] ?? d)
const n = opt('n', -35)
const d = opt('d', 0.15)
const near = opt('near', 0.5)
const max = opt('max', 0.4)
const mmss = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, '0')}`

for (const file of args.filter((a) => !a.startsWith('--'))) {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-i', file, '-af', `silencedetect=n=${n}dB:d=${d}`, '-f', 'null', '-'])
  const err = r.stderr.toString()
  const dur = /Duration: (\d+):(\d+):([\d.]+)/.exec(err)
  const total = dur ? Number(dur[1]) * 3600 + Number(dur[2]) * 60 + Number(dur[3]) : Infinity
  const starts = [...err.matchAll(/silence_start: (-?[\d.]+)/g)].map((x) => Math.max(0, Number(x[1])))
  const ends = [...err.matchAll(/silence_end: ([\d.]+)/g)].map((x) => Number(x[1]))
  const sil = starts.map((s, i) => [s, ends[i] ?? total])
  const groups = []
  for (const s of sil) {
    const g = groups.at(-1)
    if (g && s[0] - g.at(-1)[1] < near) g.push(s)
    else groups.push([s])
  }
  const hits = groups.filter((g) => g.length > 1 || g.reduce((x, [a, b]) => x + b - a, 0) > max)
  console.log(`${file}: ${total.toFixed(2)}s, ${sil.length} silences >= ${d}s below ${n} dB, ${hits.length} breaks`)
  for (const g of hits) {
    const silent = g.reduce((x, [a, b]) => x + b - a, 0)
    console.log(`  ${mmss(g[0][0])} to ${mmss(g.at(-1)[1])}  ${g.length} silence${g.length > 1 ? 's' : ''}, ${silent.toFixed(2)}s silent: ${g.map(([a, b]) => `${mmss(a)}-${mmss(b)}`).join(', ')}`)
  }
}
