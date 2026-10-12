# Maintained project operations

Current development status is in [project-state.json](../project-state.json).
The variable entry is [algorithms/variable](../algorithms/README.md), the app is
[apps/daw](../apps/daw/README.md), and previous studies are in
[reference](../reference/README.md).

| Area | Start here | Purpose |
| --- | --- | --- |
| Repository navigation/audit | [repository](repository/README.md) | Current status, complete metadata inventory and source/document layout checks |
| Requested sample collection | [NTM workflow](ntm_collection/README.md) | Canonical originals, supplied clocks, owner offset/scope and DAW review descriptors |
| Sample/reference review | [sample review](sample_review/README.md) | Drafts, accepted-map materialization and shared native geometry conversion |
| Historical path resolution | [project_storage.py](project_storage.py) | Resolve retained old data identifiers without changing clocks or frozen records |
| Local storage | [LOCAL_DATA.md](LOCAL_DATA.md) | Samples, research results, models, receipts and private runtime boundaries |

The completed dated `confirm_daw_maps.mjs`, `enroll_daw_candidates.mjs` and
`audit_offset_declarations.py` scripts moved to
[reference/sample_operations](../reference/sample_operations/README.md).
Current shared geometry remains `sample_review/daw_map_reference.mjs`.
The old browser experiment listening tool moved to
[reference/bpm_experiment_listening](../reference/bpm_experiment_listening/README.md).
Native separate reference/current `.joljak` audition is the current standard.

`data/samples/catalog.json` governs sample membership and accepted references.
Acquisition or draft saving does not enroll a recording. Offset-only finalization
must preserve owner-edited maps; changed maps require DAW-geometry materialization.
New revisions need their own owner decision and receipt paths. Browser review
servers remain explicit opt-in. Paid acquisition, experiments, runtime tests,
cleanup and source Git publication each follow the applicable owner request.
