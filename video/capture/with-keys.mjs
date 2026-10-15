#!/usr/bin/env node
// Runs a command with API keys read from the `export NAME=...` lines of ~/.zshrc, without printing them.
// Usage: node with-keys.mjs ANTHROPIC_API_KEY,ELEVENLABS_API_KEY -- <command> [args...]
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const [names, sep, cmd, ...args] = process.argv.slice(2)
if (sep !== '--' || !cmd) {
  console.error('usage: with-keys.mjs NAME[,NAME] -- command [args]')
  process.exit(2)
}

export function readKey(name) {
  if (process.env[name]) return process.env[name]
  const rc = fs.readFileSync(path.join(os.homedir(), '.zshrc'), 'utf8')
  const line = rc.split('\n').find((l) => l.trim().startsWith(`export ${name}=`))
  if (!line) return ''
  return line.trim().slice(`export ${name}=`.length).replace(/^['"]|['"]$/g, '')
}

const env = { ...process.env }
for (const n of names.split(',')) {
  const v = readKey(n)
  if (v) env[n] = v
  else console.error(`with-keys: ${n} not found`)
}
const child = spawn(cmd, args, { env, stdio: 'inherit' })
child.on('exit', (code) => process.exit(code ?? 1))
for (const s of ['SIGINT', 'SIGTERM']) process.on(s, () => child.kill(s))
