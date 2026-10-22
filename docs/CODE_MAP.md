# Source code map

The [development guide](DEVELOPMENT.md) describes current capabilities and evidence. [Project metadata](../project-state.json) provides structured component status. The [review brief](RESEARCH_REVIEW.md) relates current algorithms, measured results and open questions.

## Variable algorithm

| Concern | Source | Role |
| --- | --- | --- |
| Maintained entry | [baseline.py](../algorithms/variable/baseline.py) | Source preparation and explicit L2 prediction |
| L2 search | [stability core](../experiments/beat_event_stability_v1/core.py) | Dense source proposals and bounded path search |
| L2 scoring | [stability scoring](../experiments/beat_event_stability_v1/scoring.py) | Bar-grid evidence and quarter PCM scoring |
| Configuration | [stability common](../experiments/beat_event_stability_v1/common.py) | Measured parameters and source provenance |
| Beat-boundary changes | [beat-event core](../experiments/beat_event_map_v1/core.py) | Existing-beat declarations and continuous paths |
| Change evidence | [beat-event scoring](../experiments/beat_event_map_v1/scoring.py) | Old/new clock mismatch and observation roles |
| Source proposals | [beat-event source](../experiments/beat_event_map_v1/source.py) | Audio-derived candidates prepared before unit selection |
| Continuous clock | [map.py](../experiments/continuous_beat_map_v1/map.py) | Initial phase, accumulated quarters and beat/bar grids |
| Native conversion | [native.py](../experiments/continuous_beat_map_v1/native.py) | Research maps to ordinary DAW projects |
| Evaluation | [native_metrics.py](../experiments/beat_event_map_v1/native_metrics.py) | Reference readings and unnecessary-change penalties |
| Audio observations | [sensors.py](../experiments/variable_clock_composition_v1/sensors.py) | Source-only observation and PCM preparation |

Historical modules remain active dependencies where listed. [`experiments/__init__.py`](../experiments/__init__.py) also preserves imports of retained reference packages; no duplicate source tree is required.

## Current G21 research snapshot

G21 is a frozen evaluated candidate, separate from the maintained L2 entry. Its local research root is `data/research/runs/l2_improvement_autoresearch_v1/20261014-01a138e6-v1/`; the evaluated phase is `phases/phase-B-c250ba38c4af/`.

| Phase-relative location | Role |
| --- | --- |
| `trials/G21/full/candidate_api.py` | Full initial/meter search and complete-map L2 source-cost comparison |
| `trials/G21/full/candidate_initial_source.py` | Information-qualified source initial candidates |
| `trials/G21/full/candidate_core.py`, `candidate_scoring.py`, `candidate_emissions.py` | Continuous path search and source evidence |
| `trials/G21/held/` | Separate held-initial/meter diagnostic |
| `evaluations/G21-development16-v1/` | Candidate/control comparisons |
| `delivery/final-G21-v2/` | Results, failures, reference scope, runtime and reproduction manifest |

The original run artifacts require local research data. Selected byte-identical
source/configuration copies are available in
[reference/decoder_review/20261022/g21_full](../reference/decoder_review/20261022/g21_full/).
These copies support inspection rather than relocating the measured runtime.
[Research documentation](AUTORESEARCH.md#reproduction) records the reproduction
boundary. Earlier regression studies remain separate historical results.

## Post-comparison selection prototypes

The completed repair study is local at
`data/research/runs/map_decoder_repair_v1/20261020-source-selection-v1/`.
Eighteen policies were compared on formal44 and twelve on broad2,604. No new
tempo-path search, baseline replacement or app integration resulted.

| Review source | Role |
| --- | --- |
| [source_scores.py](../reference/decoder_review/20261022/selection_repair/source_scores.py) | Same-map legacy/pointwise/role costs and source boundary code |
| [prefix_api.py](../reference/decoder_review/20261022/selection_repair/prefix_api.py) | Candidate A: preserve initial clock and all BPM changes; select a trailing meter suffix |
| [phase_api.py](../reference/decoder_review/20261022/selection_repair/phase_api.py) | Global initial bar rotations with continuous quarter relabelling |
| [hierarchical_predictor.py](../reference/decoder_review/20261022/selection_repair/hierarchical_predictor.py) | Candidate B: literal-bar phase selection and role-aware suffix selection |
| [repair_api.py](../reference/decoder_review/20261022/selection_repair/repair_api.py) | Full-pool criterion interventions and source-only candidate enumeration |
| [evaluation](../reference/decoder_review/20261022/evaluation/) | Original provider-event and accepted-grid evaluator source |

The [snapshot manifest](../reference/decoder_review/20261022/manifest.json)
binds each review copy to its original path and bytes. Its path calculations
and imports are preserved; it is not a standalone runtime package. The
[aggregate summary](../reference/decoder_review/20261022/evaluation-summary.json)
contains no raw observations or accepted reference vectors.

## Windows application

| Concern | Source |
| --- | --- |
| Launch and packaging | [scripts](../apps/daw/scripts/), [Start Joljak.cmd](../Start%20Joljak.cmd) |
| Electron IPC, jobs, project/cache restoration | [main.cjs](../apps/daw/electron/main.cjs) |
| Decoded-buffer lifetime and reuse | [audio-cache.cjs](../apps/daw/electron/audio-cache.cjs) |
| Import, analysis and export workers | [worker.py](../apps/daw/backend/worker.py) |
| Commands and editing session | [App.tsx](../apps/daw/src/App.tsx) |
| Project schema | [model.ts](../apps/daw/src/model.ts) |
| Musical coordinates and persistent maps | [music.ts](../apps/daw/src/music.ts) |
| Streaming and sample-clock playback | [audio.ts](../apps/daw/src/audio.ts), [transport-worklet.js](../apps/daw/public/transport-worklet.js) |
| Editing transactions | [arrangement.ts](../apps/daw/src/arrangement.ts), [SelectionMove.tsx](../apps/daw/src/SelectionMove.tsx) |
| Undo/Redo | [history.ts](../apps/daw/src/history.ts) |
| Fixed analyzer | [metronome_reconstruction_v1](../experiments/metronome_reconstruction_v1/README.md) |

The frontend, Electron main process and Python worker still contain substantial application behavior. Build success is separate from native playback, recovery, persistence and export validation.

## Data and operations

[`tools`](../tools/README.md) contains collection, sample/reference review, storage and repository utilities. [`LOCAL_DATA.md`](../tools/LOCAL_DATA.md) describes source audio, features, references and reproducibility artifacts. Original recordings and large research/model files are excluded from source distribution.

Previous independent studies and completed sample operations are indexed in [`reference`](../reference/README.md). Their historical results do not select the current app analyzer or replace the maintained variable entry.
