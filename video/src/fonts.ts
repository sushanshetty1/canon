import { continueRender, delayRender, staticFile } from 'remotion'

// Funnel Display and Funnel Sans (the site's faces) and JetBrains Mono, as variable fonts, loaded before any frame.
const faces: [string, string][] = [
  ['Funnel Display', 'fonts/funnel-display-latin-wght-normal.woff2'],
  ['Funnel Sans', 'fonts/funnel-sans-latin-wght-normal.woff2'],
  ['JetBrains Mono', 'fonts/jetbrains-mono-latin-wght-normal.woff2'],
]

let started = false
let resolveReady: () => void = () => {}
/** Resolves once every face is loaded and added. */
export const fontsReady: Promise<void> = new Promise((r) => (resolveReady = r))

export function loadFonts() {
  if (started || typeof document === 'undefined') return
  started = true
  const handle = delayRender('fonts')
  Promise.all(
    faces.map(async ([family, file]) => {
      const face = new FontFace(family, `url(${staticFile(file)}) format('woff2')`, { weight: '100 900', style: 'normal' })
      await face.load()
      const set = document.fonts as unknown as { add: (f: FontFace) => void }
      set.add(face)
    }),
  )
    .then(() => {
      resolveReady()
      continueRender(handle)
    })
    .catch((e) => {
      console.error(e)
      resolveReady()
      continueRender(handle)
    })
}
