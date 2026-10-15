// Listen-check by analysis: every silence of at least `d` seconds below `n` dB, per file.
//   node scripts/gaps.mjs [--n=-40] [--d=0.4] <file> [...]
import { spawnSync } from 'node:child_process'

const args = process.argv.slice(2)
const n = args.find((a) => a.startsWith('--n='))?.slice(4) ?? '-40'
const d = args.find((a) => a.startsWith('--d='))?.slice(4) ?? '0.4'
for (const file of args.filter((a) => !a.startsWith('--'))) {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-i', file, '-af', `silencedetect=n=${n}dB:d=${d}`, '-f', 'null', '-'])
  const err = r.stderr.toString()
  const dur = /Duration: (\d+):(\d+):([\d.]+)/.exec(err)
  const total = dur ? Number(dur[1]) * 3600 + Number(dur[2]) * 60 + Number(dur[3]) : NaN
  const starts = [...err.matchAll(/silence_start: ([\d.]+)/g)].map((x) => Number(x[1]))
  const ends = [...err.matchAll(/silence_end: ([\d.]+) \| silence_duration: ([\d.]+)/g)].map((x) => [Number(x[1]), Number(x[2])])
  console.log(`${file}: ${total.toFixed(2)}s, ${starts.length} silences >= ${d}s below ${n} dB`)
  starts.forEach((s, i) => {
    const e = ends[i]
    const mmss = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, '0')}`
    console.log(`  ${mmss(s)} to ${e ? mmss(e[0]) : 'end'}  (${e ? e[1].toFixed(2) : (total - s).toFixed(2)}s)`)
  })
}
