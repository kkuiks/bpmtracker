import unittest
import tempfile
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import numpy as np

from diagnose_matched_clock import (unique_correspondence,reference_identity,
    paired_diagnostic,continuous_error,freeze_inputs,run,sha)


class MatchedClockTests(unittest.TestCase):
    def test_bidirectional_ambiguity_never_becomes_greedy_matching(self):
        result=unique_correspondence([1.,2.,3.,4.],[.99,1.01,2.,3.01,4.1],.02)
        self.assertEqual(result['pairs'],[{'reference_index':1,'prediction_index':2},{'reference_index':2,'prediction_index':3}])
        self.assertEqual(result['ambiguity_excluded_prediction_count'],2)
        self.assertEqual(result['prediction_without_nearby_reference_count'],1)
        self.assertEqual(result['unpaired_reference_count'],2)
        reverse=unique_correspondence([1.,1.02],[1.01],.02)
        self.assertEqual(reverse['matched_count'],0)
        self.assertEqual(reverse['ambiguity_excluded_reference_count'],2)

    def test_nominal_boundary_uses_ulp_only_and_still_excludes_real_excess(self):
        for predicted in [1.02,.98]:
            self.assertEqual(unique_correspondence([1.],[predicted],.02)['matched_count'],1)
        self.assertEqual(unique_correspondence([1.],[1.07],.07)['matched_count'],1)
        for predicted in [1.020001,.979999]:
            self.assertEqual(unique_correspondence([1.],[predicted],.02)['matched_count'],0)
        ambiguous=unique_correspondence([1.],[.98,1.02],.02)
        self.assertEqual(ambiguous['matched_count'],0)
        self.assertEqual(ambiguous['reference_neighbor_counts'],[2])
        self.assertEqual(ambiguous['ambiguity_excluded_prediction_count'],2)

    def test_tolerances_are_separate_and_empty_match_is_explicit(self):
        self.assertEqual(unique_correspondence([1.],[1.03],.02)['matched_count'],0)
        self.assertEqual(unique_correspondence([1.],[1.03],.07)['matched_count'],1)
        result=paired_diagnostic([1.],[4.],[1.03],.02)
        self.assertEqual(result['status'],'no_unique_correspondence')
        self.assertEqual(result['arms'],{})

    def test_identity_is_not_invented_from_event_ordinal(self):
        with self.assertRaisesRegex(ValueError,'identities unavailable'):
            reference_identity({'beats_seconds':[1.,2.,3.],'kind':'unknown','evaluation_support_seconds':[1.,3.]})

    def test_authored_tempo_integrates_missing_explicit_quarter_array(self):
        reference={'kind':'authored_midi_quarter_clock','ticks_per_quarter':480,'explicit_initial_tempo':True,
            'source_origin_shift_seconds':-.25,'tempo_events':[{'tick':0,'time_seconds':-.25,'microseconds_per_quarter':500000,'bpm_quarter':120.}],
            'beats_seconds':[.75,1.25,1.75,2.25],'evaluation_support_seconds':[.75,1.75]}
        identity=reference_identity(reference)
        np.testing.assert_array_equal(identity['quarters'],[2,3,4,5])
        self.assertEqual(identity['reference_clock_knots'][-1]['source_seconds'],1.75)
        self.assertEqual(identity['times'][-1],2.25)

    def test_observed_click_identity_is_preserved_without_inventing_curve(self):
        identity=reference_identity({'kind':'observed_creator_click_quarters','beats_seconds':[.11,.63,1.08],
                                     'quarter_indices':[4,5,6],'evaluation_support_seconds':[.11,1.08],'tempo_events':None})
        np.testing.assert_array_equal(identity['quarters'],[4,5,6])
        self.assertIsNone(identity['reference_clock_knots'])

    def test_paired_controls_keep_same_subset_and_separate_coordinates(self):
        reference=np.arange(32.)*.5
        indices=np.array([i for i in range(32) if i not in (7,8,20)])
        predicted=reference[indices]+.003
        curve=[{'pulse':0.,'source_seconds':0.},{'pulse':31.,'source_seconds':15.5}]
        result=paired_diagnostic(reference,np.arange(32.),predicted,.02,reference_knots=curve)
        arms=result['arms'];seq=arms['sequential_model_times'];indexed=arms['quarter_indexed_model_times'];ideal=arms['quarter_indexed_reference_times']
        self.assertEqual(seq['input_times_seconds'],indexed['input_times_seconds'])
        self.assertEqual(indexed['input_indices'],ideal['input_indices'])
        self.assertEqual(seq['input_indices'],list(range(len(predicted))))
        self.assertEqual(indexed['input_indices'],indices.tolist())
        self.assertTrue(result['all_arms_reference_selected_subset'])
        self.assertEqual(result['absolute_quarter_gauge_origin'],0.)
        self.assertTrue(indexed['clock_produced']);self.assertTrue(ideal['clock_produced'])
        self.assertLess(ideal['continuous_reference_clock_error']['max_absolute_seconds'],1e-9)
        self.assertAlmostEqual(indexed['continuous_reference_clock_error']['mean_absolute_seconds'],.003,places=8)
        if seq['clock_produced']:
            self.assertGreater(seq['continuous_reference_clock_error']['max_absolute_seconds'],.5)
            self.assertGreater(seq['reference_time_error_at_true_quarter_positions']['queries_outside_clock_domain'],0)

    def test_common_quarter_origin_is_preserved_without_time_alignment(self):
        reference=np.arange(20.)*.5+3.
        result=paired_diagnostic(reference,np.arange(100.,120.),reference+.004,.02)
        self.assertEqual(result['absolute_quarter_gauge_origin'],100.)
        for arm in result['arms'].values():self.assertEqual(arm['quarter_coordinate_assertion']['absolute_q0'],100.)
        self.assertAlmostEqual(result['pre_fit_timing_error']['signed_mean_seconds'],.004)
        self.assertFalse(result['source_time_shift_applied'])

    def test_insufficient_subset_keeps_all_failed_fit_arms(self):
        result=paired_diagnostic([1.,2.,3.],[8.,9.,10.],[1.,2.,3.],.02)
        self.assertEqual(len(result['arms']),3)
        for arm in result['arms'].values():
            self.assertFalse(arm['clock_produced'])
            self.assertEqual(arm['status'],'fallback_event_count_budget')
            self.assertEqual(arm['output_role'],'fallback_input_events_no_clock')

    def test_continuous_integral_includes_internal_knots(self):
        proposal={'pulse_index_span':[0.,2.],'knot_pulse_indices':[1.],'coefficients':[0.,1.5,-1.]}
        reference=[{'pulse':0.,'source_seconds':0.},{'pulse':2.,'source_seconds':2.}]
        result=continuous_error(proposal,0.,reference)
        self.assertEqual(result['integration_breakpoints_quarters'],[0.,1.,2.])
        self.assertAlmostEqual(result['max_absolute_seconds'],.5)
        self.assertAlmostEqual(result['mean_absolute_seconds'],.25)
        self.assertAlmostEqual(result['rms_seconds'],np.sqrt(1/12))

    def make_files(self,root):
        ref=root/'reference.json';ref.write_text(json.dumps({'kind':'observed_creator_click_quarters','source_audio_sha256':'a'*64,'beats_seconds':list(range(10)),'quarter_indices':list(range(4,14)),'evaluation_support_seconds':[0.,9.],'tempo_events':None}))
        ledger=root/'ledger.json';ledger.write_text(json.dumps({'tracks':[{'id':'test','retained_for_primary_scores':True}]}))
        core=root/'core.json';core.write_text(json.dumps({'id':'test','model':'beat_this','source':{'sha256':'a'*64},'references_used_for_prediction':False,'methods':{'common_minimal':{'prediction':{'beats_seconds':list(range(10))}}}}))
        cohort=root/'cohort.json';cohort.write_text(json.dumps({'proposed_fixed_diagnostic_cohort':[{'id':'test','role':'guard','reference':{'path':str(ref),'sha256':sha(ref)},'reference_record_path':str(ledger),'reference_record_sha256':sha(ledger),'prediction_inputs':[{'path':str(core),'sha256':sha(core),'model':'beat_this'}],'source_evaluation_support_seconds':[0.,9.],'reference_tier':'test','reference_caveats':{}}]}))
        return cohort,ref

    def test_configuration_and_input_hashes_are_frozen_before_any_fit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cohort,_=self.make_files(root);output=root/'output'
            def fitting(prediction,pulse_indices=None):
                self.assertTrue((output/'configuration.json').exists())
                config=json.loads((output/'configuration.json').read_text())
                self.assertTrue(config['frozen_before_execution'])
                self.assertTrue(config['input_hashes'])
                return None,prediction,'test_fallback'
            with patch('diagnose_matched_clock.fit_prediction',side_effect=fitting) as fitter,redirect_stdout(io.StringIO()):
                result=run(output,cohort)
            self.assertEqual(fitter.call_count,4)
            self.assertEqual(result['state'],'complete')
            self.assertEqual(result['changed_inputs'],[])

    def test_tampered_reference_is_rejected_before_any_fit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cohort,ref=self.make_files(root);ref.write_text(ref.read_text()+' ')
            with patch('diagnose_matched_clock.fit_prediction') as fitter:
                with self.assertRaisesRegex(ValueError,'reference artifact changed'):
                    freeze_inputs(cohort,root/'output')
            fitter.assert_not_called()

    def test_observed_click_scope_runs_c3_only(self):
        result=paired_diagnostic(np.arange(12.),np.arange(4.,16.),np.arange(12.)+.01,.02,allow_c2=False)
        self.assertNotIn('sequential_model_times',result['arms'])
        self.assertEqual(result['C2']['status'],'not_in_scope_for_observed_click_reference')
        self.assertIn('C3',result)


if __name__=='__main__':unittest.main()
