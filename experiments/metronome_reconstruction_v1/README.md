# Fixed-metronome reconstruction

This independent experiment recovers one constant quarter-note BPM, one constant
time signature, and one global downbeat offset relative to unchanged input audio.
The current interface accepts an approximate initial BPM tap only to choose a
metrical octave layer. Meter and precise BPM/phase remain inferred from audio.

The implementation does not import archived Joljak inference, weights or
observations. It uses fresh official Beat This 1.1.0 final0 evidence. Current
candidates are quarter BPM 30–400 with reduced rational denominator at most four,
and 3/4 or 4/4. Search is seeded and refined; exhaustive global optimality is not
guaranteed. Confidence flags are uncalibrated evidence diagnostics.

## Local environment and prediction

The recorded first-run environment is CPython 3.12, CPU float32 PyTorch
2.6.0+cpu/torchaudio 2.6.0+cpu, and four inference threads. The dependency lock
comes from that run's recorded environment; it is not a newly upgraded or
separately tested environment.

For a fresh local environment, install the CPU wheels and recorded packages:

```bash
python3 -m venv .venv-metronome-v1
.venv-metronome-v1/bin/pip install --index-url https://download.pytorch.org/whl/cpu \
  torch==2.6.0+cpu torchaudio==2.6.0+cpu
.venv-metronome-v1/bin/pip install \
  -r experiments/metronome_reconstruction_v1/requirements-cpu.lock
```

Provide an official local checkpoint separately; neither media nor model weights
are versioned. The CLI does not download a checkpoint automatically.

```bash
.venv-metronome-v1/bin/python -m experiments.metronome_reconstruction_v1.hinted \
  --audio input.wav --tap-bpm 155 \
  --checkpoint samples/.experiment-state/metronome-v1/final0.ckpt \
  --output proposal.json
```

Alternatively, `--evidence recording.npz` replaces `--audio`. The current evidence
format contains `beat_logits`, `downbeat_logits`, `fps` and `duration_seconds`;
frame rate must match the configuration. Omitting `--tap-bpm` selects from the
audio family without a unit hint. The quarter and downbeat event arrays in an
emitted map use seconds from original audio zero.

## Tap contract

`prepare_audio_family(evidence, config)` accepts no hint. It prepares the audio
base, admissible octave layers, rational neighbors, meter/offset proposals and
scores before `select_from_family(family, initial_quarter_bpm_tap)` is called.
The latter converts the approximate tap to an integer octave layer and selects
an already computed candidate. The raw tap cannot attract fine BPM, affect the
search neighborhood, set phase or supply meter. Same-layer hints must produce
identical entire predictions.

Insufficient acoustic evidence, an exact ambiguous octave boundary, or an
unsupported layer yields a non-map result. The initial hint's whole-recording
application depends on the constant-tempo assumption. Variable tempo and meter
changes are outside this implementation. [Tap design](design-tap-v2.json) and
[first-run design](design.json) define the contracts and limitations.

## Modules and preserved runs

| Module | Role |
| --- | --- |
| `extract.py` | Official fresh source-only logits and minimal official events |
| `grid.py`, `infer.py`, `run_fit.py` | Rational grids and first audio-only fitting |
| `hinted.py`, `hinted_run.py` | Audio family preparation and discrete initial-tap selection |
| `evaluate.py`, `benchmark.py`, `hinted_benchmark.py` | Accepted-event metrics after predictions are saved |
| `ablation.py` | Separate scoring ablation; preserves primary predictions |
| `controls.py`, `hinted_controls.py` | Explicitly scoped diagnostic controls |
| `build_listening.py`, `serve_listening.py`, `listening/` | Frozen-map listening page and exact-asset loopback server |

The source-only and separate evaluation manifests live locally in
`samples/selections/fixed-metronome-v1/`. Existing run folders are
`samples/experiments/metronome_reconstruction_v1/20261005-first26-v1/` and
`20261005-tap26-v2/` under the same parent. The cohort is the same 26 valid samples
throughout. Complete/excerpt/synthetic/auxiliary roles retain provenance while
sharing one denominator. Reference events already contain the approved
audio-relative offset; they must not receive a second shift or extrapolation.

Inputs, outputs, media, checkpoints, evidence, reports and snapshots stay local.
Preserve the existing run folders. Runner output directories must be new; do
not replace a frozen run to incorporate later interpretation or score changes.
Reference-derived tap inputs are a correct-unit diagnostic, not actual human
taps or fully automatic performance. Current public result summaries are in the
root [README](../../README.md).

## Listening page

The existing latest page manifest is `listening-bottom5/` inside the tap run.
The server uses only the Python standard library:

```bash
python3 -m experiments.metronome_reconstruction_v1.serve_listening \
  --root samples/experiments/metronome_reconstruction_v1/20261005-tap26-v2/listening-bottom5 \
  --port 8997
```

Open `http://localhost:8997/`; forward the port for a remote workspace. The server
binds to loopback and serves only the selected files. It does not expose account
state or source directories. Original audio is decoded one selected song at a
time. Music and synthesized saved-event clicks share a Web Audio sample clock,
start time, seek position and loop boundaries. Click changes are playback only.

To prepare a listening manifest for another saved run when requested:

```bash
.venv-metronome-v1/bin/python -m experiments.metronome_reconstruction_v1.build_listening \
  --run samples/experiments/metronome_reconstruction_v1/20261005-tap26-v2 \
  --samples-root samples --condition tap_only --count 5
```

The builder ranks recorded `max(quarter_max_error_ms, bar_max_error_ms)` in
descending order. It copies saved prediction events and consumes existing
accepted audio-relative reference events within their support. It runs no
inference or scoring. Reference clicks remain absent outside support.

Controls, benchmarks, integrity scans and browser checks are opt-in. Do not run
them automatically while installing, documenting, committing or resuming work.
