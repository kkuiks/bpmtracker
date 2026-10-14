# AutoResearch development handoff — updated 2026-10-14

The latest completed work is the isolated full L2 regression diagnosis below.
The owner-selected `L2_DENSE_PROPOSALS` entry and the fixed DAW analyzer remain
unchanged. The earlier v2 campaign remains closed with its original failed and
incomplete validation records.

## Full L2 regression diagnosis — 2026-10-14

`D = data/research/runs/full_l2_regression_diagnosis_v1/20261014-01a137fb-v1`.
This owner-authorized diagnosis completed 240 source-only cells, the full and
pinned/held known30 comparisons at 30/30 pairs each, the seven-material 56-cell
initial/meter factorial and 20 common-parent cost/decoder cells. It reproduced
all four full L2 regressions with the frozen v0.2/native evaluator and original
NN/PCM/prepared inputs. No new NN forward, reference change or app integration
was performed.

| Material | Full baseline C → trial006 C | Supported contribution |
| --- | --- | --- |
| Daybreak — Equilibrium | 1 → .776692 | Initial competition interacts with later meter support; new bar cost reverses the path ranking |
| Neck Deep — Can't Kick Up the Roots | 1 → .028302 | H4 admits the additional tempo-unit proposal; H4-only loses even under legacy cost/beam while H7-only preserves 1 |
| Maxime — Breathe Fire | .754027 → .716952 | New cost selects an earlier 2/4 declaration under either decoder; the baseline is already imperfect |
| In Flames — Meet Your Maker | .966295 → .698125 | Retained-root starvation and bootstrap retention; source-only scheduling/reserve interventions recover .989256/1 and repeat |

Original 119 valid held/full maps reproduce byte-for-byte, semantically, in
source scores and output metrics. The original BFMV corrected-bridge baseline
remains a `worker_failed/validation_phase_deadline` failure/0 stub. The separate
fresh baseline completes in 36.561s with C=.2536200088; candidate C=.3703378675.
The older measured full L2 maps also match 30/30. This does not retroactively
complete v2's 29/30 validation or reset its clock.

With the missing comparator closed, full variable4 mean C is .474392→.506003,
but V/W remain 0 on both methods. Full fixed complete16 mean C remains
.990532→.899083 with bad tempo declarations 2→3. The four per-material losses
still fail regression; comparison completeness is not algorithm admission.
Pinned/held V/W .1654126767→.25 and boundary success 2/17→3/17 also reproduce.

The finite common pool has 2,563 legal source-produced maps. Replacing only the
bar-cost term reverses Daybreak/Breathe Fire rankings in that pool; this is not
an executed hybrid predictor's full-cohort result. The scalar-phase restriction
leaves one complete initial head and does not independently prove a phase cause.
Root-first scheduling at the same 12 expansions does not fix the other cases,
and the one-slot whole-song constant-root reserve was tested only on In Flames.
Expected-tick omission versus aggregation/normalization remains partly
unresolved. Circle-centered development gains, full-scope regressions and new
music generalization are separate questions; overfitting is not established as
the direct cause of all four losses. Independent holdout, Windows listening and
owner-approved numerics remain unverified.

All 3,645 protected files and source/data Git indexes were preserved at diagnosis
completion. All 112 source traces were complete; cooperative Python audits found
no forbidden reference reads or live experiment imports. Eight native project
geometry roundtrips preserve C/P; Windows runtime playback is not verified.
The original campaign, measured baseline, accepted references and source clocks
remain untouched. Diagnostic copies inherit some held-core descriptive metadata;
actual I/M branches, unit policy, proposals and maps were checked separately.

| Evidence relative to `D` | Scope |
| --- | --- |
| `report.ko.md`, `status.json`, `execution-summary.json` | Owner report, completed/failed inventory, actual executions and limits |
| `protocol.json`, `inputs.json`, `provenance.json`, `input-provenance-supplement.json` | Frozen selection, source/reference boundary, geometry, unit policy and hashes |
| `comparison.tsv`, `factorial.tsv`, `branch-activation.tsv` | Known30 full/held and actual initial/meter branches |
| `score-comparison.tsv`, `component-ablation.tsv`, `search-comparison.tsv` | Same-map cost ranks, common H4+H7 controls and finite search interventions |
| `cases/`, `maps/`, `traces/`, `source-snapshots/`, `diffs/` | Case evidence, actual predictions, complete source traces and isolated code |
| `reproduction-parity.json`, `preservation-after.json`, `common-pool-audit.json` | 119 original map matches, preserved originals and legal/reference-separated common pools |
| `reproduce.md`, `sample-agent-handoff.md`, `next-research.md` | Actual commands, fresh output preparation, sampling conditions and proposed next campaign |
| `full-l2-diagnosis-20261014.zip`, `package-manifest.json`, `package-receipt.json` | Compact local delivery, omissions and SHA-256 |

The compact ZIP is 6,140,642 bytes (5.86 MiB), SHA-256
`6977ffaa50e2dad07cf11e46082a1ce7dc3599aa2567bfefbb4fff3b20086eda`.
It excludes original audio, large observations and the complete 2.3 GiB traces;
their required/retained paths and hashes remain in manifests. The report and ZIP
are local, not committed/uploaded to `joljak-data`. Only the private summary and
evidence paths were published in notes commit
`408c226f2c2dc481ccbf20a55e774c20658b3db8`; this is not a remote artifact backup.
The package receipt records 72.023 minutes from goal start to packaging completion.

The recommended next research is a new finite full-integration campaign
separating H4 unit admission, bar cost and initial-root coverage. Compare original
L2 and trial006 under both full and pinned/held conditions, retain fixed quality
and prespecified denominators, and keep new recording families sealed until
candidate freeze. `D/next-research.md` proposes at most six one-factor/understood
combination candidates. None was started by completing or documenting this
diagnosis; the original old-beat-ceiling proposal remains unrun historical work.

