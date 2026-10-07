"""Known-clock controls for post-prediction diagnostic interpretation."""

import argparse
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path

from experiments.metronome_reconstruction_v1.grid import timestamps
from .decompose import inspect_trace
from .gtzan import score_annotation
from .inference import write_json


def candidate(bpm, phase, score, down=.8):
    value=Fraction(bpm)
    return {'quarter_bpm':float(value),'bpm_fraction':{'numerator':value.numerator,'denominator':value.denominator},
            'period_seconds':60/float(value),'time_signature':{'numerator':4,'denominator':4},
            'offset_seconds':phase,'score':score,'beat_evidence':{'weighted_smooth_f1':.8},
            'downbeat_evidence':{'weighted_smooth_f1':down}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    protocol=json.loads(Path(__file__).with_name('protocol-gtzan-v1.json').read_text())
    config=json.loads(Path('experiments/metronome_reconstruction_v1/config-tap-v2.json').read_text())
    p=60/120.1
    reference={'pulse_bpm':120.1,'bar_pulse_count':4,'support_seconds':[0,10],
               'beat_times_seconds':[i*p for i in range(20)],'downbeat_times_seconds':[i*p for i in range(0,20,4)],
               'precise_producer_clock_verified':False,'notation_denominator_verified':False}
    good=candidate(120,0,.8,.2)
    selected=candidate(120,.5,.9,.95)
    prediction={**selected,'status':'fixed_map_proposal','confidence_flags':[],
        'quarter_clicks_seconds':timestamps(.5,.5,10).tolist(),'downbeats_seconds':timestamps(2,.5,10).tolist()}
    row={'id':'fixture','genre':'fixture','duration_seconds':10,
         'conditions':{'audio_only':{'prediction':prediction,'metrics':score_annotation(prediction,reference,protocol)}}}
    records=[{'score_id':1,'block':'layer_0','stage':'coarse','candidate':good},
             {'score_id':2,'block':'layer_0','stage':'coarse','candidate':selected}]
    events=[{'event':'block_finished','retained_score_ids':[2]}]
    before=deepcopy(row)
    data=inspect_trace(row,reference,records,events,{'complete':True},config,70)
    cases=[]
    def check(name,value):
        if not value:
            raise AssertionError(name)
        cases.append({'name':name,'passed':True})
    check('reference_best_candidate_is_not_primary_prediction',row==before and data['oracle_diagnostic_is_not_a_primary_prediction'])
    check('scored_but_pruned_phase_remains_visible',data['best_annotation_agreement_clock_in_family']['audio_score_rank_among_unique_family_clocks']==2
          and not data['best_annotation_agreement_clock_in_family']['retained_in_public_top_candidates'])
    check('same_rate_wrong_bar_phase_separated',data['primary_beat_f1']==1 and data['primary_downbeat_f1']==0
          and 'perfect_beats_zero_downbeats' in data['categories'])
    check('vocabulary_floor_does_not_round_reference',data['vocabulary']['nearest_bpm']==120
          and data['vocabulary']['original_reference_bpm']==120.1 and not data['vocabulary']['exact_expression'])
    check('unverified_reference_remains_unresolved',not data['reference_precision_verified']
          and not data['reference_notation_verified'] and data['causal_status'].startswith('unresolved'))
    check('downbeat_evidence_preference_is_measured_not_corrected',data['selected_downbeat_evidence_minus_annotation_phase']>.7
          and prediction['offset_seconds']==.5)
    low=candidate(60,0,.9)
    low_prediction={**low,'status':'fixed_map_proposal','confidence_flags':[],
        'quarter_clicks_seconds':timestamps(1,0,10).tolist(),'downbeats_seconds':timestamps(4,0,10).tolist()}
    low_row={**row,'conditions':{'audio_only':{'prediction':low_prediction,'metrics':score_annotation(low_prediction,reference,protocol)}}}
    missing=inspect_trace(low_row,reference,[{'score_id':1,'block':'base_search','stage':'coarse','candidate':good},
        {'score_id':2,'block':'layer_0','stage':'coarse','candidate':low}],events,{'complete':True},config,70)
    check('base_candidate_loss_distinct_from_no_generation','compatible_base_rate_lost_in_family_narrowing' in missing['categories']
          and missing['trace']['rate_compatible_base_clocks']==1 and missing['trace']['rate_compatible_family_clocks']==0)
    write_json(args.output,{'purpose':'Post-prediction mechanism diagnostics; not music accuracy','cases':cases,'passed':True})
    print(f'PASS {len(cases)} decomposition controls',flush=True)


if __name__=='__main__':
    main()
