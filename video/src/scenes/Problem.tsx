// The problem, on PostHog's own pages: the handbook still names the old owner, the ownership map moved it, and an
// answer built by search quotes the handbook with a citation. The red pin from the opening grows into the page.

import { interpolate } from 'remotion'
import { C, DISPLAY, MONO, SANS, ease } from '../brand'
import { PaperSlab, Struck, Written, clamp, pop, ramp, useSec } from '../components/ui'
import { useSceneTime } from '../timeline'
import { PIN_RECT } from './Open'

const HANDBOOK = { x: 80, y: 84, w: 700, h: 396 }
const MAP = { x: 820, y: 84, w: 700, h: 396 }
const ANSWER = { x: 80, y: 516, w: 1440, h: 300 }

const lerp = (a: number, b: number, p: number) => a + (b - a) * p

function Meta({ children }: { children: React.ReactNode }) {
  return <div style={{ fontFamily: SANS, fontSize: 18, color: C.muted }}>{children}</div>
}

export function Problem() {
  const { sec: s, fps } = useSec()
  const { c, word } = useSceneTime()

  // The pin grows into the handbook page.
  const g = interpolate(s, [0, 0.7], [0, 1], { ...clamp, easing: ease })
  const bg = ramp(s, 0.15, 0.45)
  const box = {
    x: lerp(PIN_RECT.x, HANDBOOK.x, g),
    y: lerp(PIN_RECT.y, HANDBOOK.y, g),
    w: lerp(PIN_RECT.w, HANDBOOK.w, g),
    h: lerp(PIN_RECT.h, HANDBOOK.h, g),
  }
  const red = 1 - ramp(s, 0.4, 0.4)
  const content = ramp(s, 0.55, 0.5)

  const mapIn = pop(s, c(1) - 0.2, fps)
  const mapStrike = ramp(s, c(1) + 1.2, 0.5)
  const mapWrite = ramp(s, c(1) + 1.55, 0.55)
  const edited = ramp(s, c(1) + 3.0, 0.5)

  const ansIn = pop(s, c(2) - 0.15, fps)
  const ansStrike = ramp(s, word('confident', c(2)) + 0.1, 0.55)
  const ansTag = pop(s, word('confident', c(2)) + 0.5, fps, { damping: 14, stiffness: 170, mass: 0.7 })
  const marker = ramp(s, 1.0, 0.7)

  return (
    <PaperSlab style={{ background: 'transparent', boxShadow: 'none' }}>
      <div style={{ position: 'absolute', inset: 0, background: C.paper, opacity: bg }} />

      {/* The handbook page */}
      <div
        style={{
          position: 'absolute',
          left: box.x,
          top: box.y,
          width: box.w,
          height: box.h,
          borderRadius: lerp(99, 24, g),
          background: `rgb(${Math.round(lerp(243, 224, red))}, ${Math.round(lerp(244, 57, red))}, ${Math.round(lerp(246, 44, red))})`,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 46,
            top: 0,
            height: PIN_RECT.h,
            display: 'flex',
            alignItems: 'center',
            fontFamily: SANS,
            fontWeight: 600,
            fontSize: 16,
            color: C.paper,
            whiteSpace: 'nowrap',
            opacity: 1 - ramp(s, 0.22, 0.25),
          }}
        >
          Handbook still says PostHog AI
        </div>
        <div style={{ position: 'absolute', inset: 0, padding: '34px 38px', opacity: content }}>
          <Meta>Handbook · AI products · edited Sep 23, 2026</Meta>
          <div style={{ marginTop: 14, fontFamily: DISPLAY, fontWeight: 600, fontSize: 38, letterSpacing: '-0.035em', color: C.ink }}>Current status and ownership</div>
          <div style={{ marginTop: 22, fontFamily: SANS, fontSize: 27, lineHeight: 1.6, color: C.ink }}>
            MCP is in general availability.{' '}
            <span
              style={{
                backgroundImage: `linear-gradient(to bottom, transparent 18%, ${C.marker} 18%, ${C.marker} 92%, transparent 92%)`,
                backgroundRepeat: 'no-repeat',
                backgroundSize: `${marker * 100}% 100%`,
                boxDecorationBreak: 'clone',
                WebkitBoxDecorationBreak: 'clone',
              }}
            >
              The PostHog AI team owns the MCP server,
            </span>{' '}
            <span style={{ color: C.faint }}>with a named support contact…</span>
          </div>
          <div style={{ position: 'absolute', left: 38, bottom: 30, fontFamily: SANS, fontWeight: 600, fontSize: 19, color: C.proof, opacity: edited }}>Edited six days after the ownership moved.</div>
        </div>
      </div>

      {/* The ownership map */}
      <div
        style={{
          position: 'absolute',
          left: MAP.x,
          top: MAP.y,
          width: MAP.w,
          height: MAP.h,
          borderRadius: 24,
          background: C.paper2,
          padding: '34px 38px',
          transform: `translateY(${(1 - mapIn) * 40}px)`,
          opacity: Math.min(1, mapIn * 1.3),
        }}
      >
        <Meta>Ownership map · Sep 17, 2026</Meta>
        <div style={{ marginTop: 14, fontFamily: DISPLAY, fontWeight: 600, fontSize: 38, letterSpacing: '-0.035em' }}>MCP server</div>
        <div style={{ marginTop: 30, display: 'flex', alignItems: 'baseline', gap: 18, fontFamily: DISPLAY, fontWeight: 600, fontSize: 46, letterSpacing: '-0.035em' }}>
          <Struck p={mapStrike} color={C.faint}>
            Self-Driving
          </Struck>
          <Written p={mapWrite} style={{ color: C.cobalt }}>
            Context &amp; MCP
          </Written>
        </div>
        <div style={{ marginTop: 34, fontFamily: MONO, fontSize: 18.5, lineHeight: 1.6, color: C.muted }}>
          MCP server (mcp-server): owner changed
          <br />
          from self-driving to context-and-mcp.
        </div>
      </div>

      {/* An answer built by search and summarise */}
      <div
        style={{
          position: 'absolute',
          left: ANSWER.x,
          top: ANSWER.y,
          width: ANSWER.w,
          height: ANSWER.h,
          borderRadius: 24,
          background: C.paper,
          boxShadow: `inset 0 0 0 1.5px ${C.line}`,
          padding: '50px 46px',
          transform: `translateY(${(1 - ansIn) * 40}px)`,
          opacity: Math.min(1, ansIn * 1.3),
        }}
      >
        <Meta>An answer from search and summarise</Meta>
        <div style={{ marginTop: 22, display: 'flex', alignItems: 'center', gap: 18 }}>
          <span style={{ fontFamily: SANS, fontWeight: 500, fontSize: 44, letterSpacing: '-0.015em' }}>
            <Struck p={ansStrike} color={C.ink} thickness={0.075}>
              The PostHog AI team owns the MCP server.
            </Struck>
          </span>
          <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 20, color: C.cobalt, background: C.cobaltSoft, borderRadius: 8, padding: '4px 10px' }}>1</span>
        </div>
        <div style={{ marginTop: 28, display: 'flex', alignItems: 'center', gap: 22 }}>
          <span style={{ fontFamily: SANS, fontSize: 20, color: C.muted }}>
            <span style={{ fontWeight: 600, color: C.cobalt }}>1</span>&nbsp;&nbsp;Handbook · AI products&nbsp;&nbsp;
            <span style={{ color: C.faint }}>cited</span>
          </span>
          <span
            style={{
              marginLeft: 'auto',
              transform: `scale(${0.6 + 0.4 * ansTag})`,
              opacity: ansTag,
              background: C.proof,
              color: C.paper,
              fontFamily: SANS,
              fontWeight: 600,
              fontSize: 20,
              padding: '9px 18px 10px',
              borderRadius: 99,
              boxShadow: '0 10px 26px -8px rgba(224,57,44,0.55)',
            }}
          >
            Out of date since Sep 17
          </span>
        </div>
      </div>
    </PaperSlab>
  )
}
