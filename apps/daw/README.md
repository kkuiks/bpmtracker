# Joljak audio workspace

A Windows desktop application for arranging audio on a shared tempo/signature
map, inspecting fixed-model predictions, and rendering aligned files. The interface uses React/TypeScript inside
Electron. Playback runs on a Web Audio sample clock; Python media and analysis
jobs run in separate processes. The application's editing and playback code is
independent of the archived prototypes.

## Run the assembled Windows app

During development, double-click **`Start Joljak.cmd`** in the repository root
from Windows Explorer. First launch prepares a runtime cache under
`%LOCALAPPDATA%\Joljak\development`. Later launches refresh only the built UI,
Electron code and Python adapter. Close the application before restarting to see
the current build. No manual ZIP extraction or Windows Node/Python installation
is required for this launcher.

The local portable bundle is `../../dist/Joljak-win-x64/`. Run `Joljak.exe` on
Windows. Keep the complete folder together. It includes Electron, Python 3.12,
the recorded CPU analysis dependencies and the official final0 checkpoint.
It does not require a Node.js/Python installation, WSL, or network access at
runtime. Recordings and accepted sample references are not bundled.

The owner explicitly requested a first-version audit. Actual Windows startup,
editing, playback, CPU inference, persistence, recovery and export were exercised
for the initial version; see [audit coverage and limits](audit/README.md). That
audit predates the stage A project-map/layout and stage B import/track revisions
and is not evidence that those revised behaviors have been exercised. Build and packaging do not run
these checks automatically. The owner's opt-in verification rule still applies.

## First working flow

1. Use **Import Audio** for WAV, MP3 or FLAC. Choose a target track and **One
   track**, **Different tracks**, or **Aligned stems**. Source files can be
   referenced or copied into Joljak's local media storage. A single file dropped
   into the timeline imports directly at its snapped pointer position.
2. Use Object Selection (`1`) to select an entire song event, or Range Selection
   (`2`) to choose a window inside one reference event.
3. Choose **Analyze Audio**. An optional tap (`T` in the dialog) or approximate
   quarter BPM chooses a metrical layer only. No initial meter input is accepted.
4. Audition the original proposal, then **Apply & Align**. The proposal shows the
   target project bar and signed shift before application. The reference song
   and its linked stems move together to align the first downbeat with that bar.
5. Edit the project Tempo/Signature tracks. Saved analysis values remain separate
   in the Inspector; **Apply & Align** applies an edited draft. **Restore Original
   Prediction** restores the saved values only. Apply separately to change the
   project grid and song/stem positions.
6. Save a `.joljak` project. **Save As → Collect original audio** makes a project
   portable. Export stereo WAV mix/stems/click and tempo-map JSON/MIDI.

No reference timestamps, accepted offsets, meter labels or song-specific rules
enter the analysis adapter. It imports the current fixed-metronome functions
without changing their configuration or source. All acoustic candidates and
scores are prepared before the hint file is read. Selected input bounds are
rounded to original decoded sample frames, and the result is placed on the
project timeline using the event's source-to-project mapping.

## Audio import and tracks (stage B, 0.4.3)

Drop a single file on an audio event lane to use that track and the pointer's
time. Drop below the audio lanes to create a new track. The placement preview
uses the project Snap setting; Ctrl temporarily bypasses it. Dropping into the
track list creates tracks at its insertion line, with audio at the project cursor.
Multiple files open Import Audio so placement, order and source storage remain
explicit. The import destination is captured before decoding; later cursor or
track selection changes do not redirect it. Import does not change timeline zoom.

- **One track** joins files end to end in the displayed order on the selected
  track, or one new track. Up/down arrows change the file order.
- **Different tracks** creates independent tracks with one shared start.
- **Aligned stems** creates tracks with one shared start and links their audio
  events. Linked edits (`K`) applies move/copy/split/trim/delete to the event
  group. Volume/pan/mute/solo remain independent. Group/ungroup uses Ctrl G/U.
  Apply & Align still moves grouped stems together even when ordinary Linked
  edits is disabled, as required by the approved stage A alignment decision.

The dialog offers the captured cursor/drop position, the last audio event end,
or a specified musical/seconds position. New tracks are inserted below the
selected track or at the chosen insertion point. They start Linear; importing
onto an existing track retains its time base and mixer settings.

