# Region-first variable clock composition

**Current role:** reused source sensors and geometry/evaluation helpers. The region-first composer below is a completed historical experiment, not the current standard. See [the code map](../../docs/CODE_MAP.md).

Owner-authorized extensive research on 2026-10-11. This isolated implementation
does not replace the application estimator, modify references or revive a retired
inference architecture. It reuses official Beat This final0 observations and
physical quarter-clock primitives.

The changed hypothesis is to seed from a strong continuous episode anywhere in
the original recording, refine using source-supported episodes, preserve local
rate/phase alternatives, and connect them with held phase until sustained
competing evidence justifies a change. Qualifying a clock and placing its interval
boundary use different evidence windows. Original audio is never cut/rejoined.
The beam decoder is an approximate search, not a proof of an optimal tempo map.

Eleven currently owner-approved variable songs are primary. Four meter-only and
six fixed recordings expose unwanted splits; 24 previously authored musical
controls cover four parents with six arrangements each. Three newly accepted
variable songs are confirmation material, not certified unseen recordings.

`common.py` defines a primary source-only method, ablations, four prespecified
sensitivity settings and a minimum viability gate. Numerical settings and all
source code are frozen before target predictions are scored. Initial-unit
diagnostics encode reference BPM ±5% only after source preparation, then discard
the numeric value. The constraint applies only in a source-supported initial
episode, not as a whole-song BPM target. True rate/phase dictionary diagnostics
withhold true interval boundaries and never count as automatic performance.

Execution order in `.venv-metronome-v1`: `prepare`, `sensors`, `controls`, `freeze`,
`worker --stage banks`, `encode`, `worker --stage predict`, `oracle`, `audit`,
`evaluate`, `report`. Each entrypoint takes `--run`; expensive independent inputs
can be sharded in two worker processes. All raw source arrays, candidate clocks,
tables, seed episodes, serialized predictions, current reference snapshots,
source-read receipts, metrics and figures are retained under
`data/research/runs/variable_clock_composition_v1/`.

Outputs concern quarter BPM/phase and intervals. They do not infer time signatures
or certify independently observed producer-clock timing. No gradual-tempo model,
learning, provider acquisition, app/runtime test or source Git publication is
included in this research task.

## Recorded 2026-10-11 study

Local run: `data/research/runs/variable_clock_composition_v1/20261010T185525Z-v1/`.
Read `interpretation.ko.md` for the complete judgment, then `report.ko.md`,
`decision-gate.json`, `candidate-availability.json` and `metrics.json` for evidence.
The frozen primary comparison has 1,440 serialized/scored predictions over 45
inputs, not 1,440 independent songs. It failed its minimum variable-song gate.
The main source-only condition recovered 53.85% correct quarter-clock time;
initial-unit diagnostics recovered 65.64%, with 30.59% wrong-clock time.

Twenty-two phase/rate dictionary diagnostics and a 24-configuration guard/unit
sweep (1,272 predictions) were added explicitly after scoring to diagnose causes.
They are preserved separately and are not preregistered confirmation. No
exploratory source configuration met the same numeric viability gate. The best
retrospective oracle-clock sweep recovered 90.51% correct time, supporting the
piecewise-clock representation conditionally without proving source-only clock
selection or precise transition recovery. These results recommend stopping
incremental tuning of this beat-consistency selector, retaining the source clock
proposals as research components, and avoiding app adoption. The study does not
prove that every clock-composition or variable-tempo method is impossible.
