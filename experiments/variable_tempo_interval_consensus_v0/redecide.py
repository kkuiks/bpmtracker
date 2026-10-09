"""Pre-freeze source-only decision revision; preserve the initial calibration version."""
import argparse
from pathlib import Path
import shutil
from . import core
from .io import read,write,source_array


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    if (a.run/'predictor-freeze.json').exists():raise ValueError('No pre-freeze revision after freeze')
    previous=a.run/'calibration-predictions-pre-density-guard'
    if previous.exists():raise ValueError('Already revised')
    shutil.move(str(a.run/'calibration-predictions'),str(previous))
    sources={r['id']:r for r in read(a.run/'source-inputs.json')['samples']}
    initial={r['id']:{k:v for k,v in r.items() if k!='id'} for r in read(a.run/'assumed-initial-inputs.json')['rows']}
    count=0
    for folder in sorted(p for p in previous.iterdir() if p.is_dir()):
        for path in sorted((folder/'none').glob('*.json')):
            row=sources[path.stem];data=source_array(row['evidence_path']);obs=core.observation(data)
            pred=read(path);cfg=pred['configuration'];anchors=[]
            for anchor in pred.get('initial_anchor_episodes',[]):
                h=dict(bpm=anchor['bpm'],phase=anchor['phase'],bars=[anchor['phase']])
                f=core.clock_features(obs,h,cfg)
                anchors.append(core.clip_initial_anchor(anchor,f,obs))
            pred['initial_anchor_episodes']=anchors
            for policy in ('none','initial_unit','initial_exact'):
                accepted,ambiguous,scope=core.decision(pred['episodes'],obs,cfg,initial.get(row['id']) if policy!='none' else None,policy,anchors)
                output=dict(pred,accepted=accepted,ambiguous=ambiguous,initial_information_scope=scope,initial_information_policy=policy,
                            initial_information_is_assumed_not_measured=policy!='none' and row['id'] in initial)
                write(a.run/'calibration-predictions'/folder.name/policy/path.name,output);count+=1
    write(a.run/'source-decision-revision.json',dict(predictions=count,original_calibration_predictions_preserved=str(previous),
          reason='Prevent numeric initial BPM declaration persisting through an observed metrical/octave regime change',
          source_only=True,reference_files_read=False,real_or_prospective_scores_read=False,candidate_scores_and_episode_proposals_unchanged=True))
    print('REDECIDED',count,flush=True)


if __name__=='__main__':main()
