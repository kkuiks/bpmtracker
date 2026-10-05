"""Read explicit SMF timing without inventing a meter or audio-source origin.

Returned seconds start at MIDI tick zero. A native export/source binding is
required separately before these times can be evaluated against source audio.
"""
from bisect import bisect_right
from pathlib import Path

import mido

from .prepare import digest


def _unique(values, label):
    by_tick = {}
    duplicates = 0
    for tick, value in values:
        if tick in by_tick:
            if by_tick[tick] != value:
                raise ValueError(f'conflicting simultaneous {label}')
            duplicates += 1
        by_tick[tick] = value
    return sorted(by_tick.items()), duplicates


def read_timing(path):
    midi = mido.MidiFile(path)
    if midi.type not in (0, 1) or midi.ticks_per_beat <= 0:
        raise ValueError('synchronous positive-PPQ MIDI required')
    tempos, meters = [], []
    note_count = end_tick = 0
    for track in midi.tracks:
        tick = 0
        for message in track:
            tick += message.time
            if message.type == 'set_tempo':
                if message.tempo <= 0:
                    raise ValueError('positive explicit tempo required')
                tempos.append((tick, message.tempo))
            elif message.type == 'time_signature':
                if message.numerator <= 0 or message.denominator <= 0:
                    raise ValueError('positive signature required')
                meters.append((tick, (message.numerator, message.denominator)))
            elif message.type == 'note_on' and message.velocity > 0:
                note_count += 1
        end_tick = max(end_tick, tick)
    tempos, tempo_duplicates = _unique(tempos, 'tempos')
    meters, meter_duplicates = _unique(meters, 'signatures')
    if not tempos or tempos[0][0] != 0:
        raise ValueError('explicit tick-zero tempo required; no default120 inserted')
    ticks = [tick for tick, _ in tempos]
    tpq = midi.ticks_per_beat
    origins = [0.]
    for (ta, ua), (tb, _) in zip(tempos, tempos[1:]):
        origins.append(origins[-1] + (tb-ta)*ua/(1e6*tpq))

    def seconds(tick):
        i = bisect_right(ticks, tick)-1
        return origins[i] + (tick-ticks[i])*tempos[i][1]/(1e6*tpq)

    return dict(
        native_file_sha256=digest(Path(path)), ticks_per_quarter=tpq,
        midi_type=midi.type, note_on_count=note_count, end_tick=end_tick,
        end_midi_seconds=seconds(end_tick),
        tempo_events=[dict(tick=t, quarter=t/tpq, midi_seconds=seconds(t),
                           microseconds_per_quarter=u, bpm_quarter=60e6/u)
                      for t, u in tempos],
        meter_events=[dict(tick=t, quarter=t/tpq, midi_seconds=seconds(t),
                           numerator=n, denominator=d) for t, (n, d) in meters]
                     if meters else None,
        identical_simultaneous_tempo_duplicates=tempo_duplicates,
        identical_simultaneous_meter_duplicates=meter_duplicates,
        explicit_initial_meter=bool(meters and meters[0][0] == 0),
        audio_source_origin_seconds=None, bar_anchor_quarter=None,
        source_binding_required=True,
    )
