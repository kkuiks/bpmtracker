"""Separate bar-origin evidence from latent accent-role interpretation.

Controlled intervention on the identical sealed phase/suffix candidate graph:
for each retained prefix, select its initial phase using literal neural-bar
likelihood. Then compare prefixes using the role-aware bar criterion. This
prevents cheap quarter roles from erasing the evidence that distinguishes bar
origins. No new candidate, reference phase, or identity rule is introduced.
"""
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ProcessPoolExecutor,as_completed
from collections import defaultdict
import os,json,math,hashlib
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
import numpy as np
from source_scores import ROOT,CONFIG
from experiments.beat_event_map_v1.core import state,child_state
RUN=Path(__file__).resolve().parent
BASES={'formal':ROOT/'data/research/runs/formal_map_comparison_v1/20261019-current44-v1',
       'broad':ROOT/'data/research/runs/broad_map_evaluation_v1/20261018-full-corpus-v1'}
METHODS={'literal_phase_role_suffix_mdl':False,'coded_literal_phase_role_suffix_mdl':True}

def observed_bar(value,events):
    times,weights=events['downbeat_times'],events['downbeat_weights'];duration=float(events['duration'])
    active=state(value['initial']);result=0.;noise=CONFIG['evidence_clutter_probability']
    for event in value['events']+[{'time':duration}]:
        lo,hi=np.searchsorted(times,[active['start'],event['time']]);t=times[lo:hi]
        period=60./active['bpm']*active['numerator']*4./active['denominator']
        residual=(t-active['phase']+period/2.)%period-period/2.
        agreement=np.exp(-.5*(residual/CONFIG['neural_sigma_seconds'])**2)
        result+=.5*CONFIG['bar_weight']*float(np.sum(weights[lo:hi]*np.log(noise+(1.-noise)*agreement)))
        if 'quarter' not in event:break
        active=child_state(active,event['time'],event['quarter'],event.get('bpm',active['bpm']),event.get('numerator',active['numerator']),event.get('denominator',active['denominator']))
    return result

def one(task):
    cohort,ident=task;path=RUN/f'{cohort}-hier-components/{ident}.json'
    old=json.loads((RUN/f'{cohort}-phase-components/{ident}.json').read_text())
    with np.load(BASES[cohort]/f'events/{ident}.npz',allow_pickle=False) as f:events={k:f[k].copy() for k in f.files}
    rows=[];groups=defaultdict(list)
    for original in old['candidates']:
        row={**original};literal=observed_bar(row['geometry'],events)
        row['literal_observed_bar']=literal
        row['literal_phase_score']=literal+sum(row['components'][k] for k in ('expected_bar','meter_prior','transition'))
        groups[row['retained_events']].append(row);rows.append(row)
    selections={};phase_choices={}
    for method,coded in METHODS.items():
        eligible=[]
        for n,bank in groups.items():
            code=math.log(len(bank)) if coded else 0.
            penalized=lambda c:c['literal_phase_score']-(code if c['rotation_quarters'] else 0.)
            best=max(bank,key=lambda c:(penalized(c),-c['rotation_quarters']))
            cost=code if best['rotation_quarters'] else 0.
            eligible.append((best['scores']['phase_completed_suffix_mdl']-cost,best))
        value,best=max(eligible,key=lambda x:(x[0],-x[1]['retained_events'],-x[1]['rotation_quarters']))
        selections[method]={'candidate_index':best['candidate_index'],'score':value}
        phase_choices[method]=[{'retained_events':row['retained_events'],'candidate_index':row['candidate_index'],
                                'literal_phase_score':row['literal_phase_score'],'role_prefix_score':score} for score,row in eligible]
    for row in rows:
        row['scores']={m:row['scores']['phase_completed_suffix_mdl'] for m in METHODS}
    summary={'id':ident,'candidate_count':len(rows),'selections':selections}
    payload={'source_only':True,'reference_read':False,'duration_seconds':old['duration_seconds'],
             'summary':summary,'candidates':rows,'phase_selection_per_prefix':phase_choices}
    path.parent.mkdir(exist_ok=True)
    with path.open('x') as f:json.dump(payload,f)
    return summary

def main():
    with (RUN/'hierarchical-phase-contract.json').open('x') as f:json.dump({
        'created_at_utc':datetime.now(timezone.utc).isoformat(),'reference_read':False,
        'hypothesis':'Literal neural bar evidence selects global bar origin; role-aware evidence selects meter suffix, with a boundary code',
        'methods':METHODS,'graph_unchanged_from_phase_completion':True,'adaptive_known_development':True,
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},f,indent=2)
    for cohort in BASES:
        original=json.loads((RUN/f'{cohort}-phase-selection-seal.json').read_text());rows=[]
        with ProcessPoolExecutor(max_workers=2) as pool:
            for future in as_completed([pool.submit(one,(cohort,r['id'])) for r in original['summaries']]):rows.append(future.result())
        folder=RUN/f'{cohort}-hier-components'
        seal={'completed_at_utc':datetime.now(timezone.utc).isoformat(),'reference_read':False,'sources':len(rows),
              'maps':sum(r['candidate_count'] for r in rows),'variants':METHODS,'summaries':sorted(rows,key=lambda r:r['id']),
              'component_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.json')}}
        with (RUN/f'{cohort}-hier-selection-seal.json').open('x') as f:json.dump(seal,f,indent=2)
        print(json.dumps({'cohort':cohort,'sources':seal['sources'],'maps':seal['maps']}),flush=True)

if __name__=='__main__':main()
