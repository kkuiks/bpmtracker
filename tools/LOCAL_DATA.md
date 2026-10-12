# Local data layout

`data/` is checkout-local and ignored by source Git. It is also the separate
private `kkuiks/joljak-data` Git checkout, with an exact compact-metadata
allowlist. Large non-audio checkpoints use that private repository's release
assets. Recordings, credentials and runtime caches remain excluded. The source
code and launchers live outside it; source Git does not contain a data submodule.

Current baseline selection and source roles are recorded in
[`project-state.json`](../project-state.json). The owner-selected L2 recordings,
additional-source verification and 21 native listening pairs retain their
original `research/runs/` locations. Source reorganization moves only code and
navigation; it does not shift recordings, references or frozen input paths.

| Directory | Role | Authority or entry point |
| --- | --- | --- |
| `samples/` | Canonical originals, accepted references, owner drafts and acquisition evidence | `samples/catalog.json` governs membership; [sample operations](sample_review/README.md) |
| `research/runs/` | Preserved experiment inputs, raw predictions, scores and frozen source snapshots | Each recorded run's report and manifest |
| `research/state/` | Retained preparation and diagnostic observations | The requesting experiment's documentation |
| `research/previous/` | Selected historical failure and source evidence | Dated reports; these do not start another task |
| `models/` | Official local estimator checkpoint | `final0.ckpt` |
| `runtime/` | Reused collection dependencies and browser runtime | [collection tools](ntm_collection/README.md) |
| `private/` | Account/session and private transport state | Never serve, publish or copy this into source or review assets |
| `storage/` | Consolidation receipts and path-only relocation index | `20261008-consolidation/paths.json` and subsequent scoped maintenance receipts |

The complete 2026-10-13 source reorganization receipt is
`storage/20261013-repository-organization-v1/`. It preserves a source-before
snapshot, exact move/hash records, source-bytecode cleanup and the requested
static layout audit. That snapshot is historical source, not a second current
implementation or a new inference run.

Accepted timestamps already use the original recording's audio axis. Do not add
a saved source offset twice or reset bar phase at audio zero. Source maps, owner
edits, model predictions and acceptance records remain separate.

Read current paths and roles from the indexes. Historical run filenames and
references may describe an older layout or intentionally removed collection
inputs; use `tools/project_storage.py` for retained relocated files. Missing
historical inputs do not authorize paid reacquisition or revival of an old task.
Keep actual media/source files in this checkout; the private-note link is the
sole allowed project-note exception.

The initial data publication receipt is
`storage/20261013-private-data-publication-v1/`. Its compact checkpoint record
and publication receipt identify actual backed files, exclusions, remote commit,
release and verified asset hashes. `data/README.md` and
`data/backup_tools/restore.py` describe recovery. Windows recovery/analysis and
uncommitted source are explicitly dated snapshots, not automatic enrollment or
live application directories. Subsequent results require deliberate backup;
the private repository does not schedule or auto-publish future work.
