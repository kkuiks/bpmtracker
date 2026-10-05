"""Score valid learned maps with the frozen evaluator; retain decode failures.

Failed decodes have no musical map to score. Their metrics stay unavailable and
an explicit zero contribution preserves the complete cohort denominator.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

from experiments.tempo_meter_v3.probe_resources import digest
from experiments.tempo_meter_v3.build_reviewed_review import SCORE_KEYS,six_scores
from .run_learned import EXPECTED_DECODE_FAILURES

SOURCE_FIELDS=('id','audio','source','initial_bpm','initial_bpm_source','feature_binding')


def indexed(rows,label):
    result={r['id']:r for r in rows}
    if len(result)!=len(rows):raise ValueError('duplicate identities in '+label)
    return result


def aggregation_contributions(score):
    """Use the frozen six-score aliases without modifying any musical score."""
    values=[0.]*len(SCORE_KEYS) if score.get('status')=='decode_failed' else six_scores(score)
    return {aliases[0]:float(value) if value is not None else 0.
            for aliases,value in zip(SCORE_KEYS,values)}


def evaluate(manifest_path,input_path,inventory_path,reference_directory,output,*,resume=False):
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    from experiments.analysis_legacy.music_map_contract import prepare_map
    manifest_path=Path(manifest_path);input_path=Path(input_path);inventory_path=Path(inventory_path)
    reference_directory=Path(reference_directory);output=Path(output)
    manifest=json.loads(manifest_path.read_text());source=json.loads(input_path.read_text())
    inventory=json.loads(inventory_path.read_text())
    if not manifest['complete'] or manifest['references_available_to_runner']:
        raise ValueError('complete source-only attempted cohort required')
    if not source['complete'] or source['references_available_to_runner']:
        raise ValueError('complete original source-only input required')
    if manifest['input_sha256']!=digest(input_path):raise ValueError('learned input binding differs')
    rows=indexed(manifest['rows'],'learned manifest');inputs=indexed(source['rows'],'source input')
    inv=indexed(inventory['rows'],'reference inventory')
    baseline_path=reference_directory/'scores.json';baseline=json.loads(baseline_path.read_text())
    base=indexed(baseline['rows'],'qualified baseline evaluation')
    if set(rows)!=set(inputs) or set(rows)!=set(inv) or set(rows)!=set(base):
        raise ValueError('complete cohort identities differ')
    if baseline['prediction_manifest_sha256']!=digest(input_path) or baseline['inventory_sha256']!=digest(inventory_path):
        raise ValueError('qualified baseline binding differs')
    valid=[];failed={};reference_bindings={}
    for row in manifest['rows']:
        ident=row['id'];original=inputs[ident];entry=inv[ident]
        if any(row[key]!=original[key] for key in SOURCE_FIELDS):raise ValueError('source input row differs '+ident)
        if row['source']['sha256']!=entry['audio_expected'] or digest(row['audio'])!=entry['audio_expected']:
            raise ValueError('audio binding changed '+ident)
        if Path(row['audio']).resolve()!=Path(entry['audio']).resolve():raise ValueError('audio path differs '+ident)
        if digest(entry['reference'])!=entry['reference_expected']:raise ValueError('accepted reference changed '+ident)
        prediction_path=Path(row['selected']['path'])
        if digest(prediction_path)!=row['selected']['sha256']:raise ValueError('prediction changed '+ident)
        prediction=json.loads(prediction_path.read_text())
        ref_path=reference_directory/(ident+'-reference.json');record=json.loads(ref_path.read_text())
        binding=record['reference_binding']
        if binding['sha256']!=entry['reference_expected'] or Path(binding['path']).resolve()!=Path(entry['reference']).resolve():
            raise ValueError('qualified reference binding differs '+ident)
        qualified=prepare_map(record['map'])
        if qualified['source']!=row['source'] or not base[ident]['reference_self_score_passed']:
            raise ValueError('qualified reference source/self-score differs '+ident)
        if base[ident]['reference_sha256']!=entry['reference_expected'] or qualified['support_seconds']!=base[ident]['reference_support_seconds']:
            raise ValueError('qualified reference scope differs '+ident)
        reference_bindings[ident]=dict(path=str(ref_path.resolve()),sha256=digest(ref_path))
        if prediction.get('status')=='decode_failed':
            if prediction.get('map') is not None or prediction.get('error') not in EXPECTED_DECODE_FAILURES:
                raise ValueError('invalid expected decode-failure receipt '+ident)
            if not prediction.get('source_only') or prediction.get('reference_read') is not False or prediction.get('fallback_used') is not False:
                raise ValueError('failure receipt inference scope differs '+ident)
            failed[ident]=prediction
        else:
            if prediction['map']['source']!=row['source']:raise ValueError('prediction source differs '+ident)
            valid.append(row)
    # Only real decoded maps are passed to the existing unmodified evaluator.
    output.mkdir(parents=True,exist_ok=resume)
    scored={}
    valid_directory=output/'valid-evaluation'
    if valid:
        partial_manifest=deepcopy(manifest);partial_manifest['rows']=valid
        partial_inventory=deepcopy(inventory);partial_inventory['rows']=[inv[r['id']] for r in valid]
        mp=output/'valid-manifest.json';ip=output/'valid-inventory.json'
        for path,value in [(mp,partial_manifest),(ip,partial_inventory)]:
            if path.exists():
                if not resume or json.loads(path.read_text())!=value:
                    raise ValueError('existing valid-scoring input differs '+str(path))
            else:path.write_text(json.dumps(value,indent=2)+'\n')
        command=[sys.executable,'-m','experiments.tempo_meter_v3.evaluate_reviewed','--manifest',str(mp),
                 '--inventory',str(ip),'--output',str(valid_directory)]
        existing=valid_directory/'scores.json'
        if not (resume and existing.exists()):
            with (output/'valid-evaluation.log').open('w') as stream:
                subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True)
        valid_scores=json.loads(existing.read_text())
        if valid_scores['prediction_manifest_sha256']!=digest(mp) or valid_scores['inventory_sha256']!=digest(ip):
            raise ValueError('existing frozen valid scores binding differs')
        scored=indexed(valid_scores['rows'],'valid scored rows')
        if set(scored)!={r['id'] for r in valid}:raise ValueError('valid scored cohort differs')
    results=[]
    for row in manifest['rows']:
        ident=row['id']
        if ident in failed:
            previous=base[ident];keys=list(previous['score']['scores'])
            result={key:deepcopy(value) for key,value in previous.items() if key!='score'}
            result['prediction_sha256']=row['selected']['sha256']
            result['score']=dict(status='decode_failed',error=failed[ident]['error'],
                scores=dict.fromkeys(keys,None),gates=dict.fromkeys(previous['score']['gates'],False),
                all_gates_pass=False,map_metrics_computed=False,
                reference_support_seconds=previous['reference_support_seconds'])
            reference_path=Path(reference_bindings[ident]['path'])
        else:
            result=scored[ident]
            reference_path=valid_directory/(ident+'-reference.json')
        result['aggregation_contributions']=aggregation_contributions(result['score'])
        shutil.copyfile(reference_path,output/(ident+'-reference.json'))
        results.append(result)
    keys=[aliases[0] for aliases in SCORE_KEYS] if results else []
    record=dict(scope='20 reviewed development recordings plus one auxiliary clip; not unseen',
        prediction_manifest_sha256=digest(manifest_path),input_manifest_sha256=digest(input_path),
        inventory_sha256=digest(inventory_path),qualified_baseline_scores_sha256=digest(baseline_path),
        qualified_reference_bindings=reference_bindings,new_general_equivalence_policy_applied=False,
        attempted_source_count=len(results),successful_map_count=len(valid),failure_count=len(failed),
        failure_policy='No fabricated maps or fallback; failed decode metrics unavailable, all gates failed, explicit zero aggregation contribution, full denominator retained',
        aggregation_metric_aliases=[list(aliases) for aliases in SCORE_KEYS],
        aggregation_policy='Frozen six-score aliases; individual scores and gates unchanged',
        execution_implementation_sha256=digest(__file__),
        cohort_metric_averages_with_failure_penalty={key:sum(r['aggregation_contributions'][key] for r in results)/len(results) for key in keys},
        valid_maps_scored_by='unchanged experiments.tempo_meter_v3.evaluate_reviewed',rows=results)
    (output/'scores.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--reference-directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resume',action='store_true',help='Reuse a completed, hash-bound frozen valid-map evaluation')
    a=p.parse_args();record=evaluate(a.manifest,a.input,a.inventory,a.reference_directory,a.output,resume=a.resume)
    print(json.dumps({key:record[key] for key in ['attempted_source_count','successful_map_count','failure_count']},indent=2))


if __name__=='__main__':main()
