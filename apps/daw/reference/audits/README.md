# Windows integration audit — 2026-10-05

**Reference area:** these are dated checks and implementation observations,
including later appended UI stages. Their former "current" labels belong to
those versions. Today's app/schema and development standard are described in
[the app guide](../../README.md) and [project state](../../../../project-state.json).

This audit records the first application implementation, before later project-map, import and audio-editing revisions. It reports **64 passing cases** covering Windows startup, editing, playback, analysis, project storage and export.

The measurements belong to that implementation. Its v1 clock scopes and automatic scope-end tempo restoration differ from the current v2 project map, whose events persist until the next event. [Current behavior and validation status](../../README.md) describe the latest version.

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
node apps/daw/reference/audits/core.cjs
node apps/daw/reference/audits/project-contract.cjs
.venv-metronome-v1/bin/python apps/daw/reference/audits/fixtures.py
.venv-metronome-v1/bin/python apps/daw/reference/audits/backend.py
```

`session-routing.cjs` requires the local Vite server and Playwright at `.daw-runtime/audit-tools/playwright-core`. `windows.cjs` and `windows-extended.cjs` run with the bundled Windows Electron Node runtime. Set `BPMTRACKER_PLAYWRIGHT`, `BPMTRACKER_EXE` and `BPMTRACKER_AUDIT` to the tooling, native executable and an isolated test directory.

Fixtures, recording excerpts, screenshots, job outputs and runner results are local artifacts. Adapting these suites to later versions requires matching the current project schema and interactions; old expectations about v1 clock scopes do not describe the current application.

## Numeric controls and selection — 0.6.9, 2026-10-11

This focused audit covers native Windows editing interactions.
`refinement-u1-windows.cjs` records 17 native interaction/presentation checks for
four linked WAV imports, fraction/invalid input, one-Undo scrub/fine/wheel edits,
text Undo, exact-value copy/paste, segmented linked placement, fader cancellation,
range Escape/pointer cancellation, Object-tool consistency, captured tempo and
signature edits during real playback, and normal/1024x720 presentation.

The final report is `.daw-state/refinement-u1-20261011/u1-results.json`; review
`u1-final.png`, `u1-small.png` and `u1-invalid.png`. The optional presentation-only
run records `u1-presentation-results.json`. These generated media/profiles are
separate from ordinary workspaces. File-dialog paths are queued; clipboard and pointer
cancellation are controlled renderer events. The OS clipboard is not modified.
Real IPC, Python decoding, native project opening and AudioWorklet playback run.
No estimator invocation, sample operation, full export audit or long-run benchmark
is included. This is not an automatic build/start check or a comprehensive usability evaluation.

Explicit commands, in order:

```sh
python3 apps/daw/reference/audits/refinement-u1-fixtures.py
```

From Windows PowerShell in the checkout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/refinement-u1-windows.ps1
```

Use `-VisualOnly` for just startup/import, normal/small presentation and renderer
errors after a presentation-only change. The runner assembles a separate small
Electron application and reuses the retained Python runtime. It preserves the
ordinary BPMTracker application/profile and does not start tests through the launcher.

## Numeric and selection refinements — 0.6.10, 2026-10-11

The revision adds cursor-only footer BPM declarations, whole-number BPM gestures,
hover-wheel editing, stable numeric widths, live audio-position scrubbing, and a fix
for accumulating Inspector controls after duplicated-track selection. The focused
`refinement-u1-feedback-windows.cjs` audit passed **11 checks** in the actual Windows
Electron app. It reuses the four retained WAV fixtures and audit-owned runtime with a new
isolated workspace/profile; native file opening, decoding and playback are real.
Dialog paths are queued and project state is inspected through React.

The checks cover first and existing cursor declarations plus Undo, integer/Shift
steps with exact direct fractions, unfocused hover wheel without scrolling/focus
theft, live linked move/trim previews and cancellation in Info Line and Inspector,
hovered position segments, fixed field/segment geometry through digit boundaries,
24 duplicated-track alternations with exactly one volume/pan control and separate
track values, captured playback targets, and normal/1024x720 presentation without
renderer errors. Driver corrections for visible segment wrappers, opening Inspector
folds and the track menuitem role were completed before the final passing run.

Evidence is `.daw-state/refinement-u1-feedback-20261011/u1-feedback-results.json`,
`u1-feedback-normal.png`, `u1-feedback-small.png`, `u1-feedback-inspector.png` and
`u1-feedback-layout.json`. This audit does not run inference, sample operations,
full save/export validation, a performance benchmark or a DPI sweep.

Explicit Windows PowerShell command in the checkout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/refinement-u1-feedback-windows.ps1
```

## Timeline cursor origin and stroke — 0.6.11, 2026-10-11

The origin problem occurred when returning/dragging the project cursor. The 0.6.10 native probe found that scrollbar/wheel origin was stable
but grabbing the handle 5 px left of its center and dragging outside project zero
left the cursor at 0.4166666667 seconds (5 px at 12 px/s). The pointer time had been
clamped before adding the grab offset. Probe reports are observations, not passing
correctness checks. The ruler used a clipped 1.44 px stem beside a separate 1 px
body line and duplicate marker.

`timeline-viewport-windows.cjs` passed **7 focused native checks** after correction:
direct native scrolling, Shift-wheel, scrollbar dragging, 16 origin drags with
both grab sides and Snap Off/Beat plus Return to Start, playback drag, matching
1 px stem geometry at a fractional musical position, and no renderer errors.
`-PlaybackOnly` additionally confirms the real app's playing state explicitly;
this recheck is not counted as another distinct test group. The retained generated
four-stem project and audit-owned runtime were reused with isolated profiles.
No inference, sample operation, export audit, benchmark or DPI sweep runs.

Evidence is `.daw-state/timeline-viewport-20261011/viewport-probe.json`,
`viewport-cursor-probe.json`, `viewport-results.json`,
`viewport-playback-results.json`, `cursor-before.png` and `cursor-after.png`.
The final measured DPR was 1; cursor stems both measured 1 px at the same X.

Explicit commands in Windows PowerShell in the checkout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/timeline-viewport-windows.ps1 -Probe -CursorOnly
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/timeline-viewport-windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/timeline-viewport-windows.ps1 -PlaybackOnly
```

