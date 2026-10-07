# Automatic fixed-metronome benchmark

Read a prepared dataset, qualify reference capabilities, run the
frozen fixed-metronome estimator, and produce JSON, CSV and an HTML report.
BabySlakh supplies encoded MIDI clocks; GTZAN supplies public features and
coarse beat annotations. Both paths require no per-recording listening, manual offset selection or
post-prediction reference correction.

Additional source-only methods compare the same constant BPM, 3/4 or 4/4,
and global downbeat-offset output. A paired generated-music corpus measures
defined sample-clock phase and drift, separately from real-annotation agreement.

## BabySlakh reference scope

BabySlakh v2 contains the first 20 Slakh tracks as 16 kHz WAV mixtures and stems,
with source MIDI and metadata. It is synthetic development material, not an
independent real-recording test set. The input archive is approximately 883 MB.
See the [official release](https://zenodo.org/records/4603870).

Reference parsing uses the encoded source-MIDI clock. Repeated identical tempo
and signature declarations are collapsed; effective changes exclude a recording
from the fixed-condition cohort. Implicit MIDI defaults are recorded separately.
A missing initial signature is not promoted to a 4/4 annotation.

The adapter checks paired stem WAV/MIDI files and mixture/stem consistency.
BabySlakh's metadata bookkeeping flags can disagree with files present in the
release; availability therefore follows observed paired assets. Original and
rendered-stem clock maps must agree within the configured tolerance.

Encoded BPM and explicitly declared meter support comparisons with the source
representation. These declarations do not independently establish a unique
musical interpretation or an original producer metronome. In particular, a
stored 120 BPM value can be an encoding choice; a prediction mismatch alone
does not prove that the inferred musical tempo is wrong.

The adapter does **not** establish an independent source-clock-to-audio origin.
Consequently, absolute-phase accuracy remains unscored. Source tick zero
projected to audio zero is a separate, explicitly conditional diagnostic; no
reference is shifted to improve agreement. Mixture/stem matching does not verify
the MIDI/audio origin.

## Dependencies

Use the existing [CPU estimator environment](../metronome_reconstruction_v1/README.md#environment)
and a local official final0 checkpoint. Install the two reference-processing
dependencies into a separate local directory:

```sh
.venv-metronome-v1/bin/python -m pip install --no-deps \
  --target samples/.benchmark-state/babyslakh-v1/python-deps \
  -r experiments/metronome_benchmark_v1/requirements.txt
```

The inference worker imports the existing estimator and configuration without
changing model packages, weights or numerical parameters.

## Complete candidate diagnostics

`run_gtzan --role development --limit 0 --trace` evaluates every development
feature group with the frozen estimator. Tracing preserves every tested clock,
score component, phase seed, refinement seed and retained candidate in compressed
JSONL. It wraps and restores the original functions; it does not change their
return values. Original inputs, source snapshots and predictions remain separate
from later comparisons.

```sh
PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.decompose \
  --run samples/experiments/metronome_benchmark_v1/FROZEN_RUN \
  --previous samples/experiments/metronome_benchmark_v1/PILOT_RUN \
  --output samples/experiments/metronome_benchmark_v1/ANALYSIS_RUN
```

Decomposition records vocabulary error, compatible candidates in the broad
search and final family, audio-score ranks and gaps, bar grouping and downbeat
evidence. Annotation-best candidates are explicitly reference-informed oracle
diagnostics; they never replace primary predictions. Cause remains unresolved
where model evidence and annotation interpretation cannot be adjudicated.

## Methods with the same output

`simple_clock` fits event-index lines with a robust loss, quantizes BPM to the
same rational vocabulary, and scores 3/4 or 4/4 bar phases against source events.
Its period seeds come from observed intervals; octave hypotheses, phases and
scores are prepared before hints. It uses no spectral search or original
multi-term clock objective. Configuration is frozen in `simple-clock-v1.json`.

`retained_clock` changes only candidate retention. All clocks already tested by
the original broad search and family search compete in discrete unit groups,
with their original scores unchanged. It requires a complete source-only trace.
It adds no genre-specific rule or reference-derived tempo multiplier.

Both methods separate `prepare` from `select`. A tap is encoded by the original
discrete octave rule; its number cannot affect fine BPM, phase or score. The
default estimator is not replaced by these comparison entry points.

```sh
PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.simple_clock prepare \
  --source samples/experiments/metronome_benchmark_v1/FROZEN_RUN/source-inputs.json \
  --evidence samples/experiments/metronome_benchmark_v1/FROZEN_RUN/evidence \
  --model-config samples/experiments/metronome_benchmark_v1/FROZEN_RUN/model-config.json \
  --output samples/experiments/metronome_benchmark_v1/SIMPLE_RUN

PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.simple_clock select \
  --source samples/experiments/metronome_benchmark_v1/FROZEN_RUN/source-inputs.json \
  --evidence samples/experiments/metronome_benchmark_v1/FROZEN_RUN/evidence \
  --model-config samples/experiments/metronome_benchmark_v1/FROZEN_RUN/model-config.json \
  --output samples/experiments/metronome_benchmark_v1/SIMPLE_RUN \
  --hints samples/experiments/metronome_benchmark_v1/FROZEN_RUN/unit-hints.json

PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.retained_clock prepare \
  --run samples/experiments/metronome_benchmark_v1/FROZEN_RUN \
  --output samples/experiments/metronome_benchmark_v1/RETAINED_RUN

PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.retained_clock select \
  --run samples/experiments/metronome_benchmark_v1/FROZEN_RUN \
  --output samples/experiments/metronome_benchmark_v1/RETAINED_RUN \
  --hints samples/experiments/metronome_benchmark_v1/FROZEN_RUN/unit-hints.json
```

`compare_models --run FROZEN_RUN --model simple=SIMPLE_RUN --model
retained=RETAINED_RUN --output COMPARISON_RUN` scores additional predictions
against the unchanged annotation protocol. Original conditions stay in the
comparison. Missing predictions remain in the denominator.

## Defined sample-clock music controls

`generated_controls --output CORPUS_ROOT` creates deterministic analytic
drum/bass/chord music. Eight short compositions each have seven paired variants:
straight, weak downbeat, syncopated, half-time, double-time, dropout and leading
shift. Two additional long compositions probe drift, for 58 inputs from ten
parent groups. These are controlled synthetic inputs, not 58 independent songs.

Transport markers and actual music-event placement use the declared sample
coordinates. A separate marker WAV is read against the rational transport and
excluded from every model input. The coordinate bound is one frame at 32 kHz
(0.03125 ms); it does not establish a real recording's producer clock or a
unique perceptual interpretation. Ideal reference events are generated without
the estimator's grid helper. There is no latency-changing audio postprocessing.

The long 120.1 BPM input is a predefined output-vocabulary probe. Its denominator
ten cannot be represented by the current maximum denominator four. Precision
counts on representable clocks keep a separate denominator of 57. All 58 inputs
remain in event and failure summaries.

Use the source-only `inference prepare/select` worker on the corpus manifest,
then compare methods with `score_generated --corpus CORPUS_ROOT --model-config
CONFIG --method frozen=FROZEN_RUN --method simple=SIMPLE_RUN --output
RESULTS_RUN`. `replay_clock` can reproduce full traces from cached observations
without repeating neural inference. `runtime_compare` measures the two clock
fitters on deterministic source IDs with neural inference and tracing excluded.

Focused controls for tracing, decomposition, simple fitting, candidate retention,
generated coordinates and precision scoring are separate `controls_*` modules.
Their results establish implementation contracts, not real-audio accuracy.

## Acquire the pilot inputs

From the repository root:

```sh
python3 -m experiments.metronome_benchmark_v1.acquire \
  --root samples/external/babyslakh-v2
```

The downloader checks the published archive fingerprint and resumes incomplete
transfers. Extraction retains mixtures, stems, original and stem MIDIs, and
metadata. Paths and sizes are bounded. Existing extracted files are compared
with their archive members rather than replaced with different contents.

The downloaded archive and extracted inputs remain local. The pilot uses about
2.7 GB for these source materials, before small inference and report caches.

## Run automatic evaluation

```sh
PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.run \
  --data-root samples/external/babyslakh-v2/inputs \
  --output samples/experiments/metronome_benchmark_v1/RUN_ID
```

The output directory must be new. `--prepare-only` records qualification,
references, source-only inputs and source snapshots without inference.
`--resume` continues an incomplete prepared run with unchanged model sources
and configuration; completed result directories cannot be resumed.

Qualification runs before predictions. All recordings remain in the input
catalog, with exclusions and source errors recorded. Eligible inference failures
and abstentions stay in the scored denominator. Parent identities are recorded
for future grouping of duplicates and transformations; all pilot recordings
have the development role.

Two conditions share the same acoustic observations:

- **Audio only:** the current estimator selects from audio-derived candidates.
- **Correct-unit diagnostic:** the encoded reference BPM selects a discrete
  layer after every audio family has been prepared. It supplies neither meter
  nor event times/offsets and does not attract precise BPM to the hint.

Inference runs in a separate source-only worker with CPU float32 and four
threads. Its manifest rejects reference fields. Each prediction is saved before
reference scoring. No neural training or parameter tuning is performed.

## Metrics and outputs

`report.html`, `results.json`, `results.csv` and `summary.json` contain the same
qualification and condition results. The run also stores reference records,
source-only inputs, logits, audio families, predictions, configuration and
source snapshots.

- Encoded BPM absolute/relative error at declared tolerances.
- Nearest allowed rational BPM agreement as a display-only nominal diagnostic;
  original reference values are retained for numerical errors and events.
- Meter agreement only for explicitly annotated signatures.
- Half/double and other rate disagreements, failures, abstentions and warnings.
- BPM-implied drift over input duration, distinct from observed alignment drift.
- Conditional source-zero event and clock comparisons, kept outside
  independently verified absolute-phase accuracy.

## Recorded pilot

The 2026-10-06 pilot catalogued 20 recordings. Eleven fixed-clock recordings
qualified for encoded BPM comparison, eight of which had an explicit initial
signature. Nine recordings were outside scope because of effective tempo/meter
changes or clock incompatibility. All eleven qualified parent groups were
distinct. Their complete mixtures totalled approximately 43.84 minutes.

| Condition | Nominal BPM | BPM relative error ≤0.1% | Explicit encoded meter |
| --- | ---: | ---: | ---: |
| Audio only | 9/11 | 9/11 | 8/8 |
| Correct-unit diagnostic | 9/11 | 9/11 | 8/8 |

All eight meter references are 4/4; these results do not establish 3/4 audio
performance. No inference failed or abstained. Both encoded-rate disagreements
carried warning flags and remained in the denominator. They were not simple
half/double errors, and discrete unit assistance did not resolve them.

The stored disagreements were Track00009 (120 encoded BPM versus 76.6667
automatic / 153.3333 unit-assisted) and Track00020 (120 versus 178.5 / 89.25).
Their source MIDIs had no explicit initial meter. That association is an
observation, not a measured cause or evidence for replacing their source clocks.

Absolute audio-origin qualification was zero, so independently verified phase
accuracy was not measured. The report includes conditional origin diagnostics.
This pilot demonstrates an automated execution path and agreement with stored
MIDI declarations, not complete-map accuracy or real-world generalization.

The preserved local output is
`samples/experiments/metronome_benchmark_v1/20261006-babyslakh-pilot-v1/`.
An earlier preparation-only attempt relied on stale metadata flags and is
retained separately. Source files and the two original 26-sample runs remain
unchanged; the new dataset is not enrolled into their catalog or denominator.

A fresh 2026-10-07 execution reproduced every saved prediction and the complete
summary on the same 20-recording catalog. It is preserved at
`samples/experiments/metronome_benchmark_v1/20261007-babyslakh-baseline-v1/`.
The execution review checked source/reference separation, preserved denominators
and reporting before the first public-feature corpus expansion.

## Focused controls

```sh
PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.controls \
  --output samples/.benchmark-state/babyslakh-v1/controls.json
```

The 28 parser and metric cases use independently encoded SMF fixtures and known
arithmetic: duplicate declarations, piecewise time, missing defaults, source
pairing, variable-clock exclusion, event matching capacity, retained drift,
bar-group differences, unverified phase, abstention denominators and source-only
input rejection. These controls establish their contracts, not audio accuracy.

## GTZAN public-feature evaluation

The [official feature release](https://zenodo.org/records/13922116) supplies a
306.9 MB GTZAN archive and a matching v1.0 annotation snapshot. The acquired
bundle contains **999 original clip features**, not newly downloaded audio.
They are 128-band log-mel spectrograms at 50 frames per second, stored as float16.
The worker converts them to float32 and uses the official `Spect2Frames` entry
point with the same final0 checkpoint and unchanged reconstruction parameters.
The [model documentation](https://github.com/CPJKU/beat_this#available-models)
states that GTZAN is excluded from final0's training data.

The adapter parses the original audio-aligned beat annotations. It fits every
annotated pulse by ordinary least squares solely to decide whether the clip is
close enough to a constant clock for this experiment. Admission requires a
95th-percentile absolute residual of at most 30 ms and a maximum of at most
70 ms. It requires a supported 3- or 4-pulse bar cycle where bar positions are
present. Every timestamp stays unchanged, without outlier removal or a
prediction-dependent shift. A timestamp outside feature coverage is a source
error, not an invitation to repair its label.

The fitted pulse rate is an annotation-based BPM comparison. Annotated pulses
per bar support a grouping comparison; they do not independently establish
the notation denominator or a producer's quarter-note interpretation. Primary
beat/downbeat scores use one-to-one F1 at 70 ms, with 20/30 ms diagnostics and
both macro and micro aggregation. They measure agreement with existing coarse
annotations, not original-metronome millisecond precision.

Exact feature identities stay in the same deterministically assigned role:
development, validation or reserved, using hash ranges of 60%, 20% and 20%.
The pilot takes up to 100 development groups, rotating across genre and
annotated bar-pulse-count strata. It includes one representative per exact
feature group. These rules precede predictions; inference failures and
abstentions remain in the selected denominator with zero event F1.

Exact equality does not establish all recording/artist relationships in GTZAN.
The reserved role therefore is not a final independent locked test. Validation
and reserved inputs are outside the first development inference manifest.

### Acquire and run

```sh
python3 -m experiments.metronome_benchmark_v1.acquire_gtzan \
  --root samples/external/gtzan-beat-this-v1

PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.run_gtzan \
  --data-root samples/external/gtzan-beat-this-v1/inputs \
  --output samples/experiments/metronome_benchmark_v1/RUN_ID \
  --role development --limit 100
```

`--prepare-only` writes references, source-only inputs, roles, selection and
source snapshots. Outputs must use a new directory. `--limit 0` selects the
complete chosen role; `--role validation` selects that separate role. The
runner has no option to evaluate reserved material. Acquisition retains both
published archives and extracted features/annotations, about 699 MB in total.

Three conditions share acoustic observations:

- The unchanged constant-clock model with audio-derived selection.
- Its reference-derived discrete-unit diagnostic, after every family is ready.
- Official Beat This minimal postprocessing, returning variable beat/downbeat
  events. This event baseline has a different output target from a constant map.

The feature manifest allows only source identity, bundle/key, frame geometry,
frame rate and duration. Reference times, bar counts, phases and fitted rates
cannot enter its inference worker. The separate unit-selection stage reads only
the diagnostic tap after source inference completes.

### Focused feature controls

```sh
PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.controls_gtzan \
  --output samples/.benchmark-state/gtzan-v1/controls.json
```

The 16 cases cover known pulse arithmetic, retained timestamps, coarse-reference
limits, 3-pulse grouping, missing bar labels, variable clock/cycle rejection,
unsupported bar counts, duplicate timestamps, event scoring, failure
denominators, annotation-field rejection, duplicate feature grouping and
reserved-role separation. They do not establish musical accuracy.

### Recorded GTZAN development pilot

The 2026-10-07 run catalogued all 999 supplied original features. Of these,
472 met the declared fixed-pulse approximation, 526 were outside scope, and
one had an annotation beyond feature coverage. That error remains recorded:
`gtzan_reggae_00002` ends its annotations at 30.117 seconds against a
30.020-second feature interval. Its original labels were retained.

The qualified roles contain 285 development, 87 validation and 100 reserved
entries. The selected development pilot contains 100 distinct exact feature
groups across ten genres: 96 with 4-pulse and four with 3-pulse bars. Its
feature coverage totals 50.07 minutes. Source observation extraction and clock
fitting took 672.87 seconds in the four-thread CPU worker, excluding
startup, qualification, unit selection and scoring.

| Condition · same selected 100 | Pulse BPM error ≤2% | Bar-pulse count agreement | Beat macro F1 @70 ms | Downbeat macro F1 @70 ms |
| --- | ---: | ---: | ---: | ---: |
| Automatic constant clock | 88/100 | 96/100 | 92.09% | 83.17% |
| Reference-unit diagnostic | 95/100 | 97/100 | 93.65% | 84.04% |
| Beat This minimal events | — | — | 92.26% | 83.26% |

Automatic and minimal-event conditions returned predictions for all 100 inputs.
The unit diagnostic returned 99 clocks and abstained on
`gtzan_country_00097` because the requested layer was unavailable in its audio
family. That input remains in all diagnostic denominators, with zero event F1.
No worker invocation or source inference failed.

Automatic pulse-rate disagreements comprise six half-rate, one double-rate
and five other-rate cases. One wrong-rate automatic result had no warning.
Warning absence therefore does not certify correctness. In seven automatic
cases, beat F1 at 70 ms was 1 while downbeat F1 was 0, despite agreement on
bar-pulse count. Unit selection did not resolve all grouping/alignment
disagreements with the annotations.

Automatic event F1 was similar to the minimal-event baseline on this selected
corpus. These measurements do not establish an event-accuracy improvement
from constant-clock reconstruction. Its output contract remains a fixed
metronome, whereas the baseline returns an unconstrained event sequence.

The completed output is
`samples/experiments/metronome_benchmark_v1/20261007-gtzan-development100-v1/`.
All 18 execution-contract review checks passed. The original references,
protocol, role selection, predictions and source snapshots remain together in
that run. No new neural training or reconstruction parameter tuning was used.

## Review a completed execution

```sh
PYTHONPATH=samples/.benchmark-state/babyslakh-v1/python-deps \
  .venv-metronome-v1/bin/python -m experiments.metronome_benchmark_v1.review \
  --run samples/experiments/metronome_benchmark_v1/RUN_ID \
  --output samples/.benchmark-state/RUN_ID-review.json
```

The review reconciles the catalog, selected source-only inputs, worker receipt,
condition denominators and report artifacts. It checks the separation of
reference/hint reads and unsupported precision claims, and GTZAN's role/group
selection. `--comparison PREVIOUS_RUN` additionally compares complete summaries
and saved predictions for a repeat of the same cohort. Existing reports and
predictions are read without modification; the review output must be new.

`execution_path_passed` describes an operational evaluation path. Model
accuracy is reported separately. Source errors stay recorded, and neither
adapter provides a verified original producer clock.

## Recorded expansion and method comparison

The 2026-10-07 frozen expansion evaluated all **280 development feature groups**
without changing the original estimator, configuration or qualification rule.
The original 100 inputs reproduced every prediction in all three conditions.
Their automatic beat/downbeat F1@70ms remained 92.09%/83.17%; the additional
180 inputs scored 96.96%/89.84%. The complete 280 scored 95.22%/87.46%.
This cohort change is not a model improvement. The original pilot contained all
four 3-pulse development inputs; the added inputs all have 4-pulse bars.

Automatic rate disagreements were 15 half-rate, eight double-rate and five
other-rate cases. Of those 28, 24 had compatible rates already tested in the
final family; four lacked a compatible final-family rate, including two with
compatible rates in the original broad search. Seventeen inputs had beat F1=1
and downbeat F1=0 at 70ms: disco one, hiphop three and reggae thirteen.
These are descriptive counts on this subset, not genre-wide error rates.
Annotation interpretation and sensor/model causes remain unresolved where
independent evidence is unavailable.

The three fixed-clock methods share the same source observations and reference
protocol. Configuration and model sources were frozen before the first use of
the **87 validation groups**; no parameters were retuned from validation.
Validation has only 4-pulse bars. The **98 reserved groups remain uninferred**.

| Method and condition | Development BPM ≤2% | Development beat/downbeat F1@70ms | Validation BPM ≤2% | Validation beat/downbeat F1@70ms |
| --- | ---: | ---: | ---: | ---: |
| Original automatic | 252/280 | 95.22% / 87.46% | 77/87 | 95.50% / 85.35% |
| Simple automatic | 253/280 | 95.40% / 87.59% | 77/87 | 95.32% / 85.64% |
| Retained-candidate automatic | 252/280 | 95.22% / 87.46% | 77/87 | 95.50% / 85.35% |
| Original unit diagnostic | 275/280 | 97.31% / 88.86% | 84/87 | 97.10% / 85.99% |
| Simple unit diagnostic | 277/280 | 97.95% / 88.65% | 86/87 | 98.39% / 86.24% |
| Retained-candidate unit diagnostic | 276/280 | 97.54% / 88.86% | 84/87 | 97.10% / 85.99% |

Original and retained-candidate unit diagnostics abstained once in each cohort;
simple diagnostics returned all clocks. Every condition preserves its selected
denominator. Validation bar-pulse agreement is 84/87 for every automatic method,
84/87 for the original/retained unit diagnostics and 83/87 for the simple unit
diagnostic. At 20ms, automatic validation beat/downbeat F1 is 73.10%/66.41% for
the original and 74.76%/68.03% for the simple method. These are coarse-annotation
diagnostics, not certified producer timing.

The generated corpus contains **58 inputs from ten parent compositions**,
including 48 paired contrasts. All conditions returned 58 clocks. The predefined
120.1 BPM vocabulary probe remains in the full denominator; representable-clock
precision uses 57 inputs.

| Method and condition | BPM error ≤0.1% | Declared meter | Quarter and bar maximum error ≤20ms |
| --- | ---: | ---: | ---: |
| Original automatic | 37/58 | 32/58 | 21/57 |
| Simple automatic | 37/58 | 36/58 | 26/57 |
| Original unit diagnostic | 55/58 | 34/58 | 30/57 |
| Simple unit diagnostic | 54/58 | 44/58 | 38/57 |

Retained-candidate results match the original in these controls. Both original
conditions preserved BPM/meter across all eight leading-shift pairs. The simple
automatic method changed meter in one pair; its unit diagnostic changed meter
in two. The simple method's higher aggregate precision therefore does not
establish uniformly better stability. The long representable 128.5 BPM control
had maximum quarter errors of 2.82ms original versus 1.12ms simple, without rate
drift. The 120.1 BPM unit diagnostics both returned 120 BPM and accumulated about
214ms of drift. The existing denominator-four output domain was not relaxed.

On ten deterministic source-ID selections, clock-fitting median time was
3.888s original versus 0.033s simple. These paired measurements exclude neural
inference, evidence preprocessing and tracing; they are not end-to-end speedups.
All timed predictions reproduced saved coordinates. The simpler method is a
promising comparison implementation, but mixed accuracy and shift-stability
results leave the application's default estimator unchanged.

Warning flags remain uncalibrated. In development, ten of 28 original automatic
rate disagreements had no warning; eighteen of 49 inputs below the separate
diagnostic requirement of beat and downbeat F1 both ≥0.9 also had no warning.
A flagged BPM match can still have a phase error and is not necessarily a false
warning. Flags are not per-song accuracy probabilities.

The 56 new focused contract/metric controls passed. Frozen development and
validation execution reviews each passed 18 checks. Replaying all 58 generated
inputs from cached observations with complete tracing reproduced original
clock/event coordinates. Workflow passes remain separate from musical accuracy.

### Cohorts and preserved denominators

The full GTZAN catalog retains 999 rows: 472 qualified, 526 outside the declared
fixed-clock approximation and one source error. Qualified rows form 465 exact
feature groups. Roles were assigned before predictions, with one representative
per selected feature group:

| Role | Qualified rows | Exact feature groups | Inferred in this checkpoint |
| --- | --- | --- | --- |
| Development | 285 | 280 | 280 |
| Validation | 87 | 87 | 87 |
| Reserved | 100 | 98 | 0 |

Four development groups have three-pulse bars; the other 276 have four-pulse
bars. Validation has 87 four-pulse groups. Group counts describe exact feature
identity, not verified independent songs or artists. No eligible inference
failure or abstention is removed from event or BPM denominators.

The unchanged original automatic condition has these partitioned results:

| Partition | Pulse BPM ≤2% | Half rate | Double rate | Other rate | Beat F1@70ms | Downbeat F1@70ms |
| --- | --- | --- | --- | --- | --- | --- |
| Original 100 | 88/100 | 6 | 1 | 5 | 92.09% | 83.17% |
| Additional 180 | 164/180 | 9 | 7 | 0 | 96.96% | 89.84% |
| Full 280 | 252/280 | 15 | 8 | 5 | 95.22% | 87.46% |

### Recorded rate and timing diagnostics

The following tables retain every method and condition. BPM columns compare
the unchanged fitted annotation pulse rate; bar agreement compares annotated
pulses per bar. Event scores are macro F1 percentages at the stated tolerance,
not complete-song success rates or independent producer-clock accuracy. Micro
F1 and its event counts remain in each comparison's `results.json` and
`summary.json` alongside per-input predictions and metrics.

#### Development — 280 groups

| Method/condition | BPM ≤0.1% | BPM ≤1% | BPM ≤2% | Pulses/bar | Failed/abstained |
| --- | --- | --- | --- | --- | --- |
| Original automatic | 217/280 | 252/280 | 252/280 | 276/280 | 0 |
| Original unit diagnostic | 236/280 | 275/280 | 275/280 | 277/280 | 1 |
| Minimal events | — | — | — | — | 0 |
| Simple automatic | 223/280 | 252/280 | 253/280 | 277/280 | 0 |
| Simple unit diagnostic | 242/280 | 276/280 | 277/280 | 278/280 | 0 |
| Retained automatic | 217/280 | 252/280 | 252/280 | 276/280 | 0 |
| Retained unit diagnostic | 236/280 | 276/280 | 276/280 | 277/280 | 1 |

| Method/condition | Beat 20ms | Beat 30ms | Beat 70ms | Downbeat 20ms | Downbeat 30ms | Downbeat 70ms |
| --- | --- | --- | --- | --- | --- | --- |
| Original automatic | 78.08% | 90.60% | 95.22% | 72.52% | 83.48% | 87.46% |
| Original unit diagnostic | 79.85% | 92.55% | 97.31% | 73.53% | 84.73% | 88.86% |
| Minimal events | 78.19% | 90.69% | 95.18% | 70.04% | 82.63% | 87.30% |
| Simple automatic | 77.88% | 90.43% | 95.40% | 72.23% | 83.31% | 87.59% |
| Simple unit diagnostic | 79.97% | 92.85% | 97.95% | 73.21% | 84.42% | 88.65% |
| Retained automatic | 78.08% | 90.60% | 95.22% | 72.52% | 83.48% | 87.46% |
| Retained unit diagnostic | 80.04% | 92.85% | 97.54% | 73.63% | 84.88% | 88.86% |

#### Validation — 87 groups

| Method/condition | BPM ≤0.1% | BPM ≤1% | BPM ≤2% | Pulses/bar | Failed/abstained |
| --- | --- | --- | --- | --- | --- |
| Original automatic | 69/87 | 77/87 | 77/87 | 84/87 | 0 |
| Original unit diagnostic | 76/87 | 84/87 | 84/87 | 84/87 | 1 |
| Minimal events | — | — | — | — | 0 |
| Simple automatic | 69/87 | 77/87 | 77/87 | 84/87 | 0 |
| Simple unit diagnostic | 76/87 | 86/87 | 86/87 | 83/87 | 0 |
| Retained automatic | 69/87 | 77/87 | 77/87 | 84/87 | 0 |
| Retained unit diagnostic | 76/87 | 84/87 | 84/87 | 84/87 | 1 |

| Method/condition | Beat 20ms | Beat 30ms | Beat 70ms | Downbeat 20ms | Downbeat 30ms | Downbeat 70ms |
| --- | --- | --- | --- | --- | --- | --- |
| Original automatic | 73.10% | 89.24% | 95.50% | 66.41% | 80.07% | 85.35% |
| Original unit diagnostic | 74.64% | 91.39% | 97.10% | 67.03% | 81.01% | 85.99% |
| Minimal events | 74.44% | 89.96% | 95.03% | 66.46% | 82.00% | 86.80% |
| Simple automatic | 74.76% | 90.37% | 95.32% | 68.03% | 81.01% | 85.64% |
| Simple unit diagnostic | 76.03% | 92.61% | 98.39% | 68.19% | 81.54% | 86.24% |
| Retained automatic | 73.10% | 89.24% | 95.50% | 66.41% | 80.07% | 85.35% |
| Retained unit diagnostic | 74.64% | 91.39% | 97.10% | 67.03% | 81.01% | 85.99% |

Original/retained unit diagnostics abstain on `gtzan_country_00097` in development
and `gtzan_country_00091` in validation because the encoded unit is absent from
the prepared audio family. Both remain in the respective denominators, with
zero event F1. Simple conditions have no failed or abstained clocks.

Predictor sources and settings were frozen at `2026-10-07T02:49:00.856229+00:00` before
the first validation observation. Source correspondence was recorded in
`samples/.benchmark-state/gtzan-v1/20261007-validation-method-freeze.json` and the
completed execution review; validation did not trigger another parameter change.

### Generated event scores and paired contrasts

Generated event F1 retains all 58 inputs, including the predeclared 120.1 BPM
probe. The 57-input precision subset was defined by output representability,
without correcting a reference or discarding a poor prediction. All 58 inputs
return clocks in every condition. Retained-candidate scores equal the original.

| Method/condition | Quarter 10ms | Quarter 20ms | Quarter 30ms | Quarter 70ms | Downbeat 20ms | Downbeat 70ms |
| --- | --- | --- | --- | --- | --- | --- |
| Original automatic | 83.12% | 84.74% | 85.03% | 85.03% | 61.18% | 61.46% |
| Original unit diagnostic | 90.31% | 91.17% | 91.62% | 92.76% | 63.47% | 65.28% |
| Simple automatic | 81.25% | 81.88% | 82.55% | 84.84% | 66.23% | 68.06% |
| Simple unit diagnostic | 90.08% | 90.79% | 91.36% | 93.41% | 73.30% | 75.19% |

Joint quarter/bar maximum-error counts on the 57 representable inputs are the
same at 10, 20, 30 and 70ms: original automatic 21, original unit diagnostic 30,
simple automatic 26 and simple unit diagnostic 38. These thresholds remain
diagnostics rather than a specified product acceptance criterion.

| Variant | Representable inputs | Original automatic ≤20ms | Simple automatic ≤20ms | Original unit ≤20ms | Simple unit ≤20ms |
| --- | --- | --- | --- | --- | --- |
| double_time | 8 | 3 | 4 | 4 | 6 |
| dropout | 8 | 4 | 4 | 5 | 7 |
| half_time | 8 | 4 | 4 | 6 | 6 |
| leading_shift | 8 | 3 | 4 | 4 | 5 |
| straight | 9 | 4 | 6 | 5 | 7 |
| syncopated | 8 | 0 | 0 | 2 | 2 |
| weak_downbeat | 8 | 3 | 4 | 4 | 5 |

The `straight` row includes both long inputs: ten full inputs but nine
representable clocks. Other variants each have eight inputs. The 48 comparisons
share composition and declared transport; arrangement edits can also change
noise-voice realizations. Only `leading_shift` is an exact waveform translation.
It adds 317ms while retaining the source-relative transport relation.

The simple unit diagnostic switches from 3/4 to 4/4 between
`control00_straight`/`control00_leading_shift` (60 BPM) and
`control02_straight`/`control02_leading_shift` (120 BPM). Its automatic condition
changes meter only in the latter pair. A changed BPM/meter is not credited as
phase invariance. The original and retained methods preserve rate/meter in all
eight shift pairs; corresponding phase movement residuals are a few milliseconds.

### Reliability and execution evidence

Original automatic development predictions have the following warning table:

| Reference agreement diagnostic | No warning | Warning |
| --- | --- | --- |
| Pulse BPM ≤2% | 169 | 83 |
| Pulse BPM >2% | 10 | 18 |
| Beat and downbeat F1@70ms both ≥0.9 | 161 | 70 |
| Either event F1@70ms <0.9 | 18 | 31 |

These cells do not calibrate a correctness probability. A pulse-rate match can
still have a bar-phase error. The event cutoff 0.9 is a decomposition diagnostic,
not a product pass rule.

Recorded focused controls are trace 16, decomposition 7, simple fitting 11,
generated coordinates 7, generated scoring/pairing 8 and candidate retention 7:
56 cases passed. Earlier parser/metric 28 and GTZAN qualification 16 controls
are separate evidence. Frozen development and validation execution reviews
each passed 18 checks. The final cross-run review passed 18 source-freeze,
cohort, denominator, origin and replay checks. The 58 traced cache replays
reproduce the original clock/event coordinates. These records certify execution
contracts, not musical accuracy or DAW runtime behavior.

Recorded reference/configuration inputs, raw predictions and earlier comparison
versions remain preserved. New neural training, waveform-decoder evaluation
for GTZAN, application integration, a new DAW audit and inference on the 98
reserved groups are absent from this checkpoint.

Preserved local outputs under `samples/experiments/metronome_benchmark_v1/`:

- `20261007-gtzan-development280-frozen-v1/`: unchanged predictions and complete traces.
- `20261007-gtzan-development280-analysis-v1/`: 100/180/280 partitions and oracle-labeled decomposition.
- `20261007-gtzan-development280-comparison-v2/`: same-output method comparison.
- `20261007-generated58-comparison-v2/`: defined-clock precision and paired contrasts.
- `20261007-gtzan-validation87-frozen-v1/`: first separate-role evaluation.
- `20261007-gtzan-validation87-comparison-v1/`: frozen-method validation comparison.

Generated inputs and verification records are in
`samples/external/generated-clock-contrast-v1/`. Existing samples, reference
coordinates and previous runs were preserved. No neural training was performed.
