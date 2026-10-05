# Nail The Mix collection and owner offset review

These tools are limited to the owner's restored source-collection workflow.
They do not implement or resume an analyzer, evaluator, model, benchmark,
training split or future product design.

## Current source records

The global authoritative dataset is `samples/catalog.json`: 36 formal samples
(25 complete recordings, ten original-recording excerpts and one explicit
synthetic exception) plus two auxiliary samples. `samples/README.md` records
source roles, provenance limits and the dated readiness audit.

- `samples/ntm-intake/20261005-linear3-v1/`: Secrets is owner accepted at
  -2.034500 seconds; Right Back At It Again is accepted at -7.053750 seconds.
  Both are formally registered. The Adventure is owner excluded, its remaining
  archive acquisition is cancelled, and source evidence is retained. The active
  review has two songs and no pending decisions. Complete original Logic project
  bundles were preserved during the owner's October 5 readiness check.
- `samples/ntm-intake/20261002-new3-v1/`: Waiting Room, Afterlife and HARD2TELL
  were accepted and cleaned on October 2. Its older 23+1 count describes that
  historical enrollment stage, not today's global registry.
- `samples/excluded-candidates.json`: owner-excluded source candidates. Consult
  it before selecting another collection. Exclusion is not a deletion command.

To open the current two-song review, when port 8995 is available:

```sh
python3 -B tools/ntm_collection/serve.py \
  --root samples/ntm-intake/20261005-linear3-v1 --port 8995
```

VSCode Remote users should forward port 8995 and choose Open in Browser.
The server exposes exactly the selected review files, never the entire source
storage, ZIPs, alignment stems or account state. The older preserved October 2
review can be served on port 8990 with its own batch root.

## Owner controls and current helpers

Run collection only for an actual owner-requested job. Paid archive-link
requests consume the provider allowance. Reuse completed files and partial
transfers, inspect the normal current provider access response, and preserve
receipts. Do not infer a reset from a date, request links merely to inspect them,
try all mirrors or start a background retry schedule.

The Master's original rate, origin and duration are retained. Extract actual
MIDI/DAW clocks, including native project bundles such as `.logicx`, and keep
source/accepted clock coordinates separate. Source waveform offset proposals
are starting values. The owner chooses the offset; map scope and unknown tails
are explicit. Use already shifted `master_seconds`/`master_frame` without applying
the offset again. Complete native Logic bundles remain source/layout evidence;
they were not newly decoded or treated as independent acoustic truth.

`collect_selected.py` and `prepare_selected.py` honor the active selection's
exclusion flags. Preparation preserves existing owner acceptance and cleanup state instead of
regenerating it. Acquisition recognizes intentionally cleaned completed jobs
before member access, so a removed ZIP does not trigger another paid request. `finalize_first_two_20261005.py` is scoped to the completed two-song
decision; do not replay it to replace subsequent owner choices. Earlier
`acquire.py`, `prepare.py` and `finalize.py` are fixed October 2 helpers and contain
historical automatic checks. They are not the default for new collection work.

## Standing global verification instruction

The owner permits only basic syntax checks that automatically finish within
30 seconds unless tests or verification are explicitly requested. Do not add
post-task integrity, hash-comparison, alignment, playback or regression checks,
and do not proactively request permission for unsolicited checks. Requested
source reading, acquisition, offset preparation and owner finalization remain
separate from extra verification. The October 5 final readiness audit is an
explicit one-time request; it does not enable automatic checks for future work.

Cleanup follows the applicable job-specific owner authorization after retaining
original Masters, complete clock/project sources, accepted references, decisions
and required review outputs. A sample exclusion or a documentation audit does
not itself authorize deleting source material. The owner asked to match older approved NTM samples: six approved-job temporary
files were removed; the excluded acquisition evidence was retained. The actual
disposition and exact paths are in the latest batch cleanup receipt. Historical archive and external sample
originals remain untouched.

Account/session/transport data stays private in `samples/.private/ntm/`. The
loopback login viewer uses port 8996; credentials, cookies, nonces and signed URL
queries are excluded from docs, public manifests and served sample assets.
No commit, staging, push or publication is implied by any of these procedures.
