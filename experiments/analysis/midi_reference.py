"""Read an intended MIDI quarter-note clock without estimating tempo from audio.

MIDI clock labels describe the authored timeline, not human beat annotations or
sample-exact instrument attacks. Explicit meter and source alignment are audited
separately; no prediction-based offset or octave selection is applied.
"""

from pathlib import Path

import mido
import numpy as np

from inspect_inputs import sha256


def unique_events(events, default):
    by_tick = {}
    for tick, value in events:
        if tick in by_tick and by_tick[tick] != value:
            raise ValueError("conflicting simultaneous MIDI clock events")
        by_tick[tick] = value
    if 0 not in by_tick:
        by_tick[0] = default
    result = []
    for tick,value in sorted(by_tick.items()):
        if not result or result[-1][1] != value:
            result.append((tick,value))
    return result


def read_clock(path, note_span_ticks=None):
    midi = mido.MidiFile(path)
    if midi.type not in (0,1) or midi.ticks_per_beat <= 0:
        raise ValueError("requires a synchronous PPQ MIDI file")
    tempos, meters, onsets, note_ends = [], [], [], []
    tick = 0
    for message in mido.merge_tracks(midi.tracks):
        tick += message.time
        if message.type == "set_tempo":
            if message.tempo <= 0:
                raise ValueError("tempo must be positive")
            tempos.append((tick, message.tempo))
        elif message.type == "time_signature":
            meters.append((tick, (message.numerator, message.denominator)))
        elif message.type == "note_on" and message.velocity > 0:
            onsets.append(tick)
        elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            note_ends.append(tick)
    if not onsets or not note_ends:
        raise ValueError("MIDI has no note span")
    explicit_initial_tempo = any(t == 0 for t,_ in tempos)
    explicit_initial_meter = any(t == 0 for t,_ in meters)
    tempos = unique_events(tempos, 500000)
    meters = unique_events(meters, (4,4))
    ticks = np.array([t for t,_ in tempos], dtype=float)
    seconds_per_tick = np.array([v/1e6/midi.ticks_per_beat for _,v in tempos])
    origins = np.r_[0., np.cumsum(np.diff(ticks)*seconds_per_tick[:-1])]

    def seconds(values):
        values = np.asarray(values, dtype=float)
        index = np.searchsorted(ticks, values, side="right")-1
        return origins[index]+(values-ticks[index])*seconds_per_tick[index]

    start_tick, end_tick = (min(onsets), max(note_ends)) if note_span_ticks is None else note_span_ticks
    if start_tick < 0 or end_tick <= start_tick:
        raise ValueError('invalid note support')
    quarter_ticks = np.arange(0, end_tick+1, midi.ticks_per_beat, dtype=float)
    quarter_ticks = quarter_ticks[quarter_ticks >= start_tick]
    down_ticks = []
    supported_meter = explicit_initial_meter and all(den == 4 for _,(_,den) in meters)
    boundary_valid = True
    for index,(start,(num,den)) in enumerate(meters):
        stop = meters[index+1][0] if index+1 < len(meters) else end_tick+1
        bar_ticks = midi.ticks_per_beat*4*num/den
        if index+1 < len(meters) and not np.isclose((stop-start)/bar_ticks, round((stop-start)/bar_ticks), rtol=0, atol=1e-7):
            boundary_valid = False
        down_ticks.extend(np.arange(start, stop, bar_ticks).tolist())
    down_ticks = np.asarray(down_ticks)
    down_ticks = down_ticks[(down_ticks >= start_tick)&(down_ticks <= end_tick)]
    support = seconds([start_tick,end_tick]).tolist()
    tempo_rows = [{"tick": int(t), "time_seconds": float(seconds(t)), "microseconds_per_quarter": int(value),
                   "bpm_quarter": 60e6/value} for t,value in tempos]
    meter_rows = [{"tick": int(t), "time_seconds": float(seconds(t)), "numerator": num, "denominator": den}
                  for t,(num,den) in meters]
    return {
        "kind": "authored_midi_quarter_clock", "midi_sha256": sha256(path),
        "ticks_per_quarter": midi.ticks_per_beat, "explicit_initial_tempo": explicit_initial_tempo,
        "explicit_initial_meter": explicit_initial_meter, "tempo_events": tempo_rows, "meter_events": meter_rows,
        "evaluation_support_seconds": support, "source_origin_shift_seconds": 0,
        "note_span_ticks": [int(start_tick), int(end_tick)],
        "beats_seconds": seconds(quarter_ticks).tolist(),
        "downbeats_seconds": seconds(down_ticks).tolist() if supported_meter and boundary_valid else None,
        "downbeat_label_status": "explicit_simple_meter_bar_clock" if supported_meter and boundary_valid else "excluded_missing_compound_or_unaligned_meter",
        "annotation_caveat": "Intended MIDI clock; musical pulse interpretation and instrument attack latency are not human-verified.",
    }


def clocks_agree(left, right, tolerance_seconds=1e-5):
    for kind in ("tempo_events", "meter_events"):
        if len(left[kind]) != len(right[kind]):
            return False
        for a,b in zip(left[kind], right[kind]):
            if abs(a["time_seconds"]-b["time_seconds"]) > tolerance_seconds:
                return False
            fields = ("microseconds_per_quarter",) if kind == "tempo_events" else ("numerator","denominator")
            if any(a[key] != b[key] for key in fields):
                return False
    return True
