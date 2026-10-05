import json
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from build_music_map_contract_review import build_review, sample_index


def f(value):return Fraction(value['numerator'],value['denominator'])


class ContractReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)/'first'
        cls.metadata=build_review(cls.root)
        cls.variants={v['id']:v for p in cls.metadata['pairs'] for v in p['variants']}

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def audio(self,filename):return sf.read(self.root/filename,dtype='float32')[0]

    def test_all_interpretations_preserve_exact_declared_bar_duration(self):
        for pair in self.metadata['pairs']:
            expected=f(pair['bar_duration_seconds_exact'])
            for v in pair['variants']:
                if v['meter']:
                    meter=v['meter'];q=Fraction(4*meter['numerator'],meter['denominator'])
                    self.assertEqual(q*60/f(v['quarter_bpm']),expected)
                self.assertEqual(f(v['bar_duration_quarters'])*60/f(v['quarter_bpm']),expected)
                starts=[e for e in v['click_events'] if e['kind']=='bar_start']
                self.assertEqual([e['onset_sample_index'] for e in starts],
                                 [e['onset_sample_index'] for e in pair['bar_boundaries'][:-1]])

    def test_grouping_changes_click_intervals_even_with_identical_quarter_bpm(self):
        three=self.variants['b_120_3_4'];six=self.variants['b_120_6_8']
        self.assertEqual(f(three['quarter_bpm']),f(six['quarter_bpm']))
        self.assertEqual(f(three['actual_click_rate_per_minute']),120)
        self.assertEqual(f(six['actual_click_rate_per_minute']),80)
        self.assertEqual(f(self.variants['b_shared_eighths']['actual_click_rate_per_minute']),240)
        for v,interval in [(three,Fraction(1,2)),(six,Fraction(3,4))]:
            times=[f(e['source_seconds_exact']) for e in v['click_events']]
            self.assertEqual(set(np.diff(times)),{interval})
            self.assertEqual([e['onset_sample_index'] for e in v['group_boundaries']],
                             [e['onset_sample_index'] for e in v['click_events']])
        self.assertFalse(np.array_equal(self.audio(three['click_audio_path']),self.audio(six['click_audio_path'])))

    def test_optional_grouping_matches_slow_click_without_claiming_equivalence(self):
        slow=self.variants['a_85_4_4'];fast=self.variants['a_170_8_4'];group=self.variants['a_170_8_4_grouped']
        self.assertEqual(len(fast['click_events']),2*len(slow['click_events']))
        self.assertIsNone(fast['meter']['grouping_in_denominator_units'])
        self.assertEqual(group['meter']['grouping_in_denominator_units'],[2,2,2,2])
        self.assertTrue(group['optional'])
        self.assertEqual([e['onset_sample_index'] for e in slow['click_events']],
                         [e['onset_sample_index'] for e in group['click_events']])
        np.testing.assert_array_equal(self.audio(slow['click_audio_path']),self.audio(group['click_audio_path']))
        self.assertFalse(self.metadata['equivalence_policy_decided'])

    def test_identical_backing_is_reused_and_mixes_are_exact_sums(self):
        for pair in self.metadata['pairs']:
            backing=self.audio(pair['backing_audio_path'])
            for v in pair['variants']:
                self.assertEqual(v['backing_audio_path'],pair['backing_audio_path'])
                self.assertEqual(v['backing_sha256'],pair['backing_sha256'])
                expected=(backing+self.audio(v['click_audio_path'])).astype(np.float32)
                np.testing.assert_array_equal(self.audio(v['mixed_audio_path']),expected)
                self.assertLess(v['mix_peak'],.99)

    def test_decode_geometry_onset_samples_and_common_lead(self):
        sr=self.metadata['sample_rate'];lead=sr//2
        for pair in self.metadata['pairs']:
            paths=[pair['backing_audio_path']]
            for v in pair['variants']:
                paths.extend([v['click_audio_path'],v['mixed_audio_path']])
                click=self.audio(v['click_audio_path'])
                self.assertTrue(np.all(click[:lead]==0))
                for e in v['click_events']:
                    self.assertEqual(e['onset_sample_index'],sample_index(f(e['source_seconds_exact']),sr))
                    self.assertLessEqual(abs(Fraction(e['onset_sample_index'],sr)-f(e['source_seconds_exact'])),Fraction(1,2*sr))
                    self.assertNotEqual(click[e['onset_sample_index']],0)
            for name in paths:
                info=sf.info(self.root/name)
                self.assertEqual((info.samplerate,info.frames,info.channels,info.subtype),(sr,pair['sample_frames'],1,'FLOAT'))

    def test_output_is_deterministic_and_existing_bundle_is_preserved(self):
        other=Path(self.temp.name)/'second';build_review(other)
        for p in self.root.iterdir():
            self.assertEqual(p.read_bytes(),(other/p.name).read_bytes(),p.name)
        with self.assertRaises(FileExistsError):build_review(self.root)
        self.assertTrue((self.root/'events.json').exists())

    def test_unit_table_and_pending_policy_are_visible(self):
        page=(self.root/'index.html').read_text()
        for text in ['표기상 4분음표 BPM','실제 클릭률','분당 80번','분당 240번','아직 결정하지 않았습니다','2+2+2+2']:
            self.assertIn(text,page)
        for pair in self.metadata['pairs']:
            for v in pair['variants']:
                self.assertTrue((self.root/v['diagram_path']).read_text().startswith('<svg'))
        manifest=json.loads((self.root/'manifest.json').read_text())
        self.assertFalse(manifest['equivalence_policy_decided'])
        self.assertFalse(self.metadata['external_media_used'])
        self.assertFalse(self.metadata['model_predictions'])

    def test_rejects_invalid_sample_rate_before_output_creation(self):
        for value in [0,True,48000.5,1000]:
            root=Path(self.temp.name)/'invalid'
            with self.assertRaises(ValueError):build_review(root,value)
            self.assertFalse(root.exists())


if __name__=='__main__':unittest.main()
