# Joljak audio workspace

Arrange songs and stems on a shared tempo/signature map, inspect fixed-metronome predictions, and export aligned audio and maps. Joljak runs on Windows with an English interface. The current version is **0.6.17**.

Editing, adding or deleting a tempo/signature declaration keeps other declarations
at their existing audio times. Moving selected declarations moves those points by
the requested time shift while other points stay in place. Bar/beat labels follow
the revised grid. Linear audio stays at its time; Musical audio follows its quarter
anchors, with unchanged duration and playback speed.

Variable-tempo inference is developed separately from this application; see
[development status](../../docs/DEVELOPMENT.md) and the [code map](../../docs/CODE_MAP.md).
The application uses its fixed-only Analyze command. Current source is in `src/`, `electron/`, `backend/` and
`scripts/`; recorded UI checks, design references and the earlier remote installer
are in [reference/](reference/README.md).

The initial design target is fewer than ten tracks and projects under thirty minutes. Analysis produces one constant BPM, time signature and downbeat offset for a selected song or range. The project map can contain multiple editable tempo and signature events.

## Audio cache lifetime

Decoded audio caches now follow the editing session. Reimporting an unchanged
linked source reuses its decoded buffers, while clips keep separate identities.
The current project and its retained Undo/Redo assets remain available. Switching
projects releases unused buffers after active audio jobs finish; normal exit
removes regenerable decoded caches. Startup also retries cleanup after a crash.
Original recordings, copied media, saved projects, automatic recovery and analysis
records remain stored. Buffers whose originals are missing or changed are retained.

Opening a saved project or accepting automatic recovery rebuilds missing buffers
from the original audio. That can briefly show decoding progress; it does not
change the tempo/signature map, original sample geometry, dirty state or Undo
history. The cache lives under `%APPDATA%\Joljak\workspace\audio-cache` unless
an explicit `JOLJAK_DATA` workspace is configured.

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

Hospital Hill also provides **Compare 102 / 110 BPM** and **Open
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

After one launch through **Start Joljak.cmd**, Windows associates `.joljak` files
with the current development executable for the current Windows account. Double-click opens the
project, including paths with spaces or Unicode. An existing instance receives
the request in its current window. Opening the same file preserves its current
unsaved state; opening a different file uses the ordinary unsaved-work confirmation.
An explicit startup file takes priority over automatic recovery. Close an older
running app and relaunch once after updating. File → Open Project remains
available. The registration uses HKCU and leaves Windows' protected UserChoice intact.

## Basic workflow

1. **File → Import Audio…**: select WAV, MP3 or FLAC files and choose **One track**, **Different tracks** or **Aligned stems**. Files can remain referenced at their original location or be copied into app-local media storage.
2. Select an event with Object Selection (`1`), or use Range Selection (`2`) to select part of an event.
3. **Analyze Audio**: optionally tap with `T`, `Space` or the TAP button, or enter an approximate quarter BPM. Each tap gives pressed-button feedback; holding a key does not add repeated taps. This selects a metrical layer; precise BPM, meter and phase come from audio. There is no initial meter input.
4. Audition the proposal, then use **Apply & Align**. The preview shows the target project bar and signed shift. The song and linked stems move together so the inferred first downbeat lands on that bar.
5. Edit audio, project Tempo/Signature events or saved analysis values. **Restore Original Prediction** restores saved analysis values; use **Apply & Align** separately to update the map and placement.
6. Save a `.joljak` project. **Save As → Collect original audio** gathers sources for portability. Export WAV mix/stems/click and tempo-map JSON/MIDI.

## Values, selection and Undo

Numbers use the same editing behavior throughout the Inspector, Info Line and
Transport. Drag vertically to adjust; double-click or use Tab/Enter for direct
entry. Hovering a value or position segment and scrolling adjusts it without
requiring focus or scrolling the panel. Arrow keys adjust the focused field.
BPM drag/wheel/arrow steps are whole numbers; direct entry accepts decimals and
fractions such as `400/3`. Other numeric controls retain Shift fine adjustment.
Scalar decimal places and position-segment widths stay fixed while values change.
Displayed rounding never changes the stored value or full-precision entry text.

Position fields expose bar/beat/sixteenth/tick or hours/minutes/seconds/milliseconds
segments. Drag a segment to change it; double-click to type or paste the full
position. Audio Start/End/Length scrubs in the Info Line preview
linked edits immediately; release commits once, and Escape restores the baseline.
Signature numerator is an integer field and denominator a discrete list.
While editing during playback, the text and edit target stay captured; a signature
pair stays together even if playback crosses into another meter.

