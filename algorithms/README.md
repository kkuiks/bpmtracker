# Maintained algorithm entry points

Start variable development at [`variable/baseline.py`](variable/baseline.py).
It selects the owner's **L2_DENSE_PROPOSALS** development standard and delegates
to the unchanged measured implementation. This is an explicit entry point, not
a duplicated fitter or a new measurement.

The current DAW Analyze command still calls the fixed estimator in
[`experiments/metronome_reconstruction_v1`](../experiments/metronome_reconstruction_v1/README.md).
That implementation remains the application backend and the fixed comparison.
Variable-baseline selection does not deploy a different app analyzer.

[`project-state.json`](../project-state.json) records the selected baseline and
its evidence. [`DEVELOPMENT.md`](../docs/DEVELOPMENT.md) explains the next objective;
[`CODE_MAP.md`](../docs/CODE_MAP.md) points to the actual search/scoring/contracts.

Future changes should use a new run and compare with the preserved L2 predictions.
Do not modify a recorded freeze, reference, failed-input denominator, or frozen
implementation merely to let an old run accept new source. No experiments are
started by importing these modules or reading the plans.

The closed 2026-10-13 AutoResearch v2 candidate remains in a local snapshot:
`data/research/runs/autoresearch_run_v2/20261013-campaign-v2/session/trials/trial006/candidate/`.
It improved the pinned-initial/held-meter development objective and passed known
fixed/excerpt regression in that scope. Actual full L2 integration failed fixed
regression and remained incomplete on one comparator. It has not replaced this
entry or the application estimator. See the [research handoff](../docs/AUTORESEARCH.md)
for candidate modules, frozen evidence and the single proposed next experiment.
