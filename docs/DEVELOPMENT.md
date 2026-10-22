# Development status

Joljak 0.6.17 provides a Windows audio workspace with a fixed-tempo analyzer and an editable project tempo/signature map. Variable-tempo inference is a separate research component. Its comparison baseline is **L2_DENSE_PROPOSALS**, with **G21** retained as a comparison candidate. Subsequent selection refiners remain experimental. Broad variable-tempo generalization has not been established.

[Project metadata](../project-state.json) records component status. The [code map](CODE_MAP.md) locates implementations; [research results](AUTORESEARCH.md) define the evaluation conditions and metrics. The [review brief](RESEARCH_REVIEW.md) collects current algorithm behavior, results and questions for technical review.

## Application

| Area | Implemented behavior | Validation scope |
| --- | --- | --- |
| Audio workspace | Import songs/stems, arrange and edit events, range operations, Undo/Redo, transport and mixer | Earlier native Windows audits cover specific revisions and fixtures |
| Analysis | One constant quarter BPM, signature and audio-relative downbeat offset per song/range | Uses the fixed estimator; variable research results are separate |
| Project clock | Editable persistent tempo/signature events; Linear and Musical track coordinates | 0.6.16 has focused geometry evidence; a comprehensive current-version Windows regression is outstanding |
| Save and export | `.joljak`, source collection, recovery, WAV mix/stems/click, JSON/MIDI tempo maps | Earlier integration evidence does not certify every subsequent revision |
| Decoded audio | Shared buffers for unchanged linked imports; session and Undo/Redo retention; regeneration from unchanged originals | 0.6.17 syntax, compilation, frontend build and Windows assembly completed; native cache/recovery/playback checks are outstanding |

Tempo-map edits preserve audio speed and duration. Linear tracks retain physical time; Musical tracks follow their stored quarter anchors. Other map declarations retain their audio times when declarations are edited or deleted. Raw analysis results remain separate from editable values and the shared project map.

The initial design target is fewer than ten tracks and projects under thirty minutes; this is a design scope, not a measured capacity limit. Recording, plugin hosting, MIDI performance editing, time stretching and automatic variable-map analysis are outside the implemented application features. See the [app guide](../apps/daw/README.md).

## Variable-tempo method

The fixed estimator fits one clock to an entire input. L2 instead searches a continuous, piecewise-constant tempo/signature map. Beat/downbeat observations and audio evidence propose clocks; a bounded path search chooses changes while preserving one initial phase and accumulated quarter position.

G21 retains the same official Beat This `final0` observations. It extends the source-derived initial candidates, adds evidence for metrical roles and compares its complete map with the L2 map under the original source cost. This changes the decoder and search, without neural retraining. The coarse initial BPM input selects a discrete metrical layer; its numeric value does not set fine BPM, phase or map scores.

## Measured performance

The earlier developer-validation comparison covers 62 materials: 44 catalog recordings, two auxiliaries and a separate 16-material development release. These are development materials rather than 62 independent unseen songs. Full initial/meter search is the primary condition; the held-initial/meter diagnostic is reported separately. Its prepared banks and metrics differ from the later formal44 event-grid comparison; the results below belong to that earlier protocol.

| Full-search cohort | n | L2 coverage C → G21 C | L2 post-change V/W → G21 V/W |
| --- | ---: | ---: | ---: |
| Existing fixed recordings | 16 | .990532 → .990532 | Not applicable |
| Existing excerpts | 10 | .959870 → .959870 | Not applicable |
| Existing core variable recordings | 4 | .474392 → .632760 | 0 → .333333 |
| Additional variable recordings | 6 | .417190 → .398355 | .166667 → .166667 |
| New development variable recordings | 8 | .653133 → .653133 | .174690 → .174690 |
| New fixed recordings | 6 | 1 → 1 | Not applicable |
| New meter recordings | 2 | .477162 → .477162 | Separate meter diagnostics |

C/P measure acceptable/preferred map coverage with stability penalties. V/W measure localized post-change quality, averaged within each song and then across songs. These values are not whole-song pass percentages. All results use coarse initial-unit assistance.

Circle With Me recovers three changes and removes a spurious final 2/4. ADTR recovers one of three changes; the core four recover four of 17 boundaries. Opeth and BFMV remain unresolved. Six of the new variable eight have V=0, and their mean matches L2. The additional Allageon recording retains a coverage regression (.369672 → .256664); the fixed-extension Red Miso remains at zero. Failed materials remain in the reported denominators.

Cached-observation comparisons including source preparation measure G21 at 1.67× L2 on the established 30-material cohort and 1.41× on development16. These ratios are not elapsed time divided by audio length. A separate earlier G19 fresh-file measurement took 95.90 seconds for 234.01 seconds of audio; it does not establish G21 latency on arbitrary new recordings.

## Evaluation data

The broad comparison of frozen G21 FULL, original L2 and the application's fixed estimator completed on all 2,604 qualified source/reference inputs. Source qualification and the provider-event protocol were frozen before predictions: 2,580 inputs meet the strict source-extent condition and 24 have explicitly limited overlap. Existing GTZAN includes 465 unique qualified feature groups already used during decoder development and is outside this five-dataset cohort; its complete G21 comparison is outstanding.

| Source | Current acquisition state | Reference scope |
| --- | --- | --- |
| BRID | 367 original recordings inventoried | 93 ensembles have beat/bar-position references; 274 solos are auxiliary |
| Ballroom | 685 original feature excerpts inventoried | 685 source/reference pairs; 13 catalog entries absent from the selected release |
| SMC | 217 original feature excerpts inventoried | Beat timestamps; no provider downbeat labels |
| Hainsworth | 222 original feature excerpts inventoried | 222 source/reference pairs with beat/bar-position labels |
| Raveform | All 1,423 rows attempted; 1,387 original audio sources inventoried and 36 collection failures retained | 1,387 source/reference pairs; independent listening alignment unverified |

