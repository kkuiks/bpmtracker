# Project tools

These tools manage local storage and owner review. The application and estimator
live in `apps/daw/` and `experiments/`, respectively.

| Area | Start here | Purpose |
| --- | --- | --- |
| Sample acquisition and preparation | [NTM workflow](ntm_collection/README.md) | Requested collection, canonical session storage, supplied-clock preparation and DAW review descriptors |
| Formal reference review | [Sample review](sample_review/README.md) | Owner-saved DAW edits, reference materialization and retained browser compatibility |
| Historical path resolution | [project_storage.py](project_storage.py) | Translate retained historical paths without changing clocks, annotations or frozen records |

The [local data layout guide](LOCAL_DATA.md) describes recordings, research,
models and storage receipts. The current membership and accepted-reference authority is
`data/samples/catalog.json`. Acquisition and saving a DAW draft do not enroll or
approve a recording. Use the owner's explicitly selected working map and scope
when finalizing a reference. `ntm_collection/finalize_selected.py` handles an
unchanged supplied map with an approved offset; manually edited maps require
DAW-geometry materialization.

The dated `sample_review/confirm_daw_maps.mjs`, `enroll_daw_candidates.mjs` and
`audit_offset_declarations.py` operations have completed receipts. They are
examples and historical operations, not commands to replay for new recordings.
`sample_review/daw_map_reference.mjs` contains the shared geometry conversion.
New revisions need their own inputs, owner decision and receipt paths.

Review new candidates in Joljak by default. Browser servers are explicit opt-in.
Paid acquisition, inference, tests, cleanup and source Git publication each follow
the applicable owner request; a directory or recorded experiment is not a task queue.
