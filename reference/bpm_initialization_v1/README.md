# Initial-clock ablation v1

**Reference status, 2026-10-13:** this completed study was moved intact to the reference area. Historical commands and decisions below are evidence, not current defaults or new execution requests. See [reference index](../README.md) and [current development](../../docs/DEVELOPMENT.md).

Owner-authorized research following the completed `bpm_continuity_v1` run.
Compare four initial-clock choices on the same eight fixed-rate recordings;
render every choice with the **unmodified six-second C_HOLD**. This module does
not change the application, accepted references, candidate banks, prior runs,
or model weights. No variable-tempo follow-up is started by these commands.

| Method | Initial choice |
| --- | --- |
| I0_LOCAL6 | Exact prior six-second source bootstrap |
| I1_WHOLE_RATE_LOCAL6 | Source-prepared whole-input family BPM within the shared unit, then six-second local phase |
| I2_LOCAL12 | Twelve-second trailing initial evidence, commitment at/after 12 seconds |
| I3_LOCAL24 | Twenty-four-second trailing initial evidence, commitment at/after 24 seconds |

All methods use the **same six-second audio base and discrete input power**.
Whole-input family levels are translated into this common base instead of
silently changing units when the family's base differs. Its phase and meter
are not imported. A rate absent from the unchanged final bank cannot create a
seed. Long-window seeds must also satisfy the unchanged downstream output rule
at commitment. The common seed deadline remains 30 seconds.

The full approved support remains the denominator. Waiting, NO_SEED, wrong
rates, unknown output and every failed input stay in the metrics. No per-song
method selection or post-score parameter tuning is allowed. The three
reference-derived 95/100/105% proxy inputs are identity diagnostics; they are
not collected human taps or three independent recording cohorts.

Preregistered direction gates require macro exact-nominal-clock correctness
at least 80% (phase tolerance 70 ms), actual emitted-quarter F1 no lower than
the frozen stateless proxy comparator (rescored on the same current references),
and no recording losing more than five percentage points versus I0. These are
research direction gates, not product acceptance criteria.

Whole-input fitting is a fixed-song diagnostic with future information.
The local variants also inherit offline sensor and whole-input candidate/phase
preparation. No method's seed timestamp establishes streaming latency.
Constructed fractional-clock controls challenge integer-rounding shortcuts;
they do not contribute to the eight-real-recording performance denominator.

Run `prepare`, `controls`, `run --stage build`, `run --stage freeze`,
`run --stage predict`, `audit`, `evaluate`, then `report` using a unique run
directory. The snapshot captures code/configuration before target predictions.
Source workers deny access to references, the catalog, evaluation manifests,
baseline outputs and raw proxy numbers. An audit changes inaccessible
evaluation/raw inputs and compares all outputs across worker counts; the I0
outputs are also compared byte-for-byte to the previous frozen run.

Interpretation may be written after scoring, but frozen predictions, metrics,
code and parameters must not be rewritten to improve the result.

Completed run: `data/research/runs/bpm_initialization_v1/20261010T100132Z-v1/`.
All 27 logical controls passed; 96 poisoned-reference/worker comparisons and
24 prior-baseline reproductions were byte-identical. Only the whole-input-rate
method passed all gates: macro correct-clock 87.23%, emitted-quarter F1 92.78%,
exact-rate seeds 8/8, with no per-recording loss. Its output matched the prior
exact-rate-assisted hold on all eight recordings. Local 12/24-second methods
scored 73.21%/51.95%; the latter retained two NO_SEED recordings in all metrics.
Read the run's `report.ko.md` and `interpretation.ko.md` for limits and remaining
phase/support failures; this is not an application or variable-tempo result.