The completed expansion contains **2,878 input rows and 2,604 source/provider-reference pairs**: 1,754 audio sources and 1,124 original feature inputs. The 274 unannotated BRID solos are auxiliary inputs. These totals exclude the pre-existing GTZAN material and do not certify composition independence.

All 1,754 audio sources passed full finite decoding and a separate strict codec-error check; all 1,124 original feature arrays passed identity, shape and finite-value checks. Augmentations and alternate encodings remain distinct from independent recordings. One Ballroom reference and 23 Raveform references extend beyond the actual input extent; decoded playable-sample duration replaces container duration for the audio scope check. The original labels remain unchanged. All 13 absent Ballroom feature rows are members of reported replica pairs, with one available member per pair.

The qualified scope is provider pulse/bar-event agreement, with provider tempo-grid agreement on 1,343 internally consistent Raveform inputs. Native ideal-map, written-meter and independently certified intentional-change metrics remain unsupported; independent audio/reference listening alignment is unverified. Raw-audio and feature-only results remain separate. Beat This training overlap is recorded as provenance rather than used to exclude decoder evaluation. ASAP is outside the current musical scope, Harmonix is deferred, and a matching-audio route for Metric Modulations has not been established.

The frozen comparison uses reference-derived initial pulse-unit assistance, with numerical hints discarded before fitting, and reports 10/20/30/70ms event matching with 30ms as the primary view. All 23,436 condition cases are complete: 7,853 fresh invocations and 15,583 equivalent-input reuses. The fixed model's three no-clock inputs remain zero in eligible denominators; G21 and L2 produce geometrically valid maps for every input.

| Method | Strict pulse macro F1, n=2,580 | Strict bar macro F1, n=2,363 |
| --- | ---: | ---: |
| G21 | .834787 | .801072 |
| Original L2 | .832872 | .799617 |
| Fixed linear | .789402 | .761483 |

G21's average gain over L2 is small and includes 80 pulse and 51 bar regressions. Raveform's long-audio subset is nearly tied. Provider BPM proximity does not establish change recovery: multiple-value references contain many small adjacent BPM steps and their change-location F1 is low for all methods. Paired API elapsed cost has median G21/L2 1.652x; 180 inputs exceed 2x. These are assisted provider-label comparisons, not complete-song success rates, independently certified changing maps or cold-file latency measurements.

Full evidence auditing, saved-report reproduction and scientific interpretation are complete. Evidence is under `data/research/runs/broad_map_evaluation_v1/20261018-full-corpus-v1/`, starting with `delivery/final-report.ko.md`.

The separate formal comparison also completed: 44 catalog entries, 132 fresh method calls and 264 equivalent-input reuses, with no execution or map-format failures. It uses selected accepted source-relative quarter/click/bar arrays and preserves their support and phase. One prediction-origin reference with a previously unrecorded audio digest is reported separately. All materials are known development/review inputs.

| Method | Accepted quarter macro F1, n=44 | Accepted bar macro F1, n=44 |
| --- | ---: | ---: |
| G21 | .886574 | .806210 |
| Original L2 | .882903 | .792134 |
| Fixed linear | .852085 | .804984 |

At 30ms, G21 gains 0.367 quarter and 1.408 bar percentage points over L2, with two bar regressions. Its bar mean is nearly tied with fixed. On the ten multiple-BPM references, G21 quarter/bar F1 is .715186/.491740; accepted tempo-change F1 at 1s is .341667, compared with L2 .269444 and fixed zero. At 10ms the quarter ranking reverses. Nocturne illustrates threshold sensitivity: roughly 30ms phase error gives zero 30ms F1 and about .99934 at 70ms, without shifting its reference.

Formal G21/L2 API cost has median 1.742x; three inputs exceed 2x. Full evidence and interpretation are under `data/research/runs/formal_map_comparison_v1/20261019-current44-v1/delivery/`, including `combined-report.ko.md`. Both comparison deliveries are complete. The independent eight-material set remains unopened; independent validation, final reference review, G21 Windows listening and application integration are outstanding.

The subsequent source-cost repair study executed 18 selection policies on the
formal44 cohort and twelve on broad2,604. Two tempo-preserving prototypes improve
formal/broad bar F1 from .806210/.801072 to .815747/.808510 and .817484/.804556,
respectively. They retain one formal bar regression each and 50/66 strict broad
bar regressions; neither is adopted. Quarter clocks and BPM changes are unchanged,
so this is a map-selection repair rather than new tempo-path recovery. Actual
implementations, negative trials and limits are described in
[the research study](AUTORESEARCH.md#source-cost-and-map-selection-repair-study).

No next algorithm architecture has been selected. Possible objective, search,
bar-role or initialization changes are questions for review, not established
solutions. The [review brief](RESEARCH_REVIEW.md#questions-and-possible-directions-for-review)
states these proposals separately from recorded findings. Selected source and
aggregate results are included in [the review snapshot](../reference/decoder_review/README.md);
full data-dependent reproduction still requires the original local artifacts.

## Implementation and reproducibility

The maintained L2 entry delegates to the measured implementation in `experiments/beat_event_stability_v1/`. Several earlier packages supply active source, geometry and scoring helpers; their historical names do not make them unused. G21 is retained as a separate frozen research implementation.

Comparisons preserve source/configuration provenance, original timing, failures and cohort denominators. Reference labels stay separate from inference inputs. Detailed metrics, earlier decoder comparisons and local reproduction requirements are in [AUTORESEARCH.md](AUTORESEARCH.md); data paths and distribution limits are in [LOCAL_DATA.md](../tools/LOCAL_DATA.md).
