# Joljak audio workspace

Arrange songs and stems on a shared tempo/signature map, inspect fixed-metronome predictions, and export aligned audio and maps. Joljak runs on Windows with an English interface. The current version is **0.6.6**.

The initial design target is fewer than ten tracks and projects under thirty minutes. Analysis produces one constant BPM, time signature and downbeat offset for a selected song or range. The project map can contain multiple editable tempo and signature events.

## Review formal samples in the DAW

Open **Samples**, select an enrolled recording and choose **Open sample workspace**.
The app reads `data/samples/catalog.json` and the approved audio-relative reference.
Development launch connects the checkout's library automatically; a portable app
can use **Select catalog…** to locate that catalog. Sample recordings remain in
their library and are not bundled with the app.

The library shows readable quarter-BPM labels, signatures, original clock offset,
approved reference scope and unannotated/no-grid margins. The workspace imports
the recording onto a Linear track and brings its tempo/signature map into the
existing editor. A short project lead-in puts the first audible downbeat on a
whole project bar while retaining cropped source audio. Source offset is already
included in the reference; no second offset is added. This lead-in does not claim
original DAW bar numbering.

**Sample Reference** in the Inspector provides **Audition approved click**,
**Audition edited project map**, alignment adjustment and a draft note. The approved
click uses the stored beat/bar timestamps and reference scope. The project click
uses the editable map and its ordinary persistence rules. If a source signature
boundary falls between project bars, the app identifies that import limitation
and keeps the approved click available. Stored reference evidence remains separate
from analysis inputs and raw model predictions.

Hospital Hill also has the owner-requested **Compare 102 / 110 BPM** and **Open
102 / 110 draft** options. The comparison preserves the first approved downbeat
and original musical quarter positions, then recomputes subsequent clock times;
it does not silently reset phase at each original change timestamp.

**Save sample draft** writes an editable `project.joljak` and a `proposal.json`
under `data/samples/reviews/daw-drafts/<sample-id>/<saved-time>/`. Normal project
save also retains the reference snapshot and working map. Saving a draft does
not replace the accepted reference, original offset, formal membership or frozen
research results. A changed accepted-reference version blocks draft publication
until the sample is reopened; confirmation of a new reference is a separate step.

## Run on Windows

In an assembled portable bundle, run **`Joljak.exe`** and keep the complete folder together. The bundle contains Electron, Python 3.12, CPU analysis dependencies and the official Beat This final0 checkpoint. It runs offline without a separate Node.js, Python or WSL installation. Source recordings and evaluation references are not included.

For development, run **`Start Joljak.cmd`** in the repository root from Windows Explorer. First launch requires the frontend build and `dist/Joljak-win-x64.zip`; it extracts the runtime into `%LOCALAPPDATA%\Joljak\development`. Later launches reuse that runtime and refresh the built UI, Electron code and Python adapter. Close the app before relaunching to load a new build.

The portable folder is `dist/Joljak-win-x64/` at the repository root. Updating this folder does not update the ZIP. An existing ZIP can seed the development cache, after which the launcher copies current application files from the checkout.

## Basic workflow

1. **Import Audio**: select WAV, MP3 or FLAC files and choose **One track**, **Different tracks** or **Aligned stems**. Files can remain referenced at their original location or be copied into app-local media storage.
2. Select an event with Object Selection (`1`), or use Range Selection (`2`) to select part of an event.
3. **Analyze Audio**: optionally tap or enter an approximate quarter BPM. This selects a metrical layer; precise BPM, meter and phase come from audio. There is no initial meter input.
4. Audition the proposal, then use **Apply & Align**. The preview shows the target project bar and signed shift. The song and linked stems move together so the inferred first downbeat lands on that bar.
5. Edit audio, project Tempo/Signature events or saved analysis values. **Restore Original Prediction** restores saved analysis values; use **Apply & Align** separately to update the map and placement.
6. Save a `.joljak` project. **Save As → Collect original audio** gathers sources for portability. Export WAV mix/stems/click and tempo-map JSON/MIDI.

## Review newly collected candidates

