"""Controlled missing-event, real-change and cross-coupling checks."""
import unittest
import numpy as np
from .joint_clock import associations,fit_knots,refine,peaks
from .meter_event import decode_meter
from .test_meter_duration import fixture


class JointClockTest(unittest.TestCase):
    def test_missing_beats_keep_nonconsecutive_quarter_coordinates(self):
        clock=np.array([[0.,0.],[8.,4.]])
        observed=dict(beat_times=np.array([0,.5,1,2,2.5,3,4]),bar_times=np.array([0.,2.,4.]))
        bars=[dict(q=q,n=4,d=4) for q in [0,4,8]]
        q,t,w,receipt=associations(clock,bars,observed)
        self.assertEqual(receipt['beat']['matched'],7)
        self.assertNotIn(3,q[:7]);self.assertIn(4,q[:7])
        np.testing.assert_allclose(fit_knots(q,t,w,clock[:,0],clock[:,1]),clock[:,1],atol=1e-8)

    def test_offbeats_are_not_forced_into_the_quarter_clock(self):
        clock=np.array([[0.,0.],[16.,8.]])
        observed=dict(beat_times=np.sort(np.r_[np.arange(17)*.5,np.arange(16)*.5+.25]),bar_times=np.arange(5)*2.)
        q,t,w,_=associations(clock,[dict(q=q,n=4,d=4) for q in range(0,17,4)],observed)
        np.testing.assert_allclose(fit_knots(q,t,w,clock[:,0],clock[:,1]),clock[:,1],atol=1e-8)

    def test_bar_positions_actually_change_clock_fitting(self):
        clock=np.array([[0.,.015],[16.,8.015]])
        observed=dict(beat_times=np.arange(17)*.5,bar_times=np.arange(5)*2.+.03)
        q,t,w,r=associations(clock,[dict(q=q,n=4,d=4) for q in range(0,17,4)],observed)
        fitted=fit_knots(q,t,w,clock[:,0],clock[:,1])
        self.assertGreater(fitted[0],.001)
        self.assertLess(fitted[0],.03)
        self.assertEqual(r['bar']['matched'],5)

    def test_single_broad_lobe_does_not_create_a_tiny_bar(self):
        signatures=[(2,4)]+[(4,4)]*8
        clock,logits,head,expected=fixture(signatures)
        clock[:,1]+=.03
        actual=decode_meter(clock,logits,head)['bars']
        self.assertTrue(all((b['n'],b['d']) in [(2,4),(4,4)] for b in actual))

    def test_exact_change_is_preserved_and_score_never_decreases(self):
        clock,logits,head,_=fixture([(4,4)]*16)
        q=np.arange(65);times=np.where(q<=32,q*.5,16+(q-32)*.6)
        observed=dict(beat_times=times,bar_times=times[::4])
        variable=np.array([[0.,0.],[32.,16.],[64.,35.2]])
        result=refine(variable,logits,head,observed)
        self.assertEqual(len(result['clock']),3)
        for h in result['history']:
            if h['accepted']:self.assertGreater(h['after'],h['before'])


if __name__=='__main__':unittest.main()
