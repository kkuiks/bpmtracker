# Source code map

Current status: [`project-state.json`](../project-state.json).
Development direction: [`DEVELOPMENT.md`](DEVELOPMENT.md).

## Variable algorithm

| Concern | Actual source | Role |
| --- | --- | --- |
| Maintained public entry | [baseline.py](../algorithms/variable/baseline.py) | Source preparation and explicit L2 prediction; future integration starts here |
| Selected measured fitter | [stability core](../experiments/beat_event_stability_v1/core.py) | Dense source proposals and path search; unchanged baseline |
| Selected scoring | [stability scoring](../experiments/beat_event_stability_v1/scoring.py) | Balanced bar-grid evidence and quarter PCM scoring |
| Parameters and freeze | [stability common](../experiments/beat_event_stability_v1/common.py) | Selected configuration and original-source guards |
| Legal change search | [beat-event core](../experiments/beat_event_map_v1/core.py) | Existing-beat declarations and continuous paths |
| Change evidence | [beat-event scoring](../experiments/beat_event_map_v1/scoring.py) | Old/new clock mismatch gate and observation roles |
| Source candidate preparation | [beat-event source](../experiments/beat_event_map_v1/source.py) | Adaptive audio-derived evidence, before tap encoding |
| Continuous map contract | [map.py](../experiments/continuous_beat_map_v1/map.py) | One initial phase, no independent resets, actual beat/bar grids |
| Native project conversion | [native.py](../experiments/continuous_beat_map_v1/native.py) | Saved maps to ordinary DAW projects |
| Accepted-reading metrics | [native_metrics.py](../experiments/beat_event_map_v1/native_metrics.py) | Equivalent readings with unnecessary-change penalties |
| Audio observations | [sensors.py](../experiments/variable_clock_composition_v1/sensors.py) | Retained source-only peak/PCM preparation |
| Broader measured validation | [linear validation](../experiments/linear_validation_v1/README.md) | Frozen L2 versus fixed-unit comparison; not parameter tuning |

The selected implementation is frozen for comparison. The maintained entry calls
that implementation without copying it or altering parameters. Future candidate
work needs new source/config provenance; never bypass an old freeze guard to make
a historical run accept a changed fitter.

## App and fixed comparison

| Concern | Source |
| --- | --- |
| Windows launch and packaging | [scripts](../apps/daw/scripts/) and [Start Joljak.cmd](../Start%20Joljak.cmd) |
| Electron IPC, file/cache restoration | [main.cjs](../apps/daw/electron/main.cjs) |
| Audio import, analysis and export workers | [worker.py](../apps/daw/backend/worker.py) |
| UI commands and session state | [App.tsx](../apps/daw/src/App.tsx) |
| Project schema and playback geometry | [model.ts](../apps/daw/src/model.ts) |
| Musical coordinates and persistent maps | [music.ts](../apps/daw/src/music.ts) |
| Audio streaming and sample-clock playback | [audio.ts](../apps/daw/src/audio.ts), [transport-worklet.js](../apps/daw/public/transport-worklet.js) |
| Selection/editing transactions | [arrangement.ts](../apps/daw/src/arrangement.ts), [SelectionMove.tsx](../apps/daw/src/SelectionMove.tsx) |
| Fixed analyzer and comparison | [fixed estimator](../experiments/metronome_reconstruction_v1/README.md) |
| Qualification and reference adapters | [benchmark tools](../experiments/metronome_benchmark_v1/README.md) |
| Current native-map audit tools | [audit](../apps/daw/audit/README.md) |
| Recorded UI checks/designs | [app reference](../apps/daw/reference/README.md) |

The current app Analyze command remains fixed-only. Variable development baseline
selection is not automatic app integration. `App.tsx` and the Electron/worker
files still contain substantial behavior; this cleanup preserves that behavior
and does not claim they have been split into newly runtime-tested components.

## Operations and retained dependencies

[`tools`](../tools/README.md) contains maintained sample/storage/repository
operations. Completed dated sample enrollment/confirmation commands are in
[`reference/sample_operations`](../reference/sample_operations/README.md).

The ten packages still in `experiments/` comprise the measured baseline, fixed
comparison, evaluation and reused source/search/geometry helpers. Historical
composition/window/consensus methods inside those packages are not current
recommendations; their retained helper functions are dependencies. Seven
reference-only experimental packages were moved to `reference/` without changing
their Python source. See its [catalog](../reference/README.md) for outcomes and
locations. Frozen input/result JSON and code snapshots under `data/` remain at
their original physical paths.

The original 2026-10-10 continuity plan is private historical material at
`_local/docs/research-plans/20261010-continuity/BPMTracker_BPM_Continuity_Experiment_Plan_2026-10-10.md`.
It is retained for reference; current owner decisions and source locations above
supersede its proposed workflow.
