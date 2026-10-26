# Local data layout

`data/` holds original sources, evaluation references and generated research artifacts. It is excluded from source Git. A separate private data checkout can preserve selected compact metadata and release attachments; source distribution does not include recordings, credentials, model files or complete experiment results.

| Directory under `data/` | Role | Reference |
| --- | --- | --- |
| `samples/` | Canonical original recordings, accepted references, drafts and acquisition evidence | `samples/catalog.json` defines formal membership |
| `samples/datasets/` | External audio/features, original annotations, acquisition receipts and dataset manifests | `registry.json` records representation and inventory state |
| `research/runs/` | Experiment inputs, raw predictions, scores and frozen source/configuration snapshots | Each run's manifest and report |
| `research/state/` | Prepared observations and diagnostics | Their experiment specification |
| `research/previous/` | Retained earlier source/failure evidence | Historical reports |
| `models/` | Model checkpoint | Official `final0.ckpt` |
| `runtime/` | Collection dependencies and retained acquisition runtime | [collection documentation](ntm_collection/README.md) |
| `private/` | Local credentials and session state | Excluded from review assets, source and published metadata |
| `storage/` | Storage receipts, relocation index and backup/checkpoint metadata | [repository utilities](repository/README.md) |

## Timing and provenance

Accepted timestamps already use the original recording's audio axis. Applying a source offset twice changes the reference clock. Native source maps, manually edited maps, predictions and reference registrations retain separate provenance.

Published feature containers retain provider augmentations, but inventories count original inputs separately. Alternate encodings and multiple stems do not establish independent recordings. Feature-frame extent is distinct from a certified original PCM clock.

Originals, extracted provider data, generated observations and source-only/evaluation manifests have distinct roles. Downloading a source does not establish reference alignment, a valid ideal tempo map or formal membership. [Research documentation](../docs/AUTORESEARCH.md#broad-observation-to-map-evaluation) describes current corpus qualification.

Selected algorithm/evaluator source and aggregate-only review results are
available in [reference/decoder_review](../reference/decoder_review/README.md).
They are documented review copies, not raw-data distribution or a complete
research backup. Original code freezes, event arrays, references and per-record
outputs remain in their respective local research runs.

## Paths and recovery

Canonical originals live inside `data/samples/`; historical identifiers may describe older layouts. `tools/project_storage.py` resolves retained relocated files without reinterpreting timing or frozen results. Recordings and native project geometry remain separate from regenerable caches.

BPMTracker's decoded buffers are session caches. Unchanged originals can rebuild missing buffers; original audio, saved projects, recovery files and analysis records have their own lifetime. See [audio cache behavior](../apps/daw/README.md#audio-cache-lifetime).

Data checkpoints describe only the files actually selected and uploaded. A compact source/result archive is not a complete audio/model backup. The local `data/README.md` and backup tools describe restoration where those private assets are available.
