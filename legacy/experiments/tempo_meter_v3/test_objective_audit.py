"""Independent score replay and ideal-label controls for frozen decoding."""
import itertools
import unittest
import numpy as np
from .test_meter_duration import fixture
from .meter_search import decode_meter
from .meter_objective_audit import objective_arrays,score_path


class ObjectiveAuditTest(unittest.TestCase):
    def test_score_replays_actual_dynamic_program(self):
        for signatures in [[(4,4)]*8,[(6,8)]*8,[(7,8)]*8,[(31,4)]*3,
                           [(4,4)]*3+[(2,4)]+[(4,4)]*3]:
            clock,logits,head,_=fixture(signatures)
            selected=decode_meter(clock,logits,head)
            actual=score_path(selected['bars'],objective_arrays(clock,logits,head))
            self.assertAlmostEqual(actual['total'],selected['score']*clock[-1,0],places=8)

    def test_exhaustive_two_bar_paths_cannot_outscore_dp(self):
        clock,logits,head,_=fixture([(2,4)]*2)
        arrays=objective_arrays(clock,logits,head)
        chosen=decode_meter(clock,logits,head)['score']*clock[-1,0]
        meters=[(1,4),(2,4),(3,4),(4,4),(6,8)]
        for length in range(1,5):
            for signatures in itertools.product(meters,repeat=length):
                q=0.;bars=[]
                for n,d in signatures:
                    bars.append(dict(q=q,n=n,d=d));q+=4*n/d
                if q!=4:continue
                self.assertLessEqual(score_path(bars,arrays)['total'],chosen+1e-8)

    def test_full_vocabulary_exhaustive_on_two_lattice_cells(self):
        from .meter_search import METERS, SUBDIVISION
        rng=np.random.default_rng(20261001)
        clock=np.array([[0.,.5],[.25,.625]])
        logits=rng.normal(size=(50,2))
        head=dict(events=rng.normal(size=(13,4)),numerator=rng.normal(size=(13,32)),
                  denominator=rng.normal(size=(13,5)))
        arrays=objective_arrays(clock,logits,head)
        best=-float('inf')
        # The initial bar may begin at every legal negative lattice position.
        # With a two-cell domain, only an initial bar ending at cell 1 can
        # require a second bar. This enumerates every terminal path, all 160
        # signatures, all legal pickups, without the DP recurrence.
        for n,d in METERS:
            length=round(4*n/d*SUBDIVISION)
            for first_end in range(1,length+1):
                first=dict(q=(first_end-length)/SUBDIVISION,n=n,d=d)
                if first_end>=2:
                    best=max(best,score_path([first],arrays)['total'])
                else:
                    for n2,d2 in METERS:
                        second=dict(q=1/SUBDIVISION,n=n2,d=d2)
                        best=max(best,score_path([first,second],arrays)['total'])
        selected=decode_meter(clock,logits,head)
        self.assertAlmostEqual(best,selected['score'],places=8)

    def test_rejects_discontinuous_or_off_lattice_paths(self):
        clock,logits,head,_=fixture([(4,4)]*2)
        arrays=objective_arrays(clock,logits,head)
        for bars in [[dict(q=.03,n=4,d=4)],
                     [dict(q=0,n=4,d=4),dict(q=5,n=4,d=4)]]:
            with self.assertRaises(ValueError):score_path(bars,arrays)


if __name__=='__main__':unittest.main()
