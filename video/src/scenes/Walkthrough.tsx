// The product, recorded: each scene says what a feature does, then the footage proves it, the camera springing to
// exactly the thing the voice names. Times are scene seconds; take times come from each take's log
// (node capture/inspect.mjs <take>).

import { AbsoluteFill } from 'remotion'
import { C } from '../brand'
import { Clip } from '../components/Clip'
import { CONTENT_AT } from '../components/Transitions'
import { useSceneTime } from '../timeline'
import { FlowNetwork } from './FlowNetwork'

const FULL = null

export function Idea() {
  const { c, ce, dur } = useSceneTime()
  return (
    <AbsoluteFill>
      {/* What Canon reads: every kind of source into one graph */}
      <Clip
        take="landing"
        from={CONTENT_AT - 0.1}
        to={c(1) + 0.2}
        exit
        warp={[
          [CONTENT_AT - 0.1, 9.0],
          [c(1) + 0.7, 9.0 + (c(1) + 0.8 - CONTENT_AT)],
        ]}
        shots={[{ at: 0, rect: FULL }]}
        labels={[{ at: CONTENT_AT + 0.4, until: c(1) - 0.2, title: 'canon.sushans.dev', sub: 'The site, live on PostHog’s public data' }]}
        cursor={false}
      />
      {/* The hero: facts as bars over the months they held */}
      <Clip
        take="landing"
        from={c(1) + 0.2}
        to={dur}
        enter
        warp={[
          [c(1) + 0.2, 1.05],
          [dur, 1.05 + (dur - c(1) - 0.2) * 0.95],
        ]}
        shots={[
          { at: c(1) + 0.2, rect: null },
          { at: c(2) + 0.4, rect: { x: 236, y: 480, w: 1128, h: 380 } },
        ]}
        cursor={false}
      />
      {void ce}
    </AbsoluteFill>
  )
}

export function Ask() {
  const { c, dur } = useSceneTime()
  const sentence1 = { x: 578, y: 331, w: 485, h: 29 }
  const history = { x: 1146, y: 499, w: 414, h: 349 }
  const removed = { x: 337, y: 500, w: 684, h: 88 }
  return (
    <Clip
      take="ask"
      from={0}
      to={dur}
      warp={[
        [CONTENT_AT, 0.4],
        [c(1) - 1.0, 1.25],
        [c(1) - 0.15, 2.1],
        [c(1) + 2.6, 3.1],
        [c(2) - 0.3, 4.6],
        [c(2) + 1.3, 5.7],
        [c(2) + 2.6, 7.45],
        [c(2) + 2.6, 10.05],
        [c(3) + 1.6, 12.3],
        [c(4) - 0.5, 16.9],
        [c(4) + 0.1, 17.45],
        [c(4) + 1.6, 19.7],
        [dur, 19.7 + (dur - c(4) - 1.6)],
      ]}
      shots={[
        { at: 0, rect: FULL },
        { at: c(1) - 0.1, rect: { x: 420, y: 140, w: 860, h: 470 } },
        { at: c(2) + 1.0, rect: { x: 360, y: 16, w: 1225, h: 870 } },
        { at: c(3) + 0.9, rect: history, pad: 26 },
        { at: c(4) - 0.2, rect: { x: 320, y: 290, w: 1000, h: 420 } },
      ]}
      rings={[
        { at: c(2) - 0.25, until: c(2) + 1.2, rect: sentence1, kind: 'underline' },
        { at: c(3) + 1.9, until: c(4) - 0.6, rect: { x: history.x, y: history.y + 70, w: history.w, h: history.h - 70 } },
        { at: c(4) + 2.0, until: dur - 0.4, rect: { ...removed, y: removed.y + 30, h: 58 }, color: C.faint },
      ]}
      labels={[{ at: CONTENT_AT + 0.35, until: c(1) - 0.6, title: 'Ask', sub: 'The PostHog workspace, public at canon.sushans.dev' }]}
    />
  )
}

export function Dispute() {
  const { c, dur } = useSceneTime()
  return (
    <Clip
      take="dispute"
      from={0}
      to={dur}
      warp={[
        [0, 1.2],
        [c(1) - 0.35, 5.6],
        [c(1) + 0.4, 6.8],
        [c(1) + 3.8, 8.6],
        [c(2) - 0.2, 9.75],
        [c(2) + 1.4, 11.4],
        [dur, 11.4 + (dur - c(2) - 1.4) * 0.8],
      ]}
      shots={[
        { at: 0, rect: FULL },
        { at: c(1) - 0.2, rect: { x: 400, y: 140, w: 900, h: 600 } },
        { at: c(2) + 0.5, rect: { x: 1130, y: 20, w: 450, h: 560 } },
      ]}
      rings={[
        { at: c(1) + 0.6, until: c(2) - 0.3, rect: { x: 584, y: 326, w: 680, h: 250 }, color: C.amber },
        { at: c(2) + 1.5, until: dur - 0.3, rect: { x: 1146, y: 205, w: 414, h: 66 }, color: C.amber },
      ]}
      labels={[{ at: 0.9, until: c(1) - 0.4, title: 'Disputed', sub: 'Two current sources disagree, so Canon shows both' }]}
    />
  )
}

