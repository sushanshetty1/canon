import { Composition } from 'remotion'
import { FPS, H, W } from './brand'
import { Main } from './Main'
import { placed, toFrames } from './timeline'

export function Root() {
  const { total } = placed()
  return <Composition id="CanonDemo" component={Main} durationInFrames={toFrames(total)} fps={FPS} width={W} height={H} />
}
