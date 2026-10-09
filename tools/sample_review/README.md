# Owner sample-map revalidation

**Current owner workflow — 2026-10-10:** sample listening and map correction use
the existing Windows DAW by default. Use **Samples** for formal recordings and
the [DAW candidate-review workflow](../ntm_collection/README.md#prepare-and-review-a-batch-in-joljak)
for newly acquired sources. This browser tool retains historical review evidence
and is explicit opt-in; do not start its server merely to prepare a new review.

The dated `confirm_daw_maps.mjs` and `audit_offset_declarations.py` scripts record
the owner's explicit 2026-10-10 confirmation of five edited maps and the subsequent
single-pass audit of all 36 formal references. Completed receipts are under
`data/samples/records/owner-review/20261010-reference-confirmation-v1/`. They refuse
to overwrite the completed confirmation/audit. Their dated inputs are not a
standing approval to promote later drafts; future revisions need an owner decision
and new receipt paths. Materialization uses the DAW's timing functions, preserves
old maps/native clocks, and stores quarter evaluation pulses separately from
notated-denominator audition pulses. The audit reads current approved coordinates
without adding offsets, decoding recordings, scanning ZIPs or running inference.

`enroll_daw_candidates.mjs` records the owner's subsequent explicit approval of
all eight October 10 DAW candidates, including the corrected interpretation that
Return to Earth stays enrolled and only its final uncovered tail is excluded
from reference evaluation. It uses `daw_map_reference.mjs` and actual DAW timing
functions to preserve edited geometry; it is not an offset-only source-map
finalizer. Run this dated operation only for its recorded owner decision, under
`tools.ntm_collection.storage.storage_lock`; completed receipts cannot be
overwritten. References and approved project copies are in each session's
`registered/`, and the receipt is under
`data/samples/records/owner-review/20261010-candidate-enrollment-v1/`.
Over It's approved project-end extension preserves audio/map alignment. The
Dillinger reference retains its model-seeded, owner-listening-confirmed origin.
Original audio/clock hashing, playback, inference and benchmarks are not part of
this enrollment operation.

## Retained browser workflow — explicit opt-in

When browser review is explicitly requested, prepare and serve the current
formal sample catalog for direct owner listening.
The interface preserves the existing approved maps, stored pulse/bar semantics,
audio-relative offsets, explicit support intervals and approved no-grid tails.
Auxiliaries and acquired NTM candidates remain separate from formal membership.

```sh
data/runtime/ntm-collector/venv/bin/python -B tools/sample_review/prepare.py \
  --out data/samples/reviews/20261009-formal-v1
python3 -B tools/sample_review/serve.py \
  --root data/samples/reviews/20261009-formal-v1 --port 9010
```

Open http://localhost:9010/; remote workspaces can forward port 9010.
Preparation reads native audio headers and the selected current reference files.
It computes small reference-file fingerprints to bind review decisions; it does
not hash full audio recordings, decode source ZIPs or run inference. Original
media are addressed directly rather than copied into the review batch.

The page plays audio and reference clicks from a shared Web Audio sample clock.
It reads stored audio-relative events without adding the saved offset twice.
An adjustable comparison offset is relative to the displayed map. Native
recorded pulse modes and quarter/group/bar alternatives remain explicit.
Tempo and meter events retain exact stored values, including repeated records;
annotations distinguish simple fractions, nominal storage precision and values
outside the denominator-four vocabulary. These are review aids, not automatic
musical-validity conclusions.

Owner answers are saved under the generated batch in `review-records.json` and
append-only `review-history.jsonl`, with reference versions and reviewed scope.
Playback intervals are descriptive evidence, not automatic acceptance. A current
map confirmation requires explicit listening/tempo/meter/alignment/coverage
attestations, resolved item verdicts and zero comparison offset. Candidate
review cannot mark a formal sample revalidated or enroll it in the catalog.
Every batch begins without inheriting prior acceptance as a new confirmation.

The server binds to loopback and exposes an exact asset allowlist. It stops
serving changed source assets and rejects decisions for a changed file version.
Saving review results never rewrites prior references, offsets, membership,
frozen experiments or model outputs. Owner confirmation establishes practical
musical acceptance within the stated scope; it is not an independent producer
clock millisecond certificate.