Enter commits valid input. Invalid input stays visible with an explanation;
Escape cancels. A completed scrub/fader drag is one Undo; canceled gestures add
none. Ctrl-click resets volume to 0 dB, pan to center and transport tempo to 120.
Text Undo stays in a text edit; project Undo resumes after it is committed/canceled.
Copying a value retains its full precision. Pasting stages the complete value for
review before Enter or focus-loss commits it.

The Info Line identifies Audio/Range/Tempo/Signature/Mixed selection. With multiple
linked/selected events, it shows the reference event's values and identifies
relative editing. Inspector track focus is independent of arrangement selection.
Object Selection (`1` or the toolbar) clears the active range; Escape or pointer
cancellation restores the preceding range while a new range is being drawn.

## Workspace and contextual actions

The default view contains the toolbar, Info Line, Inspector, arrangement and
Transport. Import/Export use icons and Analyze remains labelled. Zoom, horizontal
scroll and Fit Project are below the timeline. The Inspector contains the focused
track's mix controls and Event/Analysis disclosures; the Info Line owns event/map
properties. View toggles the Inspector, Tempo/Signature tracks and optional lower
Audio Editor/MixConsole. Restore Layout restores pane widths and the default view.

Right-click an event, range, track, empty lane, ruler or map point for its actions.
Right-clicking a selected member keeps the selection and lead; an unselected event
selects itself. Split Here and Paste Here use the captured pointer position.
Commands retain their opening selection/cursor during playback. Numeric readouts
offer Edit Value, Copy Exact Value, Paste Value and applicable Reset; active text
editing uses Windows text actions. Menus support arrows, Home/End, Enter, Escape,
Shift+F10 and focus return. Disabled actions show their reason.

Right-click a Transport position/locator to choose its Time Format, or the ruler
to choose its display format. These displays are independent. Timeline waveforms
are magnified for visibility; this does not change playback gain or audio data.

## Review newly collected candidates

