# AutoResearch development handoff — 2026-10-13

The v2 campaign is closed. `trial006` is a research candidate for **the same
source-fitted initial map with held meter**. Its `(V,W)` improves from
`(0.16541267669858642, 0.16541267669858642)` to `(0.25, 0.25)`. Successful boundaries
increase from 2/17 to 3/17. The candidate and H7 pass known fixed/excerpt regression
under that contract. Actual full L2 integration regresses four materials and is
incomplete on the last baseline comparator. The owner-selected L2 entry and the
fixed DAW analyzer remain unchanged.

This is a documentation handoff, not permission to resume a finished campaign,
run its unexecuted proposal, replace the app or approve numerical thresholds.

## Evidence authorities and history

[`project-state.json`](../project-state.json) is the compact current pointer.
The private topic document `_local/docs/VARIABLE_CLOCK_EXPLORATION.md` contains
recording-specific diagnosis and the detailed durable research history. Raw
outputs, references, clocks and execution ledgers remain in local private data.
A public source clone alone does not contain the recordings or observation caches.

The local evidence roots, relative to the checkout, are:

| Stage | Root | Disposition |
| --- | --- | --- |
| PC preflight | `data/research/runs/autoresearch_step_v1/20261013-preparation-v1` | Source/initial/evaluator preparation and three separate comparators |
| First campaign | `data/research/runs/autoresearch_run_v1/20261013-session-v1` | No primary adopted; 11 actual trials plus one lock refusal counted as 12 attempts |
| v1 bridge | `data/research/runs/autoresearch_run_v1/20261013-bridge-v1` | Original candidate adapter and protocol preserved |
| Second campaign (`C` below) | `data/research/runs/autoresearch_run_v2/20261013-campaign-v2` | 12 submissions, scoped primary, two auxiliary roles, all failures retained |
| Supplied v2 package | `data/research/preflight/autoresearch-next-20261013-v02/package/BPMTracker_AutoResearch_Next_2026-10-13` | `program.md`, `runtime/README.md`, immutable harness/workers and package manifest |

The packages did not contain original music or observations. The PC reused its
existing immutable NN/PCM arrays; it did not run a new network forward pass,
retrain a model, extract replacement features or requalify references.
Source-code provenance is recorded against checkout HEAD
`55da3fc07fb8e1e42714c589dc208d6ad956f4f7`. Documentation written later is not part
of that algorithm snapshot.

## Comparison and output contract

Keep these three comparators distinct:

1. `HISTORICAL_L2_UNMODIFIED`: the preserved full L2 output with its original
   initial/meter selection policy.
2. `PINNED_INITIAL_HELD_METER_L2`: newly run with the same initial BPM, meter,
   phase and source duration as every candidate. This is the direct comparator.
3. `PINNED_INITIAL_CONSTANT_MAP`: the same initial map held for the entire audio.

The historical Circle 63.08% joint map quality and 0/3 boundary success are not
the later pinned/held baseline's 99.51% map quality and 2/3 boundary success.
Input conditions differ. Never replace the direct comparator with the older
score or silently treat the candidate as a new unrestricted L2 standard.

The initial maps come from the preserved source-fitted L2 `proxy100` outputs.
This work fixes those maps; it does not measure a fresh, fully automatic,
without-tap initial estimator. A proxy label is not a literal 100 BPM tap.
Wrong initial estimates remain in the four-song/17-boundary denominator.

Inference receives only `initial`, `duration_seconds` and `data`; `data` contains
`events_path` and `prepared_source_path`. Reference clocks, transitions/counts,
evaluation roles, song IDs and filename-based target dispatch are forbidden.
Inference and scoring use separate processes. Preserve the full original audio
map, legal old-beat declarations, continuous quarter coordinates and one initial
phase. Meter is held in the main research condition. The separate full L2
integration test does not lift this condition for candidate selection.

Objective v0.2 defines acceptable quality C, preferred quality P and timely
localized success L. V averages `C × L` over post-change regions within each song,
then averages songs equally; W does the same with `P × L`. Compare `(V,W)`
lexicographically. Partial coverage with L=0 is diagnostic. Missing/failed outputs
remain failures in the frozen denominator. Different candidates' best songs
cannot be combined into one result.

The owner's R1–R6 readings remain in force: R1 alternatives are equal; R2/R3
allow both but prefer A; R4/R5/R6 allow only A. R3 covers regular 4/4→2/4 splitting
on the same ordinary beat, not arbitrary multiples or a phase error. A bar-late
change and unnecessary notation changes are not successes.

Numerical tolerances, fixed loss 0 and runtime 2× were frozen **development**
conditions, with `owner_approved_numerics=false`. Preserve the output evaluator
and protected native tolerances; changing an internal inference gate is a
different operation from changing the output success threshold.

## What the candidate implements

The selected code is `C/session/trials/trial006/candidate/`, including:

