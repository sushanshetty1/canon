// Canon's proofreader's desk, as the site defines it (web/src/index.css).
import { Easing } from 'remotion'

export const C = {
  page: '#e8e9ec',
  paper: '#fdfdfc',
  paper2: '#f3f4f6',
  night: '#0d0e12',
  night2: '#16181e',
  nightLine: '#262a33',
  line: '#e2e4e8',
  lineStrong: '#cbcfd6',
  ink: '#0d0e12',
  muted: '#5b606b',
  faint: '#8b909a',
  cobalt: '#2c46e8',
  cobaltDeep: '#2238c4',
  cobaltSoft: '#e5e9fd',
  proof: '#e0392c',
  proofSoft: '#fde6e3',
  amber: '#c97a00',
  amberSoft: '#fdf0d9',
  marker: '#ffe24a',
  markerSoft: '#fff4b0',
}

export const DISPLAY = "'Funnel Display', ui-sans-serif, system-ui, sans-serif"
export const SANS = "'Funnel Sans', ui-sans-serif, system-ui, sans-serif"
export const MONO = "'JetBrains Mono', ui-monospace, monospace"

export const FPS = 30
export const W = 1920
export const H = 1080

/** The slab every scene sits on: the footage's own 1600x900 viewport, one CSS pixel to one video pixel. */
export const SLAB = { x: 160, y: 34, w: 1600, h: 900, r: 26 }

/** The site's ease, [0.22, 1, 0.36, 1]. */
export const ease = Easing.bezier(0.22, 1, 0.36, 1)
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1)
export const easeIn = Easing.bezier(0.55, 0, 1, 0.45)
