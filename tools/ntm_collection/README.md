# Nail The Mix collection tools

Download selected source materials, extract supplied MIDI/DAW clocks and prepare an interactive Master/click alignment review in Joljak. The tools preserve original recordings and clocks while storing reviewed audio-relative references separately. They are collection utilities, not an audio inference model.

**Current owner workflow — 2026-10-10:** prepare offset review in the existing
Windows DAW. Give the owner a `daw-review.json` descriptor and the DAW opening
steps below. Browser listening pages are historical review material; do not start
a listening-page server for a new collection unless the owner specifically asks.

## Workflow

1. Prepare a batch selection identifying the recordings and required source files. Bind each song to its canonical local library directory.
2. Download selected materials using an authenticated member session. Existing files, partial transfers and transfer records support resuming a batch.
3. Extract the original Master and supplied clocks, including native DAW project bundles. Keep their original time coordinates and audio geometry.
4. Prepare source-clock metadata, an initial offset proposal from a corresponding source-stem segment, and the DAW candidate-review descriptor.
5. Use Joljak to compare the full Master and supplied clock, edit the working map/alignment and save a separate sample draft. Record the owner's selected total offset and reviewed scope.
6. Register the explicitly owner-approved working map and scope. Use `finalize_selected.py` only for an unchanged supplied map with an alignment-only approval. If tempo, signature or bar phase was edited, materialize the saved DAW geometry instead; see the [sample-review tools](../sample_review/README.md). Retired fixed-batch finalizers are available through Git history.

Archive-link generation consumes the provider's download allowance. Completed transfers and intentionally removed archives retain their disposition records, so absent ZIPs do not automatically trigger another download. Remaining download allowance comes from the current provider response rather than an inferred reset date.

## Tools

| Tool | Purpose |
| --- | --- |
| `collect_selected.py` | Download selected batch materials, reuse recorded transfers and honor exclusion flags |
| `prepare_selected.py` | Extract acquired clocks and prepare alignment review assets |
| `prepare_daw_review.py` | Turn already prepared source records into a DAW candidate descriptor; no acquisition, audio/model run or enrollment |
| `finalize_selected.py` | Enroll an unchanged supplied clock with an explicitly approved offset; does not preserve manually edited DAW geometry |
| `serve.py`, `review.html` | Retained browser-review compatibility; use only when explicitly requested |
| `login_bridge.py` | Local browser viewer for member login |
| `storage.py` | Canonical per-session storage, batch records and recording discovery |

The selection-based tools take `--batch`; collection also takes `--auth`, and `--slug` limits processing to one recording. Preparation reuses existing finalized materials and records their cleanup state. Download and preparation do not automatically turn unreviewed materials into evaluation references.

Collection reads member metadata by the selected numeric session ID and checks both ID and slug before starting transfers. A slug-filtered session listing can be empty even when that session remains accessible. Acquisition receipts record the actual date in Asia/Seoul.

Masters hosted on the member site use the authenticated browser request context. Signed archive transfers stream separately and retain their private transport links and resumable transfer receipts.

## Prepare and review a batch in Joljak

New source preparation automatically writes `daw-review.json` beside the batch
index. To adapt an already prepared batch, read its existing records directly:

```sh
python3 -B tools/ntm_collection/prepare_daw_review.py \
  --batch data/samples/intakes/<batch>
```

An optional `--slug <session-slug>` limits the descriptor. This command reads only
the retained JSON metadata. It does not redownload, re-extract, hash recordings,
run waveform alignment, launch inference, accept a map or change enrollment.
The permanent exclusion registry is checked before reading a source record.
Already approved/enrolled sessions use the formal library. A source-only entry
with retained audio geometry can open for listening and a manual draft; its BPM,
signature and offset remain unspecified. Incomplete preparation is listed as
unavailable.

Combined candidate-review indexes can use the same command with a separate
output directory:

```sh
python3 -B tools/ntm_collection/prepare_daw_review.py \
  --batch data/samples/reviews/20261009-candidates-v1 \
  --out data/samples/reviews/20261010-candidates-daw-v1
```

This preserves the selected order and reads each current canonical source record.
The prepared descriptor contains seven supplied-clock candidates and one
source-only recording. Original media and prior browser review records stay in
their existing homes.

Give the owner these steps:

1. Start Joljak from **Start Joljak.cmd** on Windows. Restart a closed app if a
   newly built version is required.
2. Open **Samples → Open candidate review…** and select the batch's
   `daw-review.json`. **Select catalog…** connects `data/samples/catalog.json` if
   the library is not already connected.
3. Select the recording and **Open sample workspace**. It is labelled
   **Candidate · unaccepted**, separately from the formal library.
4. Listen with the working project map, seek through intro/middle/end and clock
   changes, and edit the Tempo/Signature tracks or **Alignment adjustment**.
   **Audition original candidate click** compares the unchanged initial proposal.
   Source-clock scope and unannotated margins stay explicit.
