from copy import deepcopy
import unittest

from music_map_contract import interpolate_clock
from music_map_prediction_adapters import (adapt_method,adapt_core_prediction,
    adapt_bar_proposals,adapt_region_prediction,source_identity)


SOURCE={'sha256':'a'*64,'sample_rate':1000,'sample_frames':5000,'path':'same.wav',
        'duration_seconds':5.,'source_frame_offset':0,'frame_time_offset_seconds':0}


def clock():
    return {'coefficients':[0.,.5,.25],'knot_pulse_indices':[2.],
            'pulse_index_span':[-1.,6.],'support_seconds':[-.5,4.],
            'pulse_unit':'input index unit; musical interpretation unresolved','meter':None}


def candidate():
    c=clock()
    return {'id':'phase-half','clock':c,'quarter_unit':'hypothesis','phase_offset_quarters':.5,
        'musical_index_origin':'candidate_relative_unanchored','source_window_seconds':[0.,5.],
        'input_event_indexing':{'quarter_positions':[0.,1.,2.],'source_seconds':[.25,.75,1.25]},
        'indexed_grid':[{'quarter_position':u,'source_seconds':t} for u,t in [(0,0.),(1,.5),(2,1.),(3,1.75),(4,2.5),(5,3.25),(6,4.)]]}


