"""Actual PCM/MIDI export contracts using synthetic clocks, never song labels."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import mido
import numpy as np
import soundfile as sf

from complete_song_clock import rebuild_clock
from run_one_song_completion import export_midi, reference_clock, render_quarter_click


def fractional_clock():
    # Two short excursions occur inside one quarter interval. Integer-quarter
    # grid checks alone must not allow their MIDI boundaries to disappear.
    quarters = [0., 8.031337, 8.431391, 8.582917]
    periods = [60/205.123456, 60/210.654321, 60/81.25, 60/79.875]
    clock = rebuild_clock(quarters[1:], [0., periods[0], *np.diff(periods)], 14.)
    clock['meter'] = {'numerator': 4, 'denominator': 4, 'provenance': 'synthetic fixture'}
    return clock, quarters, periods


def independent_time(quarter, boundaries, periods):
    """Integrate explicit piecewise periods independently of clock_time()."""
    total = 0.
    for i, start in enumerate(boundaries):
        if quarter <= start:
            break
        end = boundaries[i+1] if i+1 < len(boundaries) else quarter
        total += max(0., min(quarter, end)-start)*periods[i]
    return total


def authored_reference():
    ticks = [0, 966, 1106]
    tempos = [500001, 490007, 500001]
    elapsed = 0.
    events = []
    for i, (tick, tempo) in enumerate(zip(ticks, tempos)):
        if i:
            elapsed += (tick-ticks[i-1])/480 * tempos[i-1]/1e6
        events.append({'tick': tick, 'time_seconds': elapsed, 'microseconds_per_quarter': tempo})
    return {'ticks_per_quarter': 480, 'source_origin_shift_seconds': 0,
            'tempo_events': events,
            'meter_events': [{'tick': 0, 'time_seconds': 0., 'numerator': 4, 'denominator': 4}]}


class OneSongExportTests(unittest.TestCase):
    def test_click_pcm_has_equal_timbre_absolute_positions_and_exact_length(self):
        rate, frames = 48000, 48000
        times = [0., .150003, .375, .9999]
        positions = np.rint(np.array(times)*rate).astype(int)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'click.wav'
            report = render_quarter_click(path, times, rate, frames)
            audio, actual_rate = sf.read(path, dtype='int16')
            self.assertEqual(actual_rate, rate)
            self.assertEqual(audio.shape, (frames,))
            self.assertEqual(sf.info(path).subtype, 'PCM_16')
            length = round(.020*rate)
            pulse = audio[:length]
            self.assertGreater(np.max(np.abs(pulse.astype(np.int32))), 0)
            for position in positions[1:-1]:
                np.testing.assert_array_equal(audio[position:position+length], pulse)
                self.assertEqual(audio[position-1], 0)
                self.assertEqual(audio[position], 0)  # sine starts at zero
                self.assertNotEqual(audio[position+1], 0)
            np.testing.assert_array_equal(audio[positions[-1]:], pulse[:frames-positions[-1]])
            self.assertTrue(np.all(audio[length:positions[1]] == 0))
            self.assertEqual(report['sample_frames'], frames)
            self.assertEqual(report['event_count'], 4)
            self.assertFalse(report['waveform']['accents'])
            self.assertLessEqual(report['onset_rounding_max_seconds'], .5/rate)

    def test_empty_click_track_is_full_length_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'silence.wav'
            render_quarter_click(path, [], 16000, 12345)
            audio, rate = sf.read(path, dtype='int16')
            self.assertEqual(rate, 16000)
            self.assertEqual(len(audio), 12345)
            self.assertFalse(audio.any())

    def test_click_rejects_invalid_events_before_writing(self):
        invalid = [[-.01], [1.], [.2, .1], [.2, .2], [float('nan')],
                   [float('inf')], [1-.25/48000], [[0.], [.1]]]
        with tempfile.TemporaryDirectory() as directory:
            for i, times in enumerate(invalid):
                with self.subTest(times=times):
                    path = Path(directory)/f'invalid-{i}.wav'
                    with self.assertRaises(ValueError):
                        render_quarter_click(path, times, 48000, 48000)
                    self.assertFalse(path.exists())

    def test_click_rejects_invalid_sample_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            for i, (rate, frames) in enumerate([(0, 100), (-48000, 100), (48000, 0), (48000, -1), (48000, 100.5)]):
                with self.subTest(rate=rate, frames=frames):
                    path = Path(directory)/f'invalid-{i}.wav'
                    with self.assertRaises(ValueError):
                        render_quarter_click(path, [], rate, frames)
                    self.assertFalse(path.exists())

    def test_reference_preserves_exact_fractional_change_positions_and_zero(self):
        reference = authored_reference()
        unchanged = deepcopy(reference)
        clock = reference_clock(reference, 4.)
        self.assertEqual(clock['source_origin_seconds'], 0)
        self.assertEqual(clock['beats_seconds'][0], 0)
        np.testing.assert_allclose(clock['knot_pulse_indices'], [966/480, 1106/480], rtol=0, atol=1e-12)
        expected = [e['time_seconds'] for e in reference['tempo_events'][1:]]
        np.testing.assert_allclose([s['start_seconds'] for s in clock['segments'][1:]], expected, rtol=0, atol=1e-12)
        self.assertEqual(reference, unchanged)

    def test_reference_rejects_nonzero_origins(self):
        variants = []
        for key, value in [('tick', 1), ('time_seconds', .01)]:
            reference = authored_reference()
            reference['tempo_events'][0][key] = value
            variants.append(reference)
        reference = authored_reference()
        reference['source_origin_shift_seconds'] = .01
        variants.append(reference)
        for reference in variants:
            with self.subTest(reference=reference):
                with self.assertRaises(ValueError):
                    reference_clock(reference, 4.)

    def test_reference_rejects_malformed_or_contradictory_metadata(self):
        variants = []
        for value in (0, -480, 480.5):
            reference = authored_reference()
            reference['ticks_per_quarter'] = value
            variants.append(reference)
        for field in ('tempo_events', 'meter_events'):
            reference = authored_reference()
            reference[field] = []
            variants.append(reference)
        for value in (.25, float('nan')):
            reference = authored_reference()
            reference['tempo_events'][1]['time_seconds'] = value
            variants.append(reference)
        reference = authored_reference()
        reference['tempo_events'][1]['tick'] = 0
        variants.append(reference)
        reference = authored_reference()
        reference['tempo_events'][1]['microseconds_per_quarter'] = -1
        variants.append(reference)
        reference = authored_reference()
        reference['meter_events'][0]['numerator'] = 3
        variants.append(reference)
        reference = authored_reference()
        reference['meter_events'][0].update(tick=480, time_seconds=.500001)
        variants.append(reference)
        for reference in variants:
            with self.subTest(reference=reference):
                with self.assertRaises(ValueError):
                    reference_clock(reference, 4.)

    def test_exported_midi_reload_keeps_short_fractional_boundaries(self):
        clock, quarters, periods = fractional_clock()
        unchanged = deepcopy(clock)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'map.mid'
            report = export_midi(path, clock, 14.)
            midi = mido.MidiFile(path)
            self.assertEqual(midi.type, 0)
            self.assertEqual(midi.ticks_per_beat, 9600)
            absolute, seconds, current_tempo = 0, 0., 500000
            changes, meters = [], []
            for event in midi.tracks[0]:
                self.assertGreaterEqual(event.time, 0)
                absolute += event.time
                seconds += event.time*current_tempo/midi.ticks_per_beat/1e6
                if event.type == 'time_signature':
                    meters.append((absolute, seconds, event.numerator, event.denominator))
                if event.type == 'set_tempo':
                    changes.append((absolute/midi.ticks_per_beat, seconds, event.tempo/1e6))
                    current_tempo = event.tempo
            self.assertEqual(meters, [(0, 0., 4, 4)])
            self.assertEqual(len(changes), len(quarters))
            self.assertEqual(changes[0][:2], (0., 0.))
            self.assertTrue(np.all(np.diff([c[0] for c in changes]) > 0))
            for quarter, period, actual in zip(quarters, periods, changes):
                self.assertLess(abs(actual[1]-independent_time(quarter, quarters, periods)), .001)
                self.assertLessEqual(abs(actual[2]-period), .5e-6+1e-12)
            # Check points inside the short excursions, as well as ordinary
            # integer beats, using only the reloaded MIDI's boundaries/periods.
            loaded_quarters, _, loaded_periods = zip(*changes)
            points = sorted(set([0., 8.05, 8.45, 8.57, *quarters, *range(1, 20)]))
            for quarter in points:
                difference = independent_time(quarter, loaded_quarters, loaded_periods)-independent_time(quarter, quarters, periods)
                self.assertLess(abs(difference), .001)
            self.assertLessEqual(abs(seconds-14.), .001)
            self.assertLess(report['grid_roundtrip_max_seconds'], .001)
            self.assertFalse(report['accepted'])
            self.assertEqual(report['origin_shift_seconds'], 0)
        self.assertEqual(clock, unchanged)

    def test_midi_rejects_malformed_or_nonzero_origin_clocks_before_writing(self):
        original, _, _ = fractional_clock()
        variants = []
        for key, value in [('source_origin_seconds', .1), ('support_seconds', [.1, 14.]),
                           ('meter', {'numerator': 3, 'denominator': 4}), ('meter', None),
                           ('coefficients', [0., .5]),
                           ('knot_pulse_indices', [float('nan'), 9., 10.])]:
            clock = deepcopy(original)
            clock[key] = value
            variants.append(clock)
        clock = deepcopy(original)
        clock['coefficients'][0] = .01
        variants.append(clock)
        with tempfile.TemporaryDirectory() as directory:
            for i, clock in enumerate(variants):
                with self.subTest(clock=clock):
                    path = Path(directory)/f'invalid-{i}.mid'
                    with self.assertRaises(ValueError):
                        export_midi(path, clock, 14.)
                    self.assertFalse(path.exists())

    def test_midi_rejects_invalid_ppq_and_collapsed_changes(self):
        clock, _, _ = fractional_clock()
        with tempfile.TemporaryDirectory() as directory:
            for i, ppq in enumerate([0, -960, 32768, 960.5, 1]):
                with self.subTest(ppq=ppq):
                    path = Path(directory)/f'invalid-{i}.mid'
                    with self.assertRaises(ValueError):
                        export_midi(path, clock, 14., ppq=ppq)
                    self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
