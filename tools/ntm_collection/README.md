# Nail The Mix collection tools

Download selected source materials, extract supplied MIDI/DAW clocks and prepare an interactive Master/click alignment review. The tools preserve original recordings and clocks while storing reviewed audio-relative references separately. They are collection utilities, not an audio inference model.

## Workflow

1. Prepare a batch selection identifying the recordings and required source files.
2. Download selected materials using an authenticated member session. Existing files, partial transfers and transfer records support resuming a batch.
3. Extract the original Master and supplied clocks, including native DAW project bundles. Keep their original time coordinates and audio geometry.
4. Prepare click/listening assets and an initial offset proposal from a corresponding source-stem segment.
5. Use the local review page to compare the Master and click at the start, middle and end, then record a selected offset and reviewed scope.
6. Register the aligned reference and source records. Batch-specific finalization routines handle their recorded inputs; they are not general-purpose finalization commands.

Archive-link generation consumes the provider's download allowance. Completed transfers and intentionally removed archives retain their disposition records, so absent ZIPs do not automatically trigger another download. Remaining download allowance comes from the current provider response rather than an inferred reset date.

## Tools

| Tool | Purpose |
| --- | --- |
| `collect_selected.py` | Download selected batch materials, reuse recorded transfers and honor exclusion flags |
| `prepare_selected.py` | Extract acquired clocks and prepare alignment review assets |
| `serve.py`, `review.html` | Serve a selected batch's Master/click review on loopback |
| `login_bridge.py` | Local browser viewer for member login |
| `acquire.py`, `prepare.py`, `finalize.py`, `finalize_first_two_20261005.py` | Fixed-batch routines with recording IDs, offsets or historical processing assumptions |

The selection-based tools take `--batch`; collection also takes `--auth`, and `--slug` limits processing to one recording. Preparation reuses existing finalized materials and records their cleanup state. Download and preparation do not automatically turn unreviewed materials into evaluation references.

## Review a prepared batch

For a local batch with review assets:

```sh
python3 -B tools/ntm_collection/serve.py \
  --root samples/ntm-intake/20261005-linear3-v1 --port 8995
```

Open `http://localhost:8995/`. Remote workspaces can forward port 8995. The page supports offset adjustment, music/click gain, downbeat accents, seeking and saved review selections. The server exposes the selected review assets, excluding ZIP archives, bulk source directories and account/session files.

The example path is a recorded local batch. Source archives and prepared assets are not included in the repository. Another prepared batch can be served by changing `--root`.

## Time coordinates

The alignment transform is:

```text
t_master_seconds = t_source_clock_seconds + offset_seconds
```

A source-waveform match provides an initial proposal. Instrument processing and pulse aliases can shift that proposal, so Master/click listening determines the working alignment. The reference retains its supported intervals and any unknown margins.

Aligned `master_seconds` and `master_frame` values already include the selected offset. Consume them directly; adding the offset again shifts the reference twice. Original project seconds, MIDI quarter positions and source-clock data remain unshifted acquisition records.

Native project files provide clock and layout evidence. Possessing a project bundle does not establish that its audio is complete or that the supplied clock independently matches the Master at millisecond precision. Listening-reviewed references establish practical alignment, without independently certifying original-click timing.

## Local data layout

`samples/catalog.json` indexes enrolled recordings, reference paths, audio geometry and supported intervals. `samples/assets.json` indexes retained source materials, and `samples/excluded-candidates.json` records excluded candidates. Intake directories hold batch selections, original clocks, aligned maps, review assets and transfer/disposition records.

An excluded candidate remains outside active collection and evaluation. Exclusion alone does not remove original source evidence. Batch cleanup retains original Masters, complete clock/project sources, aligned references and review records; archive and temporary-stem disposition is recorded separately.

Authentication state remains local and separate from source manifests and served assets. Credentials, cookies and signed download URL queries are not distributed with the repository or review page.
