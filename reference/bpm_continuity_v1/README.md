# BPM continuity research v1

**Reference status, 2026-10-13:** this completed study was moved intact to the reference area. Historical commands and decisions below are evidence, not current defaults or new execution requests. See [reference index](../README.md) and [current development](../../docs/DEVELOPMENT.md).

This recorded experiment compares stateless local clock selection (C1),
a continuity policy (C2), and a BPM-locked control with the same phase reanchor
rules (C_HOLD). It uses the unchanged official sensor and original final clock
bank, eight specified fixed recordings and two specified variable recordings.
It is isolated from the application estimator and existing frozen runs.

The primary input is one exact initial quarter-BPM scalar. Three auxiliary
conditions perturb the nominal initial reference BPM by -5%, 0%, +5% and encode
the number once as an octave power. Predictors never receive the raw proxy
number, reference phase, scope, meter, or future changes. These are reference
diagnostics, not measured human taps or an automatic quarter-unit success.

Protocol 1.2 adds C_HOLD, fixes residual unwrapping with source candidate quarter
indices, uses current support precedence without reapplying offsets, and requires
actual event-F1 nonregression in addition to the original clock-time gates.
The six-second evidence window and the shared final pool retain explicit limits.
Missing rates, NO_SEED, UNKNOWN and unsupported transitions remain in denominators.

Use `.venv-metronome-v1/bin/python` and a new unique run under
`data/research/runs/bpm_continuity_v1/`. Preparation creates the run and reuses
nine retained observation/bank pairs; it runs the same CPU sensor and original
final-bank generator once for Underoath. `controls` precedes target predictions.
`run --stage build` prepares source scores before the separate initial-input
adapter runs. `freeze` snapshots code, configuration and inputs. Prediction
workers enforce a reference-read guard. `audit` checks identical output under
incompatible evaluation sentinels and worker counts; `evaluate` is separate.
`report` produces ten PNG/SVG timelines, a Korean report and a result ZIP without
audio, weights or NPZ arrays. The recorded report lists the exact commands.

Do not rerun completed stages into an existing run or tune parameters against
the target results. The experiment does not update references, enroll samples,
replace the application model, or establish runtime, export, millisecond clock
certification, human tapping performance, or unseen-song generalization.
