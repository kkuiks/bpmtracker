"""Known-arithmetic checks for generated-clock precision accounting."""

import argparse
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path

from experiments.metronome_reconstruction_v1.grid import timestamps
from .inference import write_json
from .score_generated import paired_contrasts, score, summarize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    model=json.loads(Path('experiments/metronome_reconstruction_v1/config-tap-v2.json').read_text())
    reference={'quarter_bpm':120,'period_seconds':.5,'time_signature':{'numerator':4,'denominator':4},
        'offset_seconds':.137,'quarter_times_seconds':[.137+i*.5 for i in range(480)],
        'downbeat_times_seconds':[.137+i*2 for i in range(120)],'origin_coordinate_bound_ms':.03125}
    def prediction(bpm,offset):
        period=60/bpm
        return {'status':'fixed_map_proposal','quarter_bpm':bpm,'period_seconds':period,
            'time_signature':{'numerator':4,'denominator':4},'offset_seconds':offset,
            'quarter_clicks_seconds':timestamps(period,offset,240).tolist(),
            'downbeats_seconds':timestamps(period*4,offset,240).tolist()}
    cases=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        cases.append({'name':name,'passed':True})
    perfect=score(prediction(120,.137),reference,240,model)
    check('defined_clock_exact_match',perfect['quarter_clock']['maximum_absolute_ms']==0
          and perfect['bar_clock']['maximum_absolute_ms']==0 and perfect['quarter_f1']['20']==1)
    bar=score(prediction(120,.637),reference,240,model)
    check('bar_error_not_hidden_by_quarter_match',bar['quarter_f1']['20']==1 and bar['downbeat_f1']['20']==0
          and abs(bar['bar_clock']['maximum_absolute_ms']-500)<1e-8)
    drift=score(prediction(120.25,.137),reference,240,model)
    check('drift_not_wrapped_to_short_residual',abs(drift['quarter_clock']['accumulated_drift_ms'])>400)
    source=deepcopy(reference);source['quarter_bpm']=120.1
    value=score(prediction(120,.137),source,240,model)
    check('nonrepresentable_rate_probe_marked_before_pass_counts',not value['reference_bpm_exactly_in_output_vocabulary']
          and abs(value['vocabulary_minimum_rate_drift_ms'])>190 and source['quarter_bpm']==120.1)
    failure=score({'status':'inference_failed'},reference,240,model)
    summary=summarize([{'conditions':{'method':{'metrics':perfect}}},{'conditions':{'method':{'metrics':failure}}}],['method'])['method']
    check('failed_clock_kept_in_generated_denominator',summary['denominator']==2 and summary['returned_clocks']==1
          and summary['representable_denominator']==2 and summary['quarter_macro_f1']['20']==.5)
    check('defined_origin_does_not_become_real_producer_claim',perfect['real_producer_precision_claim'] is False)
    pairs=[{'id':'base','parent_group':'one','variant':'straight',
            'defined_reference_clock':{'offset_seconds':1.9},'conditions':{'m':{'prediction':prediction(120,1.9)}}},
           {'id':'shift','parent_group':'one','variant':'leading_shift',
            'defined_reference_clock':{'offset_seconds':2.217},'conditions':{'m':{'prediction':prediction(120,.217)}}}]
    contrast=paired_contrasts(pairs,['m'])['pairs'][0]['conditions']['m']
    check('shift_comparison_preserves_bar_wrap',contrast['same_predicted_rate_and_meter']
          and abs(contrast['bar_phase_shift_residual_ms'])<1e-8)
    pairs[1]['conditions']['m']['prediction']=prediction(121,.217)
    contrast=paired_contrasts(pairs,['m'])['pairs'][0]['conditions']['m']
    check('changed_rate_not_reported_as_phase_invariance',not contrast['same_predicted_rate_and_meter']
          and contrast['bar_phase_shift_residual_ms'] is None)
    write_json(args.output,{'purpose':'Generated-clock metric bookkeeping; not music accuracy','cases':cases,'passed':True})
    print(f'PASS {len(cases)} generated-score controls',flush=True)


if __name__=='__main__':main()
