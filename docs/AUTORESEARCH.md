# Variable-tempo research

The research pipeline converts audio-derived beat/downbeat observations into a continuous tempo/signature map. **L2_DENSE_PROPOSALS** is the maintained comparison baseline. **G21** is the preserved comparison candidate; subsequent selection refiners remain experimental and separate from the application's fixed-tempo analyzer. Known-case improvements have not yet established broad variable-tempo generalization.

The [current-state review](RESEARCH_REVIEW.md) summarizes completed comparisons,
source locations and unresolved questions. [Selected review source and aggregate
results](../reference/decoder_review/README.md) are included in the source
repository; original run inputs and predictions remain separate.

## G21 development validation

This earlier C/P/V/W validation has its own prepared source banks and assistance
conditions. It is retained as protocol-specific evidence. The later broad and
formal event-F1 comparisons below are separate studies; their scores and initial
candidate banks cannot be treated as one unchanged-input benchmark.

### Representation and method

A fixed estimator fits one BPM, signature and downbeat offset. The variable representation starts with one audio-supported phase and accumulates quarter position through piecewise-constant tempo/signature sections. Changes preserve the existing clock's beat geometry instead of independently resetting each section.

L2 searches dense source proposals using Beat This observations and available PCM evidence. G21 retains the official `final0` checkpoint and adds:

- Four early-source and four information-qualified/local initial roots in a bounded search.
- Metrical-role evidence and a quarter-role meter gate for comparing physical clocks and notation changes.
- A complete-map comparison against the original L2 map under the original source cost.
- Assignment of rebuilt initial candidates to the original metrical-unit partition by log-BPM distance before coarse unit selection.

The final change repairs an initial-unit mapping error in the preceding G19 candidate. It restores one new recording's coverage from zero to .483894717, equal to L2, without recovering its actual tempo change. The complete-map guard uses audio evidence rather than reference scores and does not guarantee an improvement on every recording.

Candidates are prepared before the coarse initial BPM input. That input selects a discrete metrical layer; its continuous numeric value does not set precise BPM, phase or scores. There is no song-specific dispatch or reference-timed proposal generation. Neural training is unchanged.

### Conditions and metrics

**Full search** estimates the initial clock and subsequent tempo/meter path. **Held initial/meter** is a diagnostic starting from a common source-fitted initial with fixed meter; the initial is not ground truth. Its results cannot substitute for full-search performance.

C/P measure acceptable/preferred map coverage with stability penalties. V/W measure localized post-change quality, averaged within each song and then equally across songs. These are not whole-song pass percentages or boundary success ratios. All results below use coarse initial-unit assistance.

### Performance and denominators

The comparison covers 62 materials: 44 catalog recordings, two auxiliaries and a separate 16-material development release. They are not 62 independent unseen songs. The 324-row comparison contains 108 actual G21 conditions, 152 exactly reused control rows and 64 newly executed control rows. The development references include manual revisions; final reference review remains pending.

| Full-search cohort | n | L2 C / P | G21 C / P | L2 V/W → G21 V/W |
| --- | ---: | ---: | ---: | ---: |
| Existing fixed complete | 16 | .990532 / .928032 | .990532 / .928032 | Not applicable |
| Existing excerpts | 10 | .959870 / .959870 | .959870 / .959870 | Not applicable |
| Existing core variable | 4 | .474392 / .474392 | .632760 / .632760 | 0 → .333333 |
| Existing meter guards | 5 | .739037 / .472450 | .739037 / .472450 | Separate meter diagnostics |
| Additional variable | 6 | .417190 / .417190 | .398355 / .398355 | .166667 → .166667 |
| Additional fixed | 1 | 0 / 0 | 0 / 0 | Not applicable |
| Qualified diagnostics | 4 | .830368 / .830368 | .830368 / .830368 | Not a primary tempo cohort |
| New variable | 8 | .653133 / .565796 | .653133 / .565796 | .174690 → .174690 |
| New fixed | 6 | 1 / 1 | 1 / 1 | Not applicable |
| New meter | 2 | .477162 / .476765 | .477162 / .476765 | Separate meter diagnostics |

Circle With Me recovers three of three tempo changes and removes a spurious final 2/4. ADTR recovers one of three changes. Across the core four, four of 17 boundaries are recovered. Opeth and BFMV remain unresolved. Six of the new variable eight have V=0; their mean equals L2. The additional Allageon recording regresses from .369671558 to .256663672 coverage, while Red Miso remains at zero. Failures remain in their original denominators.

