# Current development standard

The owner selected **L2_DENSE_PROPOSALS** as the variable-tempo development
baseline on **2026-10-13**, after directly listening to the available weak cases.
Use [`project-state.json`](../project-state.json) as the compact status authority
and [`algorithms/variable`](../algorithms/README.md) as the maintained entry point.
The measured fitter/configuration remains unchanged in
[`beat_event_stability_v1`](../experiments/beat_event_stability_v1/README.md).

The new standard means subsequent changes are compared with this actual result,
while preserving its current practical fixed-song quality. It does not turn
predictions into accepted truth, certify broad generalization, or deploy variable
inference into the DAW. The earlier approximately-99% fixed verification target
is dated experimental evidence, not a continuing veto on this owner-selected
development baseline. Keep all its scores and failures intact.

## Next objective

The primary goal is **Circle With Me**. Its accepted map has three small tempo
changes, 205→210→205→210 quarter BPM, with unchanged 4/2 meter. The current L2
result gets the opening right, misses all three transition boundaries, then
changes late and incorrectly declares 2/4. Its 63.08% joint score comes from the
opening; it is not evidence of successful variable tracking.

First distinguish missing source candidates from candidates rejected by search
or the mismatch gate. This diagnosis and any following improvement are planned,
not executed by the repository reorganization. Keep real changes on existing
beats, without phase jumps. Compare small changes in Underoath and Over It as
well, and retain ordinary fixed-song listening controls. Do not introduce song
names, accepted transition times, reference BPM, or reference roles into inference.

## Evidence and comparison

| Evidence | Recorded location | Meaning |
| --- | --- | --- |
| L2 full comparison | `data/research/runs/beat_event_stability_v1/20261012-full-v2/` | 33 known recordings; fixed, variable and meter cases separate |
| Broader fixed verification | `data/research/runs/linear_validation_v1/20261012-frozen-L2-v1/` | 10 additional real excerpts, one formal synthetic, two auxiliaries and 98 feature-only groups; source types separate |
| Owner audition | `data/research/runs/native_listening_review_v1/20261012-L2-all-weak-v1/listen-projects/` | 21 separate reference/current pairs; 22 weak feature-only cases lack original audio |
| Fixed comparison | `experiments/metronome_reconstruction_v1/` and its original frozen runs | Fixed estimator remains a useful comparison and the DAW backend |
| Reorganization audit | `data/storage/20261013-repository-organization-v1/` | Whole-checkout inventory, original source snapshot, moves and static checks |

The 98 feature groups have now been consumed in development. They are not an
untouched holdout for a changed candidate. Source-only inference, evaluation,
oracle diagnostics, full-song metrics and owner listening retain separate roles.
Sample membership and accepted references come from `data/samples/catalog.json`.

## Code and working rules

Read the [code map](CODE_MAP.md) before choosing a file to edit. The measured
baseline imports shared search/geometry/scoring helpers from earlier modules;
their old names do not make them unused. Unneeded prior studies are available in
[`reference/`](../reference/README.md). Their historical import names are retained
by the explicit `experiments` package search path, rather than duplicate source
trees or filesystem aliases. Recorded freezes are never rewritten after a move.

For a new experiment, use a new run, freeze its source/config/input selection
before inference, retain failures in denominators and export actual evaluated
maps as separate native `.joljak` files when waveform audio exists. Do not create
extra click audio tracks for owner audition. Keep the ±3% initial tap limited to
discrete unit selection, with candidates prepared before the tap.

The app remains Windows-first with an English UI. Start it through
[`Start Joljak.cmd`](../Start%20Joljak.cmd); 0.6.15 repairs the original-rate versus
48 kHz cache metadata mismatch on reopening. Audio speed, originals and map
placement are preserved. See the [app guide](../apps/daw/README.md).

Source commits/pushes remain owner-operated. Do not start experiments, runtime
tests, acquisition or deployment just because a current plan names them. Private
project notes live through `_local`; their current guide controls only note
management and authorized private publication.
