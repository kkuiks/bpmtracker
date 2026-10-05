"""Score a completed frozen gate-2 batch. Reference access exists only here."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from .probe_resources import digest


def load_bound(binding):
    p=Path(binding['path'])
    if digest(p)!=binding['sha256']:raise ValueError('bound artifact changed')
    return json.loads(p.read_text())


def references(root,rows):
    sys.path.insert(0,str(root/'experiments/analysis_legacy'))
    from experiments.tempo_meter_v2.score_primary8 import reference_map
    from experiments.tempo_meter_v2.score_scoped_primary import reference_raw
    catalog=json.loads((root/'data/corpus/primary-references-v6/catalog.json').read_text())
    table={r['id']:r for r in catalog['tracks']};result={}
    for row in rows:
        ident=row['id'];source=row['source']
        if ident=='wage_war':
            path=root/'data/runs/reference-audit/wage-war-owner-acceptance-20260930-v1/owner-acceptance.json'
            approval=json.loads(path.read_text())
            binding=dict(path='/mnt/d/NailTheMix/processed/will-carlson-wage-war-song-of-the-swamp/tempo-owner-accepted-v1.json',sha256=approval['primary_map_sha256'])
            accepted=load_bound(binding);converted=deepcopy(accepted)
            for name in ('tempo_events','meter_events'):
                for event in converted[name]:event['time_seconds']=event['master_seconds']
            raw=reference_map({},converted,source);policy=None
        else:
            track=table[ident];binding=track['accepted_tempo_map'];accepted=load_bound(binding)
            if track['canonical_audio']['sha256']!=source['sha256']:raise ValueError('reference source mismatch')
            if track['qualification']['reference_tier']=='user_reviewed_scoped_click_map':
                policy=load_bound(track['scoring_policy']);raw=reference_raw(accepted,source)
            else:
                policy=None;raw=accepted['music_map'] if 'music_map' in accepted else reference_map(track,accepted,source)
        result[ident]=dict(map=raw,accepted=accepted,policy=policy,binding=binding)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    manifest=json.loads(a.manifest.read_text())
    if not manifest['complete'] or manifest['references_available_to_runner']:raise ValueError('freeze complete predictions before scoring')
    root=Path.cwd();sys.path.insert(0,str(root/'experiments/analysis_legacy'))
    from experiments.tempo_meter_v2.score_generic13 import normal_score
    from experiments.tempo_meter_v2.score_scoped_primary import score_scoped
    refs=references(root,manifest['rows']);results=[]
    a.output.mkdir(parents=True)
    for row in manifest['rows']:
        ref=refs[row['id']];prediction=load_bound(row['selected'])
        def score(value):
            if ref['policy']:return score_scoped(ref['accepted'],ref['policy'],value,row['source'])
            return normal_score(ref['map'],value,ref['accepted']['beats_seconds'],row['id']=='daybreak_nocturne')
        oracle=score({'map':ref['map']})
        if not oracle['all_gates_pass']:raise ValueError('reference self-score fails: '+row['id'])
        result=score(prediction)
        (a.output/(row['id']+'-reference.json')).write_text(json.dumps(dict(map=ref['map'],reference_binding=ref['binding']),indent=2)+'\n')
        results.append(dict(id=row['id'],title=row['title'],score=result,prediction_sha256=row['selected']['sha256'],reference_self_score_passed=True))
        print(row['id'],json.dumps(result['scores']),flush=True)
    (a.output/'scores.json').write_text(json.dumps(dict(scope='four previously studied development recordings, not unseen',prediction_manifest_sha256=digest(a.manifest),rows=results,new_general_equivalence_policy_applied=False),indent=2)+'\n')

if __name__=='__main__':main()
