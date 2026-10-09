# Interval-consensus A research

An isolated, owner-approved follow-up after Step 0 and the seven-direction clock
study. This tests candidate-specific support episodes and a matched whole-input
control. It does not implement an automatic tempo map, meter inference or an app
estimator replacement. Source commits remain owner-operated.

The October 8 approval covers the A report and24 new constructed controls. Later
event-anchor B, PCM-corrobation C and boundary/H4 work require their next decision.
The owner permits assumed initial human BPM and beat unit. Source-only candidates
and scores are prepared before this explicit assistance channel is used.

The three policies are no input, discrete initial unit, and exact nominal initial
BPM selection. Input never supplies phase or true segment boundaries and cannot
create an unsupported clock. Initial assistance follows the first source-supported
clock episode; a persistent observed pulse-density regime change also ends it.
Later regions receive no direct BPM constraint. Inputs for this study are declared
assumptions from constructed/approved initial clocks, not collected human taps.
The fixed application's tap-only contract is unchanged.

The scorer balances observed-event explanation and expected-tick occupancy.
Capacity-one matching, original audio coordinates, strict silence, bounded gaps,
sustained alternatives and a heuristic residual-period guard are explicit.
Quarter and bar support are separate. Local context remains5 quarters for unary
alignment and25 for period consistency; this is not a claim of window-free evidence.
Source clocks remain30–400 BPM with reduced denominator<=4.

Conditions compare unchanged Original, the new score globally versus per-clock
intervals, retained clocks, separately generated broad-rate phases, source phasor
candidates, local phase/rate-phase refits,128-versus512-clock budgets and removal
of the period guard. Every source includes failure/abstention accounting. A finite
proposal cap and multiple overlapping alternatives are reported, not hidden.

The experiment separates source workers from reference evaluation. Reference
qualification and initial-information proxy extraction belong to admission;
prediction workers do not receive the full catalog/reference manifests. Whole-
search null calibration is empirical and is not a formal probability guarantee.
Software/coordinate controls are distinct from musical accuracy.

## Local run

`data/research/runs/variable_tempo_interval_consensus_v0/20261008-mcc-a-v1/`

New music: `data/samples/generated/interval-consensus-a-v1-20261008/`.
Four parent compositions have six paired clock/arrangement/weak-evidence cases.
Two parents develop settings, two are prospective relative to selection. This
is constructed transfer, not new real-music generalization or perceptual quarter
certification. Marker/reference files never enter the neural model.

Example stages, each using a new destination for a new scientific run:

```sh
.venv-metronome-v1/bin/python -m experiments.variable_tempo_interval_consensus_v0.controls --run RUN
.venv-metronome-v1/bin/python -m experiments.variable_tempo_interval_consensus_v0.worker --run RUN --stage prepare
.venv-metronome-v1/bin/python -m experiments.variable_tempo_interval_consensus_v0.worker --run RUN --stage calibration
.venv-metronome-v1/bin/python -m experiments.variable_tempo_interval_consensus_v0.evaluate --run RUN --stage calibration
.venv-metronome-v1/bin/python -m experiments.variable_tempo_interval_consensus_v0.review --run RUN --stage freeze
.venv-metronome-v1/bin/python -m experiments.variable_tempo_interval_consensus_v0.worker --run RUN --stage frozen
.venv-metronome-v1/bin/python -m experiments.variable_tempo_interval_consensus_v0.evaluate --run RUN --stage frozen
.venv-metronome-v1/bin/python -m experiments.variable_tempo_interval_consensus_v0.review --run RUN --stage review
```

`render`, the existing strict official observation worker, and `setup` prepare
the admitted data before these stages. The completed run's saved protocol and
snapshots define exact replay. Reserved98 and original frozen denominators are
preserved. No provider downloads, weights/training changes or DAW tests are included.

## Completed A checkpoint

The first unit completed with527 input IDs and16,337 prediction files (ten
conditions x three input policies plus unchanged Original). These IDs are not
independent songs.24 logical controls,35 execution checks and the identical-source
read audit passed; these are workflow evidence, not musical accuracy.

The provisional direction gate failed. On the three real variable sources,
matched-global correct nominal+quarter-phase supported time is24.59%, versus
26.92% for identical-candidate intervals. Wrong support drops8.15% to0.25%, but
the+2.33 percentage-point recovery gain misses the5-point target. Qualified fixed
real25 wrong support increases13.87% to15.94%; about98% of interval wrong-rate
time is half/double interpretation.14/15 exact nominal rates occur in the phasor
pool, but additional candidates do not establish reliable selection. ADTR's
1.655s145 clock is absent from every compared exact-nominal pool.

The two prospective constructed parents /12 inputs show52.39% correct time and
2.16% wrong time with the interval condition, versus43.87%/.29% matched-global.
Broader phase/phasor pools recover more of these constructed sources but do not
transfer safely to the actual real/fixed cohort. No post-target parameter tuning
or B/C/H4/app adoption followed.

Start with the local run's `report.ko.md`, `overview.html`, `decision-gate.json`,
`primary-real-failure-analysis.json` and `fixed-error-decomposition.json`.
The initial-density decision correction preserves its pre-correction calibration
outputs. `evaluate_serialized` repairs undefined-distance JSON serialization only;
the frozen predictor/evaluator source and all predictions remain intact.
