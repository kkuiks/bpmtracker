# Sample-map review and conversion

The shared `daw_map_reference.mjs` converter materializes editable DAW maps into audio-relative references using the same timing functions as the application. It preserves source/native geometry and separates quarter-based evaluation pulses from notated-denominator audition pulses.

## DAW review

Use **Samples** for formal recordings and the [candidate-review workflow](../ntm_collection/README.md#prepare-and-review-a-batch-in-bpmtracker) for newly acquired sources. Original audio, supplied clocks, editable drafts and accepted references remain separate.

An alignment-only revision preserves the existing tempo/signature map. A revision that changes BPM, signature events or bar phase uses the saved DAW geometry rather than an offset-only source finalizer. The reference record retains source identity, total offset, reviewed intervals, unknown margins and map provenance. A saved draft does not change formal membership or previous evaluation results.

Completed dated registration and offset-audit scripts are indexed in [reference/sample_operations](../../reference/sample_operations/README.md). Their fixed inputs and completed receipts describe historical operations rather than a general registration API. The catalog remains the membership authority.

## Retained browser workflow

The optional browser tool reviews a prepared formal catalog without copying original media:

```sh
data/runtime/ntm-collector/venv/bin/python -B tools/sample_review/prepare.py \
  --out data/samples/reviews/<review-id>
python3 -B tools/sample_review/serve.py \
  --root data/samples/reviews/<review-id> --port 9010
```

Open `http://localhost:9010/`; remote workspaces can forward port 9010. Preparation reads native audio headers and selected reference files. Small reference fingerprints bind decisions to file versions; preparation does not decode source archives or run inference.

Audio and reference clicks share a Web Audio sample clock. Stored audio-relative events already include their source offset. The adjustable comparison offset is relative to that displayed map. Pulse modes, quarter/group/bar alternatives, exact stored tempo/meter values, repeated events and supported intervals remain explicit. These displays assist listening rather than establish automatic musical correctness.

Review decisions are saved to `review-records.json` and append-only `review-history.jsonl`, with reference versions and reviewed scope. Confirmation records cover listening, tempo, meter, alignment and coverage; a current-map confirmation uses zero comparison offset and resolved item verdicts. Playback intervals alone do not establish acceptance. Candidate review does not enroll a recording or revalidate a formal reference.

The loopback server uses an exact asset allowlist, stops serving changed source assets and rejects decisions for changed versions. Saving review results does not rewrite accepted references, membership, frozen experiments or predictions. Listening supports practical musical acceptance within its stated scope rather than independently certifying a producer clock at millisecond precision.
