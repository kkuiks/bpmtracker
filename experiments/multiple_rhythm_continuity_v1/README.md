# Multiple pulse readings with change accountability

**Current role:** accepted-reading and evaluation helpers reused by current native metrics. Earlier inference directions are historical; [L2](../beat_event_stability_v1/README.md) is the development standard.

Owner-authorized rerun of the latest local octave-fold comparison on2026-10-11.
The owner permits multiple musically plausible readings but prohibits excusing
unnecessary switches by retrospectively choosing another reference at every time.
This isolated experiment keeps all five latest inference/correction arms unchanged.

All33 currently formal complete recordings are included. Original21 source maps
and clocks are reused;12 additional complete recordings receive the same source
pipeline. One model-seeded accepted reference is a separate diagnostic, so32
complete recordings form the main summary. All12 additions are constant-tempo,
constant-signature controls, including one compound-meter song and one seeded
diagnostic; they do not increase the10 actual variable-tempo songs or the5
meter-changing songs. Juno uses its new constant108 map. All
material is previously known, not a new blind corpus; no provider acquisition,
new neural architecture/weights, training, app changes or source Git publication.

Primary permissible readings:quarter, half with either retained parity, double,
notated denominator, compound large beat, and binary subdivision of that large
beat. These deterministic reference-derived rules are an operational evaluation
policy, not individual new listening certificates or a meter-prediction claim.
Broader3:2/4:3/triple/offbeat/pair-grouping readings are sensitivity diagnostics.
The accepted physical reference files and their scopes are unchanged.

A reference BPM/signature region gets one reading over its complete duration,
never one choice per predicted interval or instant. A single whole-song reading
is also reported. Original rate/phase events are counted before interpretation.
Changes explaining the same reference reading across an actual structural edge
within4s are distinguished from unnecessary switches, recovery from invalid
clocks and unsupported changes. Minor phase adjustments remain visible.

The primary stable score removes8s after every unnecessary change from otherwise
coherent valid time;4s/16s variants report this policy sensitivity. No output is
muted. Useful-song classification requires>=85% stable valid time,>=95% coverage
and zero unnecessary changes. Old exact-quarter/phase metrics remain alongside
the relaxed metrics; a held pulse can be valid across genuine octave changes
without being an exact tempo/meter map. Full meter prediction is not available.

Initial reference-derived proxies are97/100/103%, encoded only after all audio
clocks/scores are prepared. Numeric values are discarded. Same-unit pairs must
produce identical maps; any proxies crossing discrete units remain reported as
initialization sensitivity. These are not measured human taps.

Use `.venv-metronome-v1/bin/python -m
experiments.multiple_rhythm_continuity_v1.MODULE --run RUN`. Stages:prepare,
controls,freeze --stage code,worker --stage prepare,freeze --stage sources,
encode,worker --stage predict,audit,evaluate,report. Source stages support two
shards. Actual source read hooks, frozen used-input hashes, unchanged bank/edge
contracts and cached21-map replay checks are part of this requested experiment.
No post-score settings/model changes or promotion of a winning alternate arm.

Primary criteria/settings are frozen in `common.py`; source code snapshots,
normalized current reference/schema candidates, source arrays, clocks, traces,
serialized maps, change labels and figures persist under
`data/research/runs/multiple_rhythm_continuity_v1/`.

The distinction between literal and alternate metrical readings is motivated by
the [official mir_eval beat documentation](https://mir-eval.readthedocs.io/latest/api/beat.html).
This custom coherent-region/change metric is not an implementation of standard
AML, and these results must not be quoted as standard benchmark scores.

## Completed result — 2026-10-11

Run:`data/research/runs/multiple_rhythm_continuity_v1/20261011T102117Z-v1/`.
All396 serialized outputs were scored. The16 authored policy controls and the
required source/output audit passed;404 frozen input hashes were unchanged.
Of the12 added sources,8 reused identity-bound official observations and4 ran
fresh official CPU observations. No model learning or post-score tuning occurred.

On the32 non-seeded recordings with the initial-unit proxy, primary folding
improved mean coherent stable-valid time from78.78% to84.05%, reducing unnecessary
changes from39 to24. Ten songs improved,22 were unchanged and none worsened.
Useful-song criteria were met by15/32 instead of11/32. Merely rejecting the
near-half/double proposal gave81.32% and20 unnecessary changes, but harmed actual
variable-tempo tracking:77.27% versus the raw81.97% on10 variable songs.

Primary folding's variable10 gain was only81.97% ->83.75%, with useful songs
1/10 ->2/10. Added independent controls improved79.25% ->81.89%; the entire
additional mean gain came from Neck Deep. Thus the component gates passed, but
this is not a general variable-tempo/meter solution or unseen validation.

Juno's new evaluation gives raw52.58% ->fold63.13% with unnecessary changes3 ->1;
the held-clock arm is better on this song at70.36%. Wrong click phase remains.
Millions gives83.86% ->98.02% with unnecessary changes2 ->0; its raw half-rate
120 ->125 sequence already follows the genuine240 ->250 change under the new
reading policy. The benefit is retaining a consistent counting unit.

Keep this limited half/double protection as research evidence. Starting-clock
availability, phase preservation, actual change timing and other pulse groupings
remain separate problems. App adoption and any follow-up experiment are proposals.
See `interpretation.ko.md` for the Korean assessment and limitations,
`report.ko.md` for all song rows, and `metrics.json` for preserved diagnostics.
