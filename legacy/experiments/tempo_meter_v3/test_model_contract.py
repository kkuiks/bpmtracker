import unittest
import numpy as np
from .clock_search import fit_clock,select_pulse_level,initial_pulse_rate
from .meter_search import decode_meter
from .train_structure import targets


def perfect_observations(signatures,period=.5):
    lengths=[4*n/d for n,d in signatures];starts=np.r_[0,np.cumsum(lengths)];duration=.1+starts[-1]*period
    rt=np.arange(int(duration*50)+1)/50;ht=np.arange(int(duration*12.5)+1)/12.5
    raw=np.full((len(rt),2),-8.)
    head=dict(events=np.full((len(ht),4),-8.),numerator=np.full((len(ht),32),-8.),denominator=np.full((len(ht),5),-8.),tempo=np.zeros(len(ht)))
    head['events'][:,3]=8
    for i,(n,d) in enumerate(signatures):
        t=.1+starts[i]*period;stop=.1+starts[i+1]*period
        raw[abs(rt-t)<.04,1]=8;head['events'][abs(ht-t)<.08,1]=8
        mask=(ht>=t)&(ht<stop);head['numerator'][mask,n-1]=0;head['denominator'][mask,(2,4,8,16,32).index(d)]=0
        if i and signatures[i]!=signatures[i-1]:head['events'][abs(ht-t)<.12,2]=8
    return np.array([[0,.1],[starts[-1],duration]]),raw,head


class ModelContractTests(unittest.TestCase):
    def test_observed_one_bar_change_is_represented(self):
        signatures=[(4,4)]*4+[(2,4)]+[(4,4)]*4
        clock,raw,head=perfect_observations(signatures)
        bars=decode_meter(clock,raw,head)['bars']
        self.assertEqual([(b['n'],b['d']) for b in bars],signatures)

    def test_compound_and_odd_meter_not_forced_to_four(self):
        for signature in [(6,8),(7,8),(4,2)]:
            clock,raw,head=perfect_observations([signature]*8)
            bars=decode_meter(clock,raw,head)['bars']
            self.assertTrue(all((b['n'],b['d'])==signature for b in bars))

    def test_constant_clock_does_not_gain_fake_changes(self):
        q=np.arange(900);t=.137+q*60/137.5
        knots,diagnostic=fit_clock(t)
        self.assertEqual(len(knots),2);self.assertLess(diagnostic['max_pulse_residual'],1e-8)

    def test_step_clock_has_shared_phase(self):
        q=np.arange(81);t=.1+np.minimum(q,40)*.5+np.maximum(q-40,0)*.4
        knots,diagnostic=fit_clock(t)
        np.testing.assert_allclose(knots,[[0,.1],[40,20.1],[80,36.1]],atol=1e-8)

    def test_ramp_clock_is_monotonic_and_close(self):
        q=np.arange(180);t=.2+60/.15*np.log((90+.15*q)/90)
        knots,diagnostic=fit_clock(t)
        self.assertTrue(np.all(np.diff(knots,axis=0)>0));self.assertLess(diagnostic['max_pulse_residual'],.10)

    def test_unknown_meter_is_masked_not_default_four(self):
        row=dict(dataset='babyslakh',weight=.5,labels=dict(support=[0,10],beats=list(range(10)),bars=[],meter=[],tempo=[dict(time_seconds=0,bpm_quarter=60)],meter_known=False))
        y,mask,n,d,tempo,valid=targets(row,125)
        self.assertTrue(np.all(n==-100));self.assertTrue(np.all(d==-100));self.assertTrue(np.all(mask[:,1]==0))

    def test_approximate_hint_changes_only_discrete_pulse_level(self):
        bank=[dict(name='fast',clock=np.array([[0,0],[4,1.5]]),joint_score=2.),
              dict(name='slow',clock=np.array([[0,0],[4,3.]]),joint_score=1.)]
        before=[c['clock'].copy() for c in bank]
        for bpm in (79,80,81):
            candidates,decision=select_pulse_level(bank,bpm)
            self.assertEqual(candidates[0]['name'],'slow')
            self.assertEqual(decision['selected_level'],-1)
            self.assertFalse(decision['clock_fit_uses_hint'])
        self.assertEqual(select_pulse_level(bank,160)[0][0]['name'],'fast')
        for old,candidate in zip(before,bank):np.testing.assert_array_equal(old,candidate['clock'])

    def test_hint_uses_stable_span_not_noisy_opening(self):
        candidate=dict(clock=np.array([[0,0],[20,4],[60,34]]))
        self.assertAlmostEqual(initial_pulse_rate(candidate),80.)

    def test_dotted_pulse_family_does_not_collapse_into_double(self):
        bank=[dict(name='dotted',clock=np.array([[0,0],[64,60]]),joint_score=3.),
              dict(name='quarter',clock=np.array([[0,0],[96,60]]),joint_score=1.),
              dict(name='double',clock=np.array([[0,0],[128,60]]),joint_score=2.)]
        for bpm in (95,96,97):
            chosen,choice=select_pulse_level(bank,bpm)
            self.assertEqual(chosen[0]['name'],'quarter')
            self.assertEqual(choice['selected_pulse_multiplier'],1.5)

    def test_unlabelled_tail_is_not_no_grid_supervision(self):
        row=dict(dataset='rwc',weight=.5,labels=dict(support=[1,8],beats=list(range(1,9)),bars=[1,5],meter=[dict(time_seconds=1,numerator=4,denominator=4)],tempo=[dict(time_seconds=1,bpm_quarter=60)],meter_known=True))
        y,mask,*_=targets(row,125)
        self.assertTrue(np.all(mask[113:]==0));self.assertTrue(np.all(mask[:,2]==0))


if __name__=='__main__':unittest.main()
