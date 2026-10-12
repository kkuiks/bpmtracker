"""Requested mechanism controls; generated observations are not real-song evidence."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from experiments.continuous_beat_map_v1.map import validate,grid
from .common import write,CONFIG,METHODS
from experiments.metronome_benchmark_v1.metrics import event_f1
from .source import prepare,encode
from .core import nodes,state,fit

def fixture(duration,events):
    return {'status':'map','duration_seconds':duration,'initial':{'bpm':120.,'numerator':4,'denominator':4,'bar_zero_source_seconds':0.},'events':events}

def observations(prediction,role_change=False):
    quarter=grid(prediction,'quarter');bar=grid(prediction,'bar')
    if role_change:
        extra=np.arange(4.25,prediction['duration_seconds'],.5)
        quarter=np.unique(np.r_[quarter,extra])
    return {'duration':np.array(prediction['duration_seconds']),'times':quarter,'weights':np.ones(len(quarter)),
            'downbeat_times':bar,'downbeat_weights':np.ones(len(bar)),'pcm_times':grid(prediction,'beat'),
            'pcm_weights':np.ones(len(grid(prediction,'beat')))}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--fit',action='store_true');args=parser.parse_args()
    tests=[]
    def check(name,value):tests.append({'name':name,'pass':bool(value)})
    base=fixture(16.,[]);initial={**base['initial'],'bootstrap_end':16.,'bootstrap_source_mass':32.,'family_prior':0.,'initial_source_origin':'control'}
    t,q=nodes(state(initial),16.)
    check('fourth_old_beat_inside_two_second_block_is_searchable',np.any(abs(t-3.5)<1e-8))
    check('first_twelve_seconds_have_legal_tempo_candidates',np.any(abs(t-1.5)<1e-8))
    prepared=prepare(observations(base));a=encode(prepared,116.4);b=encode(prepared,123.6)
    check('same_initial_role_discards_tap_number',a==b and set(a)=={'available','unit_id','numeric_tap_discarded'})
    check('source_runs_have_no_fixed_time_span',not prepared['fixed_wall_clock_windows_used'] and any(r['end']-r['start']>12 for r in prepared['pulses']))
    cases={
        'early_change':fixture(16.,[{'time':1.5,'quarter':3.,'bpm':150.}]),
        'fourth_beat':fixture(16.,[{'time':3.5,'quarter':7.,'bpm':150.}]),
        'short_excursion':fixture(16.,[{'time':3.5,'quarter':7.,'bpm':150.},{'time':5.5,'quarter':12.,'bpm':120.}]),
        'partial_bar_meter':fixture(16.,[{'time':3.5,'quarter':7.,'numerator':3,'denominator':4}]),
        'rhythm_density_only':base,
        'weak_evidence_dropout':base,
    }
    results=[]
    if args.fit:
        for name,truth in cases.items():
          for method in ['E2_RHYTHM_ROLES','E3_SAME_UNIT_GATE']:
            source=observations(truth,name=='rhythm_density_only');bank=prepare(source);packet=encode(bank,120.)
            if name=='weak_evidence_dropout':
                for times,weights in [('times','weights'),('downbeat_times','downbeat_weights'),('pcm_times','pcm_weights')]:
                    use=source[times]<4.;source[times]=source[times][use];source[weights]=source[weights][use]
                bank=prepare(source);packet=encode(bank,120.)
            pred=fit(source,bank,packet,method)
            emitted=grid(pred,'quarter');target=grid(truth,'quarter')
            errors=np.array([min(abs(emitted-value)) for value in target])
            result={'name':name,'method':method,'legal':validate(pred)['legal'],'quarter_recall_30ms':float(np.mean(errors<=.03)),
                    'bar_f1_30ms':event_f1(grid(pred,'bar'),grid(truth,'bar'),.03),
                    'expected_events':truth['events'],'emitted_events':pred['events'],
                    'no_false_change':not pred['events'] if name=='rhythm_density_only' else None,
                    'prediction':pred,'generated_mechanism_only':True}
            results.append(result);print('CONTROL',name,method,result['quarter_recall_30ms'],result['bar_f1_30ms']['f1'],len(pred['events']),flush=True)
    write(args.out,{'representation_checks':tests,'fit_controls':results,'real_music_performance':False,
                    'failures_must_be_preserved_for_followup':True})
    print('REPRESENTATION',sum(r['pass'] for r in tests),'/',len(tests),flush=True)
    if not all(t['pass'] for t in tests):raise RuntimeError('Representation control failed')

if __name__=='__main__':main()
