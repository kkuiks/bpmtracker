import itertools
import unittest
import numpy as np
from .fixtures import fixture
from .bar_structure import decode,score_path,vocabulary
from .support import infer as support
from .latent_clock import search,time_at
from .continuous import fit


class JointContractTests(unittest.TestCase):
    def test_independent_path_score_matches_dp(self):
        obs,clock,_=fixture([(4,4)]*4+[(2,4)]+[(6,8)]*4)
        result=decode(clock,obs)
        self.assertAlmostEqual(result['score'],score_path(clock,obs,result['bars']),places=7)

    def test_exhaustive_small_bar_problem(self):
        obs,_,_=fixture([(1,16)])
        clock=np.array([[0.,.3],[.25,.425]])
        states=tuple(s for s in vocabulary() if (s['n'],s['d']) in [(1,32),(1,16),(3,4),(6,8)] and s['rhythm']=='regular' and s['visibility']=='observed')
        best=-np.inf
        for s in states:
            for end in range(1,s['length']+1):
                first=dict(q=(end-s['length'])/8,n=s['n'],d=s['d'],grouping=list(s['group']),rhythm=s['rhythm'])
                if end>=2:best=max(best,score_path(clock,obs,[first],states=states))
                else:
                    for t in states:
                        second=dict(q=.125,n=t['n'],d=t['d'],grouping=list(t['group']),rhythm=t['rhythm'])
                        best=max(best,score_path(clock,obs,[first,second],states=states))
        self.assertAlmostEqual(best,decode(clock,obs,states=states)['score'],places=7)

    def test_accent_332_is_a_rhythm_change_without_meter_change(self):
        obs,clock,gold=fixture([(4,4)]*12,accent_332=True)
        bars=[b for b in decode(clock,obs)['bars'] if 0<=b['q']<clock[-1,0]]
        self.assertEqual([(b['n'],b['d']) for b in bars],[(4,4)]*12)
        self.assertTrue(any(b['rhythm']=='syncopated' for b in bars))

    def test_missing_downbeats_retain_bar_count(self):
        obs,clock,gold=fixture([(4,4)]*16,missing_bars=range(5,10))
        bars=[b for b in decode(clock,obs)['bars'] if 0<=b['q']<clock[-1,0]]
        self.assertEqual([(b['q'],b['n'],b['d']) for b in bars],[(b['q'],b['n'],b['d']) for b in gold])

    def test_nonbar_riff_is_not_the_meter(self):
        obs,clock,gold=fixture([(4,4)]*12,riff=True)
        bars=[b for b in decode(clock,obs)['bars'] if 0<=b['q']<clock[-1,0]]
        self.assertEqual([(b['n'],b['d']) for b in bars],[(4,4)]*12)
        self.assertTrue(any(b['rhythm']=='riff_7_16' for b in bars))

    def test_rest_is_not_a_free_ending(self):
        obs,clock,_=fixture([(4,4)]*12,rest=(12,28))
        end,states=support(obs,clock)
        self.assertEqual(end,obs['duration'])
        self.assertTrue(any(s['state']=='weak_grid' for s in states['states']))

    def test_change_search_independent_of_bar_boundaries(self):
        obs,clock,bars=fixture([(4,4)]*12,tempo_changes=[(17.,.62),(31.,.5)])
        paths=search(obs,.5,beam=64,max_paths=3)
        candidates=[fit(p,obs,bars)[0] for p in paths]
        error=min(np.max(abs(time_at(c,np.arange(1,48))-time_at(clock,np.arange(1,48)))) for c in candidates)
        self.assertLess(error,.12)

    def test_all_original_meter_labels_remain_representable(self):
        states=vocabulary()
        for d in (2,4,8,16,32):
            for n in range(1,33):self.assertTrue(any(s['n']==n and s['d']==d for s in states))


if __name__=='__main__':unittest.main()
