# Estimator and experiment entry points

The application uses the fixed estimator in `metronome_reconstruction_v1/`.
Research modules remain separate from application inference. Their presence and
example commands do not authorize a new run.

| Module | Role | Documentation |
| --- | --- | --- |
| `metronome_reconstruction_v1/` | Current fixed quarter-BPM, meter and downbeat-offset estimator; original frozen experiments | [Estimator](metronome_reconstruction_v1/README.md) |
| `metronome_benchmark_v1/` | Separate qualification, reference adapters and benchmark diagnostics | [Benchmark](metronome_benchmark_v1/README.md) |
| `variable_tempo_step0/` | Completed candidate-recovery and boundary-localization diagnostics | [Step 0](variable_tempo_step0/README.md) |
| `variable_clock_exploration_v1/` | Isolated pulse-clock directions; not integrated into the app | [Clock exploration](variable_clock_exploration_v1/README.md) |
| `variable_tempo_interval_consensus_v0/` | Isolated interval-consensus follow-up and its recorded direction gate | [Interval consensus](variable_tempo_interval_consensus_v0/README.md) |

Local results and source snapshots live under `data/research/`; original and
constructed recordings are under `data/samples/`. The current corpus catalog
does not change frozen experiment inputs or denominators. Raw predictions,
source-only inference inputs, evaluation references and oracle diagnostics retain
their separate meanings. Use `tools/project_storage.py` for historical path
resolution; do not rewrite a frozen descriptor merely to match a newer layout.

The retained CPU environment is `.venv-metronome-v1/`, and the official checkpoint
is `data/models/final0.ckpt`. Windows packaging has a separate runtime and model
copy for standalone use. A benchmark score or successful build is separate from
app playback, persistence or export validation.
