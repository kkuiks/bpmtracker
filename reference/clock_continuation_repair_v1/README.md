# Source-clock continuation repair

**Reference status, 2026-10-13:** this completed study was moved intact to the reference area. Historical commands and decisions below are evidence, not current defaults or new execution requests. See [reference index](../README.md) and [current development](../../docs/DEVELOPMENT.md).

Recorded correction and fixed-estimator comparison on2026-10-11.
Confidence/unknown states preserve the existing click grid.
The preceding composer could discard an entire backward decoded half when the
initial-unit constraint eliminated its path. The accepted-map list then lacked
the prefix; later octave correction never reconstructed it.

`repair.py` repairs raw-map gaps before unchanged5% half/double correction.
For leading gaps it selects the already prepared initial source clock in the
provided discrete unit, or an earliest qualified matching episode. If no episode
qualifies, retain an acoustically supported early candidate and report low
confidence. No reference BPM/phase/boundary or continuous tap reaches the repair.
Internal/tail gaps hold the last corrected physical rate and phase. Existing raw
accepted intervals remain intact before folding. Confidence is preserved as
metadata and never mutes an already available clock. A recording with no acoustic
clock cannot acquire one from a tap.

This is an isolated research implementation, not app integration. The prior
composer, fixed estimator, source banks, raw maps, accepted references and frozen
runs are untouched. No audio decoding, neural inference, training, new inputs,
post-score tuning or source Git mutation is required.

Primary method:R1_FOLD_CONTINUE with initial-unit proxy100. R0_RAW_CONTINUE is a
component diagnostic. Same-unit97/100/103% proxies must produce identical maps.
Evaluation reuses the latest coherent multiple-reading/change policy unchanged.
Compare the same historical13 complete fixed recordings against their existing
fixed-estimator results; also score all33 complete recordings (32 non-seeded main,
10 actual variable songs). Coverage, valid continuity, unnecessary changes and
genuine transition diagnostics remain distinct. Full meter prediction is absent.

Run with `.venv-metronome-v1/bin/python -m
experiments.clock_continuation_repair_v1.MODULE`:controls --output PATH,
prepare [--run RUN],worker --run RUN [--shard N --shards2],evaluate --run RUN.
Stages are sequential except independent worker shards. Code/input freezes,
actual source read hooks, source-clock membership, raw-span preservation, complete
coverage and same-unit comparisons are part of this authorized repair comparison.

## Completed result — 2026-10-11

Run:`data/research/runs/clock_continuation_repair_v1/20261011T114302Z-v1/`.
All198 new maps have continuous full-source output and pass retained-clock/raw-span
contracts. Ten authored functional controls,66 same-unit pairs and335 unchanged
input hashes passed; source read hooks recorded zero forbidden reference reads.

Primary fixed13 stable score:fixed estimator100%, prior fold85.61%, repaired
fold93.26%. Useful songs13/13 ->9/13 ->10/13. Coverage100% after repair, but
unnecessary changes4 ->6; restored prefixes expose additional switching.
Common Sense52.52 ->100%, Red Miso54.14 ->68.71%, Waiting Room28.87 ->65.98%,
Prayer Position unchanged77.67%. Remaining gap to the fixed estimator6.74pp.
Gap filling without octave correction yields85.83% and11 unnecessary changes;
repairing before correction matters for consistent counting.

Main32 stable84.05 ->91.02%; actual variable10 stable83.75 ->87.90%, with11
unnecessary changes unchanged and useful songs still2/10. The variable gain is
almost entirely Archspire's prefix recovery31.01 ->72.38%; strict canonical
transitions0/33 ->1/33. Walker17.93 ->100% uses permitted128 compound-binary
clicks against96 quarter·6/8; it is not literal meter-map recovery or fixed13.
Unassisted fixed13 remains91.49 ->91.51%:no original large prefix gaps there.

This repairs the demonstrated output-loss contract, not all clock selection or
variable-boundary errors. Keep musical validity and unnecessary switches separate
from emission continuity. No post-score tuning, new model learning or app adoption.
The Korean assessment and all song results are in the run's `report.ko.md`.
