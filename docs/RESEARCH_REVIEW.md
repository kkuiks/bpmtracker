# Tempo-map decoder: current state and review questions

Status as of 2026-10-22. This document summarizes implemented methods and recorded
results for technical review. It does not select the next algorithm architecture.
Detailed metrics are in [AUTORESEARCH.md](AUTORESEARCH.md); application status is
in [DEVELOPMENT.md](DEVELOPMENT.md).

## What exists

| Component | Current role | Implementation |
| --- | --- | --- |
| Fixed linear estimator | Windows app's Analyze Audio implementation; one quarter BPM, 3/4 or 4/4, one audio-relative downbeat offset | [fixed implementation](../experiments/metronome_reconstruction_v1/README.md) |
| L2_DENSE_PROPOSALS | Maintained variable-tempo comparison baseline | [entry](../algorithms/variable/baseline.py), [search](../experiments/beat_event_stability_v1/core.py), [score](../experiments/beat_event_stability_v1/scoring.py) |
| G21 FULL | Evaluated research candidate; has not replaced L2 or the app | [review source](../reference/decoder_review/20261022/g21_full/candidate_api.py) |
| Selection refiner A | Evaluated, not adopted; retains G21's initial clock and all BPM changes, selects a trailing meter-only suffix to remove | [review source](../reference/decoder_review/20261022/selection_repair/prefix_api.py) |
| Selection refiner B | Evaluated, not adopted; also compares global initial bar rotations while preserving physical quarters and BPM changes | [review source](../reference/decoder_review/20261022/selection_repair/hierarchical_predictor.py) |

The [review snapshot](../reference/decoder_review/README.md) includes selected
source/configuration files, evaluator code, aggregate results and all-policy
comparison values. Its code copies retain the measured bytes and imports for
inspection; they are not relocated runtime entry points. The original experiment
implementations remain at their frozen local paths. Audio, model weights,
observation arrays, reference vectors and per-record predictions are not part of
the source repository.

## Method and input contract

The current research question is how to convert audio-derived beat/downbeat
observations into a defensible tempo/signature map. The evaluated decoder changes
retain the same Beat This `final0` detector; no neural retraining occurred.
Published-feature inputs and waveform-derived observations are separate strata.

A native map has one initial quarter BPM, signature and bar-zero phase. It then
accumulates quarter position through piecewise-constant sections. Each change lies
on a legal beat of the preceding state. Time remains continuous; a later section
cannot independently fit a new physical phase. Signature changes can start a
partial bar. Source proposals, latent rhythmic readings and output declarations
are different objects.

All headline comparisons use **initial-unit assistance**. Source candidates are
prepared first. A reference-derived coarse initial BPM proxy selects a discrete
metrical layer; its numeric value is then discarded. It does not supply fine BPM,
phase, meter, change times or a map score. Provider pulse units are not certified
written-quarter units. These results do not establish unaided automatic accuracy
or measured-human-tap performance.

L2 fits source-supported initial clocks and dense old-beat changes using bounded
path search. G21 retains four early and four information-qualified initial roots,
reconciles rebuilt source candidates with the original unit partition, and uses
additive pointwise source costs with metrical-role gates. The new branch has a
12-expansion budget and the configured declaration limit is 24. It then compares
its entire map against an original L2 fit under the original L2 source cost.
Higher scores win, including the values named `candidate_cost` in the adapter.

The search is approximate. Complete constant-tail scores influence scheduling;
locally useful partial paths may require later changes to become good complete
maps. This is an implementation property, not evidence that a specific alternate
search will improve results. The preserved adapter wraps imported search
functions, so the recorded harness uses one fresh process per prediction.

## Current comparison results

The tables use record-macro event F1 at 30ms, with 10/20/70ms views also retained.
Scores measure reference-grid agreement, not complete-song success percentages.

### Broad provider-reference comparison

The selected 2,604 inputs comprise 1,480 audio sources and 1,124 original published
feature inputs across BRID, Ballroom, SMC, Hainsworth and Raveform. Strict pulse
scoring covers 2,580 inputs; strict bar scoring covers 2,363. Twenty-four inputs
with limited source/reference overlap remain separately reported. Three fixed
no-clock results remain zero in eligible denominators.

| Method | Provider pulse F1, n=2,580 | Provider bar F1, n=2,363 |
| --- | ---: | ---: |
| Fixed linear | .789402 | .761483 |
| L2 | .832872 | .799617 |
| G21 | .834787 | .801072 |

G21/L2 bar wins/ties/losses are 79/2,233/51; pulse wins/ties/losses are
117/2,383/80. Long Raveform audio is nearly tied. Provider BPM agreement can be
high while change-location agreement is low. Raveform labels include many small
adjacent BPM steps and do not certify intentional musical changes.

This cohort supports provider event/grid agreement. It does not provide accepted
native ideal maps, independently certified written meters or intentional-change
truth. Independent listening alignment and composition independence remain
unverified. Detector-training overlap was recorded rather than used to exclude
this decoder comparison. The existing 465 qualified GTZAN feature groups are
outside this cohort and their complete G21 comparison remains unperformed.

### Formal accepted-grid comparison

The 44 catalog entries comprise 33 complete recordings, ten original excerpts
and one approved synthetic input. They are established development/review
materials. One reference has prediction-origin provenance. Accepted source-relative
quarter, rendered-click and bar vectors retain their original support and phase.

| Method | Quarter F1, n=44 | Bar F1, n=44 | Quarter / bar F1 on ten changing-tempo inputs |
| --- | ---: | ---: | ---: |
| Fixed linear | .852085 | .804984 | .593185 / .448711 |
| L2 | .882903 | .792134 | .699034 / .488596 |
| G21 | .886574 | .806210 | .715186 / .491740 |

