# Continuous native beat map v1

**Current role:** shared continuous map contract, actual grids, native project conversion and audio scoring. The earlier time-window fitter described below is historical; the selected L2 uses adaptive evidence and existing-beat search. See [current development](../../docs/DEVELOPMENT.md).

Owner-approved redesign: one initial audio-supported tempo, meter and bar phase,
then tempo/signature declarations only on the preceding map's notated beats.
Tempo changes preserve the current bar. A signature may close a partial bar and
start a new bar on the same physical beat. Confidence never interrupts the grid.

`core.py` uses retained source event peaks, fixed-model audio families and old
candidate tables as proposals. It recomputes all map scores at the derived phase;
the previous segment phases never become output anchors. A bounded beam jointly
selects tempo and eight scoped signatures. An unchanged-map path competes with
changed paths without a constant-tempo assumption about the recording. This is
research; it does not replace the fixed estimator or the DAW Analyze command.

Run preparation freezes source code, protocol and retained inputs. Source workers
prepare counting-unit candidates before evaluation-side simulated taps. Only an
opaque unit ID reaches map fitting. Initial +/-3% taps are proxies, not measured
human performance. Same-unit packets must give identical complete predictions.

Commands, in order, from the checkout with the existing metronome environment:

```sh
.venv-metronome-v1/bin/python -m experiments.continuous_beat_map_v1.controls
.venv-metronome-v1/bin/python -m experiments.continuous_beat_map_v1.prepare
.venv-metronome-v1/bin/python -m experiments.continuous_beat_map_v1.worker --run RUN --stage prepare
.venv-metronome-v1/bin/python -m experiments.continuous_beat_map_v1.encode --run RUN
.venv-metronome-v1/bin/python -m experiments.continuous_beat_map_v1.native --run RUN --audit-references
.venv-metronome-v1/bin/python -m experiments.continuous_beat_map_v1.worker --run RUN --stage predict
.venv-metronome-v1/bin/python -m experiments.continuous_beat_map_v1.evaluate --run RUN
.venv-metronome-v1/bin/python -m experiments.continuous_beat_map_v1.native --run RUN
```

Source workers accept `--shard`/`--shards`; this parallelizes computation, not
agent work. Evaluation compares all 33 retained recordings (32 main plus one
model-seeded diagnostic), the same 10 actual variable recordings, and common 13
fixed controls. New native meter/bar scores are separate from prior quarter-pulse
scores. Permitted rhythmic readings do not pardon unnecessary output changes.
Reference conversion reports incompatible clocks without shifting, resnapping or
removing accepted references. Listening pairs contain one unchanged Linear audio
track and the actual native map, with no click audio tracks or timestamp preview.
