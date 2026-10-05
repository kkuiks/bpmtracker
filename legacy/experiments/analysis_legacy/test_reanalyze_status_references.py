import unittest
import tempfile
from pathlib import Path

import numpy as np

from audit_status_references import reference_content, increasing
from reanalyze_status_references import classify_annotation_pair, map_consistency, score_annotation, saved_score_summary, is_appledouble


class ReferenceReanalysisTests(unittest.TestCase):
    def base(self):
        return {'evaluation_support_seconds':[2.,8.],
            'tempo_events':[{'time_seconds':0.,'bpm_quarter':120.}],
            'meter_events':[{'time_seconds':0.,'numerator':4,'denominator':4}]}

    def test_appledouble_audio_suffix_is_metadata_only_with_magic(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'._stem.wav'
            path.write_bytes(bytes.fromhex('00051607')+b'metadata')
            self.assertTrue(is_appledouble(path))
            path.write_bytes(b'RIFF'+b'actual audio header')
            self.assertFalse(is_appledouble(path))

    def test_constant_map_has_labels_without_positive_changes(self):
        result=reference_content(self.base())
        self.assertTrue(result['tempo']['labels_available'])
        self.assertEqual(result['tempo']['changes_in_support'],[])
        self.assertTrue(result['meter']['labels_available'])

    def test_repeated_signature_is_not_a_change(self):
        reference=self.base()
        reference['meter_events'] += [{'time_seconds':3.,'numerator':4,'denominator':4},
                                     {'time_seconds':5.,'numerator':3,'denominator':4}]
        result=reference_content(reference)['meter']
        self.assertEqual(len(result['repeated_declarations']),1)
        self.assertEqual([e['time_seconds'] for e in result['changes_in_support']],[5.])

    def test_changes_outside_or_on_support_boundaries_are_context(self):
        reference=self.base()
        reference['tempo_events'] += [{'time_seconds':t,'bpm_quarter':rate}
            for t,rate in [(1.,100.),(2.,110.),(4.,120.),(8.,130.),(9.,140.)]]
        result=reference_content(reference)['tempo']
        self.assertEqual([e['time_seconds'] for e in result['changes_in_support']],[4.])
        self.assertEqual(len(result['changes_outside_support']),4)

    def test_nonfinite_times_rates_and_support_are_rejected(self):
        for key in ('time_seconds','bpm_quarter'):
            reference=self.base();reference['tempo_events'][0][key]=float('nan')
            with self.assertRaises(ValueError):reference_content(reference)
        reference=self.base();reference['evaluation_support_seconds'][1]=float('inf')
        with self.assertRaises(ValueError):reference_content(reference)
        self.assertFalse(increasing([0.,float('inf')]))
        self.assertFalse(increasing(['invalid']))

    def test_negative_initial_map_context_is_retained(self):
        reference=self.base();reference['tempo_events'][0]['time_seconds']=-.1
        self.assertTrue(reference_content(reference)['tempo']['labels_available'])

    def test_annotation_conflicts_are_prediction_independent(self):
        base=np.array([[.1,1],[.6,2],[1.1,3],[1.6,4]])
        same=classify_annotation_pair(base,base)
        tiny=base.copy();tiny[:,0]+=.005
        shifted=base.copy();shifted[:,0]+=.021
        doubled=np.column_stack((np.arange(8)*.25+.1,np.tile([1,2,3,4],2)))
        self.assertEqual(same['classification'],'identical_parsed_labels')
        self.assertFalse(classify_annotation_pair(base,tiny)['conflicting'])
        self.assertTrue(classify_annotation_pair(base,shifted)['conflicting'])
        self.assertEqual(classify_annotation_pair(base,doubled)['classification'],'pulse_count_half_or_double_conflict')

    def test_diagnostic_scoring_never_moves_prediction(self):
        annotation=np.array([[.1,1],[.6,2],[1.1,3],[1.6,4]])
        prediction={'beats_seconds':[.13,.63,1.13,1.63],'downbeats_seconds':[.13]}
        scores=score_annotation(prediction,annotation,2.)
        self.assertEqual(scores['beats_seconds']['0.02']['f1'],0.)
        self.assertEqual(scores['beats_seconds']['0.07']['f1'],1.)
        self.assertEqual(prediction['beats_seconds'][0],.13)

    def test_missing_downbeat_labels_remain_unscored(self):
        beats={str(v):{'f1':.5} for v in (.01,.02,.03,.07)}
        scores={name:{'annotated_span':{'beats_seconds':beats,'downbeats_seconds':None}}
                for name in ('official_minimal','legacy_dbn','clock_pipeline')}
        summary=saved_score_summary([{'scores':scores}])['official_minimal']
        self.assertEqual(summary['downbeat_track_count'],0)
        self.assertIsNone(summary['macro_downbeat_f1']['0.02'])

    def test_internal_consistency_detects_missing_quarter(self):
        reference=self.base();reference['beats_seconds']=[0.,.5,1.5]
        reference['downbeats_seconds']=[0.]
        result=map_consistency(reference)
        self.assertFalse(result['quarter_interval_consistent_1e_5'])
        self.assertEqual(result['quarter_interval_max_error'],1.)


if __name__=='__main__':unittest.main()