On the ten changing-tempo references, G21's 1s change-location macro F1 is .341667
against L2 .269444. G21 matches nine of 37 reference tempo changes under that
time-only rule. Boundary matching with the new BPM, meter and bar phase is a
stricter question. G21's bar mean across all 44 is nearly tied with fixed.

At 10ms the overall quarter ranking is fixed > L2 > G21. One formal recording's
roughly 30ms initial error produces zero quarter F1 at 30ms and about .99934 at
70ms. Its reference was not shifted or excluded. Tolerance sensitivity is a
substantial limitation of interpreting a single headline score.

### Post-comparison selection experiments

Eighteen scoring/selection policies were tested on formal44; twelve were also
tested on broad2,604. Frozen observations/upstream maps were reused explicitly,
with eight fresh G21 graph calls to check composition. These adaptive experiments
did not retrain the detector or implement a new tempo-path search.

| Method | Formal bar F1, n=44 | Strict broad bar F1, n=2,363 | Formal / broad bar regressions against G21 |
| --- | ---: | ---: | ---: |
| G21 | .806210 | .801072 | — |
| A: `role_meter_suffix_mdl` | .815747 | .808510 | 1 / 50 |
| B: `coded_literal_phase_role_suffix_mdl` | .817484 | .804556 | 1 / 66 |

Both preserve the physical quarter clock and every selected tempo change.
Quarter F1 and changing-tempo boundary F1 therefore remain unchanged. A gives
the larger broad average gain; B gives the larger formal bar average. Some
regressions are large, including zero bar F1 after removing a compensating meter
declaration. Both regress on a formal changing-meter recording. A's broad gains
primarily come from Raveform; other provider bar means regress slightly.

At 70ms, formal bar F1 is .823884 for G21, .825080 for A and .836522 for B. A's
formal gain is smaller at that tolerance. Full-pool score substitutions and
less constrained suffix removal were also executed; their quarter-clock losses
and unsuccessful results are retained in the
[all-policy table](../reference/decoder_review/20261022/policy-comparison.csv).
No replacement algorithm was adopted.

## What the diagnostics establish

- **Ranking headroom exists in the recorded pool.** Thirteen formal inputs have
  a recorded alternate map non-worse in quarter/bar F1 at both 30/70ms and better
  on at least one axis. The finite pool is not the complete proposal graph.
- **The final guard has mixed effects.** On recovered formal maps it raises mean
  quarter/bar F1 from .857876/.783762 to .886574/.806210, while rejecting better
  maps on some inputs. Simply removing it is not supported by these averages.
- **The legacy interval score is not partition invariant.** With the clock and
  observations held fixed, changing only integration boundaries changes two
  diagnostic scores by +7.141521 and +3.251740. Additive pointwise totals differ
  only by roundoff. A same-map, one-channel substitution reverses two guard
  decisions; it was not validated as a replacement guard over the broad corpus.
- **Literal state counts exceed some search policies.** Two accepted sequences
  require 43 and 68 declarations after simultaneous changes are grouped, above
  the configured 24. These are literal representation counts, not proven
  minimum equivalent-grid complexity or an F1 upper bound.
- **Runtime cost is material.** Matched G21/L2 API elapsed medians are 1.652x on
  broad2,604 and 1.742x on formal44. These cached-observation measurements are
  not independent cold audio-to-map timings.

G21's actual emission code includes an expected-bar tick penalty, despite stale
contrary comments and metadata in the preserved snapshot. The code copies retain
those bytes; the aggregate interpretation above follows the executed arithmetic.

## Protocol and evidence boundaries

Earlier 62-material developer validation used C/P coverage and V/W post-change
metrics, different source-bank preparation and its recorded initial-unit
conditions. These metrics cannot be pooled with the event-F1 tables above.
Across shared formal inputs, the seven active observation arrays match on all
44, but complete prepared banks match on 37 and selected-unit candidate lists
on 38. An unchanged detector or fitter does not imply identical inference inputs.
Earlier Circle With Me gains belong to that earlier protocol.

Broad/formal predictions and reports are complete. Independent evaluation on
eight reserved materials, final manual reference auditing, G21 Windows listening
and variable-model application integration remain unperformed. Recorded build,
native geometry, playback, reference agreement and independent generalization
are different kinds of evidence.

The review snapshot makes source inspection and aggregate review possible from
a source-only checkout. Full reproduction still requires the separately stored
original inputs, observations, reference supports, checkpoint and recorded
environment. No new inference, benchmark, playback test or acquisition was run
to prepare this review.

## Questions and possible directions for review

The following are unselected proposals and questions, not established solutions
or an ordered roadmap:

- Could a common source objective compare initials, partial paths and completed
  maps more consistently? Additive costs are one possibility, but the executed
  full-pool substitutions already show that additivity alone is insufficient.
- Could time-directed search or a different path budget retain useful short
  episodes and later returns? Candidate coverage, phase continuity, pruning and
  runtime would need measurement; a larger graph could also select worse maps.
- Could bar/accent roles and initial bar phase be better distinguished without
  collapsing quarter-clock accuracy? The A/B tradeoff leaves this unresolved.
- How much remaining error comes from source-clock admission, observation
  ambiguity, reference precision or representation, rather than path selection?
- What combination of event, changing-map, false-declaration, cohort regression
  and runtime evidence would justify a replacement? No new product threshold is
  asserted here, and these means alone do not determine that decision.

Alternative explanations and approaches remain open. The current code and
results establish a reviewable starting point rather than a selected next design.