Held-initial/meter V/W is .25 on the established core four, equal to the earlier trial006 diagnostic. On the new variable eight it is .041667, equal to trial006 and below held L2's .0625. This diagnostic does not establish full-search improvement.

### Runtime and validation scope

Three alternating matched timing pairs share cached observations and PCM. Median G21/L2 ratios including source candidate preparation are **1.668706** on the established 30-material cohort and **1.414131** on development16. Full-search fitting alone is 1.757788× / 1.604439×. These ratios compare algorithms; they are not processing time divided by recording length.

An earlier G19 fresh-file run, including decoding and observation preparation, took **95.901 seconds for 234.011 seconds of audio**. This is a single-file measurement, not a G21 unseen-recording or Windows latency guarantee.

Recorded execution evidence includes 108 exact native re-scores, 552 semantically equal repeated maps, 62 full-search initial-unit/budget checks and 46 exact held-condition comparisons. Native geometry evidence covers 96 projects, 60,448 worklet clicks and 64 inverse-quality comparisons. These counts describe repeated execution and geometry rather than additional songs or listening evaluations.

Final reference review, independent evaluation on eight reserved materials, G21 Windows listening and application integration are outstanding. The independent set has not been opened or evaluated. Broader variable/meter generalization is unestablished.

## Broad observation-to-map evaluation

The completed broad comparison targets the **decoder's conversion of observations into valid tempo maps** across musical styles. Frozen G21 FULL, original L2 and the application's fixed estimator were evaluated on the qualified five-dataset corpus. Beat-detector training overlap is recorded as provenance rather than used to exclude this decoder comparison; this does not establish end-to-end independence of the neural detector.

### Sources and current collection state

