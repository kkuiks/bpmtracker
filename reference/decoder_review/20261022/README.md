# G21 and selection-repair source snapshot

Prepared for source review on 2026-10-22 from experiments completed by 2026-10-20.
The [review brief](../../../docs/RESEARCH_REVIEW.md) summarizes current behavior,
results, reference limitations and open questions.

| Path | Role |
| --- | --- |
| [g21_full/candidate_api.py](g21_full/candidate_api.py) | Initial enrichment, root retention, FULL search and final L2 source-cost comparison |
| [g21_full/candidate_core.py](g21_full/candidate_core.py) | Source-supported changes, local evidence, approximate path search and pruning |
| [g21_full/candidate_emissions.py](g21_full/candidate_emissions.py) | Pointwise emissions, expected-bar ticks and accent-role evidence |
| [g21_full/parameters.json](g21_full/parameters.json) | Measured configuration |
| [selection_repair/source_scores.py](selection_repair/source_scores.py) | Legacy/pointwise/role decomposition and boundary code |
| [selection_repair/prefix_api.py](selection_repair/prefix_api.py) | Tempo-preserving trailing meter refinement, including candidate A |
| [selection_repair/phase_api.py](selection_repair/phase_api.py) | Quarter-preserving initial bar rotations and suffix pool |
| [selection_repair/hierarchical_predictor.py](selection_repair/hierarchical_predictor.py) | Literal-bar initial phase, role-aware suffix selection, including candidate B |
| [selection_repair/repair_api.py](selection_repair/repair_api.py) | Full-pool criterion interventions, including unsuccessful policies |
| [evaluation](evaluation/) | Original broad/formal grid scorers and shared event arithmetic |
| [evaluation-summary.json](evaluation-summary.json) | Selected aggregate metrics, denominators, regressions and interpretation limits |
| [policy-comparison.csv](policy-comparison.csv) | All 18 new policies plus three controls; empty broad fields mean not evaluated there |
| [manifest.json](manifest.json) | Original relative source paths, byte counts and SHA-256 identities |

## Use and reproduction boundary

Application identifiers in the review copies use the current BPMTracker name.
Configuration and algorithm parameters are unchanged. The manifest distinguishes
current copy hashes from recorded original hashes where naming changed.
Path calculations, imports and recorded evaluation metadata are retained
for review. **Do not use this folder as a relocated runtime package.** In
particular, repair imports and the formal evaluator's support table still depend
on their original run environment. The hierarchy predictor imports its literal
bar-scoring helper from the included `run_hierarchical_phase.py`; that driver is
included to expose the exact executed code, not to start another campaign.

For recorded execution, use the original paths in the manifest with the original
anonymous source packets, observations, reference support and environment.
Frozen run references and results have not been rewritten. No full reproduction
from a source-only checkout is claimed.

Shared L2/source/geometry dependencies remain in `experiments/` and the maintained
entry remains in `algorithms/variable/`. Additive G21 costs do include an
expected-bar penalty although some snapshot comments/metadata say otherwise.
Some prototype module descriptions refer to inherited earlier experiments;
actual FULL behavior is described by the executed API/configuration and review
brief, not those stale labels.

The summary describes assisted, known-material development results. Provider
event agreement, accepted formal-grid agreement, earlier C/P/V/W metrics and
independent generalization are not interchangeable. A/B retain per-input losses
and have not replaced L2, G21 or the application's fixed analyzer.
