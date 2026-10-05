import copy
import unittest
import numpy as np
from .build_gate_review import make_map
from .equivalence_probe import compare, validate
from .review_audio import render_click


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.ref=make_map([(4,4)]*4+[(2,4)]+[(4,4)]*4)
        self.alt=make_map([(4,4)]*3+[(6,4)]+[(4,4)]*4)

    def test_local_merge_and_split_are_symmetric_and_not_certified(self):
        for a,b in [(self.ref,self.alt),(self.alt,self.ref)]:
            v=compare(a,b)
            self.assertTrue(v['eligible_local_rebar'])
            self.assertFalse(v['strict'])
            self.assertFalse(v['musical_equivalence_certified'])
            self.assertEqual(v['policy_status'],'unapproved_proposal')

    def test_global_rebar_rejected(self):
        self.assertFalse(compare(make_map([(4,4)]*10),make_map([(2,4)]*20))['eligible_local_rebar'])

    def test_compound_not_simple_even_without_grouping(self):
        for group in (False,True):
            a=(3,4,[1,1,1]) if group else (3,4)
            b=(6,8,[3,3]) if group else (6,8)
            v=compare(make_map([a]*8),make_map([b]*8))
            self.assertFalse(v['strict'] or v['eligible_local_rebar'])

    def test_late_phase_and_different_tempo_rejected(self):
        for clock in ([[0,.16],[34,20.56]],[[0,0],[17,11],[34,20.4]]):
            bad=copy.deepcopy(self.alt);bad['clock']=clock
            self.assertEqual(compare(self.ref,bad)['reason'],'different_physical_clock')

    def test_two_matching_bars_required(self):
        a=make_map([(4,4),(2,4)]+[(4,4)]*5)
        b=make_map([(6,4)]+[(4,4)]*5)
        self.assertFalse(compare(a,b)['eligible_local_rebar'])

    def test_known_grouping_conflict_rejected(self):
        a=copy.deepcopy(self.ref);b=copy.deepcopy(self.alt)
        a['bars'][3]['grouping']=[2,2];a['bars'][4]['grouping']=[2]
        b['bars'][3]['grouping']=[3,3]
        self.assertFalse(compare(a,b)['eligible_local_rebar'])

    def test_stable_meter_boundaries_preserved_in_both_directions(self):
        a=make_map([(4,4)]*8)
        b=make_map([(4,4)]*2+[(8,4)]+[(4,4)]*4)
        for first,second in ((a,b),(b,a)):
            value=compare(first,second)
            self.assertFalse(value['eligible_local_rebar'])
            self.assertEqual(value['reason'],'stable_meter_boundary_removed')

    def test_mixed_block_cannot_hide_stable_boundary_removal(self):
        a=make_map([(4,4)]*4+[(2,4)]+[(4,4)]*4)
        b=make_map([(4,4)]*2+[(10,4)]+[(4,4)]*4)
        self.assertEqual(compare(a,b)['reason'],'stable_meter_boundary_removed')

    def test_uniform_local_split_is_not_a_new_equivalent_answer(self):
        a=make_map([(4,4)]*7)
        b=make_map([(4,4)]*3+[(2,4)]*2+[(4,4)]*3)
        self.assertFalse(compare(a,b)['eligible_local_rebar'])

    def test_constraint_is_not_song_or_four_four_specific(self):
        for n,d in [(3,4),(7,8),(5,16)]:
            a=make_map([(n,d)]*8)
            b=make_map([(n,d)]*3+[(2*n,d)]+[(n,d)]*3)
            self.assertEqual(compare(a,b)['reason'],'stable_meter_boundary_removed')

    def test_invalid_geometry_rejected(self):
        for change in ({'n':True},{'d':3},{'grouping':[3]},{'q':float('nan')}):
            value=copy.deepcopy(self.ref);value['bars'][0].update(change)
            with self.assertRaises(ValueError):validate(value)

    def test_multiple_local_edits_one_path(self):
        a=make_map([(4,4)]*3+[(4,4),(2,4)]+[(4,4)]*5+[(4,4),(2,4)]+[(4,4)]*3)
        b=make_map([(4,4)]*3+[(6,4)]+[(4,4)]*5+[(6,4)]+[(4,4)]*3)
        v=compare(a,b);self.assertTrue(v['eligible_local_rebar'])
        self.assertEqual(sum(x['reference_count']!=x['prediction_count'] for x in v['alignment']),2)


class RenderTests(unittest.TestCase):
    def test_odd_bar_is_not_lost_between_quarters(self):
        sound,indices=render_click(1000,5000,[0,1,2,3,4],[0,3.5])
        self.assertIn(3500,indices);self.assertAlmostEqual(float(sound[3500]),.4,places=6)

    def test_no_duplicate_or_out_of_support_click(self):
        sound,indices=render_click(1000,1000,[-1,0,.5,1],[0,1],[0])
        self.assertEqual(indices,[0,500]);self.assertEqual(len(sound),1000)
        self.assertLessEqual(np.max(abs(sound)),.401)


if __name__=='__main__':unittest.main()
