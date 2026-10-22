# Beat-event map stability research

**Current role:** measured L2_DENSE_PROPOSALS search, scoring and configuration, exposed through [algorithms/variable](../../algorithms/README.md). The measurements below retain their original cohorts and source versions; current evaluation is summarized in [development status](../../docs/DEVELOPMENT.md).

The latest isolated research candidate is G21; its results and the planned
next step, broad observation-to-tempo-map data expansion, are maintained in
[AutoResearch](../../docs/AUTORESEARCH.md) and [development status](../../docs/DEVELOPMENT.md).
This module retains its dated L2 evidence; it is not a G21 large-corpus result.

Recorded focus, 2026-10-12: improve ordinary fixed-song joint pulse/bar
validity and prevent unnecessary map changes within the current variable design.
This module keeps adaptive evidence, old-beat declarations, one initial phase,
partial-bar signatures, ±3% initial unit-only taps, and uninterrupted clicks.
It does not force a constant map, select a method by reference role, change
accepted readings, or replace app inference.

The parent is `beat_event_map_v1/20261012-full-v4`. Its common fixed12 excluding
Red Miso scores 98.6838% pulse and 90.8222% joint stable validity; remaining common
failures are Neck Deep and Waiting Room. The expanded fixed set also includes
an In Flames bar error. These are known development cases, not unseen evidence.

L1 uses symmetric downbeat/grid F1 rather than a predominantly one-way observed
downbeat explanation. PCM uses a quarter period independent of signature, so
3/4 versus 6/8 relabelling does not earn a subdivision-density bonus. L2 adds a
source-only density requirement for tempo-proposal pulse runs: at least 0.8 of
their expected ticks must have observations. This reuses the existing initial
qualification level. It is a hypothesis to test, not a certified threshold.
Initial candidates and all other search budgets/gates retain the parent rules.

Freeze pilot and final comparisons before inference. Report all unsuccessful
controls, fixed/variable/meter groups, strict tempo changes, prior good-song
regressions, and native listening cases. Do not count a fixed-song improvement
as success if it merely blocks real changes. Keep reference-informed diagnostics
outside source workers. Proposed or failed variants are not app defaults.

The completed primary run is
`data/research/runs/beat_event_stability_v1/20261012-full-v2/` (L2, all 33 known
recordings). Fixed12 joint stable validity improves 90.8222% to 99.0185%; all ten
previously perfect scores remain perfect, and Neck Deep recovers to 100%.
Waiting Room still declares 190 BPM after source 171.174 seconds. Expanded fixed16
excluding Red Miso improves 91.2734% to 99.0532%; In Flames retains an unnecessary
initial-rate correction. Whole-source unscored tails are not certified by these
scores; Tommy Walker has a new 279-BPM declaration after its approved support.

Variable10 joint validity rises 26.7254% to 44.0071%, but pulse accuracy falls
69.5587% to 65.9480%, and strict canonical tempo transitions fall 5/33 to 1/33.
This is a fixed-song recovery result, not successful general variable adoption.
All 99 maps pass the contract, 66 same-unit comparisons are identical, and 16
synthetic controls pass. Four native pairs include recovery, remaining fixed
errors and Deadman's variable regression. All eight projects and 6,468 clicks
pass actual renderer/worklet checks; Windows audible playback remains untested.
The Korean report and listening guide are in the completed run.
