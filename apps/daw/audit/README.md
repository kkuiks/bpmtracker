# Explicit DAW foundation audit — 2026-10-05

The owner requested a comprehensive first-version audit, including actual Windows
execution. This is one scoped authorization. These scripts are never invoked by
ordinary development, compilation, packaging or application startup.

The audited implementation uses Windows Electron 44.5.1, React/TypeScript,
AudioWorklet playback and the bundled Python 3.12.10 CPU runtime. Original source
recordings, accepted references and both preserved 26-sample runs were not changed.
No source commit, staging, push, acquisition or paid purchase was performed.

## Functional coverage

| Area | Coverage |
| --- | --- |
| Native startup | Production local protocol, sandbox preload, rendered interface, no uncaught renderer exceptions |
| Media | WAV/MP3/FLAC, mono/stereo, 44.1/48/96 kHz, streamed HQ resampling, waveform peaks, Unicode/spaces, copied/referenced sources, corrupt and unsupported-channel input |
| Editing | Object/range selection, movement between tracks, Alt-drag copy, split, trim, linked stems, clipboard/cut/paste/duplicate, range deletion leaving a gap, erase, undo/redo, zoom and Help |
| Transport/mix | Real Windows AudioContext playback, stop/seek/cycle, volume/pan/mute/solo, mono pan/stereo balance, front-event overlap priority, master gain, scoped bar-accented click |
| Analysis | Actual bundled CPU inference, whole event and selected original-frame range, no reference/meter input, saved proposal, audition/apply/edit/reset, immutable prediction retention through undo, cancellation |
| Hint contract | 155/160/165 replay against the prepared synthetic audio family produces identical complete predictions; numeric tap is not retained as a continuous feature |
| Project I/O | Repeated save, open round trip, media collection/relative paths, close/restart recovery, fresh-workspace cache regeneration, missing-source relocation, malformed graph rejection |
| Job ownership | New projects reject previous import/analysis completion; obsolete cache restoration is ignored; old imports/analysis are cancelled on switching projects |
| Exports | Aligned stereo 48 kHz/24-bit WAV mix/stems/click, source scope/phase JSON, quantized MIDI, edited meter click interval, underlying tempo restoration after overlapping scopes |
| Initial size target | Nine independent asset/cache identities, a 29m59s generated mono recording, 15 seconds of real-time playback and seek/play near the end |

The named suites contain 60 cases: 12 editing/history/worklet cases, 10 Python
audio/export cases, 6 project-contract cases, 3 controlled React completion and
selection cases, and 29 unique native Windows cases. Some Windows checks were
rerun separately after a failed test selector or measurement hook was corrected;
repeat executions are not additional cases. Development-launch checks are
reported separately. Four additional checks passed: cached Windows startup,
native malformed-project rejection without changing the current arrangement,
native click/JSON/MIDI export, and React/CSS hot reload in the actual Windows
desktop with the real preload bridge. All 64 cases passed after scoped reruns.

The Windows AudioWorklet render and native WAV mix were compared over 504,000
stereo frames (10.5 seconds). Maximum absolute sample difference was
`1.341104507446289e-7`, within the 24-bit export quantization bound. The mix also
matches the sum of independently rendered stems within quantization error.

## Corrections made

- Disabled unavailable click/map options can no longer enable an empty export;
  the backend also rejects requests with no output.
- Import no longer advertises Cubase's deselection shortcut. Numeric controls
  expose precise accessible labels.
- New/open resets the engine cursor, and clock-only projects retain their
  timeline extent and File-menu export access.
- Worker completion waits for stdout/stderr to close. Native math libraries are
  limited to four threads before import; allocation failures receive an actionable
  message. The model algorithm, configuration and checkpoint remain unchanged.
- Project switches isolate previous jobs. Select All clears prior clock/range
  focus, so Delete removes the selected audio events.
- Project validation rejects unknown assets/tracks, duplicate identities, invalid
  master settings and events extending beyond their decoded sources.
- MIDI metronome spacing follows the edited denominator, and tempo resumes the
  underlying scope when an overriding region ends.
- The Windows launcher refreshes actual packaged application files. Passing a
  source directory to a packaged Electron executable does not replace its app.
  It also clears inherited `ELECTRON_RUN_AS_NODE` for the desktop child, so a
  launch from VS Code opens the GUI. The real script was checked in that environment.

## Limits of this audit

Native file dialogs were supplied deterministic test-owned paths by Playwright;
their interactive Windows navigation was not manually exercised. Real IPC,
filesystem work, decoders, processes, application code and AudioWorklet were used.
Controlled React tests mock only worker completion to reproduce races; they are
not native audio or inference evidence.

Inference used a generated 24-second pulse train and the selected 4–18 second
window of an owned 30-second excerpt from a preserved recording. This checks
adapter behavior and result scope. It is not an unseen-song accuracy benchmark,
reference qualification or evidence that bar grouping is always correct.

The size fixture uses nine distinct cache identities with NTFS hardlinks to one
mono stimulus. It is a streaming and channel-workload check, not nine different
stereo songs or a 30-minute continuous playback soak. Observed aggregate Electron
working set was approximately 650 MiB; shared pages can be counted in several
processes, and this excludes a concurrently running analysis worker.

Physical loudspeaker quality/listening judgment, every Windows audio device,
every codec/container variant and every mouse/key combination are outside the
measured coverage. Musical model accuracy remains the existing experiment's
separate evidence. MIDI requires a tempo even outside clock scopes; it uses a
120 BPM derivative there, while JSON retains exact scopes and click WAV is silent
outside them. Transport view settings and locators are session state.

The host initially had only about 250 MiB of available virtual memory. This
caused native allocation/GPU failures and interrupted sessions. Successful native
analysis and the remaining checks ran after available commit rose to about
2.2 GiB. No page-file settings or unrelated applications were changed by the
agent. Test profiles/data were isolated and test processes were closed.

## Repeating checks requires an explicit request

From the repository root, with the existing development dependencies:

```sh
node apps/daw/audit/core.cjs
node apps/daw/audit/project-contract.cjs
.venv-metronome-v1/bin/python apps/daw/audit/fixtures.py
.venv-metronome-v1/bin/python apps/daw/audit/backend.py
```

`session-routing.cjs` requires the local Vite server and an opt-in Playwright
installation at `.daw-runtime/audit-tools/playwright-core`. `windows.cjs` and
`windows-extended.cjs` run under the bundled Windows Electron Node runtime with
`JOLJAK_PLAYWRIGHT`, `JOLJAK_EXE` and `JOLJAK_AUDIT` pointing to isolated tooling,
the native executable and a test directory. Prepare generated media and an
explicitly approved real-recording excerpt there. Native runner results,
screenshots, jobs and media remain ignored local artifacts.
