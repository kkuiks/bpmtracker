# Variable clock exploration after Step 0

An isolated directional experiment in source-only pulse-clock proposals for
piecewise stable tempo. It compares locally indexed affine compression,
multiscale clock witnesses, source phase transport, a physical phasor bank, and
sparse-tick abstention. An unchanged Original constant-clock estimator is the
baseline. None of these implementations is integrated into the Windows app.

The predictors accept sensor arrays and optional source-derived attack/silence
information, without song identity, reference BPM, meter, phase or boundaries.
There are no per-recording inference parameters or exceptions. Returned BPMs
remain in 30–400 with reduced denominator at most four. A continuous latent line
fit is recorded separately; event scores use the declared rational output clock.
There is no tap input or automatic meter inference. The native neural pulse unit
is not independently certified quarter notation; octave alternatives are
diagnostics, not equivalent strict-quarter successes.

## Methods

| Arm | Mechanism |
| --- | --- |
| `affine_mdl` | Infer local missing-pulse counts, then compare piecewise affine descriptions of event time. |
| `multiscale` | Compare local line witnesses across 2/4/8/16/32/64-second views; window edges are not tempo changes. |
| `transport` | Add source-inferred line intersections for conditional phase-continuous boundary proposals. |
| `phasor_transport` | Test all rational rates locally before fitting event coordinates for each physical clock hypothesis. |
| `phasor_abstain` | Preserve sparse-tick hypotheses as UNKNOWN and omit their definite changes. |
| `raw_onset_transport` | Propose physical pulse clocks directly from source attacks, separately frozen after the main study. |
| `raw_onset_initial_neural_unit` | Select a discrete initial source-neural pulse-level relation for the raw clocks; unsupported domain intervals remain UNKNOWN. |

Optional attack variants use multiband spectral novelty from source PCM to sharpen
nearby neural event timestamps. Those attacks are not original metronome clicks.
Strict digital silence is a source observability check, not a general no-grid or
drumless classifier. Confidence rules are heuristic, not calibrated probabilities.

Local periodicity is an established direction in
[PLPDP research](https://arxiv.org/abs/2308.10355). Separate metrical interpretations
are motivated by [metric-level evaluation](https://arxiv.org/abs/2210.06817).
The novelty claimed here is a new project experiment combining and contrasting
these mechanisms, without a claim of a world-first algorithm.

## Recorded execution

Local run: `data/research/runs/variable_clock_exploration_v1/20261008-clock-witness-v1/`.
Start with `report.md`, `comparison-summary.json`, `frozen-evaluation.json`,
`observation-controls-rate-audit.json`, `execution-review.json`, and the standalone
PNG/SVG trajectory figures. The HTML report links the same local figures.
`report.ko.md` is the readable Korean outcome, `all-directions-summary.json`
adds the two source-onset challengers, and `onset-report.md` records their separate
freeze and domain-guard failure/correction. Four supplementary controls have
their own source-only observations, predictions and evaluation.

On the three real recordings, neural phasor transport improves nominal-majority
segment recovery from Original 5/15 to 8/15, and 1% rate-time agreement from
55.42% to 84.17%. Exact native changes remain 1/24/11 TP/FP/FN. Attack-snapped
abstention gives 3/20/9, while proposing changes on 12/26 original fixed inputs.
The same arm detects 0/16 exact changes on twelve fresh constructed inputs.
Direct source-onset variants produce 148/144 false real changes. These are
component-level directional results, not an adopted variable-tempo decoder.

The run admits 499 input IDs: previous Step 0 36, generated fixed 58, original
fixed 26, GTZAN development 280 and already-used validation 87, plus twelve fresh
constructed inputs from four parent groups. These are not 499 independent songs.
The vocabulary probe duplicates an existing constructed waveform across cohorts.
Reserved 98 GTZAN groups are not consumed. Formal enrollment remains governed by
`data/samples/catalog.json`; generated research inputs are not automatically enrolled.

Selection uses four deterministic development inputs per genre and ten variants
of constructed parent 5100. Real variable references, remaining development,
already-used validation and the twelve prospective constructed inputs are outside
selection. The fresh music remains from the existing analytic renderer family,
so it is not independent real-music generalization or perceptual certification.

## Pipeline

Use the retained CPU environment. Media, old observations and official final0 are
local data and are not distributed with source code. Each execution needs a new
run directory and, for `prospective`, a new canonical constructed corpus directory.
The recorded prospective corpus uses
`data/samples/generated/variable-clock-exploration-v1-20261008/`.

```sh
PY=.venv-metronome-v1/bin/python
RUN=data/research/runs/variable_clock_exploration_v1/NEW_RUN
$PY -m experiments.variable_clock_exploration_v1.prepare --run "$RUN" --stage build
$PY -m experiments.variable_clock_exploration_v1.prepare --run "$RUN" --stage features
$PY -m experiments.variable_clock_exploration_v1.run --run "$RUN" --stage calibration
$PY -m experiments.variable_clock_exploration_v1.evaluate --run "$RUN" --stage calibration
$PY -m experiments.variable_clock_exploration_v1.prepare --run "$RUN" --stage freeze
$PY -m experiments.variable_clock_exploration_v1.run --run "$RUN" --stage frozen
$PY -m experiments.variable_clock_exploration_v1.evaluate --run "$RUN" --stage frozen
```

The recorded execution added its phasor and abstention arms before real
prediction/scoring, preserving intermediate calibration files. Final selection
followed a completeness check. `prospective` creates the declared new parent
groups; `observations` independently replays official inference through a strict
source-only schema; `baseline` fits unchanged Original to those new inputs.
Recorded source-isolation controls reject reference fields and succeed with an
invalid evaluation sentinel. Preparation/controls are separate from inference
and evaluation. Re-running scripts is an experiment, never implicit in startup.
The commands above illustrate the initial core pipeline. Exact replay of the
completed comparison uses its saved protocol, selected configuration, source
index and source snapshot, which include the additional arms and admitted
prospective inputs. `onset` and `onset_report` run/evaluate the separate waveform
challenger; `stress` and `stress_predict` prepare and predict the supplementary
constant-BPM recordings. They do not change the original run's frozen indexes.

## Interpretation

- Native, octave-equivalent, nominal BPM, event timing and boundary metrics remain
  distinct. Change-count matches alone are not correct clock sequences.
- UNKNOWN consumes coverage/event recall. Missing, failed and short cases remain
  in denominators. A candidate found near a time does not establish full support.
- Real reference maps support practical owner agreement, without independent
  producer-clock millisecond precision. GTZAN is approximately fixed/coarse
  annotation evidence, not independently certified false producer changes.
- Circle retains its accepted 4/2 interpretation. BabySlakh Track00008 is encoded
  rate-only because source-clock/audio origin is unresolved.
- Phase transport is conditional on continuity inferred from source fits. Its
  errors and unresolved cases do not certify physical exactness.
- This is exploratory research, not an adopted recursive decoder, app model
  replacement, runtime validation or formal product acceptance threshold.