5. Use **Save sample draft**. This saves a `project.joljak` and `proposal.json`
   under `data/samples/reviews/daw-drafts/<id>/<saved-time>/`. Continue a saved
   edit with **File → Open**; opening the catalog entry starts from its source
   reference rather than a saved working draft.
6. Ask the owner to state the final **Total working offset** and scope. A saved
   draft alone is not acceptance. The proposal's `proposed_offset_seconds` is the
   total offset; `additional_alignment_adjustment_ms` is only the adjustment to
   the initial source offset. Do not confuse the two or apply the base offset twice.

Source-only recordings open with the project metronome off. The editable
120 BPM / 4/4 project defaults are working values, not supplied clock evidence.
There is no original candidate click or total source offset for these entries.
Their saved draft keeps the manual map, audio placement and note, with source
clock/offset fields explicitly absent.

For an alignment-only approval with an unchanged source tempo/signature map,
`finalize_selected.py` can consume the explicit total offset and owner statement.
If the owner edited BPM, signature events or bar phase, that offset-only finalizer
does not consume those map edits. Preserve the project/proposal and prepare a
consistent accepted map from the working geometry under the owner's explicit
approval; do not silently re-enroll the unchanged supplied map. Neither saving
nor opening a candidate alters `catalog.json`, accepted references or frozen runs.

Other acquisition providers may prepare the same descriptor format. Each
recording has an ID/title, canonical `audio_path` and `reference_path`, and an
explicit `initial_offset_seconds`. Its referenced prepared source record contains
the matching `slug`/`audio`, `duration_seconds`, `project_end_seconds`, source-time
`tempo_events`, `meter_events`, `quarters` and `bars`. Preserve known source
extent and uncertainty; a missing clock remains missing. Paths are relative to
`data/samples`, with no media aliases or embedded credentials.

## Historical browser-review route

Use this only for an explicitly requested browser review of retained material:

```sh
python3 -B tools/ntm_collection/serve.py \
  --root data/samples/intakes/20261005-linear3-v1 --port 8995
```

Open `http://localhost:8995/`. Remote workspaces can forward port 8995. The page supports offset adjustment, music/click gain, downbeat accents, seeking and saved review selections. The server exposes the selected review assets, excluding ZIP archives, bulk source directories and account/session files.

The example path is a recorded local batch. Source archives and prepared assets are not included in the repository. Another prepared batch can be served by changing `--root`.

An optional `source_only_songs` list in the batch index can expose a Master without a supplied clock. Such recordings have no click map or accepted alignment merely from acquisition.

## Time coordinates

The alignment transform is:

```text
t_master_seconds = t_source_clock_seconds + offset_seconds
```

A source-waveform match provides an initial proposal. Instrument processing and pulse aliases can shift that proposal, so Master/click listening determines the working alignment. The reference retains its supported intervals and any unknown margins.

Aligned `master_seconds` and `master_frame` values already include the selected offset. Consume them directly; adding the offset again shifts the reference twice. Original project seconds, MIDI quarter positions and source-clock data remain unshifted acquisition records.

Native project files provide clock and layout evidence. Possessing a project bundle does not establish that its audio is complete or that the supplied clock independently matches the Master at millisecond precision. Listening-reviewed references establish practical alignment, without independently certifying original-click timing.

## Local data layout

All sample material is stored as ordinary files under the checkout's
`data/samples/`. NTM sessions use `data/samples/ntm/<session-slug>/`; new source
Masters, archives, clocks and review outputs stay in that session's `collection/`.
A session has one physical home regardless of batch or approval status. Batch
selection/review descriptors live in `data/samples/intakes/<batch>/` and refer
directly to the canonical files. No song directory links or alternate media
homes are created.

`data/samples/catalog.json` alone governs enrollment. `assets.json` indexes
sources; `ntm-library-index.json` records retained sessions and their statuses.
`ntm-storage.json` binds the NTM root relative to the checkout on both Windows
and Linux. Missing storage stops processing, without a fallback or overwrite.
Raw projects retain native geometry. Relocation changes storage paths, never
BPM, meter, offset, support, source coordinates, approval or eligibility.

`data/samples/excluded-candidates.json` is checked before storage creation or
provider requests by session ID, slug and normalized recording identity.
The Adventure (session 12897) remains permanently excluded, deleted and barred
from reconsideration or download. Two acquired recordings remain unenrolled;
source acquisition and storage discovery never imply owner approval.

The 2026-10-08 consolidation's source fingerprints, comparison receipt and
path-only relocation index are in `data/storage/20261008-consolidation/`.
Frozen research records keep their scientific values and historical identifiers;
research readers resolve those identifiers to actual canonical files. Earlier
migration receipts remain dated evidence. Retired fixed-batch source routines
are available through Git history; they are not current entry points.

The preserved acquisition Python/browser runtime is in
`data/runtime/ntm-collector/`. Authentication and signed transfer state remain
in `data/private/ntm/`, excluded from Git and served assets. Normal app builds,
Windows launch/runtime caching and packaging retain their existing workflow.