Original-file copying means Joljak's app-local workspace/media storage, not the
current project's folder. With it disabled, originals are referenced. The choice
and placement preset are remembered for subsequent imports; a single-file drop
uses that source-storage choice. Preferences are remembered when Import is
confirmed; cancelling the dialog restores the prior choices. Save As collection remains the portable-project
path. Cancelled/failed/unplaced imports remove only that job's newly allocated
media/cache directories, after its worker/file handles close. Adopted project
assets, undo resources and existing user media are preserved.

`T`, the track-list plus button, blank-list double-click or Project/track menus
open **Add Audio Track**, with name and count. Ctrl-click selects individual
tracks; Shift-click selects a contiguous range. A normal click selects one track.
Passive header areas, including volume/pan readouts, select the track. Track
buttons select their track while retaining their own action. Header dragging uses
the default arrow cursor consistently. The Info Line retains a fixed 50 px height
for no selection, audio events, tempo and signatures.
Timeline content fills its visible viewport, and grid/cursor lines share that
content height. The track-list viewport ends above the horizontal scrollbar to
keep its visible rows aligned with the audio lanes.
Drag a track name or blank header area to reorder the selected tracks, using the
insertion line. Track order is also reflected in the MixConsole. Right-click a
track or use its `…` menu for select-all-events, duplicate, remove and move up/down.
`Shift Delete` removes selected tracks, with confirmation if they contain audio.
Track operations and audio imports participate in Undo/Redo.

Track duplication preserves the chosen track settings and event/source placement,
shares media, and gives copied event groups new IDs. Saved clocks refer to the
copied events while their original raw analysis receipts remain unchanged. Track
removal deletes only events on those tracks, preserving source media, analysis
records and the shared Tempo/Signature map. Existing group members on other
tracks remain. This revision was compiled/assembled without a new runtime audit.

The first follow-up to the owner-requested A/B review restores track-name
double-click editing without interfering with header dragging. Track/channel
focus now preserves the selected event, range or map object; the Inspector shows
the active track while the Info Line retains the selected object. Notifications
appear at the upper right and their body does not intercept pointer events.
The earlier 0.4.2 review is evidence for that version, not a runtime result for
these 0.4.3 fixes.

The owner delegated the remaining A/B recommendations, with five explicit
workflow choices: separate stem-track groups per song; a distinct song-level
move/copy action carrying audio, stems and associated map events; conflict review
only when alignment/map application conflicts; bottom BPM changes from the
cursor; original-value restoration followed by separate application.
The song-level command and conflict review belong to subsequent implementation
groups and are not provided by this first interaction-fix revision.

Reference workflows: [audio import](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/importing_audio_and_midi/importing_audio_and_midi_importing_audio_files_t.html),
[import options](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/importing_audio_and_midi/importing_audio_and_midi_open_options_dialog_r.html),
[track insertion](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/track_handling/track_handling_tracks_via_the_project_menu_adding_t.html),
[track selection](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/track_handling/track_handling_selecting_tracks_t.html),
[reorder](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/track_handling/track_handling_moving_tracks_in_the_track_list_t.html)
and [remove](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/track_handling/track_handling_removing_tracks_t.html).
Installed Cubase Pro 15 was inspected in an owned temporary project before this
stage was approved. These references do not claim complete Cubase parity.

## Editing contract

Implemented Cubase-style actions include object/range selection, multi-event
movement, constrained dragging, Alt-drag copies, Alt-click splits, normal sizing,
linked stem edits, clipboard operations, range deletion without closing the gap,
locator/cycle editing and undo/redo. On one audio track, only the front event
plays where events overlap. **Move to Front** (`U`) changes that priority.

- `1`, `2`, `3`, `5`: object, range, split, erase.
- `Space`, `Enter`, `Num 0`: start/stop, start, stop.
- `Num .`, `Num 1`, `Num 2`: project start, left locator, right locator.
- `Shift P/L/R`: focus the project/left/right position input.
- `Ctrl Num 1/2`: set the left/right locator at the project cursor.
- `P`, `Alt P`, `Num /`: locators to selection, loop selection, cycle toggle.
- `C`, `F`, `J`: metronome, auto-scroll, snap.
- `G`, `H`, `Shift F`: zoom out, zoom in, fit project.
- `Ctrl Z`, `Ctrl Shift Z`: undo, redo.
- `Ctrl C/X/V/D`: copy, cut, paste, duplicate.
- `Alt X`, `Shift X`: split at cursor, split range boundaries.
- `Ctrl G/U`, `K`: group, ungroup, linked editing.
- `T`, `M`, `S`: add audio track, mute track, solo track.
- `Ctrl S`, `Ctrl Shift S`: save, save as.
- Lower event corners trim by hiding/revealing source content, without stretching.
- `Ctrl` constrains drag direction; on sizing it temporarily disables snapping.
- `Ctrl+wheel` zooms at the pointer; `Shift+wheel` pans horizontally.

