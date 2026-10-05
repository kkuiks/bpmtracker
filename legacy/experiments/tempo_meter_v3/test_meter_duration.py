"""Behavioral guards: stable gaps, unusual meters and a single short bar."""
import unittest
import numpy as np
from .meter_duration import decode_meter, interpolate


def fixture(signatures, missing=()):
    starts=np.r_[0.,np.cumsum([4*n/d for n,d in signatures])]
    duration=starts[-1]*.5
    t=np.arange(int(np.ceil(duration*50))+1)/50
    down=np.full(len(t),-7.)
    for i,q in enumerate(starts[:-1]):
        if i not in missing:
            down=np.maximum(down,-7+16*np.exp(-.5*((t-q*.5)/.045)**2))
    logits=np.column_stack([np.full(len(t),3.),down])
    st=np.arange(int(np.ceil(duration*12.5))+1)/12.5
    events=np.zeros((len(st),4));events[:,1]=np.interp(st,t,down);events[:,2]=-8
    nums=np.full((len(st),32),-6.);dens=np.full((len(st),5),-6.)
    for i,(n,d) in enumerate(signatures):
        mask=(st>=starts[i]*.5)&(st<=starts[i+1]*.5)
        nums[mask,n-1]=6;dens[mask,(2,4,8,16,32).index(d)]=6
        if i and signatures[i]!=signatures[i-1]:
            events[abs(st-starts[i]*.5)<.12,2]=8
    return np.array([[0.,0.],[starts[-1],duration]]),logits,dict(events=events,numerator=nums,denominator=dens),starts


class DurationPriorTest(unittest.TestCase):
    def test_supported_unusual_meters_remain_available(self):
        for signature in [(4,4),(6,8),(7,8),(31,4)]:
            with self.subTest(signature=signature):
                clock,logits,structure,expected=fixture([signature]*8)
                bars=decode_meter(clock,logits,structure)['bars']
                actual=[b for b in bars if 0<=b['q']<expected[-1]]
                self.assertEqual([(b['n'],b['d']) for b in actual],[signature]*8)
                np.testing.assert_allclose([b['q'] for b in actual],expected[:-1])

    def test_one_short_bar_is_not_smoothed_away(self):
        signatures=[(4,4)]*5+[(2,4)]+[(4,4)]*5
        clock,logits,structure,expected=fixture(signatures)
        actual=[b for b in decode_meter(clock,logits,structure)['bars'] if 0<=b['q']<expected[-1]]
        self.assertEqual([(b['n'],b['d']) for b in actual],signatures)
        np.testing.assert_allclose([b['q'] for b in actual],expected[:-1])

    def test_missing_downbeats_do_not_require_a_long_bar(self):
        clock,logits,structure,expected=fixture([(4,4)]*16,missing=range(5,10))
        actual=[b for b in decode_meter(clock,logits,structure)['bars'] if 0<=b['q']<expected[-1]]
        self.assertEqual([(b['n'],b['d']) for b in actual],[(4,4)]*16)
        np.testing.assert_allclose([b['q'] for b in actual],expected[:-1])


if __name__=='__main__':
    unittest.main()
