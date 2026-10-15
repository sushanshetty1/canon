// API keys from the environment, or from the `export NAME=...` lines of ~/.zshrc. Never printed.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export function readKey(name) {
  if (process.env[name]) return process.env[name]
  try {
    const rc = fs.readFileSync(path.join(os.homedir(), '.zshrc'), 'utf8')
    const line = rc.split('\n').find((l) => l.trim().startsWith(`export ${name}=`))
    if (!line) return ''
    return line.trim().slice(`export ${name}=`.length).replace(/^['"]|['"]$/g, '')
  } catch {
    return ''
  }
}
