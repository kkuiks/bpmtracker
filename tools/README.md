# Project tools

The tools support dataset collection, reference review, local storage and repository inspection. Application and algorithm entry points are listed in the [code map](../docs/CODE_MAP.md).

| Area | Entry | Purpose |
| --- | --- | --- |
| Project status and repository metadata | [repository](repository/README.md) | Component status, source layout and static metadata inspection |
| Recording collection | [NTM workflow](ntm_collection/README.md) | Original audio, supplied clocks and DAW review descriptors |
| Reference review | [sample review](sample_review/README.md) | Drafts, accepted-map geometry and native conversion |
| Historical paths | [project_storage.py](project_storage.py) | Resolve retained relocated data identifiers without changing clocks |
| Data layout | [LOCAL_DATA.md](LOCAL_DATA.md) | Sources, references, research results, models and runtime state |

`data/samples/catalog.json` defines formal membership and accepted references. Acquisition and draft saving remain separate from registration. Offset-only revisions preserve the edited map; tempo/signature/phase revisions use the saved DAW geometry and retain their provenance and reviewed scope.

Shared map conversion is implemented in `sample_review/daw_map_reference.mjs`. Completed dated registration scripts are indexed in [reference/sample_operations](../reference/sample_operations/README.md). The earlier browser listening utility is retained in [reference/bpm_experiment_listening](../reference/bpm_experiment_listening/README.md); current sample review uses ordinary BPMTracker projects with original audio and the project metronome.
