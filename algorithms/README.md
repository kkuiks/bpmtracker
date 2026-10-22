# Algorithm entry points

The maintained variable-tempo entry is [`variable/baseline.py`](variable/baseline.py). It selects **L2_DENSE_PROPOSALS** and delegates to the measured fitter in [`experiments/beat_event_stability_v1`](../experiments/beat_event_stability_v1/README.md).

The Windows application's Analyze Audio command uses the [fixed estimator](../experiments/metronome_reconstruction_v1/README.md). It returns one quarter BPM, one signature and one audio-relative downbeat offset. Variable research instead represents a continuous piecewise-constant tempo/signature map, with one initial phase and accumulated quarter position.

**G21** is the preserved evaluated comparison candidate. It extends source-derived initial candidates and metrical-role evidence, then compares its complete map with L2 under the original source cost. It uses the same Beat This observations without neural retraining. Subsequent selection refiners remain experimental; none has replaced the maintained L2 entry or application analyzer.

The [development guide](../docs/DEVELOPMENT.md) summarizes current results and limits. The [code map](../docs/CODE_MAP.md#current-g21-research-snapshot) locates the frozen candidate, and [research documentation](../docs/AUTORESEARCH.md) defines metrics, full versus held search, reference scope and reproduction requirements.

The five-dataset decoder comparison completed on 2,604 qualified audio/feature inputs. At the primary 30ms tolerance, strict-cohort pulse F1 was G21 .83479, L2 .83287 and fixed .78940; bar F1 was .80107, .79962 and .76148. These are provider-label agreement scores under discrete initial-unit assistance, with different pulse/bar denominators. G21's small average gain includes regressions and a median 1.65x L2 API cost. Feature-only and waveform conditions, failed-input denominators and original code/configuration remain distinct.

The separate formal44 comparison is also complete. Accepted quarter/bar F1 is G21 .88657/.80621, L2 .88290/.79213 and fixed .85209/.80498, with median G21/L2 API cost 1.74x. These known-material grid scores include bar regressions and tolerance-dependent rankings; G21's formal bar average is nearly tied with fixed. Application adoption and independent variable/meter validation remain outstanding.

Eighteen post-comparison scoring/selection policies were evaluated on formal44,
twelve also on broad2,604. Two tempo-preserving refiners improve some bar means
but retain substantial per-input regressions and leave tempo-change detection
unchanged. Their results are development evidence, not a selected new baseline.

The [review brief](../docs/RESEARCH_REVIEW.md) describes current methods, results
and unselected research questions. [Review source copies](../reference/decoder_review/README.md)
make G21 and the refiners inspectable from a source-only checkout. The original
local run paths remain the measured execution locations.
