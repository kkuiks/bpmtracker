"""Check numerical output and hint information contracts of the simple clock."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from experiments.metronome_reconstruction_v1.infer import make_evidence
from .controls_trace import fixture
from .inference import write_json
from .simple_clock import prepare_family, select


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    model=json.loads(Path('experiments/metronome_reconstruction_v1/config-tap-v2.json').read_text())
    config=json.loads(Path(__file__).with_name('simple-clock-v1.json').read_text())
    cases=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        cases.append({'name':name,'passed':True})
    for bpm,meter,weak in [(120,4,False),(83+1/3,3,True)]:
        evidence=make_evidence(*fixture(bpm,meter,weak),model)
        family=prepare_family(evidence,model,config)
        check(f'{bpm}:source_generates_candidates',family['status']=='audio_family_prepared' and len(family['candidates'])>0)
        before=deepcopy(family)
        predictions=[select(family,value) for value in [bpm-2,bpm,bpm+2]]
        check(f'{bpm}:same_unit_predictions_identical',predictions[0]==predictions[1]==predictions[2])
        check(f'{bpm}:hint_does_not_change_prepared_family',family==before)
        prediction=select(family)
        check(f'{bpm}:same_fixed_output_contract',model['bpm_min']<=prediction['quarter_bpm']<=model['bpm_max']
              and prediction['bpm_fraction']['denominator']<=4 and prediction['time_signature']['numerator'] in [3,4]
              and prediction['time_signature']['denominator']==4
              and 0<=prediction['offset_seconds']<prediction['time_signature']['numerator']*prediction['period_seconds'])
        check(f'{bpm}:no_continuous_hint_or_meter_feature',all(not value['time_signature_supplied']
              and not value['raw_tap_number_used_after_unit_selection'] for value in predictions))
    empty=make_evidence(np.full(1000,-8),np.full(1000,-8),20,model)
    check('no_events_cannot_create_clock',select(prepare_family(empty,model,config))['quarter_bpm'] is None)
    write_json(args.output,{'purpose':'Simple-clock output and hint contracts; not music accuracy','cases':cases,'passed':True})
    print(f'PASS {len(cases)} simple-clock controls',flush=True)


if __name__=='__main__':main()
