from copy import deepcopy
from fractions import Fraction
import unittest
from music_map_contract import prepare_map, render_bars, interpolate_clock, normalize_support


def fixture(n=4, d=4, *, grouping=None):
    return {'schema_version':1,'source':{'sha256':'0'*64,'sample_rate':48000,'sample_frames':384000},
            'clock_knots':[{'pulse':-4.,'source_seconds':-2.},{'pulse':20.,'source_seconds':10.}],
            'quarters_per_pulse':{'numerator':1,'denominator':1},
            'meter_events':[{'pulse':-4.,'numerator':n,'denominator':d,'grouping':grouping,'bar_action':'continue'}],
            'bar_anchor_pulse':0.,'shared_origin_id':None,'support_seconds':[[0.,8.]],
            'analysis_condition':'constructed_fixture'}


class MusicMapContractTests(unittest.TestCase):
    def test_five_eighth_bars_are_not_restricted_to_quarter_event_subset(self):
        raw=fixture(5,8,grouping=[2,3])
        result=render_bars(raw)
        self.assertEqual(result['status'],'rendered')
        bar=next(b for b in result['bars'] if b['start_seconds']==0)
        self.assertEqual(bar['end_seconds'],1.25)
        self.assertEqual(bar['end_pulse'],2.5)
        self.assertEqual(bar['group_times_seconds'],[0,.5])

    def test_unknown_units_and_unknown_grouping_have_different_meanings(self):
        raw=fixture();prepared=prepare_map(raw)
        self.assertFalse(prepared['capability']['grouping_declared_everywhere'])
        self.assertEqual(render_bars(raw)['status'],'rendered')
        raw['quarters_per_pulse']=None
        self.assertEqual(render_bars(raw)['status'],'unresolved_pulse_unit')

    def test_negative_context_and_small_phase_offset_are_retained(self):
        raw=fixture()
        for knot in raw['clock_knots']:knot['source_seconds']-=.019
        bars=render_bars(raw)
        zero_bar=next(b for b in bars['bars'] if b['start_pulse']==0)
        self.assertAlmostEqual(zero_bar['start_seconds'],-.019)
        self.assertEqual(raw['bar_anchor_pulse'],0)
        self.assertFalse(bars['alignment_applied'])

    def test_clock_interior_knots_are_preserved_with_equal_bar_endpoints(self):
        raw=fixture();raw['clock_knots']=[{'pulse':0.,'source_seconds':0.},
            {'pulse':2.,'source_seconds':.5},{'pulse':4.,'source_seconds':2.},
            {'pulse':16.,'source_seconds':8.}]
        raw['meter_events'][0]['pulse']=0
        bar=render_bars(raw)['bars'][0]
        self.assertEqual(bar['phase_knots'],[{'phase':0.,'source_seconds':0.},
            {'phase':.5,'source_seconds':.5},{'phase':1.,'source_seconds':2.}])

    def test_natural_meter_change_supports_fractional_quarter_boundary(self):
        raw=fixture(5,8);raw['meter_events'].append({'pulse':2.5,'numerator':3,'denominator':4,
                                                  'grouping':None,'bar_action':'continue'})
        bars=render_bars(raw)['bars']
        self.assertTrue(any(b['start_pulse']==2.5 and b['end_pulse']==5.5 for b in bars))

    def test_nonbarline_reset_is_explicitly_unsupported_not_silently_ignored(self):
        raw=fixture();raw['meter_events'].append({'pulse':1.,'numerator':4,'denominator':4,
                                                  'grouping':None,'bar_action':'restart'})
        self.assertEqual(render_bars(raw)['status'],'unsupported_nonbarline_meter_or_reset')
        raw['meter_events'][-1]['bar_action']='continue'
        self.assertEqual(render_bars(raw)['status'],'rendered')

    def test_support_hole_is_not_filled_by_clock_geometry(self):
        raw=fixture();raw['support_seconds']=[[0,3],[4,8]]
        self.assertEqual(prepare_map(raw)['support_seconds'],[[0.,3.],[4.,8.]])
        self.assertEqual(normalize_support([[0,2],[2,3],[3.000001,4]],8),[[0.,3.],[3.000001,4.]])

    def test_source_hash_is_not_promoted_to_shared_origin(self):
        raw=fixture();prepared=prepare_map(raw)
        self.assertIsNone(prepared['shared_origin_id'])
        self.assertFalse(prepared['capability']['reference_qualified_by_constructor'])
        self.assertEqual(raw,fixture())

    def test_invalid_geometry_and_unannounced_extrapolation_are_rejected(self):
        for change in ('reverse_time','zero_unit','out_of_source_support','extrapolation'):
            raw=fixture()
            if change=='reverse_time':raw['clock_knots'][1]['source_seconds']=-3
            elif change=='zero_unit':raw['quarters_per_pulse']['numerator']=0
            elif change=='out_of_source_support':raw['support_seconds']=[[0,9]]
            else:raw['clock_knots'][1]['source_seconds']=7
            with self.subTest(change=change),self.assertRaises(ValueError):prepare_map(raw)
        with self.assertRaises(ValueError):interpolate_clock(fixture()['clock_knots'],21)

    def test_future_meter_context_does_not_invalidate_defined_clock(self):
        raw=fixture();raw['meter_events'].append({'pulse':21.,'numerator':3,'denominator':4,
                                                  'grouping':None,'bar_action':'restart'})
        self.assertEqual(render_bars(raw)['status'],'rendered')
        self.assertEqual(len(prepare_map(raw)['meter_events']),2)

    def test_roundoff_at_declared_meter_boundary_does_not_duplicate_barline(self):
        raw=fixture();raw['clock_knots']=[{'pulse':0.,'source_seconds':0.},
            {'pulse':1.2,'source_seconds':8.}]
        raw['quarters_per_pulse']={'numerator':40,'denominator':3}
        raw['meter_events']=[{'pulse':0.,'numerator':4,'denominator':4,'grouping':None,'bar_action':'continue'},
            {'pulse':.3,'numerator':3,'denominator':4,'grouping':None,'bar_action':'continue'}]
        result=render_bars(raw)
        self.assertEqual(result['status'],'rendered')
        self.assertEqual(sum(abs(t-2.)<1e-8 for t in result['bar_events_seconds']),1)

    def test_explicit_nonquarter_pulse_unit_converts_only_declared_coordinates(self):
        raw=fixture(6,8,grouping=[3,3]);raw['quarters_per_pulse']={'numerator':3,'denominator':2}
        bar=next(b for b in render_bars(raw)['bars'] if b['start_pulse']==0)
        self.assertEqual(bar['end_pulse'],2.)
        self.assertEqual(bar['end_seconds'],1.)
        self.assertEqual(bar['group_times_seconds'],[0.,.5])


if __name__=='__main__':unittest.main()