| Source | Available representation | Current state and reference limits |
| --- | --- | --- |
| GTZAN | Published features | 465 unique qualified groups already used during decoder development; complete G21 evaluation outstanding |
| [BRID](https://zenodo.org/records/14051323) | Original short percussion audio | 367 inventoried recordings; 93 ensembles with beat/bar-position references and 274 auxiliary solos |
| [Ballroom](https://github.com/CPJKU/BallroomAnnotations) | Published original features | 685 inventoried excerpts/reference pairs; 13 of 698 catalog entries absent from the selected release |
| [SMC](https://zenodo.org/records/13922116) | Published original features | 217 inventoried excerpts/reference pairs; beat labels without downbeats |
| [Hainsworth](https://zenodo.org/records/13922116) | Published original features | 222 inventoried excerpts/reference pairs, with beat/bar-position labels |
| [Raveform](https://mir-aidj.github.io/raveform/) | Original platform audio and curated annotations | 1,387 acquired/reference-paired; 36 source failures retained; provider-event metrics qualified, independent alignment unverified |

BRID/Ballroom provide 1,052 original inputs and 778 source/reference pairs in the completed first batch. Published augmentations, replica families and alternate audio encodings do not count as independent recordings. One Ballroom reference extends 120ms beyond the feature extent; the discrepancy remains recorded without shifting or trimming its annotation.

Together the completed acquisition batches contain **2,878 input rows and 2,604 source/provider-reference pairs**, including 274 unannotated auxiliaries. They comprise 1,754 audio sources and 1,124 original feature inputs, excluding existing GTZAN. Every original source passed identity and structural checks, including full finite decoding and a separate strict codec pass for audio. The final comparison retains 2,580 strict-extent inputs and 24 limited-overlap inputs: one Ballroom reference and 23 Raveform references extend beyond the actual input extent. No labels were shifted or corrected. The 13 Ballroom feature absences each correspond to one side of a reported replica pair, with one acquired member per pair.

Raveform's curated metadata covers about 160.69 hours. 280 rows have multiple distinct provider BPM values; these labels do not independently certify intentional tempo changes or native ideal maps. The provider CSV's downbeat field contains bar positions rather than a binary downbeat flag. Actual audio availability remains part of the inventory, including all 36 failed-source cases. Of the acquired sources, 278 have multiple distinct provider BPM values; that count is not a certified tempo-change cohort.

ASAP's piano-performance/rubato focus is outside this evaluation scope. Harmonix is deferred. Metric Modulations provides annotated recording identities, but a compatible independent audio route has not been established. No result is inferred from these collection decisions.

### Reference and comparison protocol

The source selection and comparison protocol were frozen before new predictions:

1. Source version, original timing, reference capabilities and waveform/feature extent.
2. Recording/composition families, exact duplicates, prior decoder exposure and frozen selection.
3. Shared observation provenance and separate raw-audio versus feature-only conditions.
4. Distinct complete-recording/excerpt, fixed/tempo/meter and real/synthetic cohorts.
5. Map coverage, localized changes, false declarations, failures, runtime and resource metrics supported by each reference.

The exhaustive capability matrix contains all 2,927 provider rows and seven explicit metric decisions per row. Provider pulse agreement is available on 2,604 inputs, bar-event agreement on 2,387, and tempo-grid agreement on 1,343 internally consistent Raveform inputs. Of the latter, 269 have multiple distinct provider BPM values. These are provider-label capabilities, without native ideal-map, written-meter or independently certified intentional-change truth. Independent audio/reference listening alignment and composition independence remain unverified.

The comparison preserves the existing initial-unit-assisted condition: source candidates precede hint encoding, the reference-derived pulse proxy only selects a discrete unit, and its numerical value never enters fitting. Unit-selection sensitivity uses 97/100/103% proxies; identical model inputs are explicitly reused without new timing claims. Shared final0 observations, feature-only inputs without PCM, failed cases and metric-specific denominators remain distinct. Event matching reports 10/20/30/70ms tolerances, with the primary view fixed at 30ms before results.

### Completed broad comparison

All 2,604 inputs completed 7,812 primary method cases and 23,436 cases across the three initial-unit conditions. These comprise 7,853 fresh method invocations and 15,583 explicitly equivalent-input reuses. G21 and L2 each produced 2,604 geometrically valid maps; the fixed estimator produced 2,601 maps and three unsupported-source-octave results. The latter remain zero in applicable metric denominators, giving nine failure-table rows across the conditions. There were no controller or infrastructure gaps.

The primary table uses record-macro F1 at the predeclared 30ms one-to-one event tolerance. Pulse and literal-quarter agreement use 2,580 strict inputs; bar agreement uses the 2,363 with bar labels. Scores are not complete-song success rates or written-meter accuracy.

| Method | Provider pulse F1 | Literal-quarter F1 | Provider bar F1 |
| --- | ---: | ---: | ---: |
| G21 FULL | .834787 | .835214 | .801072 |
| Original L2 | .832872 | .833442 | .799617 |
| Fixed linear | .789402 | .789402 | .761483 |

G21's mean advantage over L2 is 0.192 percentage points for pulses and 0.145 for bars. Paired pulse wins/ties/losses are 117/2,383/80; bars are 79/2,233/51. BRID bar F1 regresses by 0.177 points. In the long-audio Raveform strict subset, G21 gains only 0.019 points for pulses and 0.010 for bars. At 70ms, Raveform pulse F1 is slightly higher for L2. Both variable methods exceed the fixed estimator's overall event scores, while G21 does not consistently improve every input, metric or aggregation. The 24 limited-overlap inputs remain a separate reported cohort.

On the 1,321 consistent Raveform tempo grids inside the strict pulse cohort, 1,059 have one provider BPM and 262 have multiple values. More than 98% of scored duration is within 1% of the provider BPM for every method. In the multiple-value stratum, change-location macro F1 at 1s is only .001165 for G21, .001255 for L2 and zero for fixed. The 262 references contain 32,423 adjacent changes, with a median step of 0.02 BPM; all individual relative steps are below 1%. Small adjacent steps do not bound cumulative excursion. These values describe provider-label granularity and agreement, without certifying intended musical changes. BPM proximity is not evidence of successful boundary recovery.

Paired primary G21/L2 API elapsed cost has median 1.652x, p95 2.071x and maximum 4.116x; 180 of 2,604 inputs exceed 2x. CPU ratios are recorded separately. Shared preparation, G21 enrichment/guard cost, fixed candidate selection, fresh workers and equivalent-input reuse have separate receipts. Component sums under concurrent execution are not three independently measured cold-file latencies. Process RSS is not a measured concurrent whole-job peak.

The final evidence audit passed all frozen-code, reference, original-source, case-coverage, geometry, failure and event-arithmetic checks. Saved-report reproduction matched numeric results except report creation time and matched all six case/qualification/runtime tables byte for byte. Scientific interpretation and raw regression examples are recorded separately from the unchanged generated report. Local evidence is under `data/research/runs/broad_map_evaluation_v1/20261018-full-corpus-v1/delivery/`, starting with `final-report.ko.md`, `scientific-review.json` and `final-artifact-sha256.json`.

### Completed formal reference-grid comparison

The separate comparison completed on all 44 current formal catalog entries after qualification of every selected accepted reference, full original audio and supported range. Its 396 condition-method results comprise 132 fresh calls and 264 equivalent-input reuses, with no execution or native-format failures. The corpus contains 33 complete recordings, ten original excerpts and one approved synthetic recording.

| Method | Accepted quarter F1 | Accepted rendered-click F1 | Accepted bar F1 |
| --- | ---: | ---: | ---: |
| G21 FULL | .886574 | .876016 | .806210 |
| Original L2 | .882903 | .869224 | .792134 |
| Fixed linear | .852085 | .847971 | .804984 |

These are 30ms record-macro agreement scores on the accepted saved arrays. G21/L2 quarter wins/ties/losses are 3/41/0; bars are 2/40/2. G21's mean gains of 0.367 quarter and 1.408 bar percentage points include Deadman and Roundabout bar regressions. Its overall bar mean is nearly tied with fixed. The ten original excerpts have equal quarter means across methods, while fixed has the higher bar mean. Single-BPM references include changing-meter material and must not all be called fully constant maps.

The ten multiple-BPM references give G21/L2/fixed quarter F1 .715186/.699034/.593185 and bar F1 .491740/.488596/.448711. Their 1s accepted change-location macro F1 is .341667/.269444/0. Across 37 accepted changes, G21 predicts 12 events with nine matches; L2 predicts 11 with seven matches. Event counts and per-input macro F1 are different summaries. Same-value phase declarations remain in the separate accepted meter-declaration comparison; its 11 positive-reference rows average .060606 for both variable methods at 1s.

The 10ms quarter ranking is fixed > L2 > G21. Nocturne has zero quarter F1 at 30ms but about .99934 at 70ms, with a saved median residual near 30.214ms. The reference was neither shifted nor excluded. G21/L2 API elapsed cost has median 1.742x, p95 2.066x and maximum 2.638x; three of 44 inputs exceed 2x. Source preparation, CPU timing, cumulative batch/process RSS and reuse remain distinct from cold-file latency and concurrent whole-job memory.

One prediction-origin reference is a separate stratum; its historical audio digest was unrecorded, so current bytes are bound without claiming a historical identity certificate. Explicit accepted quarter, rendered-click and bar arrays retain their coordinate, endpoint and support semantics without reconstructing a native reference map. These are established development/review materials, not an independent generalization set. Accepted-grid scores do not replace the earlier C/P/V/W metrics.

Actual report reproduction, all-case evidence audit and scientific interpretation passed. The original generated eight files are preserved. Local evidence is under `data/research/runs/formal_map_comparison_v1/20261019-current44-v1/delivery/`, including `final-report.ko.md`, `combined-report.ko.md`, `scientific-review.json`, `resources-and-diagnostics.json` and `final-artifact-sha256.json`. Both requested comparisons and their reports are complete; independent reserved-eight evaluation and application integration remain separate outstanding work.

## Source-cost and map-selection repair study

Eighteen source-scoring/selection policies were implemented and evaluated on the
44 formal inputs; twelve were also compared across all 2,604 broad inputs. The
study reused frozen observations and upstream maps, with eight actual fresh G21
graph calls for composition parity. No neural retraining or new acquisition was
needed. These are adaptive development comparisons, not independent validation.

The legacy interval criterion changes when an identical clock is integrated over
different partitions. A controlled constant-clock calculation changes its score
by +7.141521 on Meet Your Maker and +3.251740 on BFG Division; additive pointwise
costs differ only by numerical roundoff. Replacing only the beat term reverses
the corresponding two-map guard decisions. This diagnoses a ranking contributor,
without establishing that single-channel substitution as a validated decoder.
G21 already includes an expected-bar tick penalty despite stale contrary metadata.

Two conservative prototypes preserve the physical quarter clock and every BPM
change. A retains the selected initial clock and compares retaining trailing
meter changes with truncating their suffix under its source criterion. B also enumerates legal global initial bar rotations, using
literal bar observations to select origin and role-aware evidence to select the
suffix, with source-derived boundary and phase code lengths.

| Method | Formal bar F1, n=44 | Strict broad bar F1, n=2,363 | Formal / broad bar losses against G21 |
| --- | ---: | ---: | ---: |
| G21 | .806210 | .801072 | — |
| A: tempo-preserving suffix selection | .815747 | .808510 | 1 / 50 |
| B: literal-phase and role-suffix selection | .817484 | .804556 | 1 / 66 |

These are 30ms macro F1 values. Quarter-grid scores remain unchanged at all four
tolerances. A's strict broad bar wins/ties/losses are 165/2,148/50; its gains
primarily come from Raveform, while other provider bar means regress slightly.
B repairs several severe phase-related losses from suffix removal but introduces
other phase errors. Both regress on the formal Jinjer reference. At 70ms, formal
bar F1 is .823884 for G21, .825080 for A and .836522 for B.

Full-pool score replacements and broader suffix removal were also executed and
retain their negative results. The new refiners do not reconstruct missing tempo
paths: formal changing-ten quarter F1 .715186 and 1s tempo-change F1 .341667 remain
unchanged. Neither prototype replaces L2, G21 or the application analyzer.

Local implementation and evidence are under
`data/research/runs/map_decoder_repair_v1/20261020-source-selection-v1/`, including
`prefix_api.py`, `hierarchical_predictor.py`, `report.ko.md`,
`all-variants-comparison.csv`, `results-summary.json` and `REPRODUCE.md`.

The [source-review snapshot](../reference/decoder_review/20261022/README.md)
includes the selected algorithms, evaluator logic and aggregate results. Possible
changes to objectives, search, bar roles and initialization remain unselected
proposals in [the review questions](RESEARCH_REVIEW.md#questions-and-possible-directions-for-review),
not conclusions established by these partial refinements.

## Full L2 regression diagnosis — 2026-10-14

The preceding trial006 candidate improved a held-initial/meter objective (.165413 → .25) but regressed under full search. Its original full comparison ended at 29/30 pairs. A separate diagnosis completed 240 cells and both full and held 30/30 comparisons, reproducing four regressions with unchanged observations and references.

| Recording | Full L2 C → trial006 C | Supported contribution |
| --- | --- | --- |
| Daybreak — Equilibrium | 1 → .776692 | Initial competition interacts with meter support; changed bar cost reverses path ranking |
| Neck Deep — Can't Kick Up the Roots | 1 → .028302 | Additional tempo-unit admission loses quality even with the earlier cost/beam |
| Maxime — Breathe Fire | .754027 → .716952 | Changed cost favors an earlier 2/4 declaration; L2 is already imperfect |
| In Flames — Meet Your Maker | .966295 → .698125 | Initial-root scheduling and bootstrap retention suppress a better path |

Finite-pool ranking reversals and controlled root interventions explain their stated comparison scope; they do not establish a universally improved decoder. G21 is a separate subsequent candidate. Earlier failures, source versions and denominators remain retained.

## Reproduction

The maintained baseline is [`algorithms/variable/baseline.py`](../algorithms/variable/baseline.py), with implementation/configuration in [`experiments/beat_event_stability_v1/`](../experiments/beat_event_stability_v1/README.md). The [code map](CODE_MAP.md) lists source, geometry and scoring dependencies.

Local G21 artifacts use:

```text
data/research/runs/l2_improvement_autoresearch_v1/20261014-01a138e6-v1/
  phases/phase-B-c250ba38c4af/
    trials/G21/full/
    trials/G21/held/
    evaluations/G21-development16-v1/
    delivery/final-G21-v2/
```

The delivery contains comparison/cohort tables, per-material losses, tempo/meter boundaries, localized regions, reference scope, timing, a candidate freeze and the independent evaluation specification. `report.ko.md` describes the recorded result. The separate compact archive `delivery/G21-development16-repro-v2.zip` is 92,376,713 bytes, SHA256 `2449afec4dea984dcc7faf890b67ec131475278d9260cfdeb21aa4212e642c0f`.

Full local run artifacts are excluded from the public source clone. The selected
review copies and aggregate tables in `reference/decoder_review/` support source
inspection but do not supply a complete runtime environment. Reproduction also
requires the manifested original inputs, compatible observation arrays, reference
supports and official checkpoint. The compact archive does not include audio,
weights or reserved evaluation material; its existence is not a complete remote backup.

Collection records reside under `data/research/runs/observation_corpus_expansion_v1/`, and dataset manifests under `data/samples/datasets/`. [Local data documentation](../tools/LOCAL_DATA.md) describes the separation between sources, evaluation references, generated results and credentials. Frozen results retain their original inputs, source snapshots, failures and precision.
