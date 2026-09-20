from pathlib import Path
import tempfile
import unittest

import mido
import numpy as np

from midi_reference import read_clock


class MidiReferenceTests(unittest.TestCase):
    def write_midi(self, directory, messages, resolution=480):
        midi = mido.MidiFile(ticks_per_beat=resolution)
        midi.tracks.append(mido.MidiTrack(messages))
        path = Path(directory)/'clock.mid'
        midi.save(path)
        return path

    def test_small_tempo_step_uses_preceding_tempo_and_header_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_midi(directory, [mido.MetaMessage('set_tempo',tempo=600000),
                mido.MetaMessage('time_signature',numerator=4,denominator=4),
                mido.Message('note_on',note=36,velocity=90),
                mido.MetaMessage('set_tempo',tempo=585366,time=960),
                mido.Message('note_off',note=36,time=960)],resolution=240)
            result = read_clock(path)
            np.testing.assert_allclose(result['beats_seconds'][:5],np.arange(5)*.6)
            self.assertAlmostEqual(result['beats_seconds'][-1],2.4+4*.585366)
            self.assertEqual(result['tempo_events'][1]['time_seconds'],2.4)
            np.testing.assert_allclose(result['downbeats_seconds'],[0,2.4,2.4+4*.585366])

    def test_explicit_meter_change_and_nonzero_note_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_midi(directory,[mido.MetaMessage('time_signature',numerator=4,denominator=4),
                mido.Message('note_on',note=60,velocity=80,time=480),
                mido.MetaMessage('time_signature',numerator=3,denominator=4,time=1440),
                mido.Message('note_off',note=60,time=2880)])
            result = read_clock(path)
            self.assertEqual(result['evaluation_support_seconds'],[.5,5.])
            self.assertEqual(result['downbeats_seconds'],[2.,3.5,5.])
            self.assertFalse(result['explicit_initial_tempo'])

    def test_missing_or_compound_meter_is_not_invented_as_quarter_beat_truth(self):
        for meter in (None,(6,8)):
            with tempfile.TemporaryDirectory() as directory:
                messages=[] if meter is None else [mido.MetaMessage('time_signature',numerator=meter[0],denominator=meter[1])]
                messages += [mido.Message('note_on',note=60,velocity=80),mido.Message('note_off',note=60,time=3840)]
                result=read_clock(self.write_midi(directory,messages))
                self.assertIsNone(result['downbeats_seconds'])

    def test_conflicting_simultaneous_tempo_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.write_midi(directory,[mido.MetaMessage('set_tempo',tempo=500000),
                mido.MetaMessage('set_tempo',tempo=600000),mido.Message('note_on',note=60,velocity=80),
                mido.Message('note_off',note=60,time=960)])
            with self.assertRaises(ValueError):read_clock(path)

    def test_late_meter_change_one_tick_off_bar_is_not_rounded_into_ground_truth(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.write_midi(directory,[mido.MetaMessage('time_signature',numerator=4,denominator=4),
                mido.Message('note_on',note=60,velocity=80),
                mido.MetaMessage('time_signature',numerator=3,denominator=4,time=1600*1920+1),
                mido.Message('note_off',note=60,time=1440)])
            self.assertIsNone(read_clock(path)['downbeats_seconds'])


if __name__ == '__main__':
    unittest.main()