| File | Responsibility |
| --- | --- |
| `candidate_api.py` | Read the anonymous immutable packet and return one native map |
| `candidate_common.py`, `parameters.json` | Snapshot-local configuration |
| `candidate_core.py` | Source proposals, legal phase transport and bounded path selection |
| `candidate_emissions.py` | Pointwise weighted observation log costs and prefix sums |
| `candidate_scoring.py` | Existing source explanation and symmetric bar/PCM gate components |
| `candidate_base_scoring.py` | Revalidated H7 mismatch/PCM gate |

The path state retains BPM, meter, anchor time/quarter, bar quarter, phase, start
and declaration count. Only identical future states are merged by completed
prefix cost. Constant-tail completion is a queue-order heuristic, rather than a
requirement that every intermediate short episode improve the final map.
Nonpositive future emissions and transition costs give a prefix upper bound.
The chosen 12-expansion/128-queue/24-declaration budgets still make traversal
approximate. The implementation is not exhaustive Viterbi or a proven optimum.

Pulse explanations are latent observation roles rather than output tempo events.
The channels/roles form a weighted composite likelihood; calibrated statistical
independence is not established. This first retained emission model does not
penalize every empty expected tick. Its limitations became visible when a larger
source vocabulary produced an unsupported dense tempo path. Preserve this
counterexample before extending the source bank.

No active algorithm entry or DAW worker imports this snapshot automatically.
Do not copy it into a frozen old implementation to bypass its guard.

## Executed experiments and causal findings

| v2 trial | Change | Result | V=W |
| --- | --- | --- | ---: |
| 001 | Original H7 fixed recovery | Fixed auxiliary preserved | 0.165413 |
| 002 | Original H4 source unit interpretations | Coverage auxiliary preserved | 0.165413 |
| 003 | Original H3 internal time-kernel/speed variant | Unsafe coverage; rejected | 0.165413 |
| 004 | H4+H7 combination | No new primary/archive gain | 0.165413 |
| 005 | Pointwise costs plus phase-state decoder, 36 expansions | Runtime overflow; five outputs failed | 0.250000* |
| 006 | Same decoder bounded to 12 expansions | Primary retained | 0.250000 |
| 007 | Source-family diversity at final run retention | Fixed bad declarations increased | 0.165413 |
| 008 | Source retention plus selected decoder | Main tie; coverage side effects | 0.250000 |
| 009 | New emissions inside original beam | Combination improvement absent | 0.165413 |
| 010 | New phase decoder with legacy interval cost | Combination improvement absent | 0.165413 |
| 011 | Symmetric expected-bar costs with new source bank | No additional main gain | 0.250000 |
| 012 | Same costs with original source bank | No additional main gain | 0.250000 |

`*` Trial005 is FAILED and ineligible despite its partial variable score. All
ten denominator slots, missing fixed outputs and runtime overflow were retained.

The original search had already constructed a fully successful continuous path
for the song improved by trial006. The winner cost/path selection preferred a
different map. Component ablations 004/006/009/010 support the combined cost and
path change in this known cohort; they do not prove necessity on unseen music.

Baseline stage diagnosis across 17 boundaries: raw-clock retention 6, unit
filter 3, ranking 1, path selection 1, invalid visited prefix 4, successful winner
2. Final primary: raw-clock retention 6, unit filter 1, ranking 1, gate 1, invalid
visited prefix 5, successful winner 3. A prefix failure is conditional on visited
paths, not a proof of global impossibility under pinned initialization.

Neutral raw-run replay recovered qualified clocks before final512 retention.
The unchanged generator's live-run48 limit remains bounded. Source retention
restored four of the six affected regions but did not produce further timely
success. Probe04 has a partially truncated trace; absence after truncation is
unknown. Probe05 completely reproduced the final candidate's ten meaning maps.

H7 and H4 are useful parents with different roles, not two adopted primary
candidates. H3's three alternating baseline/candidate pairs are a non-admitting
timing diagnostic: median ratio 0.760312, with primary coverage regression.
The primary's alternating-pair median ratio is 0.967261; it passes the 2× limit
but fails separate speed-archive admission. No significance claim was made.

## Verification scopes and failures

| Verification | Observed result |
| --- | --- |
| Pinned/held baseline, 10 inputs × 3 repeats | Identical status/initial/events/full duration and objective; median 37.901077 s |
| Primary development | V/W=0.25; frozen fixed pilot and 2× runtime requirements pass |
| Known held-map regression, primary and H7 | All fixed16/excerpt10 retain per-song C/P and bad-change requirements |
| Known complete group | C .987435→.990532; P .924935→.928032; bad changes 3→2 |
| Known excerpt group | C=P=1; bad changes 0, unchanged |
| First full L2 bridge | Literal100 unit-policy mistake; only6/26 historical baselines match; preserved invalid attempt |
| Corrected full L2 bridge | Existing source unit recovered from prepared candidates;26/26 historical fixed/excerpt baseline maps match |
| Candidate with full initial/meter competition | Four fixed/excerpt materials regress; complete group C .990532→.899083 and bad changes2→3 |
| Final full L2 comparator | 29/30 pairs complete; last baseline hits20-minute cap and remains failure/0 in denominator |
| Fresh-run preparation baseline | One neutral10-input reproduction; three standalone matched-preparation timing repeats incomplete |
| Independent holdout / Windows listening / approved numerics | Not verified / not performed / not approved |

