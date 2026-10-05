import unittest
import numpy as np
from .fixtures import fixture
from .bar_structure import decode
from .latent_clock import search,time_at
from .continuous import fit


class StructureTests(unittest.TestCase):
    def test_ideal_meter_group_and_short_change(self):
        for signatures in [[(4,4)]*8,[(6,8)]*8,[(7,8)]*8,[(31,4)]*3,[(4,4)]*4+[(2,4)]+[(4,4)]*4]:
            obs,clock,gold=fixture(signatures)
            got=decode(clock,obs)['bars']
            actual=[b for b in got if -.01<=b['q']<clock[-1,0]]
            self.assertEqual([(b['n'],b['d']) for b in actual],signatures)
            np.testing.assert_allclose([b['q'] for b in actual],[b['q'] for b in gold],atol=1e-6)

    def test_latent_missing_events_and_half_time(self):
        for half,rest in [(True,None),(False,(12,20))]:
            obs,clock,gold=fixture([(4,4)]*10,half_time=half,rest=rest)
            paths=search(obs,.5,beam=16,max_paths=2)
            path=min(paths,key=lambda p:p['loss'])
            fitted,_=fit(path,obs)
            q=np.arange(1,40)
            self.assertLess(np.max(abs(time_at(fitted,q)-time_at(clock,q))),.08)
            self.assertLessEqual(len(fitted),3)

    def test_small_tempo_change_preserves_same_quarter_number(self):
        obs,clock,_=fixture([(4,4)]*32,tempo_changes=[(63.,.5025)])
        paths=search(obs,.5,beam=32,max_paths=3)
        errors=[np.max(abs(time_at(fit(p,obs)[0],np.arange(1,128))-time_at(clock,np.arange(1,128)))) for p in paths]
        self.assertLess(min(errors),.02)

    def test_new_tempo_boundary_not_restricted_to_bars(self):
        obs,clock,gold=fixture([(4,4)]*10,tempo_changes=[(17.,.6)])
        paths=search(obs,.5,beam=32,max_paths=3)
        fitted=[fit(p,obs)[0] for p in paths]
        errors=[np.max(abs(time_at(c,np.arange(1,40))-time_at(clock,np.arange(1,40)))) for c in fitted]
        self.assertLess(min(errors),.10)


if __name__=='__main__':unittest.main()
