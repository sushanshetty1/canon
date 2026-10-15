import type { ComponentType } from 'react'
import { AbsoluteFill, Html5Audio, Sequence, staticFile } from 'remotion'
import { C } from './brand'
import { Captions, cues } from './components/Captions'
import { Transitioned } from './components/Transitions'
import { loadFonts } from './fonts'
import { Close } from './scenes/Close'
import { Graph } from './scenes/Graph'
import { Numbers } from './scenes/Numbers'
import { Open } from './scenes/Open'
import { Problem } from './scenes/Problem'
import { Ask, BusFactor, Connect, Decisions, Dispute, Fix, Idea, WhoKnows } from './scenes/Walkthrough'
import { SceneContext, placed, sceneTime, toFrames } from './timeline'

loadFonts()

const SCENES: Record<string, ComponentType> = {
  open: Open,
  problem: Problem,
  idea: Idea,
  graph: Graph,
  ask: Ask,
  dispute: Dispute,
  fix: Fix,
  whoknows: WhoKnows,
  busfactor: BusFactor,
  decisions: Decisions,
  connect: Connect,
  numbers: Numbers,
  close: Close,
}

export function Main() {
  const { scenes } = placed()
  const list = cues(scenes)
  return (
    <AbsoluteFill style={{ background: C.page }}>
      {scenes.map((p) => {
        const Scene = SCENES[p.id]
        return (
          <Sequence key={p.id} name={p.id} from={toFrames(p.start)} durationInFrames={toFrames(p.dur)}>
            <SceneContext.Provider value={sceneTime(p)}>
              <Transitioned scene={p}>
                <Scene />
              </Transitioned>
            </SceneContext.Provider>
            <Sequence from={toFrames(p.delay ?? 0)} name={`${p.id} voice`} layout="none">
              <Html5Audio src={staticFile(p.voice.file)} />
            </Sequence>
          </Sequence>
        )
      })}
      <Captions list={list} />
    </AbsoluteFill>
  )
}