A `daw-review.json` descriptor pairs retained audio with supplied-clock records following
the [collection workflow](../../tools/ntm_collection/README.md#prepare-and-review-a-batch-in-joljak).
Use **Samples → Open candidate review…** and open that descriptor. Candidates
remain labelled unaccepted and do not appear as new formal enrollment.

The Inspector shows **Initial proposal**, **Alignment adjustment** and **Total
working offset**. For example, a +30 ms source offset with +20 ms adjustment means
a +50 ms total working offset. **Audition original candidate click** retains the
initial proposal; the ordinary working project click follows edited map/placement.
Use **Save sample draft** to retain the working project and total offset.
Reference registration is a separate operation that records the chosen map,
source timing and reviewed scope; draft saving does not change the accepted reference.

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

Object-tool double-click, Ctrl E or Return opens the selected event in the lower **Audio Editor**. Its local Range, Trim and Split tools edit the event non-destructively. The pane shows the source waveform, project cursor/grid and event boundaries, with zoom/fit and an explicit Analyze button. **MixConsole** and **Editor** tabs share the lower zone; switching tabs retains the opened event and editor view. **View → MixConsole** opens the mixer. Drag the divider above the lower zone to resize it.

Alt X in the Project window splits selected events, or all intersecting events when none are selected. In the focused Audio Editor it targets that event. Shift X splits at both range boundaries.

Right-click an overlap to select a hidden event. **Move to Front** (`U`) and **Move to Back** (`Shift U`) change order. At each time, only the front event on a track is audible.

A gesture makes one undo entry. No-op edits leave history unchanged. Undo/Redo shows the next action; original media and raw analysis records remain retained across history changes.

Ordinary event and range edits leave the shared Tempo/Signature map in place. A separate song-level move/copy operation carrying audio, stems and related map events is still pending.

## Project map and timing

The toolbar and Info Line sit above the arrangement. Tempo and Signature are compact project tracks sharing the audio grid. The Info Line edits their properties and the Inspector lists their points. MixConsole opens in the lower zone; Transport sits at the bottom. Toolbar zone buttons show/hide the Inspector and map tracks. Inspector and track-list widths are adjustable by dragging their right dividers; these sizes and the lower-zone height are local layout preferences.

Audio-only selections show the first selected event's Start, End, editable Length and Source in on the Info Line. Multiple audio selections show their count and a different value color; existing relative movement/trimming rules apply. A single tempo or signature point shows its own position and value. Mixed audio/map selections and multiple map points retain Move Selection controls. Position edits use the same collision checks as arrangement movement.

New projects start with whole-project values of **120 BPM, 4/4**, no declared map points, a Bars+Beats ruler and a 30-minute project duration. Whole-project values also apply before the first declaration of that kind. Each declared tempo/signature holds until the next point, including through silence. No automatic point is inserted at project start or at a song/range end.

**Project → Project Setup** changes project duration. Content length is separate: exports use the content range or locators. Import and alignment extend project duration when necessary. Switching the ruler between Bars+Beats and Seconds does not change a track's time base.

### Linear and Musical tracks

| Time base | Effect of a project tempo edit |
| --- | --- |
| Linear | Event positions remain fixed in seconds. |
| Musical | Event quarter positions remain fixed, so their physical positions move with the map. |

Switching time base preserves current placement. Source offsets, audio duration and playback speed remain fixed in both modes. Tempo edits affect every Musical track, so a later song can need realignment after changing earlier tempo events.

### Map editing

Tempo and signature events use the shared quarter clock. A signature can start on an existing notated beat inside a bar: that beat ends the partial preceding bar and starts the new signature's first bar. Tempo-only edits preserve the current bar. Project format v3 stores signature `quarter` positions and derives display bar numbers. Versions 1/2 still open with their original timing and audio placement.

Click a map point to edit it in the Info Line. Double-click or right-click a map lane to declare a point. Drag a tempo point horizontally for position and vertically for BPM. Every declared point, including one at project start/bar 1, can move or be removed with Erase/Delete or its action menu. Removing all points of a kind leaves its whole-project value in effect.

Tempo, Signature and audio-event position fields use the same
**Bar.Beat.Sixteenth.Tick** format, such as `5.1.1.0`, in both the Inspector and
Info Line. Range bounds and custom import positions use that format too,
independently of the ruler display. Enter or focus loss applies the position;
Escape cancels it. A bare bar number such as `5` expands to `5.1.1.0`.
Signature positions use existing beat starts (`bar.beat.1.0`); invalid positions are
rejected with an inline explanation. A point at `1.1.1.0` uses the same editable
position control as other points. Position editing uses the current project map and
preserves the existing move/trim and Linear/Musical timing rules. Durations,
source-relative timing and alignment-adjustment fields retain their time units;
Transport keeps its explicit optional seconds display.

The bottom **Tempo** field always declares the entered BPM **at the cursor**, including the first point in a new project. It preserves the whole-project base and preceding values; an occupied position updates the existing point. The cursor is captured when editing begins, including during playback. **Time signature** still edits the whole-project value when no signature points exist; with points it declares at a captured existing beat (`bar.beat.1.0`). Enter or focus loss commits; Escape cancels. Entering the current BPM at another position still declares a point. Map lanes also support declarations through `+` or double-click. Existing manual tempo positions are preserved; research-generated maps impose the additional rule that every tempo/signature change lies on the preceding map's beat.

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
points require existing beat destinations. An incompatible signature boundary or a
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

Dragging the cursor head reaches project zero regardless of which side of the handle was grabbed. Its line has the same width and alignment through the ruler and track area. Visual pixel alignment does not round the audio or musical clock.

Ctrl-wheel zooms around the pointer, Shift-wheel pans horizontally, and fit shows the project. Playback auto-scroll yields briefly during zoom and cursor dragging.

Inspector and MixConsole provide track volume, pan, mute and solo. The Inspector uses compact horizontal volume/pan controls; MixConsole keeps vertical volume faders. Pan has a neutral rail without a filled segment. Its center line marks 0, and volume reference lines mark 0 dB, including Stereo Out. Ordinary drags snap near those lines; continuing through the line releases the snap. Shift enables fine adjustment without snapping, and numeric inputs remain precise. Ctrl-click resets pan to center or volume to 0 dB. The volume fader's bottom detent is silence. Track volume/pan drags commit one history entry against the value before the preview. Click volume is independent and saved with the project. Playback and click export use the same click level.

The click's new default is **+6 dB above the former default**. **Click boost**
displays 0 dB at this new default and permits up to **+12 dB above it**; Ctrl-click
resets the click fader to that default. Both the slider and numeric field use this
same reference. Opening an older project still at its former default raises that
default once in memory. Saved custom levels and mute are retained. Opening does
not overwrite saved project files or change audio placement, maps or references.
Changing click volume keeps the current reference/analysis audition selected.

## Save, recover and export

Projects use schema v3 with assets, tracks, clips, whole-project `bpm` and `signature` values, declared tempo/signature events, saved clocks and original analysis records. Signature events store their quarter coordinates; their bar numbers are derived display values. Save As can collect original audio for portability. Project recovery and cache regeneration use the application workspace; missing sources can be relocated. Project switches cancel stale import/analysis jobs and reject their completions. Exports retain their original project snapshot.

Older v1 projects open with preserved audio placement and saved predictions, whole-project 120 BPM/4/4 values and no declared points. Older v2 projects recover whole-project values from their former starting state and convert bar-only signatures to quarters at their original positions. Identified default-origin automatic points and the start-state copies generated by 0.6.4 are removed during in-memory migration; manually declared, imported and analysis-origin points remain editable, including points at zero/bar 1. Migration preserves audio placement and prediction records, and opening does not overwrite the file.

Source-rate PCM is used for analysis. Streamed SoXR HQ 48 kHz PCM is used for playback and audio export. WAV mix, stems and click share the selected start, sample rate and frame length. Stems respect mute/solo, volume, pan and master gain. Mono uses pan; stereo uses balance. Overlapping events follow the same front-event priority in playback and rendering.

Opening a project or recovering a session restores the decoded playback rate and frame count from the local cache. This also supports generated listening projects that store only original-audio metadata. Incomplete caches are regenerated on project opening. Original sample-rate geometry, clip timing and tempo/signature maps remain unchanged. If 44.1 kHz audio sounded lower and slower after reopening in an older build, close Joljak and run **Start Joljak.cmd** to load the current version, then open the same project again.

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

For a separate Windows PC connected with VS Code Remote SSH, run `npm run dev` on the development host and forward port **8998** to local **127.0.0.1:8998**. The development server serves the prepared runtime, small app update and installer under `/__joljak_preview__/`. On the Windows PC, download `Install-Joljak-Preview.ps1` from that route and run it with Windows PowerShell. It installs under `%LOCALAPPDATA%\Joljak\remote-preview`, resumes partial runtime downloads and opens the folder containing **Start Remote Preview.cmd**. This command opens the real Windows app against the forwarded UI; audio files, playback, analysis and projects stay on that Windows PC. Frontend edits reload through the tunnel. Close the app and rerun the installer after Electron/Python application updates; the installed runtime is reused. The small update archive must be prepared from the current built application files.

## Validation status and limits

| Area / revision | Recorded evidence | Remaining scope |
| --- | --- | --- |
| Initial integration | 64 Windows editing, playback, analysis, persistence, recovery and export cases | Specific revision and fixtures; see the [integration audit](reference/audits/README.md) |
| Controls and workspace, 0.6.9–0.6.12 | Focused native Windows checks for numeric editing, selection, cursor geometry and workspace/context menus | No comprehensive current-version playback/export/DPI regression |
| Map declaration geometry, 0.6.16 | 13 focused geometry checks, including preservation of later declaration times after deletion | Current-version Windows interaction and playback review |
| Decoded-cache lifetime, 0.6.17 | Syntax parsing, TypeScript compilation, frontend build and Windows app-file assembly | Native cache regeneration, recovery and playback checks |

`npm run build` bundles the frontend; project-wide TypeScript checking is a separate operation. Builds and packaging do not execute accuracy benchmarks or certify runtime behavior. Earlier observations retain their version-specific scope in [validation history](reference/VALIDATION_HISTORY.md).

Algorithm benchmark scores are recorded separately from application startup, editing, playback, project persistence and export validation. The variable-tempo research candidate is not the app analyzer.

Cubase Pro 15 informs familiar editing interactions, including [import](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/importing_audio_and_midi/importing_audio_and_midi_importing_audio_files_t.html), [tool modifiers](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/preferences/preferences_editing_tool_modifiers_r.html), [normal sizing](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/parts_events/parts_and_events_resizing_events_with_the_object_selection_tool_normal_sizing_t.html) and [overlapping audio](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/track_handling/track_handling_audio_overlapping_handling_t.html). Complete Cubase behavior is outside the implementation scope.

Recording, VST, MIDI performance editing, fades, FX/buses, automation, time stretching, pitch changes and automatic tempo/meter-change inference are not implemented. The separate song-level audio/stem/map command and alignment conflict review remain pending.
