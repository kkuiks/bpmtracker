# Automatic fixed-metronome benchmark

Read a prepared dataset, qualify reference capabilities, run the
unchanged fixed-metronome estimator, and produce JSON, CSV and an HTML report.
BabySlakh supplies encoded MIDI clocks; GTZAN supplies public features and
coarse beat annotations. Both paths require no per-recording listening, manual offset selection or
post-prediction reference correction.

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