Full L2 means actual original initial-head and meter-proposal competition in a
research copy, not a held-map output wrapper. The corrected bridge selects the
existing discrete source unit by matching the already frozen initial candidate;
it does not read a reference or use that BPM as a fine fitting target. Preserve
both bridge attempts and their separate outputs. The missing baseline makes a
complete full-L2 variable comparison ineligible; its aggregate is not a gain claim.

The raw-clock-generation variants were discarded. Their fresh preparation costs
are included on the candidate side, but the three-repeat matched fresh baseline
timing control was not completed. The retained primary and parents use the
original frozen prepared bank, so this limitation does not certify or invalidate
their separately matched timing scope.

## Budget and preservation

The campaign used 12/24 submissions, 5/6 probes and two timing candidates
(rejected H3 diagnostic plus the primary), each with three alternating pairs.
Checkpoint files follow trials6 and12. Block2 produced new causal evidence but no
main/auxiliary gain; closure was a finite evidence-based decision, not the rule
for two consecutive blocks without any progress/evidence.

Whole clock elapsed147.486 minutes, without reset. Formal setup closure was
211 seconds late although setup artifacts sealed within15 minutes. Validation
inference stopped automatically at20 minutes; formal phase closure was30 seconds
late. These recorded stage-limit overruns are disclosed, not converted to passes.
The first full-L2 bridge mistake consumed validation time before correction.

Preserve all frozen runs, references, audio, clocks, observations and source
snapshots. The campaign performed no source commit/push, publication or app
replacement. Later documentation maintenance does not rewrite that evidence or
its 3,113-file artifact manifest. The independent backup checkpoint predates this
campaign; do not assume these later artifacts have already been published/backed up.

## Proposed next single experiment

A legal candidate with valid local before/after output readings reaches the
mismatch gate. Its old beat score .5897 exceeds the old .55 ceiling while the
new score .8217 has gain+.2320; the new bar score .5304 fails the separate .65
floor. This is a witnessed local rejection. Later PCM veto and winner selection
are unknown.

The proposal removes only `ob <= CONFIG['gate_old_ceiling']` from the pulse-gate
conjunction in the copied `candidate_base_scoring.py`. Keep the accent gate's
old-bar ceiling, new floors, gains, masses, H7 PCM veto, budgets and evaluator.
Raising the shared parameter would also change the bar branch and is not this
single ablation. Target evidence is evaluator-side only; no song identity or
accepted time/rate is put in inference.

A new authorized campaign would freeze one generic candidate, run one neutral
probe and the entire development cohort, and check known fixed regression if
eligible. Do not substitute a per-song best result, finish the old campaign by
resetting its clock, or promote the old scoped candidate into the app.

## Re-entry and artifacts

Start by reading `C/campaign-status.json`, `report.ko.md`, `resume.md`,
`verification-limitations.json` and `next-one-experiment.json`. Then follow:

- Protocol, seal and validation plan: `session/protocol.json`, `session/seal.json`,
  `validation-plan.json`, `validation-inputs.json`.
- Attempts/code/cards: `session/attempts.json`, `session/results.tsv`,
  `session/trials/`, `cards/`, `lineage.json`, `source-code-lineage.json`.
- Boundary diagnosis: `diagnosis.reviewed.json`, `diagnosis.primary.reviewed.json`,
  both boundary TSVs, `boundary-comparison.tsv`, stage-evidence JSON and traces.
- Timing: `session/controls/summary.json`, `supplemental-benchmarks/trial003/`,
  `session/benchmarks/trial006/`, `cli-logs/commands.jsonl`.
- Regression and mistakes: `validation/known/`, `validation/l2/`,
  `validation/l2-corrected-unit/`, `search-closure-clarification.json`.
- Checks/checkpoints: `checks/`, `checkpoints/`, `session/checkpoints/`.
- Listening/reproduction: `listen-guide.ko.md`, `listen-projects/manifest.json`,
  `reproduce.md`. There are56 separate native projects; playback is unverified.

These are read-only status commands; they do not start inference:

```bash
cd /home/yooch/code/joljak
C=data/research/runs/autoresearch_run_v2/20261013-campaign-v2
python3 tools/repository/status.py
python3 "$C/invoke.py" harness status
python3 "$C/invoke.py" clock status
```

The historical worker commands in `reproduce.md` require a separately authorized
reproduction and fresh output destinations. Never rerun `init/start/trial/probe`
against the closed ledger or alter its frozen inputs to make an old replay pass.
