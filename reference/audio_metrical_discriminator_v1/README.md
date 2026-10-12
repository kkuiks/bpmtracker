# Original-audio metrical discriminator

**Reference status, 2026-10-13:** this completed study was moved intact to the reference area. Historical commands and decisions below are evidence, not current defaults or new execution requests. See [reference index](../README.md) and [current development](../../docs/DEVELOPMENT.md).

Owner-authorized on 2026-10-11 after the role/meter selector failed its focus gate.
This study asks whether original-audio relative accent/repetition patterns provide
information for choosing quarter-unit interpretations. It is a component probe,
not a new tempo-map estimator or application model replacement.

Native local pulse clocks come from the retained source-only physical clock bank.
Candidate unit relations are prepared before tap input. Four audio frequency bands
provide onset-accent autocorrelation and circular bar profiles across 2/3/4/5/6/7/8
quarter spans. Their spectral magnitudes, relative low/high accent phases and
initial-pattern differences are tempo-normalized features, not a certified kick/
snare transcription. No whole-song constant BPM or fixed4/4 template is assumed.

Five small conditional linear rankers compare neural-only, audio-only, initial
audio-pattern and combined observations. Eleven known recordings are used for
fitting and song-group cross-validation; ten other known recordings (five variable,
two meter-only, three fixed) are validation. Twenty-four inherited authored music
controls are not trained. All material has been used previously; the new learner's
fitting split is disjoint, but this is not fresh unseen-music certification.

The complete split, regularizer search and decision criteria are frozen before
target feature extraction/scoring. The two confirmatory audio hypotheses are
audio-plus-initial-pattern and audio/neural-plus-initial-pattern versus the same
neural-only supervised ranker. Other arms are diagnostics, not post-hoc defaults.
Regularization/normalization are selected from development songs only. Training
reference labels are allowed for those songs; actual read hooks reject validation
feature/reference reads during fitting and all reference reads during prediction.

Reference-derived initial97/100/103% proxies are separately encoded after all
source features exist. Numeric tap values are discarded; only a source-relative
discrete unit index is used. Compound relationships are an explicit research
contract, not a change to the fixed app's octave-only input contract. Neither raw
tap BPM nor absolute candidate BPM is a learned feature. Initial unit inputs are
not imposed as a whole-song rate range or immutable neural multiplier.

Unit success means the selected source-relative candidate is within5% of the
reference quarter rate at the source-defined window center. This tolerance is
distinct from the +/-3% assumed tap variation and from exact nominal clock/phase/
boundary correctness. Unavailable/unrepresentable validation windows remain in
the denominator. Only supervised training filters low reference-window purity.
Fine BPM, physical phase, click F1 and complete change localization are not
claimed by this experiment.

Stages in the retained `.venv-metronome-v1`: `prepare`, `controls`, `freeze`,
`worker` (raw PCM/source features), `encode`, `labels` (development only), `train`,
`predict`, `evaluate`, `audit`, `report`. Every stage takes `--run`. Feature and
prediction workers may use two shards. Set BLAS threads to1 for deterministic,
bounded CPU execution. No dependency installation, fresh neural inference,
instrument separation, acquisition, playback tests or source Git publication is
part of the study. Original audio coordinates and accepted references remain.

Local artifacts are retained in `data/research/runs/audio_metrical_discriminator_v1/`.
Group-balanced coefficients, feature normalization, CV results, all candidate
features/rankings, references, code/model/input freezes and standalone figures
make the experiment reviewable.

The rhythmic observation hypothesis is motivated by
[rhythmic pattern modeling](https://ismir2013.ismir.net/wp-content/uploads/2013/09/51_Paper.pdf)
and [instrument-conditioned beat analysis](https://arxiv.org/abs/2209.07140).
Their results do not establish performance on this progressive/variable cohort.
This implementation is not a reproduction of either paper's complete model.

## Recorded outcome

Run: `data/research/runs/audio_metrical_discriminator_v1/20261011T070804Z-v1/`.
Start with `interpretation.ko.md`. All45 inputs were processed and900 predictions
scored. Eleven real songs fitted the rankers; ten others validated them. With
initial-unit assistance, the combined audio/neural ranker improved held-out
variable-song unit accuracy64.89 ->68.07%, versus its neural-only learned baseline.
The song-bootstrap gain interval is+1.43 to+5.62pp. This is a small positive
discriminative effect, not no information; both prespecified viability hypotheses
failed. Juno's true108 ->216 change with4/8 ->6/8 remains0% correct unit afterward.
Predictions mostly select144, numerically the dotted-quarter rate of216/6/8.

The combined model obtains100% unit accuracy on Over It and improves fixed/meter
controls, but the twenty-four authored music controls regress90.63 ->85.10%.
Unit relations are available for97.54% of held-out variable centers, and100% on
Juno; missing candidates alone do not explain failure. The dataset/feature model
does not establish robust compound-meter quarter interpretation. Train-time3:2
unit examples are scarce, and there is no actual2x tempo change in the six
development variable songs. Neither end-to-end clock nor app success is claimed.

Agent recommendation: do not connect this ranker as an adopted automatic decoder
or keep tuning the same representation. Retain the modest acoustic information
and source clock components; pause this automatic-extension research direction
unless materially different representation/data evidence is supplied. User review
of ambiguous musical units/meter is a product alternative requiring its own work,
not a completed semi-automatic feature or a project-wide abandonment decision.
