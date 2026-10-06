# Windows integration audit — 2026-10-05

This audit records the first application implementation, before later project-map, import and audio-editing revisions. It reports **64 passing cases** covering Windows startup, editing, playback, analysis, project storage and export.

The measurements belong to that implementation. Its v1 clock scopes and automatic scope-end tempo restoration differ from the current v2 project map, whose events persist until the next event. [Current behavior and validation status](../README.md) describe the latest version.

Subsequent workflow comparisons examined 0.4.2 and 0.4.4. Version **0.5.0** has a completed frontend build and Windows app-file refresh, without new runtime, playback, regression, export round-trip or inference results. These scripts are first-version audit tools rather than an updated regression suite for 0.5.0.

## Environment

The audit used Windows Electron 44.5.1, React/TypeScript, AudioWorklet playback and the bundled Python 3.12.10 CPU runtime. Integration fixtures were separate from the original sample recordings, evaluation references and recorded 26-sample experiments.

Audit scripts run separately from ordinary build, packaging and startup.

## Coverage and results

| Area | Coverage |
| --- | --- |
| Native startup | Local application protocol, sandbox preload, rendered interface, no uncaught renderer exceptions |
| Media | WAV/MP3/FLAC, mono/stereo, 44.1/48/96 kHz, streamed HQ resampling, waveform peaks, Unicode/spaces, copied/referenced sources, corrupt and unsupported-channel input |
| Editing | Object/range selection, movement between tracks, Alt-drag copy, split, trim, linked stems, clipboard, range deletion leaving a gap, erase, undo/redo, zoom and Help |
| Transport/mix | Windows AudioContext playback, stop/seek/cycle, volume/pan/mute/solo, mono pan/stereo balance, front-event overlap priority, master gain, scoped accented click |
| Analysis | Bundled CPU inference, whole event and original-frame range, no reference/meter input, saved proposal, audition/application/edit/restoration, immutable prediction retention and cancellation |
| Hint contract | 155/160/165 against a prepared synthetic audio family yields identical complete predictions; the numeric tap is not a continuous feature |
| Project I/O | Save/open round trips, media collection, relative paths, restart recovery, cache regeneration, missing-source relocation and malformed graph rejection |
| Job routing | Project switches reject stale import/analysis completions and cancel previous jobs; obsolete cache restoration is ignored |
| Exports | Aligned stereo 48 kHz/24-bit WAV mix/stems/click, source scope/phase JSON, quantized MIDI, edited denominator and v1 overlapping-clock behavior |
| Size fixture | Nine distinct asset/cache identities, a 29m59s generated mono stimulus, 15 seconds of playback and seek/play near the end |

The named suites contain 60 cases: 12 editing/history/worklet cases, ten Python audio/export cases, six project-contract cases, three controlled React completion/selection cases and 29 unique native Windows cases. Four additional checks cover cached startup, native malformed-project rejection, native click/JSON/MIDI export and React/CSS hot reload through the real preload bridge.

All 64 cases passed after reruns. Corrected selectors and measurement hooks led to some repeated Windows executions; those reruns are not counted as additional cases.

The Windows AudioWorklet render and native WAV mix were compared over **504,000 stereo frames (10.5 seconds)**. Maximum absolute sample difference was `1.341104507446289e-7`, within the 24-bit export quantization bound. The mix also matched the sum of independently rendered stems within quantization error.

## Implementation details covered

- Frontend and backend reject an export with no selected output.
- Numeric controls expose accessible labels; unavailable actions stay disabled.
- New/open resets the engine cursor. The v1 clock-only project fixture retained its timeline extent and export access.
- Worker completion waits for stdout/stderr closure. Native math libraries are limited to four threads, and allocation failures produce a memory-specific message.
- Project switches isolate jobs. Select All clears incompatible selections so Delete targets selected audio.
- Project loading rejects unknown media/tracks, duplicate identities, invalid master settings and clips outside source bounds.
- MIDI click spacing follows the edited denominator. V1 scope overlap restores the underlying clock when the overriding scope ends.
- The Windows launcher refreshes packaged `resources/app` files and clears inherited `ELECTRON_RUN_AS_NODE` for its desktop child.

## Limits

Native file dialogs used deterministic fixture paths supplied through Playwright; interactive Windows navigation was not manually exercised. Real IPC, filesystem operations, decoders, worker processes and AudioWorklet execution were used. Controlled React cases mock worker completion to reproduce races.

Inference fixtures were a generated 24-second pulse train and the 4–18 second window of a local 30-second recording excerpt. They establish adapter behavior and result scope, without providing an unseen-song accuracy benchmark or general bar-grouping result.

The size fixture uses NTFS hardlinks to one mono stimulus with nine distinct cache identities. It measures streaming and channel workload, rather than nine different stereo songs or thirty minutes of continuous playback. Aggregate Electron working set was approximately 650 MiB; shared pages may be counted across processes, and this excludes a concurrent analysis worker.

The audit does not cover loudspeaker listening quality, every Windows device, every codec/container variant or every mouse/key combination. Model accuracy is measured separately. V1 MIDI used a 120 BPM derivative outside clock scopes, while JSON retained exact scopes and click WAV was silent there. Current v2 exports follow the persistent project map.

Initial runs encountered native allocation/GPU failures with about 250 MiB of available virtual memory. Successful native inference and the remaining checks ran with about 2.2 GiB available. Test profiles and media were isolated from normal application data.

## Run the first-version suites

From the repository root, with development dependencies installed:

```sh
node apps/daw/audit/core.cjs
node apps/daw/audit/project-contract.cjs
.venv-metronome-v1/bin/python apps/daw/audit/fixtures.py
.venv-metronome-v1/bin/python apps/daw/audit/backend.py
```

`session-routing.cjs` requires the local Vite server and Playwright at `.daw-runtime/audit-tools/playwright-core`. `windows.cjs` and `windows-extended.cjs` run with the bundled Windows Electron Node runtime. Set `JOLJAK_PLAYWRIGHT`, `JOLJAK_EXE` and `JOLJAK_AUDIT` to the tooling, native executable and an isolated test directory.

Fixtures, recording excerpts, screenshots, job outputs and runner results are local artifacts. Adapting these suites to later versions requires matching the current project schema and interactions; old expectations about v1 clock scopes do not describe the current application.