Agents prepare `daw-review.json` from retained supplied-clock records following
the [collection workflow](../../tools/ntm_collection/README.md#prepare-and-review-a-batch-in-joljak).
Use **Samples → Open candidate review…** and open that descriptor. Candidates
remain labelled unaccepted and do not appear as new formal enrollment.

The Inspector shows **Initial proposal**, **Alignment adjustment** and **Total
working offset**. For example, a +30 ms source offset with +20 ms adjustment means
a +50 ms total working offset. **Audition original candidate click** retains the
initial proposal; the ordinary working project click follows edited map/placement.
Use **Save sample draft** to retain the proposed project and total offset, then
report the desired reference and reviewed scope to the agent. Explicit approval
is separate from draft saving.

Candidate workspaces add whole-bar project lead-in so positive source-offset
alternatives can move audio earlier while keeping it inside the project. This
changes project placement only; source audio and source clocks keep their native
geometry. The initial and total source offsets are independent of that lead-in.

A **Source only · unaccepted** entry can open its full recording without a
supplied metronome. BPM, signature and source offset show **Not supplied**. The
ordinary project starts with an editable 120 BPM / 4/4 grid and its metronome
off; these defaults are not reference evidence. Save a manual working-map draft
or a note with **Save sample draft**. Such a draft has no calculated source
offset and remains outside formal membership.

## Import audio and manage tracks

A single file dropped onto an audio lane imports onto that track at the pointer time. Dropping below the lanes creates a track. Snap controls placement; Ctrl bypasses Snap temporarily. Dropping into the track list inserts tracks at the indicated row and places their audio at the project cursor.

Multiple files open Import Audio so file order, placement and source storage can be selected. The destination is captured before decoding; moving the cursor or changing track selection during decoding does not redirect the import. Import preserves the current zoom.

| Import mode | Placement |
| --- | --- |
| One track | Files follow one another on the selected track or one new track, in the displayed order. |
| Different tracks | Each file gets an independent track with the same start time. |
| Aligned stems | Each file gets a track with the same start time; events are linked for group editing. |

Placement can use the captured cursor/drop time, the last audio event end or a specified musical/seconds position. New tracks start **Linear**. Import onto an existing track retains its mixer settings and time base.

The copy option stores originals in Joljak's app-local media directory. **Save As → Collect original audio** is the way to gather sources beside a portable project. Confirmed import preferences are remembered; cancellation restores the previous choices. Cancelled or failed imports release only their newly allocated media and cache files. Existing project assets and undo resources remain available.

- `T`, the track-list plus button, blank-list double-click or Project menu opens **Add Audio Track**, with name and count.
- Click a track header to select a track. Ctrl-click selects individual tracks; Shift-click selects a contiguous range. Track focus preserves the selected event, range or map object.
- Double-click a track name to rename it. Drag headers to reorder the selected tracks; MixConsole follows the same order.
- Track context menus provide select-all-events, duplicate, remove and move up/down. `Shift Delete` removes selected tracks, with confirmation when they contain audio.
- Duplication shares source media and gives copied event groups new IDs. Removal affects events on the selected tracks, retains source media and analysis records, and leaves the shared map in place.
- Imports and track changes participate in Undo/Redo.

## Edit audio

Object Selection (`1`) selects and moves events. Its lower corner handles trim by hiding or revealing source content. Range Selection (`2`) selects a time window across tracks. Split (`3`) and Erase (`5`) retain their own actions at event corners. Shift marquee adds to the selection.

Events can move between tracks, be copied with Alt-drag, split with Alt-click, or be split at the cursor with Alt X. Ctrl constrains the movement axis while dragging an event. During trim and range gestures, Ctrl bypasses Snap. Alt and Ctrl can change during a drag; previews follow the current modifiers and movement limits.

**Linked edits** (`K`) carries move/copy/split/trim/delete across a stem group. Ctrl G groups events and Ctrl U ungroups them. Mixer controls remain independent. **Apply & Align** moves linked stems together regardless of the ordinary Linked edits setting.

### Range and clipboard

Double-click an event with Range Selection to select its full duration. Shift extends a range. Drag the selected range's body to move its audio, Alt-drag to copy, or drag its edges to resize the selection. The Info Line edits range Start, End and Length without moving audio. Range deletion leaves the gap in place.

Range clipboard data preserves the selected duration, leading/trailing silence and empty rows between source tracks. Paste starts at the cursor on the selected destination track and retains relative track spacing. Missing destination rows create tracks. Copies become selected. Ctrl D duplicates after the event selection span or the full selected range.

For example, copying a 1–5 s range containing audio only at 2–4 s and pasting at 12 s places audio at 13–15 s and selects the complete 12–16 s range.

Audio Cut/Copy/Paste is unavailable while a Tempo/Signature point is selected. Delete acts on the visible audio or map selection. Saved analysis drafts have a separate **Remove Saved Clock** button.

### Audio Editor and overlapping events

Object-tool double-click, Ctrl E or Return opens the selected event in the lower **Audio Editor**. Its local Range, Trim and Split tools edit the event non-destructively. The pane shows the source waveform, project cursor/grid and event boundaries, with zoom/fit and an explicit Analyze button. Opening it closes the lower MixConsole.

Alt X in the Project window splits selected events, or all intersecting events when none are selected. In the focused Audio Editor it targets that event. Shift X splits at both range boundaries.

Right-click an overlap to select a hidden event. **Move to Front** (`U`) and **Move to Back** (`Shift U`) change order. At each time, only the front event on a track is audible.

A gesture makes one undo entry. No-op edits leave history unchanged. Undo/Redo shows the next action; original media and raw analysis records remain retained across history changes.

Ordinary event and range edits leave the shared Tempo/Signature map in place. A separate song-level move/copy operation carrying audio, stems and related map events is still pending.

## Project map and timing

The toolbar and Info Line sit above the arrangement. Tempo and Signature are separate project tracks sharing the audio grid. Their Inspector lists and edits map events. MixConsole opens in the lower zone; Transport sits at the bottom.

New projects start with whole-project values of **120 BPM, 4/4**, no declared map points, a Bars+Beats ruler and a 30-minute project duration. Whole-project values also apply before the first declaration of that kind. Each declared tempo/signature holds until the next point, including through silence. No automatic point is inserted at project start or at a song/range end.

**Project → Project Setup** changes project duration. Content length is separate: exports use the content range or locators. Import and alignment extend project duration when necessary. Switching the ruler between Bars+Beats and Seconds does not change a track's time base.

### Linear and Musical tracks

| Time base | Effect of a project tempo edit |
| --- | --- |
| Linear | Event positions remain fixed in seconds. |
| Musical | Event quarter positions remain fixed, so their physical positions move with the map. |

Switching time base preserves current placement. Source offsets, audio duration and playback speed remain fixed in both modes. Tempo edits affect every Musical track, so a later song can need realignment after changing earlier tempo events.

### Map editing

Tempo events use the shared quarter clock; signature events attach to whole project bars. Bar numbering continues through songs and signature changes.

Click a map point to edit it in the Inspector. Double-click a map track or use its `+` button to declare a point. Drag a tempo point horizontally for position and vertically for BPM. Every declared point, including one at project start/bar 1, can move or be removed with Erase/Delete. Removing all points of a kind leaves its whole-project value in effect.

Tempo, Signature and audio-event position fields use the same
**Bar.Beat.Sixteenth.Tick** format, such as `5.1.1.0`, in both the Inspector and
Info Line. Range bounds and custom import positions use that format too,
independently of the ruler display. Enter or focus loss applies the position;
Escape cancels it. A bare bar number such as `5` expands to `5.1.1.0`.
Signature positions use whole-bar starts (`x.1.1.0`); invalid positions are
rejected with an inline explanation. A point at `1.1.1.0` uses the same editable
position control as other points. Position editing uses the current project map and
preserves the existing move/trim and Linear/Musical timing rules. Durations,
source-relative timing and alignment-adjustment fields retain their time units;
Transport keeps its explicit optional seconds display.

The bottom **Tempo** and **Time signature** fields edit the whole-project value when that kind has no declared points, regardless of cursor position. Once a kind has points, committing its bottom field declares the entered value **at the cursor**, preserving preceding values. At an occupied position it updates that point. Time signature accepts entries such as `4/4` or `7/8`; declaring a signature requires a whole-bar cursor position (`x.1.1.0`). Enter or focus loss commits; Escape cancels. Entering the current value at another position still declares a point. To start point-based editing, use the map lane's `+` button or double-click it.

Existing point/Inspector editing changes that point's value. **Apply & Align** also assesses tempo and signature separately: without declarations of that kind, it applies the analyzed value to the whole project without creating points. With existing declarations, it inserts/updates the analysis at the aligned scope start or first downbeat bar and preserves preceding whole-project values. Alignment conflict review is still pending.

The ruler, musical position, snap, ordinary click and map export use the project map. Bars+Beats displays `bar.beat.sixteenth.tick`, with 120 display ticks per sixteenth; stored second and quarter coordinates keep their full precision.

### Select and move audio and clock points together

Object Selection (`1`) can select audio events, multiple Tempo points and
multiple Signature points together. Shift-click adds or removes an item;
Shift-clicking a selected linked stem toggles its linked audio group. Drag a
selection box across the audio and map lanes, or press Ctrl A in the Project
window to select all three kinds. Selecting another unselected item without
Shift replaces the selection; dragging an already selected item keeps the group.

Drag a member of a mixed selection horizontally to move the entire group.
**Move Selection** in the Inspector and Info Line shows the selected counts,
**Selection position** in Bars+Beats, and **Move by** with Bars/Beats units and
−1/+1 buttons. The earliest selected item determines the numeric destination.
The destination grid excludes the moving clock and uses whole-project values
before remaining declarations, so moving a tempo map does not use its former location as the new timing
reference. Audio-only multi-selections can use the same numeric controls.

Selected audio and map points share one physical time shift. BPM/signature
values, source audio ranges, duration and playback speed stay fixed. Selected
Musical audio is moved once; unselected Musical tracks follow the resulting map
normally and Linear tracks keep their absolute placement. The pointer preview
uses the same transaction as the committed move, with one Undo/Redo entry.
Joint audio/map moves also retain the sample's existing alignment adjustment.

When a point at project start is included, it moves with the group without
creating a replacement point at zero/bar 1. Signature
points require whole-bar destinations. An incompatible signature boundary or a
collision with an unselected map point blocks the complete move and displays
the reason, without partially moving audio or overwriting another point.
Mixed-selection drags preserve each audio track; audio-only drags retain their
existing track moves and Alt-copy. Copy/Cut/Duplicate/Split currently require an
audio-only selection. Delete removes selected items together, including points
at project start; whole-project values stay available without a map point.

## Analysis and saved predictions

The adapter uses the [fixed-metronome estimator](../../experiments/metronome_reconstruction_v1/README.md) with its recorded configuration. It receives selected source audio, without evaluation timestamps, alignment offsets, meter labels or song-specific rules. Selection bounds are rounded to original decoded sample frames. Candidates and scores are prepared before the tap is read.

The separate [benchmark comparison](../../experiments/metronome_benchmark_v1/README.md#recorded-expansion-and-method-comparison)
records frozen development/validation and defined-clock results for this estimator
and two alternative clock fitters. The application's adapter still uses the
original estimator; the comparison implementations are not integrated into the
app. They use the same neural observations, without new neural training.

Raw predictions and source bounds remain separate from editable saved clocks and the project map. Audition previews a saved clock without applying it; ordinary project click can be restored afterwards. **Restore Original Prediction** restores saved values without running the model or changing placement.

Split and copied fragments inherit saved clocks where source audio overlaps the original analyzed range. Their drafts are independent, while original source bounds and raw results remain unchanged. Audition and application use the remaining intersection and preserve original downbeat phase. Extending a clip does not extend the inferred scope into unobserved audio.

**Apply & Align** shows a placement preview, updates the project map and shifts the song and linked stems to a real bar. Each track retains its chosen time base. Persistent project map events remain working arrangement values beyond the analyzed scope; they do not extend the prediction's audio coverage.

When a kind has no declared points, its analyzed value becomes the whole-project
value before computing placement. The downbeat offset still aligns audio/stems;
it does not delay the start of the whole-project tempo or signature. Reapplying
the same saved analysis replaces only its untouched analysis-origin declarations,
so **Apply & Align** can correct a 0.6.5 application without rerunning analysis.
Manual edits and declarations from other analyses remain in place. Both the
placement preview and application use the same calculation.

## Transport and mixer

Transport provides L/R locators, Cycle, Stop, Start, musical position, tempo/meter, click volume and output meters.

Stop preserves position, Start resumes, and a second Stop while stopped returns to the last playback start. Space toggles playback. Num Enter always starts/resumes; Return starts when no event is selected and otherwise opens Audio Editor. Drag the lower ruler or cursor head to seek while stopped or playing; Ctrl bypasses Snap.

Ctrl-wheel zooms around the pointer, Shift-wheel pans horizontally, and fit shows the project. Playback auto-scroll yields briefly during zoom and cursor dragging.

Inspector and MixConsole provide track volume, pan, mute and solo. The volume fader has a dB readout, Shift fine adjustment and Ctrl-click reset to 0 dB; its bottom detent is silence. Click volume is independent and saved with the project. Playback and click export use the same click level.

The click's new default is **+6 dB above the former default**. **Click boost**
displays 0 dB at this new default and permits up to **+12 dB above it**; Ctrl-click
resets the click fader to that default. Both the slider and numeric field use this
same reference. Opening an older project still at its former default raises that
default once in memory. Saved custom levels and mute are retained. Opening does
not overwrite saved project files or change audio placement, maps or references.
Changing click volume keeps the current reference/analysis audition selected.

## Save, recover and export

Projects use schema v2 with assets, tracks, clips, whole-project `bpm` and `signature` values, declared tempo/signature events, saved clocks and original analysis records. Save As can collect original audio for portability. Project recovery and cache regeneration use the application workspace; missing sources can be relocated. Project switches cancel stale import/analysis jobs and reject their completions. Exports retain their original project snapshot.

Older v1 projects open with preserved audio placement and saved predictions, whole-project 120 BPM/4/4 values and no declared points. Older v2 projects recover whole-project values from their former starting state. Identified default-origin automatic points and the start-state copies generated by 0.6.4 are removed during in-memory migration; manually declared, imported and analysis-origin points remain editable, including points at zero/bar 1. Migration preserves audio placement and prediction records, and opening does not overwrite the file.

Source-rate PCM is used for analysis. Streamed SoXR HQ 48 kHz PCM is used for playback and audio export. WAV mix, stems and click share the selected start, sample rate and frame length. Stems respect mute/solo, volume, pan and master gain. Mono uses pan; stereo uses balance. Overlapping events follow the same front-event priority in playback and rendering.

JSON retains whole-project values separately from declared map coordinates, saved source-relative clocks and raw analyses. MIDI includes the active tempo/signature at its export origin as required for playback. It is a quantized interchange derivative with export-origin/bar markers, rather than an exact recording of the original source clock.

## Keyboard and mouse reference

| Input | Action |
| --- | --- |
| `1` / `2` / `3` / `5` | Object / Range / Split / Erase |
| Object double-click / Ctrl E / Return with event selected | Open Audio Editor |
| Space / Num Enter / Num 0 | Toggle playback / Start / Stop |
| Num . / Num 1 / Num 2 | Project start / left locator / right locator |
| Shift P / L / R | Focus project / left / right position field |
| Ctrl Num 1 / 2 | Set left / right locator at cursor |
| P / Alt P / Num / | Locators to selection / loop selection / toggle Cycle |
| C / F / J | Metronome / auto-scroll / Snap |
| G / H / Shift F | Zoom out / zoom in / fit project |
| Ctrl-wheel / Shift-wheel | Zoom at pointer / horizontal pan |
| Ctrl Z / Ctrl Shift Z | Undo / Redo |
| Ctrl C / X / V / D | Copy / Cut / Paste / Duplicate |
| Alt-drag | Copy event or range contents |
| Range body / edge drag | Move contents / resize selection |
| Alt X / Shift X | Split at cursor / range boundaries |
| U / Shift U | Move to Front / Back |
| Ctrl G / Ctrl U / K | Group / Ungroup / Linked edits |
| T / M / S | Add Audio Track / Mute / Solo |
| Ctrl S / Ctrl Shift S | Save / Save As |
| Shift Delete | Remove selected tracks |

## Build and package

Build in Linux/WSL with Node.js/npm and the [Python CPU analysis environment](../../experiments/metronome_reconstruction_v1/README.md#environment). Place the official checkpoint at `data/models/final0.ckpt`.

```sh
cd apps/daw
ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci
npm run build
```

From the repository root, assemble the portable runtime and the ZIP needed for the first development launch:

```sh
python3 apps/daw/scripts/package_windows.py --zip
```

For routine updates, rebuild the UI and refresh the existing bundle:

```sh
python3 apps/daw/scripts/package_windows.py --refresh-app
```

Add `--zip` to refresh the distribution archive as well. `--resume` continues an incomplete bundle produced by this builder. Downloads and wheel caches are stored in `.daw-runtime/`; generated bundles are stored in `dist/`. The builder packages the pinned Windows x64 / CPython 3.12 / CPU dependency set.

For live React/CSS updates in the Windows app:

```sh
cd apps/daw
npm run dev:windows
```

Restart development launch after Electron or Python adapter changes. Build the UI before using `Start Joljak.cmd` for a built-app review. Frontend hot reload does not replace the packaged analysis runtime.

Development configuration uses `JOLJAK_PYTHON` for Python, `JOLJAK_DATA` for the workspace and `JOLJAK_DEV_URL` for the Vite server. Production uses a local application protocol with a sandboxed preload bridge. Playback runs on an AudioWorklet sample clock; media, analysis and rendering jobs run in separate Python processes.

## Validation status and limits

| Version | Available evidence |
| --- | --- |
| Initial implementation | [Windows integration audit](audit/README.md): 64 editing, playback, analysis, persistence, recovery and export cases, with recorded measurements and fixture limits. |
| 0.4.2 | Import/track workflow comparison against native Cubase and controlled material. |
| 0.4.4 | Audio-editing workflow comparison and timeline observations. |
| 0.5.0 | Vite build and Windows app-file refresh; no new runtime, playback, regression, export round-trip or inference results. |
| 0.6.0 | Formal sample library, source-reference audition and separate draft storage; Vite build and Windows app-file refresh only. No new app runtime, playback, persistence, export or inference checks. |
| 0.6.1 | Louder click default and +12 dB relative control range; imported candidate-review descriptors and explicit total-offset proposals. Vite build and Windows app-file refresh only; no new runtime/playback or model checks. |
| 0.6.2 | Combined candidate queues, source-only listening/manual drafts, source-description context and whole-bar lead-in for positive alignment proposals. Syntax parsing, Vite build and Windows app-file refresh only; no new runtime/playback, persistence, export or model checks. |
| 0.6.3 | Unified Bars+Beats position entries for tempo, signature, audio, ranges and import placement, with matching Inspector/Info Line controls. Vite build and Windows app-file refresh only; no new runtime/playback, persistence, export, regression or model checks. |
| 0.6.4 | Mixed audio/tempo/signature selection, cross-lane marquee, Ctrl A, atomic group movement and Bars/Beats shift controls with retained start state. UI build and Windows app-file refresh only; no new runtime/playback, persistence, export, regression or model checks. |
| 0.6.5 | Whole-project tempo/signature values without automatic start points, cursor declarations from Transport, editable/removable first points, and compatible in-memory project migration. Basic syntax parsing, UI build and Windows app-file refresh only; no new runtime/playback, persistence, export, regression or model checks. |
| 0.6.6 | Analysis application uses whole-project values for kinds without declared points and supports explicit reapplication of saved analysis to repair 0.6.5 placement. UI build and Windows app-file refresh only; no new runtime/playback, persistence, export, regression or model checks. |

`npm run build` bundles the frontend; it does not run TypeScript project-wide type checking or the audit suites. Build, packaging and startup do not run audits or accuracy benchmarks. Earlier observations describe their respective revisions.

The 2026-10-07 benchmark evaluated 280 GTZAN development groups, 87 separate
validation groups and 58 generated musical inputs outside the application.
Its model scores and implementation-contract controls do not certify 0.5.0
startup, playback, project persistence or export behavior. The app-file version
and runtime-validation status in the table remain unchanged.

Cubase Pro 15 informs familiar editing interactions, including [import](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/importing_audio_and_midi/importing_audio_and_midi_importing_audio_files_t.html), [tool modifiers](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/preferences/preferences_editing_tool_modifiers_r.html), [normal sizing](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/parts_events/parts_and_events_resizing_events_with_the_object_selection_tool_normal_sizing_t.html) and [overlapping audio](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/track_handling/track_handling_audio_overlapping_handling_t.html). Complete Cubase behavior is outside the implementation scope.

Recording, VST, MIDI performance editing, fades, FX/buses, automation, time stretching, pitch changes and automatic tempo/meter-change inference are not implemented. The separate song-level audio/stem/map command and alignment conflict review remain pending.
