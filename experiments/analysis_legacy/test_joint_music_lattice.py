from dataclasses import replace
import json
from unittest.mock import patch
import unittest

import numpy as np

from joint_music_lattice import (JointConfig, infer_joint_music_map, first_stable_window,
    fixed_schedule_data_score)


def fixture(patterns, fps=40., lead=.5, tail=.5):
    """Source-only manufactured channel evidence; no reference objects in payload."""
    cursor=lead;bars=[];primary=[]
    for meter,bpm in patterns:
        length=180/bpm  # all fixture bars span3quarters
        bars.append(cursor)
        offsets=(0.,1.,2.) if meter=='simple' else (0.,1.5)
        primary.extend(cursor+q*60/bpm for q in offsets)
        cursor+=length
    duration=cursor+tail;frames=round(duration*fps)
    beat=np.full(frames,-8.);down=np.full(frames,-8.)
    for t in primary:beat[int(np.floor(t*fps+.5))]=8.
    for t in bars:down[int(np.floor(t*fps+.5))]=8.
    source={'sha256':'a'*64,'sample_rate':4000,'sample_frames':round(duration*4000)}
    return beat,down,fps,source,bars


class JointMusicLatticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simple=fixture([('simple',80)]*4)
        cls.compound=fixture([('compound',80)]*4)
        cls.simple_result=infer_joint_music_map(*cls.simple[:4])
        cls.compound_result=infer_joint_music_map(*cls.compound[:4])
        cls.guided_result=infer_joint_music_map(*cls.compound[:4],guide_bpm=160)

    def test_fixed_primary_grouping_distinguishes_same_length_bars(self):
        a,b=self.simple_result,self.compound_result
        self.assertIsNotNone(a['map']);self.assertIsNotNone(b['map'])
        self.assertTrue(all(len(x['grouping'])==3 for x in a['path']))
        self.assertTrue(all(len(x['grouping'])==2 for x in b['path']))
        for result in (a,b):
            self.assertTrue(all(abs(x['source_end_seconds']-x['source_start_seconds']-2.25)<1e-10 for x in result['path']))
            self.assertIsNone(result['map']['shared_origin_id'])
            self.assertFalse(result['map']['accepted'])

    def test_unhinted_same_mask_meter_alias_is_not_unique(self):
        result=self.compound_result
        self.assertTrue(result['diagnostics']['identical_mask_aliases_present'])
        self.assertFalse(result['diagnostics']['musical_meter_uniqueness_certified'])
        self.assertTrue(result['diagnostics']['reported_tie_counts_are_lower_bounds_not_global_uniqueness_tests'])
        aliases=result['diagnostics']['observational_template_aliases']
        self.assertTrue(aliases)
        names={v['template_id'] for v in aliases[0]['same_data_score_alternatives']}
        self.assertTrue({'2/4:1+1','6/8:3+3'}<=names)
        self.assertFalse(result['score_components']['calibrated_confidence'])

    def test_scalar_guide_infers_unit_without_meter_or_unit_input(self):
        result=self.guided_result
        self.assertEqual(result['guide']['inferred_unit_quarters'],{'numerator':1,'denominator':2})
        self.assertTrue(all(x['numerator']==6 and x['denominator']==8 for x in result['path']))
        self.assertFalse(result['guide']['triplet_guide_unit_one_third_supported'])
        self.assertEqual(result['guide_window'],self.compound_result['guide_window'])
        self.assertFalse(result['diagnostics']['reference_used_for_prediction'])

    def test_first_stable_window_is_earliest_before_longest_region_pruning(self):
        fps=40.;events=np.r_[1.+np.arange(8)*.5,12.+np.arange(30)*.5]
        beat=np.full(1200,-8.);beat[np.rint(events*fps).astype(int)]=8.
        source={'sha256':'a'*64,'sample_rate':4000,'sample_frames':120000}
        window=first_stable_window(beat,fps,source)
        self.assertEqual(window['status'],'found')
        self.assertEqual(window['source_support_seconds'],[1.,4.5])
        self.assertEqual(window['event_indices'],[0,8])
        self.assertEqual(len(window['event_times_seconds']),8)

    def test_silent_prefix_does_not_become_guide_window_source_zero(self):
        values=fixture([('compound',80)]*4,lead=3.)
        result=infer_joint_music_map(*values[:4],guide_bpm=160)
        self.assertEqual(result['guide_window']['start_seconds'],3.)
        self.assertTrue(result['path'][0]['source_start_seconds']>=3.)
        self.assertTrue(result['diagnostics']['uncovered_source_intervals'])

    def test_later_tempo_change_is_not_flattened_by_local_guide(self):
        values=fixture([('compound',80)]*4+[('compound',100)]*3)
        result=infer_joint_music_map(*values[:4],guide_bpm=160)
        self.assertIsNotNone(result['map'])
        early=[x for x in result['path'] if x['source_end_seconds']<=9.5]
        late=[x for x in result['path'] if x['source_start_seconds']>=9.5]
        self.assertTrue(early and late)
        self.assertTrue(all(abs((x['source_end_seconds']-x['source_start_seconds'])-2.25)<1e-8 for x in early))
        self.assertTrue(all(abs((x['source_end_seconds']-x['source_start_seconds'])-1.8)<1e-8 for x in late))
        self.assertTrue(all(x['local_score_components']['guide']==0 for x in late))

    def test_boundary_aligned_meter_change_can_change_primary_group_count(self):
        values=fixture([('simple',80)]*4+[('compound',80)]*4)
        result=infer_joint_music_map(*values[:4])
        self.assertIsNotNone(result['map'])
        counts=[len(x['grouping']) for x in result['path']]
        self.assertIn(3,counts);self.assertIn(2,counts)
        self.assertGreaterEqual(len(result['map']['meter_events']),2)
        self.assertFalse(result['diagnostics']['midbar_tempo_changes_supported'])
        self.assertFalse(result['diagnostics']['nonbarline_resets_supported'])

    def test_no_evidence_no_fabricated_guide_window_or_map(self):
        beat,down,fps,source,_=self.compound
        for level in (-8.,0.):
            b=np.full_like(beat,level);d=np.full_like(down,level)
            result=infer_joint_music_map(b,d,fps,source,guide_bpm=160)
            self.assertEqual(result['status'],'guide_window_unresolved')
            self.assertIsNone(result['map']);self.assertIsNone(result['guide_window']['source_seconds'])
        result=infer_joint_music_map(np.ones_like(beat),np.ones_like(down),fps,source)
        self.assertEqual(result['status'],'ambiguous_no_temporal_discrimination')
        self.assertIsNone(result['map'])

    def test_free_role_identical_observation_masks_remain_equal(self):
        beat,down,fps,source,_=self.compound
        same_bars=[.5,2.75];same_events=[.5,1.625,2.75,3.875]
        simple_with_free_role=fixed_schedule_data_score(beat,down,fps,same_bars,same_events)
        compound_with_free_role=fixed_schedule_data_score(beat,down,fps,same_bars,same_events)
        self.assertEqual(simple_with_free_role['data_energy'],compound_with_free_role['data_energy'])
        self.assertFalse(simple_with_free_role['calibrated_likelihood'])

    def test_reference_keys_are_rejected_and_source_path_cannot_choose_meter(self):
        beat,down,fps,source,_=self.simple
        with self.assertRaises(ValueError):infer_joint_music_map(beat,down,fps,{**source,'expected_meter':'6/8'})
        with self.assertRaises(TypeError):infer_joint_music_map(beat,down,fps,source,reference_path='truth.json')
        with patch('builtins.open',side_effect=AssertionError('inference must not read files')):
            result=infer_joint_music_map(beat,down,fps,{**source,'path':'misleading_correct_6_8.wav'})
        self.assertEqual(result['path'],self.simple_result['path'])
        self.assertEqual(result['score_components'],self.simple_result['score_components'])

    def test_budget_failures_are_explicit_and_do_not_return_successful_prefix(self):
        values=self.compound
        for config,status in [(replace(JointConfig(),max_transition_comparisons=1),'budget_exceeded_transition_comparisons'),
                              (replace(JointConfig(),max_working_memory_bytes=1),'budget_exceeded_memory')]:
            result=infer_joint_music_map(*values[:4],config=config)
            self.assertEqual(result['status'],status);self.assertIsNone(result['map'])
            self.assertIn('guide_window',result)
        with self.assertRaises(ValueError):infer_joint_music_map(*values[:4],config=replace(JointConfig(),beam_width=0))

    def test_absence_of_identical_template_alias_never_certifies_uniqueness(self):
        result=self.simple_result
        self.assertTrue(result['diagnostics']['no_identical_mask_alias_in_frozen_vocabulary'])
        self.assertFalse(result['diagnostics']['musical_meter_uniqueness_certified'])
        self.assertTrue(result['diagnostics']['local_topk_may_discard_ties_before_beam_sort'])

    def test_impossible_durations_are_bounded_by_available_frames(self):
        beat=np.array([8.,-8.,-8.,-8.]);source={'sha256':'a'*64,'sample_rate':1000,'sample_frames':1000}
        result=infer_joint_music_map(beat,beat,1e9,source)
        self.assertEqual(result['status'],'budget_exceeded_memory')
        self.assertIsNone(result['map'])

    def test_cropped_midbar_guide_does_not_force_bar_start_to_source_zero(self):
        beat,down,fps,source,_=fixture([('compound',80)]*6,lead=0.)
        crop=45
        beat,down=beat[crop:],down[crop:]
        source={**source,'sha256':'b'*64,'sample_frames':int(len(beat)/fps*source['sample_rate'])}
        result=infer_joint_music_map(beat,down,fps,source,guide_bpm=160)
        self.assertEqual(result['guide_window']['start_seconds'],0.)
        self.assertIsNotNone(result['map'])
        self.assertLess(result['map']['clock_knots'][0]['source_seconds'],0.)
        self.assertEqual(result['map']['support_seconds'][0][0],0.)
        actual_starts=[b['source_start_seconds'] for b in result['path'] if b['source_start_seconds']>=0]
        self.assertAlmostEqual(actual_starts[0],1.125)
        self.assertNotIn(0.,actual_starts)
        self.assertTrue(result['path'][0]['downbeat_emission_censored'])
        self.assertTrue(result['path'][0]['censored_primary_sample_frames'])
        self.assertFalse(result['diagnostics']['authored_musical_origin_inferred'])
        altered=down.copy();altered[-1]=100000.
        again=infer_joint_music_map(beat,altered,fps,source,guide_bpm=160)
        self.assertEqual(result['score_components'],again['score_components'])
        self.assertEqual(result['path'],again['path'])

    def test_low_native_resolution_filters_duplicate_and_endpoint_samples(self):
        beat=np.array([8.,-1.,8.,-1.,8.]);down=np.array([8.,-1.,-1.,-1.,8.])
        source={'sha256':'a'*64,'sample_rate':100,'sample_frames':500}
        result=infer_joint_music_map(beat,down,1.,source)
        for bar in result['path']:
            frames=bar['native_primary_sample_frames']
            self.assertEqual(len(frames),len(set(frames)))
            self.assertTrue(all(0<=f<5 for f in frames))
            self.assertTrue(all(f<bar['logit_end_frame'] for f in frames))
        json.dumps(result,allow_nan=False)

    def test_results_are_finite_serializable_and_score_components_sum(self):
        result=self.guided_result;score=result['score_components']
        self.assertAlmostEqual(sum(score[k] for k in ('beat','downbeat','tempo_prior','template_prior','guide')),score['total'])
        json.dumps(result,allow_nan=False)
        self.assertLessEqual(result['resources']['transition_comparisons']+result['resources']['start_comparisons'],100_000_000)
        self.assertEqual(result['guide_window'],first_stable_window(*[self.compound[i] for i in (0,2,3)]))


if __name__=='__main__':unittest.main()