export function Fix() {
  const { c, dur } = useSceneTime()
  return (
    <Clip
      take="fix"
      from={0}
      to={dur}
      warp={[
        [CONTENT_AT, 0.6],
        [c(1) - 0.4, 3.45],
        [c(1) + 0.9, 5.6],
        [c(2) - 0.1, 7.2],
        [c(3) - 0.2, 9.4],
        [c(4) - 0.5, 12.9],
        [c(4) + 0.6, 14.95],
        [c(4) + 2.2, 17.8],
        [c(4) + 3.4, 19.4],
        [dur, 19.4 + (dur - c(4) - 3.4) * 0.6],
      ]}
      shots={[
        { at: 0, rect: FULL },
        { at: c(1) + 0.7, rect: { x: 310, y: 270, w: 900, h: 120 } },
        { at: c(2) - 0.2, rect: { x: 310, y: 270, w: 900, h: 210 } },
        { at: c(3) - 0.1, rect: { x: 1250, y: 236, w: 320, h: 230 }, max: 1.5 },
        { at: c(4) - 0.4, rect: { x: 1250, y: 236, w: 320, h: 420 } },
        { at: c(4) + 3.0, rect: { x: 240, y: 330, w: 1350, h: 520 } },
      ]}
      rings={[
        { at: c(1) + 1.4, until: c(2) - 0.2, rect: { x: 330, y: 322, w: 818, h: 55 }, color: C.proof },
        { at: c(2) + 0.2, until: c(3) - 0.2, rect: { x: 330, y: 286, w: 430, h: 32 }, kind: 'underline' },
        { at: c(2) + 0.7, until: c(3) - 0.2, rect: { x: 330, y: 436, w: 380, h: 25 } },
        { at: c(3) + 0.4, until: c(4) - 0.5, rect: { x: 1273, y: 250, w: 267, h: 47 }, pad: 8 },
        { at: c(4) + 3.3, until: dur - 0.3, rect: { x: 1272, y: 400, w: 290, h: 92 } },
      ]}
      labels={[{ at: CONTENT_AT + 0.35, until: c(1) + 0.3, title: 'Fix queue', sub: '12 lines on 5 pages, each with its correction' }]}
    />
  )
}

export function WhoKnows() {
  const { c, dur } = useSceneTime()
  return (
    <Clip
      take="whoknows"
      from={0}
      to={dur}
      warp={[
        [CONTENT_AT, 0.4],
        [c(1) - 0.5, 3.1],
        [c(1) + 0.25, 4.0],
        [c(1) + 1.6, 5.6],
        [dur, 5.6 + (dur - c(1) - 1.6) * 0.9],
      ]}
      shots={[
        { at: 0, rect: FULL },
        { at: CONTENT_AT + 0.6, rect: { x: 480, y: 230, w: 880, h: 560 } },
        { at: c(1) + 0.9, rect: { x: 1158, y: 20, w: 430, h: 470 } },
      ]}
      rings={[
        { at: c(0) + 1.8, until: c(1) - 0.6, rect: { x: 938, y: 416, w: 150, h: 52 } },
        { at: c(1) + 1.9, until: dur - 0.3, rect: { x: 1186, y: 238, w: 376, h: 64 } },
      ]}
      labels={[{ at: CONTENT_AT + 0.35, until: c(1) - 0.4, title: 'Who knows', sub: 'People ranked by what they did, with every piece of evidence' }]}
    />
  )
}

export function BusFactor() {
  const { c, dur } = useSceneTime()
  const footAt = c(3) - 0.55
  return (
    <AbsoluteFill>
      <FlowNetwork until={footAt + 0.6} />
      <Clip
        take="busfactor"
        from={footAt}
        to={dur}
        enter
        warp={[
          [footAt, 0.95],
          [dur, 0.95 + (dur - footAt)],
        ]}
        shots={[
          { at: footAt, rect: { x: 470, y: 40, w: 900, h: 300 } },
          { at: c(3) + 2.9, rect: { x: 470, y: 380, w: 900, h: 190 } },
        ]}
        rings={[{ at: c(3) + 3.6, until: dur - 0.3, rect: { x: 576, y: 440, w: 170, h: 74 }, color: C.proof }]}
        labels={[{ at: c(3) + 3.2, until: dur, title: 'Bus factor', sub: 'Pipeline sources rests on gilbert09 alone' }]}
        cursor={false}
      />
    </AbsoluteFill>
  )
}

