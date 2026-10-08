# Nail The Mix collection tools

Download selected source materials, extract supplied MIDI/DAW clocks and prepare an interactive Master/click alignment review. The tools preserve original recordings and clocks while storing reviewed audio-relative references separately. They are collection utilities, not an audio inference model.

## Workflow

1. Prepare a batch selection identifying the recordings and required source files. Bind each song to its canonical local library directory.
2. Download selected materials using an authenticated member session. Existing files, partial transfers and transfer records support resuming a batch.
3. Extract the original Master and supplied clocks, including native DAW project bundles. Keep their original time coordinates and audio geometry.
4. Prepare click/listening assets and an initial offset proposal from a corresponding source-stem segment.
5. Use the local review page to compare the Master and click at the start, middle and end, then record a selected offset and reviewed scope.
6. Use `finalize_selected.py` to register the explicitly owner-approved offset/map and source records. Retired fixed-batch finalizers are available through Git history.

Archive-link generation consumes the provider's download allowance. Completed transfers and intentionally removed archives retain their disposition records, so absent ZIPs do not automatically trigger another download. Remaining download allowance comes from the current provider response rather than an inferred reset date.

## Tools

| Tool | Purpose |
| --- | --- |
| `collect_selected.py` | Download selected batch materials, reuse recorded transfers and honor exclusion flags |
| `prepare_selected.py` | Extract acquired clocks and prepare alignment review assets |
| `finalize_selected.py` | Save an explicitly owner-approved offset/map and enroll a selected recording |
| `serve.py`, `review.html` | Serve a selected batch's Master/click review on loopback |
| `login_bridge.py` | Local browser viewer for member login |
| `storage.py` | Canonical per-session storage, batch records and recording discovery |

The selection-based tools take `--batch`; collection also takes `--auth`, and `--slug` limits processing to one recording. Preparation reuses existing finalized materials and records their cleanup state. Download and preparation do not automatically turn unreviewed materials into evaluation references.

Collection reads member metadata by the selected numeric session ID and checks both ID and slug before starting transfers. A slug-filtered session listing can be empty even when that session remains accessible. Acquisition receipts record the actual date in Asia/Seoul.

Masters hosted on the member site use the authenticated browser request context. Signed archive transfers stream separately and retain their private transport links and resumable transfer receipts.

## Review a prepared batch

For a local batch with review assets:

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
