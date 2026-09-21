"""Whole-source timing and explicit-assistance contracts, without real-song labels."""
from copy import deepcopy
import unittest

import numpy as np

from complete_song_clock import assemble_clock, assist_clock, rebuild_clock
from fit_clock import clock_time


def conditional_fixture():
    # The middle is intentionally unobserved. Its exact beat count must remain
    # conditional, even though this test fixture knows how the audio clock arose.
    rate_a, rate_b = .5, 60/114
    truth = lambda q: rate_a*np.asarray(q)+np.maximum(0,np.asarray(q)-40)*(rate_b-rate_a)
    left_q=np.arange(30,dtype=float);right_q=np.arange(60,91,dtype=float)
    left_t,right_t=truth(left_q),truth(right_q)
    def candidate(name,region,times,period):
        return {'id':name,'region':{'id':region},'evidence_score_not_confidence':1.,
                'phase_offset_quarters':0.,
                'source_support_seconds':[float(times[0]),float(times[-1])],
                'input_event_indexing':{'source_seconds':times.tolist(),
                                       'quarter_positions':np.arange(len(times),dtype=float).tolist()},
                'clock':{'coefficients':[float(times[0]),period],'knot_pulse_indices':[]}}
    regions={'regions':[{'id':0},{'id':1}],
             'candidates':[candidate('early',0,left_t,rate_a),candidate('late',1,right_t,rate_b)],
             'unknown_bridges':[{'source_start_seconds':float(left_t[-1]),
                                'source_end_seconds':float(right_t[0]),'quarter_count':None}]}
    observed=np.r_[left_t,right_t];logits=np.full(55*50,-8.,dtype=float)
    for time in observed:logits[round(time*50)]=8.
    return regions,{'first_model':observed.tolist()},{'first_model':(logits,50.)},truth


class CompleteClockTests(unittest.TestCase):
    def test_rebuild_covers_entire_source_and_preserves_continuity(self):
        result=rebuild_clock([4.],[0.,.5,.1],7.)
        self.assertEqual(result['support_seconds'],[0.,7.])
        self.assertEqual(result['segments'][0]['start_seconds'],0.)
        self.assertAlmostEqual(result['segments'][-1]['end_seconds'],7.)
        self.assertEqual(result['segments'][0]['end_seconds'],result['segments'][1]['start_seconds'])
        self.assertFalse(result['accepted']);self.assertFalse(result['source_audio_modified'])
        times=np.array(result['beats_seconds'])
        self.assertEqual(times[0],0.)
        self.assertTrue(np.all((times>=0)&(times<7)))
        self.assertTrue(np.all(np.diff(times)>0))

    def test_negative_roundoff_at_exact_zero_does_not_delete_first_beat(self):
        result=rebuild_clock([],[ -8.34e-14,.5],3.)
        self.assertEqual(result['indexed_grid'][0]['quarter_position'],0.)
        self.assertEqual(result['indexed_grid'][0]['source_seconds'],0.)
        self.assertNotIn(3.,result['beats_seconds'])
        self.assertEqual(len(result['beats_seconds']),6)
        # A real negative beat stays outside the source; epsilon handling must
        # not pull a materially shifted event back onto sample zero.
        shifted=rebuild_clock([],[-.001,.5],3.)
        self.assertEqual(shifted['indexed_grid'][0]['quarter_position'],1.)

    def test_rebuild_rejects_invalid_shape_and_nonmonotonic_clock(self):
        for knots,coefficients,duration in [([1.],[0.,.5],4.),([], [0.,-.5],4.),
                                            ([float('nan')],[0.,.5,.1],4.),([],[0.,.5],0.)]:
            with self.subTest(knots=knots,coefficients=coefficients):
                with self.assertRaises(ValueError):rebuild_clock(knots,coefficients,duration)

    def test_observed_dropout_produces_conditional_candidates_without_reference_input(self):
        regions,observations,logits,truth=conditional_fixture()
        before=deepcopy(regions);before_observations=deepcopy(observations);before_logits=logits['first_model'][0].copy()
        result=assemble_clock(regions,observations,logits,55.)
        self.assertFalse(result['reference_used_for_prediction'])
        self.assertFalse(result['bridge_certified']);self.assertFalse(result['accepted'])
        self.assertTrue(result['candidates'])
        self.assertTrue(any(abs(c['boundary_seconds']-float(truth(40)))<.01 for c in result['candidates']))
        for candidate in result['candidates']:
            self.assertEqual(candidate['clock']['support_seconds'],[0.,55.])
            self.assertFalse(candidate['clock']['source_audio_modified'])
        self.assertEqual(regions,before);self.assertEqual(observations,before_observations)
        np.testing.assert_array_equal(logits['first_model'][0],before_logits)

    def test_assisted_anchors_are_exact_and_explicitly_not_automatic(self):
        regions,observations,logits,truth=conditional_fixture()
        automatic=assemble_clock(regions,observations,logits,55.)
        automatic['selected_candidate_id']=min(automatic['candidates'],key=lambda c:abs(c['boundary_seconds']-truth(40)))['id']
        anchors=[{'quarter_position':float(q),'source_seconds':float(truth(q)),
                  'provenance':'synthetic test fixture supplied explicitly'} for q in (0,40,100)]
        original=deepcopy(automatic);original_anchors=deepcopy(anchors)
        result=assist_clock(automatic,anchors,0,{'numerator':4,'denominator':4},55.)
        self.assertTrue(result['reference_used_for_prediction'])
        self.assertFalse(result['assistance']['human_actions_measured'])
        self.assertEqual(result['assistance']['anchors'],anchors)
        self.assertFalse(result['source_audio_modified'])
        self.assertEqual(result['indexed_grid'][0]['quarter_position'],0)
        self.assertEqual(result['indexed_grid'][0]['source_seconds'],0)
        for anchor in anchors:
            value=clock_time([anchor['quarter_position']],result['knot_pulse_indices'],result['coefficients'])[0]
            self.assertAlmostEqual(value,anchor['source_seconds'],places=9)
        self.assertEqual(automatic,original);self.assertEqual(anchors,original_anchors)

    def test_assistance_rejects_missing_provenance_duplicate_or_reversed_anchors(self):
        regions,observations,logits,truth=conditional_fixture()
        automatic=assemble_clock(regions,observations,logits,55.)
        good=[{'quarter_position':float(q),'source_seconds':float(truth(q)),
               'provenance':'explicit synthetic anchor'} for q in (0,40,100)]
        missing=deepcopy(good);missing[1].pop('provenance')
        duplicate=deepcopy(good);duplicate[2]=deepcopy(duplicate[1])
        reversed_times=deepcopy(good);reversed_times[2]['source_seconds']=5.
        outside=deepcopy(good);outside[2]['source_seconds']=56.
        for anchors in (missing,duplicate,reversed_times,outside):
            with self.subTest(anchors=anchors):
                with self.assertRaises(ValueError):assist_clock(automatic,anchors,0,{'numerator':4,'denominator':4},55.)
        with self.assertRaises(ValueError):assist_clock(automatic,good,float('nan'),{'numerator':4,'denominator':4},55.)


if __name__=='__main__':unittest.main()
