# Fixed-metronome reconstruction

Estimate one constant quarter-note BPM, one constant time signature and one global downbeat offset from audio. Beat This supplies beat/downbeat observations; the estimator fits an ideal metronome grid across the input.

The current domain is **30–400 quarter BPM**, using integers or reduced fractions with denominator at most four, and **3/4 or 4/4**. Tempo ramps, tempo changes and meter changes are outside this model. Candidate search uses spectral seeds, phase folding and refinement; exhaustive global optimality is not guaranteed. Confidence flags describe uncalibrated evidence diagnostics.

An optional initial approximate quarter-BPM tap selects a metrical octave layer. Precise BPM, meter and phase are inferred from audio. There is no time-signature input.

## Environment

The recorded environment uses CPython 3.12, CPU float32 PyTorch/torchaudio 2.6.0+cpu, Beat This 1.1.0 with the official final0 checkpoint, and four inference threads. `requirements-cpu.lock` records that environment.

```sh
python3 -m venv .venv-metronome-v1
.venv-metronome-v1/bin/pip install --index-url https://download.pytorch.org/whl/cpu \
  torch==2.6.0+cpu torchaudio==2.6.0+cpu
.venv-metronome-v1/bin/pip install \
  -r experiments/metronome_reconstruction_v1/requirements-cpu.lock
```

Provide a local [official checkpoint](https://github.com/CPJKU/beat_this#available-models). Media and weights are not distributed with this repository, and the prediction CLI does not download weights automatically.

## Predict a clock

Run from the repository root:

```sh
.venv-metronome-v1/bin/python -m experiments.metronome_reconstruction_v1.hinted \
  --audio input.wav --tap-bpm 155 \
  --checkpoint samples/.experiment-state/metronome-v1/final0.ckpt \
  --output proposal.json
```

Omit `--tap-bpm` for automatic selection. `--evidence recording.npz` can replace `--audio`; it contains `beat_logits`, `downbeat_logits`, `fps` and `duration_seconds`. Its frame rate must match the configuration.

The result includes BPM, its rational representation, time signature, period, downbeat offset, scores, diagnostics and click timestamps. Times are seconds relative to original audio zero. The offset is a canonical downbeat position modulo one bar; original DAW bar numbering is not inferred.

Insufficient acoustic evidence, an exact octave boundary or an unsupported tap layer produces a result without a clock. A returned clock is a proposal, and an absent confidence flag is not a correctness guarantee.

## Tap behavior

`prepare_audio_family(evidence, config)` receives no hint. It computes the audio base, octave layers, rational neighbors, meter/phase candidates and scores. `select_from_family(family, initial_quarter_bpm_tap)` then converts the tap to an integer power-of-two layer and chooses an existing candidate.

The continuous tap value is discarded after layer selection. It cannot set precise BPM, center a search neighborhood, change scores, anchor phase or supply meter. Same-layer hints produce identical complete predictions. The neighborhood width depends on audio duration and the audio base.

The tap refers to the initial section. Using that layer throughout the input relies on the constant-tempo assumption. [Tap specification](design-tap-v2.json) and [automatic-fit specification](design.json) describe the search, objective and evaluation conditions.

## Modules

| Module | Purpose |
| --- | --- |
| `extract.py` | Source-only Beat This logits and official baseline events |
| `grid.py`, `infer.py`, `run_fit.py` | Rational grids, automatic candidate fitting and batch prediction |
| `hinted.py`, `hinted_run.py` | Audio-family preparation and discrete tap selection |
| `evaluate.py`, `benchmark.py`, `hinted_benchmark.py` | Reference comparison and reports after prediction |
| `ablation.py` | Scoring ablation kept separate from primary predictions |
| `controls.py`, `hinted_controls.py` | Synthetic, metric and tap-contract controls |
| `build_listening.py`, `serve_listening.py`, `listening/` | Saved-map listening page and loopback asset server |

## Recorded experiments

The fixed-condition cohort has 26 samples: 13 complete recordings, ten original-recording excerpts, two synthetic recordings and one GuitarSet auxiliary recording. Its meters are 24 instances of 4/4 and two of 3/4. Every sample contributes to one common denominator, including failed predictions.

The automatic run has 19/26 nominal BPM matches and 26/26 stored meter matches. A reference-derived correct-unit diagnostic has 26/26 nominal BPM and meter matches, with quarter and bar maximum errors both within 20 ms for 24/26 and 30 ms for 25/26. The [root result summary](../../README.md#실험-결과) gives the conditions and remaining errors.

Reference-derived taps test correct-unit assistance; they are not measured human taps or automatic performance. The cohort is known development material. References preserve their recording origins, supported intervals and alignment limits; they are not independently certified original-click timing. Nominal BPM agreement is distinct from exact equality to stored reference values.

Original audio, manifests, observations, reports and run snapshots are local data, absent from a source-only checkout. For a checkout with these materials, the layout is:

```text
samples/selections/fixed-metronome-v1/
  all-valid-inference.json       source inputs only
  all-valid-evaluation.json      references and supported intervals
samples/experiments/metronome_reconstruction_v1/
  20261005-first26-v1/            automatic results
  20261005-tap26-v2/              unit-hint diagnostic and no-hint control
```

Prediction runners use new output directories and reject an existing run directory. Evaluation consumes stored audio-relative reference events within their supported intervals. It does not add another alignment offset or reconstruct references from original clocks. Ablations and diagnostics use separate outputs from primary runs.

## Listen to saved results

With a prepared local run, start the standard-library server:

```sh
python3 -m experiments.metronome_reconstruction_v1.serve_listening \
  --root samples/experiments/metronome_reconstruction_v1/20261005-tap26-v2/listening-bottom5 \
  --port 8997
```

Open `http://localhost:8997/`. Remote workspaces can forward port 8997. The server binds to loopback and serves only the selected recordings and page assets. Playback loads one recording at a time, with music and clicks on the same Web Audio clock. Predicted/reference switching, gain, seeking and looping change playback only.

To build a page from an existing saved run:

```sh
.venv-metronome-v1/bin/python -m experiments.metronome_reconstruction_v1.build_listening \
  --run samples/experiments/metronome_reconstruction_v1/20261005-tap26-v2 \
  --samples-root samples --condition tap_only --count 5
```

The builder ranks recorded `max(quarter_max_error_ms, bar_max_error_ms)` and copies saved prediction/reference events. It performs no inference or scoring. Reference clicks stop outside reference support. Recorded control results establish their specific contracts; they do not establish unseen-song accuracy.
