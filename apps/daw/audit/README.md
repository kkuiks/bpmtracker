# Current native-map checks

These three tools check the continuous tempo/signature model and native listening
exports. Run them only as part of an focused check; ordinary builds and
launches do not run them.

| Tool | Scope |
| --- | --- |
| [continuous-map.cjs](continuous-map.cjs) | Renderer/map geometry and source-preserving declarations |
| [continuous-map-backend.py](continuous-map-backend.py) | Python map/export geometry adapter |
| [continuous-map-projects.cjs](continuous-map-projects.cjs) | Project validator, actual renderer and metronome worklet against exported maps |

The project audit explicitly does not decode or audibly play source audio.
Its passing click geometry did not cover the cache-rate bug fixed in 0.6.15.
Build, metronome geometry and actual Windows media playback are separate evidence.

Recorded integration checks, UI refinements, launch checks and their fixtures
are retained in [`../reference/audits`](../reference/audits/README.md).
The complete native L2 audition pack remains at
`data/research/runs/native_listening_review_v1/20261012-L2-all-weak-v1/`.
