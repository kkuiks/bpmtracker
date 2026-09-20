from pathlib import Path
import tempfile
import unittest

from prepare_public_corpus import safe_target, read_published_beats
from run_corpus_benchmark import score_events, score_clock


class PublicCorpusTests(unittest.TestCase):
    def test_beat_only_annotations_do_not_become_negative_downbeat_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'example.beats'
            path.write_text('0.1\n0.6\n1.1\n')
            beats,downbeats=read_published_beats(path)
            self.assertEqual(beats,[.1,.6,1.1])
            self.assertIsNone(downbeats)
            path.write_text('0.1 0\n0.6 0\n1.1 0\n')
            self.assertIsNone(read_published_beats(path)[1])

    def test_archive_paths_cannot_escape_or_target_windows_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertEqual(safe_target(root,'dataset/track.wav'),root/'dataset/track.wav')
            for name in ('../escape','/tmp/escape','C:/escape','dir\\escape','a/../../escape'):
                with self.subTest(name=name), self.assertRaises(ValueError):safe_target(root,name)

    def test_missing_downbeat_labels_remain_unscored_and_window_is_explicit(self):
        reference={'beats_seconds':[.5,1.,1.5,2.], 'downbeats_seconds':None,
                   'evaluation_support_seconds':[.5,2.]}
        prediction={'beats_seconds':[0,.5,1.,1.5,2.,2.5], 'downbeats_seconds':[0,2.]}
        result=score_events(reference,prediction,0)
        self.assertIsNone(result['downbeats_seconds'])
        self.assertEqual(result['beats_seconds']['0.07']['f1'],1.)

    def test_half_rate_is_not_oracle_corrected_in_midi_clock_metrics(self):
        reference={'beats_seconds':[0,.5,1,1.5,2], 'evaluation_support_seconds':[0,2],
                   'tempo_events':[{'time_seconds':0,'bpm_quarter':120}]}
        proposal={'segments':[{'start_seconds':0,'end_seconds':2,'pulse_rate_per_minute':60}]}
        score=score_clock(reference,proposal)
        self.assertEqual(score['quarter_rate_mae'],60)
        self.assertEqual(score['median_predicted_to_reference_rate_ratio'],.5)
        self.assertIsNone(score['changes_0_5s'])
        self.assertEqual(score['false_changes_on_constant_reference'],0)


if __name__=='__main__':
    unittest.main()
