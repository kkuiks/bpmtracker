"""Offline production-map supervision. Inference never imports this module."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from experiments.tempo_meter_v3.probe_resources import digest

VALIDATION_GROUPS={'daybreak','walker','rwc','state_shirt'}


def group_for(ident):
    if ident.startswith('daybreak_'):return 'daybreak'
    if ident=='walker_he-will-hold-me-fast':return 'walker'
    if ident=='rwc_p002':return 'rwc'
    if ident=='legacy_circle':return 'circle'
    if ident=='state_shirt_hospital_hill':return 'state_shirt'
    # Collapse all NTM projects conservatively; shared producer identity is not
    # fully verified. They cannot straddle weight fitting and validation.
    return 'ntm_projects'


def nearest_soft(times,events,sigma):
    events=np.sort(np.asarray(events,float))
    if not len(events):return np.zeros(len(times),np.float32)
    ix=np.searchsorted(events,times)
    delta=np.minimum(abs(times-events[np.clip(ix,0,len(events)-1)]),abs(times-events[np.clip(ix-1,0,len(events)-1)]))
    return np.exp(-.5*(delta/sigma)**2).astype(np.float32)


def target(reference,count,no_grid=(),fps=50):
    from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters,emitted_bars
    from experiments.analysis_legacy.music_map_contract import prepare_map
    reference=prepare_map(reference)
    times=np.arange(count)/fps
    valid=np.zeros(count,bool)
    for lo,hi in reference['support_seconds']:valid|=(times>=lo)&(times<hi)
    y=np.stack([nearest_soft(times,emitted_quarters(reference),.030),nearest_soft(times,emitted_bars(reference),.040)],1)
    y=np.column_stack([y,valid.astype(np.float32)])
    for lo,hi in no_grid:
        index=(times>=lo)&(times<hi);valid[index]=True;y[index]=0
    return y,valid.astype(np.float32)


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True)
    p.add_argument('--inventory',type=Path,required=True);p.add_argument('--reference-directory',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    inputs=json.loads(a.input.read_text());inventory=json.loads(a.inventory.read_text())
    inv={r['id']:r for r in inventory['rows']};a.output.mkdir(parents=True,exist_ok=False);rows=[]
    for row in inputs['rows']:
        ident=row['id'];entry=inv[ident]
        if entry['role']!='finished_recording_development':continue
        if digest(entry['reference'])!=entry['reference_expected']:raise ValueError('accepted source reference changed')
        reference_file=a.reference_directory/(ident+'-reference.json');record=json.loads(reference_file.read_text())
        if record['reference_binding']['sha256']!=entry['reference_expected']:raise ValueError('adapter binding differs')
        ref=record['map'];group=group_for(ident);duration=row['source']['sample_frames']/row['source']['sample_rate']
        no_grid=[]
        if ident in {'walker_he-will-hold-me-fast','forrester-savell-karnivool','jens-bogren-opeth'}:
            end=ref['support_seconds'][-1][1];no_grid=[[end,duration]]
        feature=Path('data/cache/tempo-meter-v3/acoustic-v1')/(row['source']['sha256']+'.npz')
        receipt=json.loads(feature.with_suffix('.json').read_text())
        if receipt['binding']!=row['feature_binding'] or digest(feature)!=receipt['feature_sha256']:raise ValueError('feature binding changed')
        with np.load(feature) as z:count=len(z['logits'])
        y,mask=target(ref,count,no_grid);path=a.output/(ident+'.npz');np.savez_compressed(path,y=y,mask=mask)
        rows.append(dict(id=ident,group=group,split='validation' if group in VALIDATION_GROUPS else 'train',
            audio=row['audio'],source=row['source'],initial_bpm=row['initial_bpm'],features=str(feature.resolve()),
            feature_sha256=receipt['feature_sha256'],targets=str(path.resolve()),targets_sha256=digest(path),
            reference_map=str(reference_file.resolve()),reference_map_sha256=digest(reference_file),
            accepted_reference_sha256=entry['reference_expected'],no_grid=no_grid,
            qualification=dict(owner_reviewed=True,sample_exact_timing_certified=False,grouping_supervised=False,
                bpm_regression_supervised=False,tempo_change_supervised=False,meter_classes_supervised=False,
                quarter_and_bar_events_supervised=True,grid_support_supervised=True,unknown_outside_approved_support_masked=True,
                beat_this_pretraining_exposure='known RWC exposure' if group=='rwc' else 'not established')))
    groups={s:{r['group'] for r in rows if r['split']==s} for s in ['train','validation']}
    assert not groups['train']&groups['validation']
    manifest=dict(complete=True,rows=rows,known_development_material=True,unseen_generalization_test=False,
        group_policy='All NTM conservatively together; Daybreak, Walker, RWC and State Shirt held from weight fitting',
        source_manifest_sha256=digest(a.input),inventory_sha256=digest(a.inventory),
        qualification='Owner-reviewed useful maps, not millisecond gold; producer grouping collapsed conservatively; auxiliary excluded',
        target_contract='50fps quarter sigma30ms/bar sigma40ms/grid support binary; support mask and explicit no-grid negative labels; no interval-BPM regression or inferred grouping')
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(rows=len(rows),splits={s:sum(r['split']==s for r in rows) for s in groups},groups={s:sorted(g) for s,g in groups.items()})))


if __name__=='__main__':main()
