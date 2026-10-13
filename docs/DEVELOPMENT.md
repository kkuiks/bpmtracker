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

## Completed AutoResearch and the next proposed experiment

The 2026-10-13 AutoResearch v2 campaign is closed. Its `trial006` candidate improves
the frozen **pinned-initial, held-meter** objective `(V,W)` from
`(0.16541267669858642, 0.16541267669858642)` to `(0.25, 0.25)`. One of four known
development songs has all three boundaries successful; the other three still
score zero. Successful boundaries increase from 2/17 to 3/17. The weighted
objective is not the fraction of successful boundaries.

The candidate and H7 fixed parent pass the separately frozen 16 known fixed
complete recordings and 10 original excerpts under that same input restriction.
The actual full L2 initial/meter integration fails fixed regression on four
materials, and its final variable comparator is incomplete. These results do not
replace the owner-selected L2 entry, authorize app integration, approve product
thresholds, or establish independent generalization. See
[`AUTORESEARCH.md`](AUTORESEARCH.md) for provenance, artifacts and limits.

The next proposed experiment is one generic ablation of the mismatch gate's
absolute **old-beat ceiling**. Retain the new-evidence floor, gain/mass rules and
H7 PCM veto. An observed legal candidate provides a local gate-failure witness;
neither later PCM admission nor full-path selection is established. Run the same
candidate on the entire frozen development cohort and retain fixed regression
requirements. A separate authorized campaign is needed; neither this proposal
nor the closed v2 session is an execution queue.

The earlier Circle roadmap is retained in `project-state.json` as
`historical_circle_roadmap`. Its original unrestricted L2 joint score of 63.08%
and 0/3 successful boundaries remain historical evidence. The later constrained
baseline and candidate use different input conditions. Do not overwrite or
substitute their scores. Keep declarations on existing beats without phase jumps,
and do not pass identities, reference times/rates or evaluation roles to inference.

## Evidence and comparison

| Evidence | Recorded location | Meaning |
| --- | --- | --- |
| L2 full comparison | `data/research/runs/beat_event_stability_v1/20261012-full-v2/` | 33 known recordings; fixed, variable and meter cases separate |
| Broader fixed verification | `data/research/runs/linear_validation_v1/20261012-frozen-L2-v1/` | 10 additional real excerpts, one formal synthetic, two auxiliaries and 98 feature-only groups; source types separate |
| Owner audition | `data/research/runs/native_listening_review_v1/20261012-L2-all-weak-v1/listen-projects/` | 21 separate reference/current pairs; 22 weak feature-only cases lack original audio |
| Fixed comparison | `experiments/metronome_reconstruction_v1/` and its original frozen runs | Fixed estimator remains a useful comparison and the DAW backend |
| Reorganization audit | `data/storage/20261013-repository-organization-v1/` | Whole-checkout inventory, original source snapshot, moves and static checks |
| Closed AutoResearch v1 | `data/research/runs/autoresearch_run_v1/20261013-session-v1/` | No primary adopted; H3/H4/H7 code and failed trials preserved |
| Closed AutoResearch v2 | `data/research/runs/autoresearch_run_v2/20261013-campaign-v2/` | Scoped primary; known regression pass, full L2 failed/incomplete |

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
