# Local half/double clock correction confirmation

**Reference status, 2026-10-13:** this completed study was moved intact to the reference area. Historical commands and decisions below are evidence, not current defaults or new execution requests. See [reference index](../README.md) and [current development](../../docs/DEVELOPMENT.md).

Owner-requested component confirmation on 2026-10-11. This experiment reuses the
immutable M3 physical clock bank, evidence tables, phase candidates and complete
source-derived maps for all 21 real recordings from the region-composition run.
It does not modify the app, accepted references, raw audio or prior frozen code.

The intervention is applied in chronological map order. When a new raw rate,
divided by 2 or 0.5, lies within 5% of the previously selected rate, prefer an
existing source-supported clock at that folded rate. Its phase must be nested
with the raw clock; source quality and prior phase continuity rank the retained
alternatives. When no such candidate is supported, hold the previous source clock
and phase. Non-octave ratios are unchanged. Initial units are not global numeric
BPM targets, and the local selected rate may evolve outside the initial band.

Compare unchanged maps, octave veto with hold, primary folding at 5%, and fixed
3%/8% sensitivity arms. Initial reference-derived 97/100/103% proxies are separately
encoded and must equal the cached source map's discrete input exactly. These are
conditional diagnostics, not collected human tapping performance.

The default assumes near-2x/0.5x transitions are changed counting. It includes no
independent detector of genuine octave changes. Juno and authored ambiguity
counterexamples remain visible, as do unavailable folded clocks, wrong phase,
incorrect initial units and imperfect inherited boundaries. This is a component
probe on known material, not a replacement full selector or unseen-song proof.

Run stages with `.venv-metronome-v1/bin/python -m
experiments.octave_fold_confirmation_v1.MODULE --run RUN`: `prepare`, `controls`,
`freeze`, `encode`, `worker`, `audit`, `evaluate`, `report`. Source-only read hooks,
same-unit checks, unchanged-source hashes and retained-clock/interval contracts
are part of this requested confirmation. No new neural inference, model training,
installation, acquisition, playback server or source Git publication is included.

Settings and criteria live in `common.py` and are frozen before new target scores.
Outputs are under `data/research/runs/octave_fold_confirmation_v1/`; begin with
`interpretation.ko.md` and `report.ko.md` after completion.

## Recorded outcome

Run: `data/research/runs/octave_fold_confirmation_v1/20261011T083547Z-v1/`.
The prespecified component criteria passed on known material. With initial-unit
assistance, 11-variable-song correct-clock time increased from 65.64% to 72.19%;
half/double error time fell from 14.64% to 6.54% (55.34% relative reduction).
Click F1 rose from 83.91% to 85.14%. Veto-only recovered 67.27% correct time and
reduced F1 to 80.86%, supporting actual folded clock/phase selection over merely
holding the previous value. All source clocks and interval edges were unchanged.

Four variable songs improved, six were unchanged and Juno regressed. Millions
rose from 39.50% to 98.02%, preserving 240/250/240; Over It rose from 59.20% to
78.18%. The 21 small-change post-context exact-rate average rose from 44.14% to
63.67%. The strict inherited transition criterion remained 0/34.

Universal-loss criteria failed: genuine Juno 108/216 post-change correct-clock
time fell from 27.55% to zero; incorrect first-clock retention also harmed
Common Sense. Without initial-unit assistance, variable correct time regressed
53.85% to 44.35%. Primary mean gain without Millions was only 1.35 percentage
points. Keep component benefit, starting-clock reliability, genuine-octave
exceptions and boundary recovery separate. No app/default adoption occurred.

All 252 outputs, 191 input hashes, 42 baseline semantic comparisons, 42 same-unit
comparisons and source-clock/boundary preservation checks passed. Six PNG/SVG
figures and complete current-reference snapshots are retained. No post-score
Python/configuration changes, extra model inference, media/reference edits or
source Git mutations were made.
