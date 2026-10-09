# Local data layout

`data/` is checkout-local and ignored by source Git. It holds recordings,
references, research evidence, models and collection runtime material. The source
code and launchers live outside it.

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

Accepted timestamps already use the original recording's audio axis. Do not add
a saved source offset twice or reset bar phase at audio zero. Source maps, owner
edits, model predictions and acceptance records remain separate.

Read current paths and roles from the indexes. Historical run filenames and
references may describe an older layout or intentionally removed collection
inputs; use `tools/project_storage.py` for retained relocated files. Missing
historical inputs do not authorize paid reacquisition or revival of an old task.
Keep actual media/source files in this checkout; the private-note link is the
sole allowed project-note exception.