In 0.4.4 the timeline owns scale and scroll position together. Ctrl-wheel keeps
the same time under the pointer and applies the visible range, native scroll
and waveform drawing before one paint. Continuous inputs accumulate against
the latest requested view, without delayed scroll callbacks. Precision-wheel
deltas are proportional; zero vertical deltas do not zoom. Playback auto-scroll
briefly yields during a zoom gesture.

Source behavior references: [tool modifiers](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/preferences/preferences_editing_tool_modifiers_r.html),
[normal sizing](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/parts_events/parts_and_events_resizing_events_with_the_object_selection_tool_normal_sizing_t.html),
[event movement](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/parts_events/parts_and_events_moving_with_the_object_selection_tool_t.html),
[overlapping audio](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/track_handling/track_handling_audio_overlapping_handling_t.html),
[edit commands](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/key_commands/key_commands_edit_category_c.html),
[transport commands](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/key_commands/key_commands_transport_category_c.html),
[zoom commands](https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/key_commands/key_commands_zoom_category_c.html).
These are implementation references, not a claim that all Cubase behavior has
been reproduced or runtime-validated.

## Project timing and layout (owner-approved stage A)

The editing toolbar and Info Line are above the arrangement. Tempo and Signature
are separate project tracks with the same bar/beat grid as audio; their Inspector
shows an event list and the selected event editor. MixConsole is a collapsible
lower zone. The bottom Transport is one compact row: adjacent L/R fields,
Cycle/Stop/Start, position, tempo/signature, metronome level and stereo output
meter. Inspector has a vertical volume fader with a dB scale/readout, horizontal
pan, M/S and the small clock/note switch. Event details and analysis are
collapsible. Inspector and MixConsole share the volume component; Shift-drag
adjusts finely, Ctrl-click restores 0 dB, and the bottom detent is silence. The click level has its own slider/numeric field, is audible while
adjusting, and is saved with the project; the same level is used for click export.

New projects have **120 BPM, 4/4 and a Bars+Beats ruler** before any analysis.
There are no default badges or separate fallback ranges. The first specified
value replaces the initial value for its map; later events hold until the next
event. Explicitly entering 120 BPM or 4/4 also establishes a user value.
Switch the ruler to Seconds without changing a track's time base. **Project →
Project Setup** sets an independent timeline/playback length (initially 30 minutes).
Content end remains separate; export uses the content range or explicit locators.
Import/alignment extends the project if its new audio would exceed that length.

- A new audio track starts **Linear**: tempo edits preserve event positions in
  seconds. The Inspector and track header have the clock/note switch.
- A **Musical** track preserves event quarter positions while tempo changes move
  its events. Switching time base preserves current physical placement. Source
  offset, audio duration and playback speed stay fixed in both modes.
- Tempo events are steps on the shared quarter clock. Signature events live on
  whole project bars; numbering continues through all songs and signature changes.
  Click a point to edit it in the Inspector, double-click a track to add an event,
  or use its `+` button at the cursor. Drag tempo points horizontally to move
  their position and vertically to change BPM. Grabbing a point or signature
  flag preserves its original pointer offset. The initial tempo point permits
  BPM adjustment but stays at the start; the initial signature also stays put.
  Erase/Delete removes non-initial points.
- Bottom BPM input inserts/updates a step at the cursor and preserves the earlier
  tempo. It establishes preceding initialization as a chosen working value when
  needed, rather than changing that earlier segment. Point/Inspector editing
  remains the way to change an existing event. This is the owner's explicit
  interaction choice, not a claim of identical Cubase tempo-mode behavior.
- The ruler, musical position, snap, ordinary metronome and exported project maps
  consume the same project map. L/R flags and their range highlight are integrated
  into the ruler/event display. Locator fields follow the Transport time format. Bars+Beats displays
  bar.beat.sixteenth.tick, with 120 display ticks per sixteenth; actual stored
  seconds/quarter positions retain their precision.
