# Variable Tempo Expansion Step 0

An isolated prerequisite study for discrete, piecewise-stable baseline tempo
maps: rate proposals, oracle quarter-clock support, neighboring-clock boundaries
and fixed negative controls. It produces research diagnostics. Automatic
recursive reconstruction and application integration are outside this toolkit.

Original, final0, the denominator-four vocabulary, tap-only octave contract and
application adapter remain unchanged. Simple is a comparison/proposal method.
Primary real variable references have fixed 4/4. Circle With Me keeps 4/2 in
rate-only diagnostics; unresolved waveform origin precludes absolute boundaries.

## Recorded study

Local evidence is in
`samples/experiments/variable_tempo_step0/20261007-step0-v1/`. Media, reference maps,
weights and result directories are excluded from source distribution.

Thirty constructed inputs come from three parent compositions. Together with
three primary real recordings, two rate-only secondary inputs and the existing
120.1 BPM fixed probe, they form 36 Original inputs. Fixed feature controls retain
280 development and 87 already-used validation groups; reserved98 is unconsumed.

**Decision: DO NOT PROCEED TO STEP 1 YET.** Primary real nominal rates survived
broad scoring on 10/15 segment instances, but final narrowing on only 5/15.
Across ten recording/rate targets, final recovery was 3/10. Local rate unions
recover more hypotheses without certifying phase or valid support. Short support,
fixed false proposals and boundary ambiguity remain. Local `report.md`,
`report.ko.md` and `summary.json` preserve all conditions and denominators.

## Pipeline

1. Inventory references and capabilities before new predictions.
2. Generate same-composition step-tempo music. Independently verify transport
   coordinates; keep marker/click channels out of model inputs.
3. Freeze protocol, admission, source-only inputs and Original snapshots.
4. Run unchanged Original with complete tracing; then open evaluation references.
5. Characterize candidate loss. Study source-only local proposals in separate
   prediction/evaluation workers; window edges never become tempo changes.
6. Supply a rate/phase oracle and measure MATCH / MISMATCH / UNKNOWN. Separate
   phase contradiction from evidence for a different nominal rate.
7. Supply neighboring oracle clocks, localize on the original timeline and retain
   plateaus, frame sensitivity and misses. Source support can bracket comparison.
8. Check fixed negative controls and end at a decision gate.

## Environment and entry points

Use the existing [CPU estimator environment](../metronome_reconstruction_v1/README.md#environment)
and local official final0 checkpoint. Outputs must be new. Example setup:

```sh
.venv-metronome-v1/bin/python -m experiments.variable_tempo_step0.inventory \
  --output samples/experiments/variable_tempo_step0/NEW_RUN/inventory
.venv-metronome-v1/bin/python -m experiments.variable_tempo_step0.generated \
  --output samples/experiments/variable_tempo_step0/NEW_RUN/corpus
.venv-metronome-v1/bin/python -m experiments.variable_tempo_step0.prepare \
  --run samples/experiments/variable_tempo_step0/NEW_RUN
.venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.inference prepare \
  --source samples/experiments/variable_tempo_step0/NEW_RUN/source-inputs.json \
  --config samples/experiments/variable_tempo_step0/NEW_RUN/model-config.json \
  --checkpoint samples/.experiment-state/metronome-v1/final0.ckpt \
  --output samples/experiments/variable_tempo_step0/NEW_RUN/original --trace
.venv-metronome-v1/bin/python -m experiments.variable_tempo_step0.candidate \
  --run samples/experiments/variable_tempo_step0/NEW_RUN
```

Later modules expose stages through `--help`: `proposal`, `support`, `acoustic`,
`negative`, `boundary`, `report` and `review`. Run/configuration records identify
preserved comparison versions. Support calibration, prediction and evaluation
are separate; source/evaluation workers remain distinct. Review checks execution
contracts separately from musical accuracy.

## Interpretation

- Rates are separate from physical phase. The same BPM can recur with another
  phase. Candidate unions anywhere in a recording do not establish actual support.
- Oracle rates/phases are supplied information; their results are not automatic
  variable accuracy. Quarter support is not global bar-phase accuracy.
- Strong sensor peaks can occur in exactly zero audio. Strict waveform silence
  is an observability check, not general drumless-section detection. No GTZAN
  waveform is available for this check.
- Window and support lengths are sweeps, not adopted product minimum durations.
  Correlated 20ms frame rounding enters the local-rate uncertainty proxy, which
  is not a calibrated musical correctness probability.
- Support anchors bound a boundary objective. Their edges are not returned as
  changes. Phase-continuity estimates use supplied oracle phases and assume
  quarter-grid changes; preserve them separately from audio-only evidence.
- Precise constructed transport does not certify perceptual uniqueness or
  real-music generalization. Owner maps support practical agreement without
  independent millisecond certification. Every failure/miss remains recorded.
- A wholly wrong hypothesis suggests replacement, not necessarily an internal
  tempo change. UNKNOWN never means grid termination.

## Listen

```sh
python3 -m http.server 8998 --bind 127.0.0.1 \
  --directory samples/experiments/variable_tempo_step0/20261007-step0-v1/corpus
```

Open `http://localhost:8998/`, forwarding the port for remote workspaces. Music
and authored-click versions support plausibility checks. Listening does not tune
the estimator or replace programmatic transport ground truth.
