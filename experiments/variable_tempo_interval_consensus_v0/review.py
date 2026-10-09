"""Freeze exact sources/settings, then check required execution invariants."""
import argparse
from pathlib import Path
from tools.project_storage import ROOT
from .io import read,write,digest


def paths(run):
    code=list(Path(__file__).parent.glob('*.py'))
    code += [ROOT/'experiments/metronome_reconstruction_v1'/name for name in ('infer.py','hinted.py','grid.py','config-tap-v2.json')]
    code += [ROOT/'experiments/variable_clock_exploration_v1'/name for name in ('phasor.py','clock.py','observations.py')]
    code += [run/name for name in ('protocol.json','source-inputs.json','assumed-initial-inputs.json','selected-config.json')]
    code += list((run/'candidate-banks').glob('*.json'))
    code += [Path(r['evidence_path']) for r in read(run/'source-inputs.json')['samples']]
    return sorted(set(code))


def check_freeze(run):
    frozen=read(run/'predictor-freeze.json')
    for path,value in frozen['files'].items():
        if digest(path)!=value:raise ValueError('Frozen source/settings changed: '+path)
    return True


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--stage',choices=['freeze','review'],required=True);a=p.parse_args()
    if a.stage=='freeze':
        if (a.run/'predictor-freeze.json').exists():raise ValueError('A freeze must be new')
        if not read(a.run/'controls-v1.json')['mandatory_passed']:raise ValueError('Controls failed')
        cfg=read(a.run/'selected-config.json')
        write(a.run/'predictor-freeze.json',dict(files={str(p.resolve()):digest(p) for p in paths(a.run)},
              selected=cfg,primary_real_and_prospective_evaluation_not_started=True,
              official_model_sha256=digest(ROOT/'data/models/final0.ckpt'),initial_assumptions_are_explicit_input_channel=True))
        index=read(a.run/'evaluation-index.json')['rows']
        refs={str(Path(r['reference_path']).resolve()):digest(r['reference_path']) for r in index}
        write(a.run/'evaluation-freeze.json',dict(manifest_sha256=digest(a.run/'evaluation-index.json'),reference_files=refs,
              prediction_worker_does_not_open_this_reference_guard=True,preparation_qualification_and_initial_proxy_extraction_permitted=True))
        print('FROZEN',len(paths(a.run)),flush=True)
    else:
        checks=[]
        checks.append(dict(name='frozen_source_correspondence',passed=check_freeze(a.run)))
        sources=read(a.run/'source-inputs.json')['samples']
        receipt=read(a.run/'frozen-receipt.json')
        checks.append(dict(name='complete_source_accounting',passed=receipt['completed'] and len(receipt['rows'])==len(sources) and not receipt['exceptions']))
        checks.append(dict(name='all_logical_controls',passed=read(a.run/'controls-v1.json')['mandatory_passed']))
        for condition in read(a.run/'protocol.json')['conditions']:
            for policy in ('none','initial_unit','initial_exact'):
                folder=a.run/'frozen-predictions'/condition/policy
                checks.append(dict(name=condition+'/'+policy,passed={p.stem for p in folder.glob('*.json')}=={r['id'] for r in sources}))
        checks.append(dict(name='formal_catalog_and_reserved_unchanged_by_admission',passed=read(a.run/'admission.json')['reserved98_consumed']==0 and not read(a.run/'admission.json')['formal_catalog_changed']))
        checks.append(dict(name='new_music_24_coordinate_checks',passed=read(ROOT/'data/samples/generated/interval-consensus-a-v1-20261008/coordinate-verification.json')['all_passed']))
        write(a.run/'execution-review.json',dict(checks=checks,all_passed=all(c['passed'] for c in checks),
              software_procedure_checks_not_music_success=True,official_model_unchanged=digest(ROOT/'data/models/final0.ckpt')==read(a.run/'predictor-freeze.json')['official_model_sha256']))
        print('REVIEW',sum(c['passed'] for c in checks),'/',len(checks),flush=True)
        if not all(c['passed'] for c in checks):raise SystemExit(1)


if __name__=='__main__':main()
