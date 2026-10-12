# Measured implementations and shared experiment code

The owner-selected variable development standard is **L2_DENSE_PROPOSALS**.
Start at [algorithms/variable](../algorithms/README.md),
[project-state.json](../project-state.json) and the [code map](../docs/CODE_MAP.md).
The measured L2 implementation stays at its original path and keeps its original
Python/configuration bytes, preserving the two current frozen runs.

The DAW Analyze command still uses the fixed estimator. Recorded experiment
pipelines and their old decisions remain evidence, not task queues or app defaults.

| Package | Current role |
| --- | --- |
| [beat_event_stability_v1](beat_event_stability_v1/README.md) | Selected L2 fitter/scoring/configuration; L1 remains its recorded comparison |
| [beat_event_map_v1](beat_event_map_v1/README.md) | Shared adaptive source preparation, old-beat search, mismatch gate and native metrics; E0-E3 are historical comparisons |
| [continuous_beat_map_v1](continuous_beat_map_v1/README.md) | Shared continuous map/grid/validator/native conversion/audio scoring; its earlier wall-clock search is historical |
| [multiple_rhythm_continuity_v1](multiple_rhythm_continuity_v1/README.md) | Shared accepted-reading/reference evaluation; equivalent readings do not excuse unnecessary switches |
| [variable_clock_composition_v1](variable_clock_composition_v1/README.md) | Reused source sensors and geometry/evaluation helpers; its former region-first composer is historical |
| [variable_clock_exploration_v1](variable_clock_exploration_v1/README.md) | Reused source/family observations; former pulse-clock directions are historical |
| [variable_tempo_interval_consensus_v0](variable_tempo_interval_consensus_v0/README.md) | Retained source-clock I/O/helpers used by later modules; failed consensus direction is not the selected algorithm |
| [linear_validation_v1](linear_validation_v1/README.md) | Completed frozen L2 additional-source verification and fixed comparison |
| [metronome_reconstruction_v1](metronome_reconstruction_v1/README.md) | Current app fixed analyzer and retained fixed-only comparison |
| [metronome_benchmark_v1](metronome_benchmark_v1/README.md) | Qualification/reference/benchmark tools; alternate fitters are diagnostics |

Seven reference-only packages moved to [reference](../reference/README.md).
Their original `experiments.<package>` imports remain available via the package
search path. No source trees or recording aliases were duplicated. Historical
freezes must use original snapshots; their recorded paths/hashes were not rewritten.

Current results remain under `data/research/runs/beat_event_stability_v1/20261012-full-v2/`
and `data/research/runs/linear_validation_v1/20261012-frozen-L2-v1/`.
The full native audition guide is in
`data/research/runs/native_listening_review_v1/20261012-L2-all-weak-v1/listen-projects/`.
The owner accepts this as a development baseline despite the missed old
approximately-99% broader fixed condition. All numerical scores, source types,
failures, accepted references and frozen source snapshots remain unchanged.

Local results/observations are under `data/research/`; originals are under
`data/samples/`; the official checkpoint is `data/models/final0.ckpt` and the CPU
environment is `.venv-metronome-v1/`. The catalog does not alter frozen inputs or
denominators. New experiments need their applicable owner request and new
source/config/input provenance. Model scores, builds, native metronome geometry
and actual Windows media playback remain separate evidence.
