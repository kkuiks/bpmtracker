# Pinned-initial step-tempo preparation

This research module creates a separate, measured continuation baseline. It
retains L2's source observations, dense-proposal filter, internal score, mismatch
gate and path budgets. Only the initial map is pinned to a preserved source-fitted
L2 result and all later signature proposals are suppressed before truncation.
It also produces a constant map from that exact initial state. Historical L2
outputs are copied byte-for-byte and rescored; they are not the direct baseline.

The source worker receives opaque recording keys, fixed observation/candidate
inputs and an inferred initial map. It never imports the output evaluator and
audits data reads against an exact allowlist. Separate evaluation processes use
the immutable references, selection and package 0.2 objective. Numerical limits
remain proposals, and tolerance sensitivity is not algorithm improvement.

Use the existing research virtual environment. For a fresh run:

```bash
.venv-metronome-v1/bin/python -m algorithms.variable.autoresearch_step_v1.prepare \
  --run <new-absolute-run-path> --package <extracted-package-path> \
  --selection <prespecified-selection.json> --baseline-run <preserved-L2-run>
.venv-metronome-v1/bin/python -m algorithms.variable.autoresearch_step_v1.run --run <run>
.venv-metronome-v1/bin/python -m algorithms.variable.autoresearch_step_v1.evaluate --run <run>
.venv-metronome-v1/bin/python -m algorithms.variable.autoresearch_step_v1.review --run <run>
```

Preparation refuses existing run paths, outputs refuse overwrites, and the driver
can resume completed worker receipts. A code/input/reference change requires a
new run. Never edit a freeze to accept changed code. The timing diagnostics in
`review` use known later reference rates only for listening and tolerance review;
they are explicitly excluded from inference and aggregate candidate results.

This module performs no optimizer search, neural retraining, sample acquisition,
reference editing, source Git publication or application integration.
