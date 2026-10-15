# Canon demo video

The hackathon demo, composed with [Remotion](https://www.remotion.dev) from headless recordings of the site and an
ElevenLabs voiceover. Output: `out/canon-demo.mp4`, 1920x1080, 30 fps, H.264 with AAC audio.

```sh
cd video
npm install
npm run voice     # voice and timing (cached; only changed scenes are generated again)
npm run render    # out/canon-demo.mp4
```

## How it is made

| Path | What it is |
| --- | --- |
| `capture/takes.mjs` | Every recorded scene, scripted: clicks, typing with a person's rhythm, smooth scrolls, drags |
| `capture/lib.mjs` | Headless Chrome with a CDP screencast of 2x frames (3200x1800 for a 1600x900 viewport), and the log of every interaction |
| `capture/repos.json` | The repository list the New workspace picker shows (the owner's repositories; see below) |
| `narration/script.json` | The narration, scene by scene, in caption-sized chunks, and the voice settings |
| `scripts/voice.mjs` | ElevenLabs text to speech with timestamps, one request per scene, cached in `voice/cache` |
| `src/timing.json` | The voice timing every cut and caption follows |
| `src/scenes.json` | The running order, transitions and pacing |
| `src/` | The composition: scenes, transitions, the footage camera, cursor and captions |

Each take is a folder of frames in `public/captures/<take>/` with `take.json`: when each frame was painted, and every
pointer sample, click, key and named element rectangle. The composition draws the cursor and click ripples from that
log, time-warps the footage so each action lands on the word that names it, and springs the camera into the
rectangle being discussed. `node capture/inspect.mjs <take> [seconds...]` lists a take's events and frames.

## Re-record

Public takes record https://canon.sushans.dev. Signed-in takes (`fix`, `connect`, `newws`, `members`) record a
local stack: the API on 8798 with development sign-in against a copy of the PostHog graph, and Vite on 4198.

```sh
docker exec canon-falkordb-1 redis-cli GRAPH.COPY canon_posthog canon_posthog-v
cd server && GITHUB_TOKEN=$(gh auth token) CANON_DEV_LOGIN=1 CANON_ACCOUNTS_GRAPH=canon_accounts_video \
  CANON_SYNC_MINUTES=0 CANON_ISSUES_DRY_RUN=1 CANON_DATA_DIR=../video/.stack-data \
  node ../video/capture/with-keys.mjs ANTHROPIC_API_KEY -- uv run canon serve --port 8798
cd web && CANON_API=http://localhost:8798 npx vite --port 4198 --strictPort
curl -s "localhost:8798/auth/dev-login?login=sushanshetty1&next=/app" >/dev/null
docker exec canon-falkordb-1 redis-cli GRAPH.QUERY canon_accounts_video \
  "MATCH (u:User {id:'dev-sushanshetty1'}) MERGE (w:Workspace {slug:'posthog-v'}) ON CREATE SET w.name='PostHog', w.public=false
   MERGE (u)-[m:MEMBER]->(w) SET m.role='owner', m.at='2026-10-15T09:00:00Z'"
cd video && node capture/run.mjs all          # or a list of takes
```

Approving in the `fix` take is a dry run: nothing reaches GitHub. Development sign-in has no GitHub token, so the
`newws` take serves the repository picker the owner's repositories (`capture/fetch-repos.mjs`) and the server
reads the chosen public repository with `GITHUB_TOKEN`. Afterwards, delete what the stack made:
`GRAPH.DELETE canon_posthog-v`, `canon_accounts_video` and `canon_sushanshetty1-cachet-cli`.

After re-recording, check each take's times (`node capture/inspect.mjs <take>`) against the warps in
`src/scenes/Walkthrough.tsx`.

## Re-voice

`npm run voice` reads `ELEVENLABS_API_KEY` from the environment or the `export` line in `~/.zshrc` (never printed),
and calls `POST /v1/text-to-speech/{voice}/with-timestamps` once per scene (or once per entry in a scene's `parts`)
with the model and voice in `narration/script.json` (Eric, `eleven_v4`). Only text that changed is generated again;
a part whose exact words an earlier take of the scene already speaks is cut out of that take instead.

The narration plays as one continuous read. Each clip is loudness-matched, then trimmed to its sound (a 10 ms window
with no sample at -35 dBFS is silence), with 6 ms fades at every cut. A burst of sound under 0.12 s between two
pauses (a click, a breath, the start of a cut-off word) is removed with the silence around it; a pause between
phrases is shortened to 0.26 s, and to 0.12 s next to a single short word, so no two audible pauses sit close
together. `src/scenes.json` starts each scene's line a breath after the previous one, with one deliberate 1 s pause
before the benchmark, and the transitions play under the voice.

Checks: `node scripts/mix.mjs` writes the narration track alone (`out/voice-mix.wav`) as the video places it;
`node scripts/breaks.mjs <file>` groups silences of 0.15 s or more below -35 dB that sit within 0.5 s of each other
and reports every group of two, or any group over 0.4 s; `node scripts/gaps.mjs <file>` lists single silences of
0.4 s or more below -40 dB. `npm run voice:draft` uses macOS `say` instead (writes files, plays nothing).

## Review

`npm run still -- --scenes` and `npm run still -- --transitions` render stills to `out/stills/`;
`npm run still -- 42.5 97` renders those seconds. Everything renders headless and silent.

## Licence

Remotion is free for individuals and for companies of up to three people, which covers this project; larger teams
need a company licence (see [remotion.dev/license](https://www.remotion.dev/license)). The fonts (Funnel Display,
Funnel Sans, JetBrains Mono) are under the SIL Open Font License. There is no music.

## Notes

- The voice is ElevenLabs (Eric, `eleven_v4`), cached for all 13 scenes in `voice/cache`.
- A full render takes about ten minutes on an M-series Mac at `--concurrency=8`.
- The disputed answer is "How often are growth reviews held?": at recording time "How do I escalate a support
  ticket?" answered with five verified sentences and no dispute.
- No Ask answer showed an out-of-date verdict at recording time (the model avoids stating replaced facts as current);
  the video shows out-of-date lines in the fix queue and the removed sentence in Ask instead.