- Applying a fixed-model result inserts/updates a tempo event at the aligned
  analyzed start and a signature event on its first downbeat bar. Other existing
  events are preserved. Neither map automatically restores an earlier value at
  the scope/song end or in silence. First downbeat alignment still shifts the
  song and linked stems together, after establishing missing initial values.
  The inference receipt retains its actual source range: persistence of a working
  project event is not a prediction about unobserved audio or variable-tempo analysis.
- Project tempo edits affect all Musical tracks. Linear tracks retain their
  absolute positions; a later song can require explicit realignment after edits
  to earlier map events. Moving/copying audio does not move the project map.
- Saved analysis scopes and original predictions stay separate from project-map
  edits. Trim/split hides or divides audio without changing source-relative
  predictions. Saved scopes follow their reference event placement; they survive
  reference deletion as records. Analysis audition is explicitly marked as a
  preview and can return to the ordinary project metronome without applying it.

Playback controls follow the inspected Cubase flow: Stop preserves the current
sample position; Start resumes; a second Stop while stopped returns to the last
playback start. Space toggles playback. Start while playing does not pause. Drag
the lower ruler or cursor head to locate; dragging during playback continues at
the new position, with Snap respected (Ctrl temporarily bypasses it). Locator
editing stays in the upper ruler. Auto-scroll does not compete with a drag.
Control revisions invalidate old position replies and pending loads; resume keeps
the exact worklet stop sample rather than seeking to an older UI notification.

Project schema **v2** saves the independent project duration, ruler format,
quarter tempo events, bar signature events and track time bases. Existing v1
projects open without rewriting their files. Their saved clocks/predictions and
physical audio placement are preserved; use **Apply & Align** to apply a
saved clock to the new shared map. The migration provides the 120 BPM/4/4 default
rather than silently converting independent clock phases into a global map.
Projects save `timingPolicy: persistent`. Older v2 projects have identifiable
non-initial default-origin automatic returns removed and their missing initial
values established from the first explicit events. Migration preserves physical
audio placement and all analysis receipts. Unmarked manual/analysis-origin
events are retained because they cannot safely be distinguished from real edits;
inspect/remove those explicitly if needed. Opening does not overwrite the file.

Playback/export use the same gain, stereo-balance/mono-pan, overlap priority and
click synthesis conventions. Source-rate PCM is retained for inference; streamed
SoXR HQ 48 kHz PCM is used for playback/export. Original media stays unchanged.
The playback cache is loaded in bounded two-second chunks. WAV outputs share one
selected origin, sample rate and frame length. Stems respect track mute/solo,
volume, pan and master gain.

JSON preserves exact quarter/bar and second coordinates, source-relative saved
clocks and original prediction records. MIDI is a quantized derivative of the
project map, with export-origin/bar markers; it is not producer ground truth.
The editable arrangement has bounded undo history. Imported assets and original
analysis records remain independent of undoing their application. Recovery and
media/model job files remain in the local application workspace.

First scope excludes recording, VST, MIDI performance editing, fades, FX/buses,
automation, time-stretching, pitch changes and automatic tempo/meter inference.

## Development and packaging

```sh
cd apps/daw
ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci
npm run build
# Live React/CSS updates in the actual Windows desktop application:
npm run dev:windows
```

Development launch can use `JOLJAK_PYTHON` for the existing CPU model environment,
`JOLJAK_DATA` for a workspace-local runtime directory and `JOLJAK_DEV_URL` for a
local Vite server. The production app uses a secure custom local protocol and
does not serve arbitrary source directories.

`dev:windows` starts local Vite and the cached native runtime. React/CSS changes
reload immediately. After Electron/Python adapter edits, close Joljak, stop Vite
with `Ctrl+C` and restart the command. Use `npm run build` before reviewing the
built application through `Start Joljak.cmd`. The frozen analysis module/runtime
is not replaced by a frontend hot reload.

From the repository root, after building the UI:

```sh
python3 apps/daw/scripts/package_windows.py
# After the runtime is assembled, update application files and the distribution ZIP:
python3 apps/daw/scripts/package_windows.py --refresh-app --zip
```

`--resume` is reserved for refreshing an incomplete bundle generated by that
builder. Downloads/caches stay in ignored `.daw-runtime/`; the generated bundle
stays in ignored `dist/`. Cross-platform pip marker resolution is avoided by
downloading the complete recorded environment with `--no-deps`, targeting
Windows x64 / CPython 3.12 / CPU PyTorch. Existing system installations are not
modified. Do not run automatic benchmarks or playback checks when packaging.
