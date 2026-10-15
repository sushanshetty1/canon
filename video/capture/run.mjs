// node capture/run.mjs <take> [<take> ...] | all
import { TAKES } from './takes.mjs'

const names = process.argv.slice(2)
const list = names.includes('all') ? Object.keys(TAKES) : names
if (!list.length) {
  console.log('takes:', Object.keys(TAKES).join(' '))
  process.exit(0)
}
for (const name of list) {
  if (!TAKES[name]) throw new Error(`no take ${name}`)
  console.log(`recording ${name}`)
  await TAKES[name]()
}