## Closed v2 campaign — 2026-10-13

The v2 campaign is closed. `trial006` is a research candidate for **the same
source-fitted initial map with held meter**. Its `(V,W)` improves from
`(0.16541267669858642, 0.16541267669858642)` to `(0.25, 0.25)`. Successful boundaries
increase from 2/17 to 3/17. The candidate and H7 pass known fixed/excerpt regression
under that contract. Actual full L2 integration regresses four materials and is
incomplete on the last baseline comparator in that ended campaign. The
owner-selected L2 entry and the
fixed DAW analyzer remain unchanged.

This is a documentation handoff, not permission to resume a finished campaign,
run its unexecuted proposal, replace the app or approve numerical thresholds.

## Evidence authorities and history

[`project-state.json`](../project-state.json) is the compact current pointer.
Its `latest_diagnosis` records the completed follow-up; `current_research` keeps
the original closed v2 campaign record, including its 29/30 validation scope.
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

This was the v2 closeout proposal and remains unexecuted. The current recommended
direction follows the separate
[2026-10-14 diagnosis](#full-l2-regression-diagnosis--2026-10-14); this gate-only
proposal does not explain the four full L2 regression mechanisms by itself.

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

This is a prospective minimum experiment, not a frozen or approved new campaign.
Its new clock, budget, timing controls, evaluator/input seals and baseline wiring
have not been created. Before `init`, distinguish the original pinned/held L2
control (.1654126767) from the retained trial006 incumbent (.25), and prescribe
comparison with both. Calling trial006 an unmodified L2 baseline would be wrong.
Do not edit the old protocol or inject a parent into its closed archive.

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

These commands read saved JSON without changing the campaign tree:

```bash
cd /home/yooch/code/joljak
C=data/research/runs/autoresearch_run_v2/20261013-campaign-v2
python3 -B tools/repository/status.py
python3 -B -m json.tool "$C/campaign-status.json"
python3 -B -m json.tool "$C/campaign-clock.json"
python3 -B -m json.tool "$C/session/state.json"
```

The archived `invoke.py` creates CLI logs and appends `commands.jsonl` even for
`status`; its `clock status` also rejects a finished clock. The older status
examples in `C/reproduce.md` are therefore superseded by the commands above.
The archived instructions and wrapper remain unchanged as historical evidence.
Do not execute that wrapper, submit/finalize/validation/export scripts or
`init/start/trial/probe` against the closed tree. Historical worker argv require
a separately authorized reproduction, fresh output/log destinations and a new
seal for changed source; never edit a freeze to make a replay pass.

## Fresh-session handoff audit — 2026-10-14

The audit reconciled saved records and checked declared paths, without running
inference, evaluation, tests, playback or content-hash validation. Its local
receipt/report are under
`data/storage/20261014-autoresearch-handoff-audit-v1/`.

| What the next session can rely on | Scope and remaining limit |
| --- | --- |
| Same-PC evidence | All 3,113 manifest-listed files, 10 development packets/references, 28 validation rows, 505 protected paths, the declared Python and 56 listening projects exist. Presence does not revalidate their digests or runtime. |
| Saved results | Primary .25 versus direct L2 .1654126767; known held-map regression passes; full L2 fails four materials and lacks one baseline. No new result was produced by this audit. |
| Published notes | The earlier notes publication reached `5ee66233824fe9259d63f613836ca4ea358452b7`; subsequent audit publication has its own receipt. Source/data commits remain owner-operated. |
| Fresh-machine recovery | No files under the preparation/v1/v2 run roots are tracked in data Git, and the earlier checkpoint manifest contains none of these runs or the Next package. A source/notes/data clone plus that checkpoint cannot restore this research. No later remote backup was verified. |
| Further research | The campaign is finished; the single gate proposal is unrun. A new authorized protocol and preserved inputs are prerequisites, rather than a restart of the old clock. |

For a fresh machine, the concrete missing stores are the listed preparation,
v1 session/bridge, v2 campaign and Next-package roots, plus the original
recordings and NN/PCM/prepared-source dependencies named in
`session/protocol.json` and `validation-inputs.json`. Original music was excluded
from the previous checkpoint. No new backup/upload or acquisition was performed.
On this PC those paths are present; do not confuse that with remote durability.

Three interpretation cautions prevent a fresh reader from overstating results:

- **Lineage:** trial006's recorded checkout parent is `seed`; H4/trial002 and
  H7/trial001 are code donors, not a different recorded parent. Saved donor code
  digests match v1 H4/trial004, H7/trial007 and H3/trial003. This audit compared
  recorded digests; it did not recompute source hashes.
- **Frozen code erratum:** trial006 `candidate_core.py` retains the copied header
  claiming unchanged scores/search. Its body implements the changed decoder and
  emissions described above. `parameters.json` selects 12 expansions, despite
  a fallback of 36 in the code. Preserve the frozen bytes and use the body,
  parameters, experiment card and lineage to interpret them.
- **Diagnosis and timing limits:** stage counters use the canonical held-meter
  equal-bar witness and visited paths; they are not exhaustive proofs over all
  acceptable R1–R3 readings. Full-L2 pair-time totals cover 29 completed records,
  not all 30 denominator inputs or a complete matched speed comparison.

The supplied `research_review.ko.md` records seven papers/official implementations
that motivated v2, alongside `program.md`, `SESSION_START.txt` and `GOAL.txt`.
They are design context, not evidence of an exact implementation or independent
generalization. Keep the package, campaign findings and proposed next protocol
distinct. Older private Step0/fresh-start documents retain dated decisions and
now point to this current authority.