class PredictionAdapterTests(unittest.TestCase):
    def test_curve_identity_negative_context_and_unresolved_quarter_names(self):
        c=candidate();method={'clock':c['clock'],'prediction':{'beats_seconds':[e['source_seconds'] for e in c['indexed_grid']]},'status':'unaccepted'}
        before=deepcopy(method);view=adapt_method(method,SOURCE,provenance={'path':'saved'},candidate=c)
        self.assertEqual(method,before)
        self.assertEqual(view['map']['clock_knots'][0],{'pulse':-1.,'source_seconds':-.5})
        self.assertEqual(view['map']['support_seconds'],[[0.,4.]])
        self.assertIsNone(view['map']['quarters_per_pulse'])
        self.assertIsNone(view['map']['meter_events'])
        self.assertIsNone(view['map']['shared_origin_id'])
        for e in c['indexed_grid']:
            self.assertAlmostEqual(interpolate_clock(view['map']['clock_knots'],e['quarter_position']),e['source_seconds'])
        self.assertEqual(view['adaptation']['candidate_declarations']['input_event_indexing'],c['input_event_indexing'])
        self.assertIn('pre-phase',view['adaptation']['input_event_indexing_basis'])

    def test_native_events_do_not_invent_clock_support_or_bar_origin(self):
        view=adapt_method({'clock':None,'prediction':{'beats_seconds':[.5,1.5],'downbeats_seconds':[.5]},'status':'official'},SOURCE,provenance={})
        self.assertEqual(view['status'],'events_only')
        self.assertEqual(view['events']['beats_seconds'],[.5,1.5])
        self.assertEqual(view['map']['clock_knots'],[])
        self.assertEqual(view['map']['support_seconds'],[])
        self.assertIsNone(view['map']['bar_anchor_pulse'])

    def test_fallback_remains_events_only_and_original_failure_preserved(self):
        v=adapt_method({'clock':None,'prediction':[.1,.6],'status':'fallback_segment_budget'},SOURCE,provenance={})
        self.assertEqual(v['status'],'events_only')
        self.assertEqual(v['original_status'],'fallback_segment_budget')
        self.assertFalse(v['map']['capability']['clock'])

    def test_emitted_point_off_curve_is_rejected(self):
        c=candidate();c['indexed_grid'][3]['source_seconds']+=.001
        with self.assertRaisesRegex(ValueError,'does not equal'):
            adapt_method({'clock':c['clock'],'prediction':{'beats_seconds':[e['source_seconds'] for e in c['indexed_grid']]}},SOURCE,provenance={},candidate=c)

    def test_fitted_event_off_integer_lattice_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'integer pulse lattice'):
            adapt_method({'clock':clock(),'prediction':[.5,1.01]},SOURCE,provenance={})

    def test_support_intersection_does_not_extend_clock_or_source(self):
        c=clock();c['support_seconds']=[-2.,20.]
        v=adapt_method({'clock':c,'prediction':[0.,.5,1.]},SOURCE,provenance={})
        self.assertEqual(v['map']['support_seconds'],[[0.,4.]])
        c.pop('support_seconds')
        v=adapt_method({'clock':c,'prediction':[]},SOURCE,provenance={})
        self.assertEqual(v['map']['support_seconds'],[])
        self.assertTrue(v['map']['capability']['clock'])

    def test_source_boundary_violation_is_preserved_and_flagged(self):
        v=adapt_method({'clock':None,'prediction':[.5,5.0055],'status':'saved_legacy'},SOURCE,provenance={})
        self.assertEqual(v['events']['beats_seconds'],[.5,5.0055])
        check=v['adaptation']['event_validation']
        self.assertFalse(check['physical_source_bounds_valid'])
        self.assertEqual(check['outside_physical_source']['beats_seconds'][0]['event_index'],1)
        self.assertTrue(check['boundary_violations_preserved_without_clipping'])

    def test_floating_endpoint_roundoff_checks_without_changing_events(self):
        c=clock();t=4.+1e-13
        v=adapt_method({'clock':c,'prediction':[t]},SOURCE,provenance={})
        self.assertEqual(v['events']['beats_seconds'],[t])
        self.assertEqual(v['adaptation']['emitted_grid_identity']['checked_count'],1)
        self.assertTrue(v['adaptation']['emitted_grid_identity']['passed'])

    def test_nonmonotonic_or_nonfinite_curves_are_rejected(self):
        for coefficients in [[0.,-.5,0.],[0.,float('nan'),.25]]:
            c=clock();c['coefficients']=coefficients
            with self.assertRaises(ValueError):adapt_method({'clock':c,'prediction':[]},SOURCE,provenance={})

    def test_bar_binding_cannot_be_attached_to_another_grid(self):
        core={'methods':{'meter_free_clock':{'prediction':{'beats_seconds':[.5,1.,1.5,2.]}}}}
        ref={'core_prediction_path':'core.json','core_prediction_sha256':'b'*64,
             'bar_input_grid':'unchanged_meter_free_clock_prediction','bars':{'fixed':{
                 'bar_start_pulse_indices':[0,2],'downbeats_seconds':[.5,1.5],
                 'meter_events':[{'pulse_index':0,'pulses_per_bar':2,'quarter_note_denominator':None}]}}}
        view=adapt_bar_proposals(ref,core,core_path='core.json',core_sha256='b'*64)['fixed']
        self.assertIsNone(view['concrete_meter_events'])
        self.assertIsNone(view['quarters_per_pulse'])
        wrong=deepcopy(core);wrong['methods']['meter_free_clock']['prediction']['beats_seconds'][2]=1.6
        with self.assertRaisesRegex(ValueError,'bound source grid'):
            adapt_bar_proposals(ref,wrong,core_path='core.json',core_sha256='b'*64)
        with self.assertRaisesRegex(ValueError,'source hash'):
            adapt_bar_proposals(ref,core,core_path='core.json',core_sha256='c'*64)

    def test_regions_remain_separate_with_unknown_bridge(self):
        c=candidate();second=deepcopy(c);second['id']='region1';second['clock']['coefficients'][0]=3.;second['clock']['pulse_index_span']=[0.,2.];second['clock']['support_seconds']=[3.,4.]
        second['indexed_grid']=[{'quarter_position':0,'source_seconds':3.},{'quarter_position':1,'source_seconds':3.5},{'quarter_position':2,'source_seconds':4.}]
        core={'id':'x','model':'beat_this','source':SOURCE}
        reg={'id':'x','model':'beat_this','source':SOURCE,'core_prediction_path':'core.json','core_prediction_sha256':'b'*64,
             'generated':{'candidates':[c,second],'selected_candidate_id':c['id'],'unknown_bridges':[{'start_seconds':2.,'end_seconds':3.}]}}
        views=adapt_region_prediction(reg,core,artifact_path='region.json',artifact_sha256='c'*64,core_path='core.json',core_sha256='b'*64)
        self.assertFalse(views['regions_joined']);self.assertFalse(views['full_song_map'])
        self.assertEqual(len(views['candidate_views']),2)
        self.assertEqual(views['unknown_bridges'],reg['generated']['unknown_bridges'])
        self.assertTrue(all(v['map']['shared_origin_id'] is None for v in views['candidate_views'].values()))

    def test_source_clock_identity_rejects_implicit_source_offsets(self):
        a=source_identity(SOURCE);other={**SOURCE,'sha256':'b'*64}
        self.assertNotEqual(a['clock_id'],source_identity(other)['clock_id'])
        with self.assertRaisesRegex(ValueError,'nonzero'):
            source_identity({**SOURCE,'frame_time_offset_seconds':.01})

    def test_selected_candidate_requires_bound_artifact(self):
        core={'id':'x','model':'beat_this','source':SOURCE,'methods':{'selected':{
            'clock':clock(),'prediction':[],'selected_candidate_id':'missing'}}}
        with self.assertRaisesRegex(ValueError,'missing'):
            adapt_core_prediction(core,artifact_path='core.json',artifact_sha256='b'*64)


if __name__=='__main__':unittest.main()