The historical probe reports describe 0.6.10. Running the probe command against
a newer prepared bundle records that newer app; it does not recreate old behavior.

## Workspace layout and menus — 0.6.12, 2026-10-11

This audit evaluates the implemented workspace layout and contextual menus. `refinement-u2-windows.cjs`
uses the audit-owned Electron runtime, retained four WAV fixtures and unique
profiles. File-dialog paths are queued; decoding, project opening, the renderer,
clipboard and playback cursor are native. No inference or export job is started.

The main run passed **9 checks**: import/startup, 1440x940 and 1024x720 layout,
right-click selection/lead/cursor/focus preservation, linked duplication and
one-Undo restoration, edge/submenu placement and disabled multi-track actions,
captured BPM input during playback with exact copy/staged paste, first map-point
editing/deletion, layout/map visibility and origin/stroke preservation, and
duplicate-track controls with contextual analysis entry/cancellation.

The contextual run passed **4 additional checks**: range boundary silence and
empty-row preservation, captured lane/ruler/import destinations during playback,
mixed audio/map menu scope and atomic deletion, and Linear/Musical placement and
tempo behavior. Final map presentation was rechecked with 24px Info Line and
30px Transport signature fields. A keyboard recheck covers Tab focus, menu Delete/Undo,
menu-bar arrows, and the editable-text bridge. The native text-menu callback is
captured for its role template; the OS popup's appearance and interactive native
file-picker navigation are not manually inspected. Setup/recheck repetitions are
not counted as additional distinct checks.

Corrections found during the native review include compact Analyze-button
clipping, Inspector focus changes on a selected linked member's right-click,
readout right-click incorrectly entering text mode, mixed Inspector map scope,
and layout/keyboard restoration. Driver corrections covered shortcut-inclusive
accessible names, disabled-item clicks, the range overlay selector, Shift map
selection, signature declaration semantics and separator serialization.

Reports: `.daw-state/refinement-u2-20261011/{u2-results,u2-context-results,u2-keyboard-results,u2-map-results}.json`.
Screenshots include `u2-wide.png`, `u2-compact.png`, `u2-event-menu.png`,
`u2-track-menu.png`, `u2-range.png`, `u2-mixed-menu.png`, `u2-tempo.png`,
`u2-signature.png`, `u2-analysis-entry.png` and `u2-time-base.png`.
Measured DPR is 1. This is a focused UX/connection audit, without a DPI sweep,
human listening assessment, inference, full persistence/export validation,
sample enrollment or performance benchmark. A comprehensive product usability evaluation is not established by this audit.

Explicit Windows PowerShell commands from the checkout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/refinement-u2-windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/refinement-u2-windows.ps1 -ContextOnly
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/refinement-u2-windows.ps1 -KeyboardOnly
powershell -NoProfile -ExecutionPolicy Bypass -File apps/daw/reference/audits/refinement-u2-windows.ps1 -MapOnly
```

## Project-file opening — 0.6.13

A focused native check reused the audit-owned Windows executable with a new
profile and media-free project fixtures. It passed startup opening of a Unicode
path containing spaces, explicit-file priority over an existing recovery copy,
second-instance forwarding to one window, preserving unsaved state when the same
file is requested, and cancel/accept handling for a different file. Renderer errors
were empty; evidence is `.daw-state/project-opening-20261011/project-open-result.json`.

TypeScript, Electron JavaScript and the two PowerShell scripts were parsed, and
Vite/build assembly succeeded. The ordinary app instance remained open and its
application files were not refreshed. HKCU association registration runs on the
next normal Start BPMTracker launch; Explorer double-click through that registered
association is not claimed as already exercised. No media decoding, inference,
export or broad regression suite was run for this change.

## Continuous signature positions — 0.6.14

`continuous-map.cjs` exercises actual renderer map/arrangement functions and the
Electron project validator. It checks mid-bar old-beat changes, compound eighth
boundaries, tempo continuity, illegal destinations, v2 migration, a v3 JSON
round trip, and preservation of the saved Juno project's audio/map timing.
`continuous-map-backend.py` compares the export worker's clock geometry with those
renderer fixtures and executes its JSON/MIDI map-export branch for v2/v3 maps.
These are focused checks for the continuous-map representation. Evidence is
under `data/research/design-reviews/20261011-continuous-beat-map-v1/implementation-checks/`.
They do not establish loudspeaker listening or Windows GUI playback correctness.

`continuous-map-projects.cjs RUN` additionally validates the selected native
research projects against their serialized source maps, checks original relative
media paths, and executes the ordinary metronome worklet around every emitted
source click. The 2026-10-12 delivery passed 8 projects and 9,825 clicks, without
using reference-timestamp preview playback. This is a computation/serialization
check; original media decoding and Windows device/GUI playback were not run.

Run from the checkout using the installed Node and Python environments:

```sh
node apps/daw/audit/continuous-map.cjs
python3 apps/daw/audit/continuous-map-backend.py
```
