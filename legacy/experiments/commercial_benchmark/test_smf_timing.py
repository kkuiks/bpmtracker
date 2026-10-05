import tempfile
from pathlib import Path
import unittest

import mido

from .smf_timing import read_timing


class SmfTimingTests(unittest.TestCase):
    def save(self, midi):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name)/'native.mid'
        midi.save(path)
        return path

    def test_ppq_and_compound_meter_do_not_change_quarter_time_unit(self):
        m = mido.MidiFile(type=1, ticks_per_beat=960)
        m.tracks.append(mido.MidiTrack([
            mido.MetaMessage('set_tempo', tempo=625000),
            mido.MetaMessage('time_signature', numerator=6, denominator=8),
            mido.MetaMessage('set_tempo', tempo=500000, time=2880),
            mido.MetaMessage('time_signature', numerator=7, denominator=8),
            mido.MetaMessage('end_of_track', time=3360),
        ]))
        r = read_timing(self.save(m))
        self.assertEqual(r['tempo_events'][1]['quarter'], 3.)
        self.assertEqual(r['tempo_events'][1]['midi_seconds'], 1.875)
        self.assertEqual(r['end_midi_seconds'], 3.625)
        self.assertEqual(r['meter_events'][1]['denominator'], 8)
        self.assertIsNone(r['bar_anchor_quarter'])
        self.assertIsNone(r['audio_source_origin_seconds'])

    def test_missing_signature_stays_unknown_in_tempo_only_export(self):
        m = mido.MidiFile(type=0, ticks_per_beat=480)
        m.tracks.append(mido.MidiTrack([
            mido.MetaMessage('set_tempo', tempo=500000),
            mido.MetaMessage('end_of_track', time=480),
        ]))
        r = read_timing(self.save(m))
        self.assertIsNone(r['meter_events'])
        self.assertFalse(r['explicit_initial_meter'])

    def test_conflicting_clock_tracks_fail_instead_of_choosing_an_answer(self):
        m = mido.MidiFile(type=1)
        for tempo in [500000, 600000]:
            m.tracks.append(mido.MidiTrack([mido.MetaMessage('set_tempo', tempo=tempo)]))
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            read_timing(self.save(m))

    def test_identical_clock_tracks_deduplicate_but_missing_initial_tempo_fails(self):
        m = mido.MidiFile(type=1)
        for _ in range(2):
            m.tracks.append(mido.MidiTrack([mido.MetaMessage('set_tempo', tempo=500000)]))
        r = read_timing(self.save(m))
        self.assertEqual(len(r['tempo_events']), 1)
        self.assertEqual(r['identical_simultaneous_tempo_duplicates'], 1)
        m.tracks = [mido.MidiTrack([mido.MetaMessage('set_tempo', tempo=500000, time=480)])]
        with self.assertRaisesRegex(ValueError, 'tick-zero'):
            read_timing(self.save(m))


if __name__ == '__main__':
    unittest.main()
