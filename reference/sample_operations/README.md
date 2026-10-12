# Completed sample operations

These scripts implement dated, already completed owner-confirmation/enrollment
operations. Keep them for inspection and provenance; their hardcoded targets and
receipt paths are not a queue to replay.

- `confirm_daw_maps.mjs`: materialize selected owner-confirmed map revisions.
- `enroll_daw_candidates.mjs`: record the selected approved enrollments.
- `audit_offset_declarations.py`: inspect that dated formal-map cohort.

Shared current map conversion remains at
[`tools/sample_review/daw_map_reference.mjs`](../../tools/sample_review/daw_map_reference.mjs).
Current source/reference operations are documented in
[`tools/sample_review`](../../tools/sample_review/README.md) and
[`tools/ntm_collection`](../../tools/ntm_collection/README.md).

Sample membership comes from `data/samples/catalog.json`; a saved draft, old
script or reference proposal does not approve a new recording.
