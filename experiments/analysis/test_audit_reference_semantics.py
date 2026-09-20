import tempfile
import unittest
from pathlib import Path
import mido
from audit_reference_semantics import midi_evidence, qualify, note_grid_diagnostics


class ReferenceSemanticsTests(unittest.TestCase):
    def test_renderer_meter_does_not_certify_original_intent(self):
        with tempfile.TemporaryDirectory() as d:
            paths=[Path(d)/name for name in ('original.mid','rendered.mid')]
            for path,meter in zip(paths,(False,True)):
                midi=mido.MidiFile(ticks_per_beat=192)
                track=mido.MidiTrack();midi.tracks.append(track)
                track.append(mido.MetaMessage('set_tempo',tempo=652173))
                if meter:track.append(mido.MetaMessage('time_signature',numerator=4,denominator=4))
                track.append(mido.Message('note_on',note=36,velocity=90,time=40))
                track.append(mido.Message('note_off',note=36,time=48));midi.save(path)
            original,rendered=map(midi_evidence,paths)
            result=qualify(original,rendered,{'downbeat_label_status':'excluded_original_meter_not_explicit'})
            self.assertFalse(original['explicit_initial_meter'])
            self.assertTrue(rendered['explicit_initial_meter'])
            self.assertEqual(original['explicit_meter_events'],[])
            self.assertIn('rendered_meter_must_not_be_attributed_to_original',result['review_flags'])
            self.assertFalse(result['labels_changed'])
            self.assertFalse(result['exclude_from_existing_reports'])

    def test_phase_offset_is_diagnostic_without_label_repair(self):
        ticks=[40+i*48 for i in range(100)]
        result=note_grid_diagnostics(ticks,192)
        self.assertEqual(result['sixteenth_grid_zero_fraction_within_one_tick'],0)
        self.assertEqual(result['sixteenth_grid_mode_fraction_within_one_tick'],1)
        self.assertEqual(result['sixteenth_grid_mode_offset_ticks'],40)


if __name__=='__main__':
    unittest.main()