export function Decisions() {
  const { c, dur } = useSceneTime()
  const switchAt = c(1) - 0.3
  return (
    <AbsoluteFill>
      <Clip
        take="decisions"
        from={0}
        to={switchAt}
        exit
        warp={[
          [0, 0.9],
          [switchAt, 7.6],
        ]}
        shots={[
          { at: 0, rect: FULL },
          { at: c(0) + 3.4, rect: { x: 1118, y: 12, w: 470, h: 440 } },
        ]}
        rings={[{ at: c(0) + 3.9, until: switchAt, rect: { x: 1146, y: 200, w: 300, h: 80 } }]}
        labels={[{ at: 0.9, until: c(0) + 3.2, title: 'Decisions', sub: 'Every RFC, from proposal to replacement' }]}
      />
      <Clip
        take="catchup"
        from={switchAt}
        to={dur}
        enter
        warp={[
          [switchAt, 1.3],
          [c(1) + 0.4, 2.0],
          [c(2) - 0.2, 4.6],
          [c(2) - 0.2, 22.7],
          [dur, 22.7 + (dur - c(2) + 0.2) * 0.85],
        ]}
        shots={[
          { at: switchAt, rect: { x: 290, y: 160, w: 1260, h: 360 } },
          { at: c(2) - 0.1, rect: { x: 292, y: 140, w: 860, h: 380 } },
        ]}
        rings={[{ at: c(1) + 1.6, until: c(2) + 0.2, rect: { x: 1370, y: 214, w: 150, h: 306 } }]}
        labels={[{ at: switchAt + 0.4, until: dur, title: 'Catch me up', sub: 'Everything that changed since you left, checked' }]}
      />
    </AbsoluteFill>
  )
}

export function Connect() {
  const { c, word, dur } = useSceneTime()
  const a = CONTENT_AT - 0.1
  const b = c(1) + 0.1
  const d = c(3) - 0.15
  const e = c(3) + 3.0
  const notion = word('Notion', c(1))
  const linear = word('Linear', c(1))
  const jira = word('Jira', c(1))
  const conf = word('Confluence', c(1))
  const files = word('files', c(1))
  return (
    <AbsoluteFill>
      <Clip
        take="sources"
        from={a}
        to={b}
        exit
        warp={[
          [a, 1.6],
          [b + 0.6, 1.6 + (b + 0.6 - a)],
        ]}
        shots={[{ at: a, rect: { x: 440, y: 40, w: 1100, h: 840 } }]}
        labels={[{ at: a + 0.3, until: b, title: 'Sources', sub: 'What the PostHog workspace reads, and the facts each gives' }]}
        cursor={false}
      />
      <Clip
        take="connect"
        from={b}
        to={d}
        enter
        exit
        warp={[
          [b, 0.9],
          [notion - 0.15, 2.24],
          [linear - 0.15, 4.12],
          [jira - 0.15, 5.93],
          [conf - 0.15, 7.82],
          [files - 0.15, 9.64],
          [d + 0.6, 9.64 + (d + 0.6 - files)],
        ]}
        shots={[
          { at: b, rect: FULL },
          { at: c(2) - 0.3, rect: { x: 290, y: 60, w: 760, h: 200 } },
        ]}
        rings={[{ at: c(2) + 0.2, until: d, rect: { x: 300, y: 196, w: 560, h: 24 }, kind: 'underline', pad: 4 }]}
        labels={[{ at: b + 0.3, until: c(2) - 0.4, title: 'Connect a source', sub: 'Slack, Notion, Linear, Jira, Confluence or files' }]}
      />
      <Clip
        take="newws"
        from={d}
        to={e}
        enter
        exit
        warp={[
          [d, 4.7],
          [d + 1.9, 8.05],
          [d + 1.9, 25.0],
          [d + 2.5, 25.6],
          [d + 2.5, 35.2],
          [e + 0.6, 35.8],
        ]}
        shots={[{ at: d, rect: { x: 470, y: 200, w: 900, h: 500 } }, { at: d + 1.9, rect: FULL }]}
        labels={[{ at: d + 0.3, until: e, title: 'New workspace', sub: 'From any repository you can read, private ones too' }]}
      />
      <Clip
        take="members"
        from={e}
        to={dur}
        enter
        warp={[
          [e, 9.4],
          [dur - 1.0, 12.6],
          [dur, 13.6],
        ]}
        shots={[{ at: e, rect: { x: 1170, y: 20, w: 420, h: 480 } }]}
        labels={[{ at: e + 0.3, until: dur, title: 'Members', sub: 'Only the people you invite can open it' }]}
      />
    </AbsoluteFill>
  )
}
