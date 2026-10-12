# Metrical clock roles experiment

**Reference status, 2026-10-13:** this completed study was moved intact to the reference area. Historical commands and decisions below are evidence, not current defaults or new execution requests. See [reference index](../README.md) and [current development](../../docs/DEVELOPMENT.md).

Owner-authorized on 2026-10-11, after the initial tap tolerance changed from
5% to 3%. This is isolated research, with no app integration or source Git
publication. Prior frozen implementations, original audio and accepted maps
remain unchanged.

The new observation model separates a physical quarter clock from the neural
pulse role, an internal meter-length hypothesis and a neural downbeat observation
role. Missing alternating neural beats no longer penalize the physical quarter
clock as if every quarter were a missed observation. Raw beat logits supplement
event timing. Source-derived local bar-cycle coherence is a secondary factor;
it is not treated as a certified bar/meter observation. All hypotheses are
connected on original audio coordinates by an offline approximate beam search.
Weak evidence keeps the clock and its phase moving. True octave changes remain
available when the source observations support them.

Identical neural observations can arise from genuine tempo changes or from
simultaneous subdivision/meter changes. A paired authored observation control
exposes this ambiguity. The primary method prefers four-quarter initial bars
and persistent meter, with explicit frozen ablations; it does not prove that
audio uniquely specifies notation. Bar/meter states are internal hypotheses,
not a full time-signature-map result.

Initial tap proxies are 97%, 100% and 103% of the reference initial quarter rate.
After source candidates are prepared, an isolated encoder selects a discrete
source-relative unit relation and discards the numeric tap. Compound 3:2 unit
relations are a new declared research contract. They do not change the fixed
app estimator's octave-only contract. Only an eight-second source-defined
initial episode is constrained. These proxies are not measured human taps.

The frozen focus gate tests Underoath, Over It and Millions before broader
prediction. If it passes, all eleven variable songs, four meter-only controls,
six fixed controls and twenty-four inherited authored-music controls are used.
All are known material, not unseen evaluation. Separate metrics report nominal
unit errors, click F1, unsupported nominal-rate regions and matched rate-pair
boundary errors. The old study's strict criteria remain intact.

Use `.venv-metronome-v1/bin/python -m experiments.metrical_clock_roles_v1.MODULE`.
Stages: `prepare`, `observability` (reference-informed diagnostic), `controls`
(known-clock observation controls), `freeze`, `worker --stage prepare`, `encode`,
`worker --stage predict`, `evaluate --stage focus`, then optionally broad source
preparation/encoding/prediction and `evaluate --stage broad`, `audit`, `report`.
Each entrypoint takes `--run`. Preparation/prediction may be sharded, but the
reference encoder and evaluation remain separate. Actual data-read hooks reject
reference reads in the source worker; they are not an OS sandbox claim.

Methods/settings/decision criteria are frozen before target predictions. Full
source tables, latent contexts, serialized maps, code snapshots, reference
snapshots, sensor diagnostics, control failures and figures are retained locally
under `data/research/runs/metrical_clock_roles_v1/`.

Joint metrical inference is motivated by [BeatNet](https://arxiv.org/abs/2108.03576).
Raw beat/downbeat observations and caution about forced postprocessing are
motivated by [Beat This](https://arxiv.org/abs/2407.21658). This study uses retained
Beat This observations, not a BeatNet model, DBN replacement or new training.

## Recorded outcome

Run: `data/research/runs/metrical_clock_roles_v1/20261011T060446Z-v1/`.
Start with `interpretation.ko.md`. The frozen primary focus gate failed; no broader
predictions were run. Three known recordings were evaluated in twelve arms:
78 new serialized predictions plus six prior baselines, 84 scored comparisons.
With initial-unit assistance, correct-clock time changed from 96.97 to 75.44%
on Underoath, 59.20 to 33.76% on Over It, and 39.50 to 46.65% on Millions.
The three-song macro changed from 65.22 to 51.95%; click F1 from 90.21 to 83.96%.
The primary recovered zero of ten correct rate-pair boundaries within four seconds.

Reference-informed post-score diagnosis finds source-qualified correct-clock
states for 96.75/96.27/99.47% of the respective supports. Roles-only and wider
search improve some cases but do not solve Over It. No alternate arm was promoted
after scoring. This rejects this implementation, not every joint-meter method or
the physical piecewise-clock representation. Continue automatic research only
with a testable discriminator between actual tempo and observation-role changes;
more costs on the same neural events are not established as sufficient.
