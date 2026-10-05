"""Comparison contracts: separate change causes and valid hierarchy padding."""
import unittest
import numpy as np
import torch
from .structure_compare import CompareModel,targets,observed_bar_ids


class ComparisonContracts(unittest.TestCase):
    def row(self):
        return dict(dataset='procedural',weight=1.,labels=dict(support=[0.,4.],beats=[0.,.5,1.,1.5,2.,2.6,3.2,3.8],bars=[0.,1.,2.8],
            meter_known=True,meter=[dict(time_seconds=0.,numerator=4,denominator=4),dict(time_seconds=1.,numerator=3,denominator=4)],
            tempo=[dict(time_seconds=0.,bpm_quarter=120.),dict(time_seconds=2.,bpm_quarter=100.)],no_grid=[]))

    def test_meter_and_tempo_changes_are_separate(self):
        events,_,_,_,_,_=targets(self.row(),50)
        self.assertGreater(events[12,2],.9);self.assertLess(events[12,4],.001)
        self.assertGreater(events[25,4],.99);self.assertLess(events[25,2],.001)

    def test_unknown_meter_fields_are_masked(self):
        row=self.row();row['labels']['meter_known']=False
        _,mask,num,den,_,_=targets(row,50)
        self.assertTrue(np.all(num==-100));self.assertTrue(np.all(den==-100));self.assertTrue(np.all(mask[:,2]==0))

    def test_hierarchy_uses_source_proposals_and_handles_padding(self):
        torch.set_num_threads(2)
        logits=np.full((60,2),-3.,np.float32);logits[[5,25,45],1]=4.
        ids=observed_bar_ids(logits)
        self.assertEqual(len(np.unique(ids)),4)
        model=CompareModel('C');x=torch.randn(2,60,514);padding=torch.zeros((2,60),dtype=torch.bool);padding[1,40:]=True
        bars=torch.from_numpy(np.tile(ids,(2,1)))
        outputs=model(x,padding,bars)
        self.assertEqual(outputs['events'].shape,(2,60,5));self.assertTrue(torch.isfinite(outputs['events']).all())
        loss=outputs['events'][~padding].square().mean();loss.backward()
        self.assertTrue(torch.isfinite(model.input.weight.grad).all())


if __name__=='__main__':unittest.main()
