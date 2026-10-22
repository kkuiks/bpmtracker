# Beat-event map research v1

**Current role:** shared source preparation, legal beat-boundary search, mismatch gate and native metrics for the selected L2 baseline. E0-E3 remain earlier recorded comparisons. See [the code map](../../docs/CODE_MAP.md).

Recorded redesign and resilient verification, 2026-10-12. This is an
isolated experiment; the DAW Analyze command and fixed estimator are unchanged.

The intended unit is a musical beat and a source-supported evidence run, rather
than a fixed wall-clock analysis block. Source pulse runs grow with observations
and end when accumulated incompatible evidence exceeds their source-noise model.
They supply proposed rates/phases, never independent output phase anchors.
Initial hypotheses include coherent opening runs and existing audio-only family
proposals. Later source runs can contradict those hypotheses. Taps select only
an audio-created discrete initial counting role; their numeric values are dropped.

The map search compares legal old-beat boundaries throughout a currently held
region. Tempo changes preserve bar position; a signature change can close a
partial old bar. Every candidate's new phase is derived from the shared beat.
The search has no first-12-second prohibition, fixed 24-second initialization,
two-second boundary blocks, three-beat-per-block restriction or wall-clock hold
timer. Numerical matching widths and candidate/beam budgets remain explicit
computational/model choices; removing time windows does not make inference exact.

Mechanics v0 exposed a short out-and-back failure before real target scoring.
Corrective iterations preserve intermediate source fits, retain pending paths
whose next declaration may complete an explanation, and integrate pseudo log
evidence by observed information mass. Pending-path ranking then used the complete
observed prefix. Failed controls and frozen code remain in the earlier snapshots.
This is not a calibrated probability model.

E0 is an unselected diagnostic without a mismatch gate. The final run compares
E1 (mismatch gate), E2 (gate plus per-observation rhythmic-role mixture), and E3
(E2 plus the nearest octave-related quarter rate for each proposed source pulse
clock). E3 is not a global octave-change prohibition: weak harmonic proposals can
still cause octave flips. Tempo and meter evidence remain separate. Weak or
absent evidence keeps the active click; it does not mute a known clock.

Run source preparation before reading taps or references. Freeze each iteration
before prediction; preserve failed outputs and explanations. Pilot changes must
be tied to diagnosed generic failures, not per-song thresholds. Complete-song
metrics, synthetic mechanics, oracle diagnostics and execution audits are distinct.
All recordings are known development material; there is no unseen claim.

Final comparisons use current accepted maps, the existing common fixed cohort
(also a Red-Miso-excluded fixed12 view), actual variable10 and meter5. Native
listening pairs contain original Linear audio and the ordinary project metronome,
with no click-audio track or timestamp-preview adapter. Windows audible playback
requires separate validation and must not be inferred from serialization checks.

The completed run is
`data/research/runs/beat_event_map_v1/20261012-full-v4/`: 33 known recordings,
99 fits and 297 serialized maps. Main32 excludes the model-seeded Dillinger
diagnostic. Four representation controls and 12 synthetic fits pass; all final
maps are legal, retain clicks, and satisfy 198 same-unit equality checks. Eight
native projects pass actual renderer/worklet comparison for 8,330 clicks. Windows
media decoding and audible playback remain untested.

The intended real-variable improvement was not achieved. On variable10, E3 pulse
accuracy is 69.56% versus C1 71.63%; stable joint pulse/bar validity is 26.73%
versus 48.91%. Strict canonical tempo transitions fall from 8/33 to 5/33.
Fixed12 excluding Red Miso improves from C1 96.27% to E3 98.68% pulse accuracy,
but the original fixed estimator still scores 100%. Reduced false declarations
do not establish correct variable tracking. E3 must not replace app inference.

Fifteen oracle-initial-map fits are diagnostic only. Providing correct initial
BPM, meter and phase does not solve later tracking. Preserve the physical map
contract; investigate coherent neural rhythmic roles, grid-density scoring and
joint initial selection before another full run. The Korean analysis and native
listening instructions are `report.ko.md` and `listen-projects/README.ko.md` in
the completed run. Proposed follow-ups are not an instruction to start work.
