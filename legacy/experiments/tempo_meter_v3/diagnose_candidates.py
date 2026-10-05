"""Audit frozen candidate quality; oracle comparisons are diagnosis only."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from .build_reviewed_review import six_scores
from .evaluate_batch import load_bound, references
from .evaluate_reviewed import adapt_extra, score_extra
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    from experiments.tempo_meter_v2.score_generic13 import normal_score
    from experiments.tempo_meter_v2.score_scoped_primary import score_scoped
    manifest=json.loads((a.run/'predictions/manifest.json').read_text())
    if not manifest['complete']:raise ValueError('complete frozen predictions required')
    inv={r['id']:r for r in json.loads((a.run/'reference-inventory.json').read_text())['rows']}
    old_ids={r['id'] for r in json.loads(Path('data/corpus/primary-references-v6/catalog.json').read_text())['tracks']}
    refs=references(Path.cwd(),[r for r in manifest['rows'] if r['id'] in old_ids or r['id']=='wage_war'])
    results=[]
    a.output.mkdir(parents=True,exist_ok=False)
    for row in manifest['rows']:
        ident=row['id'];entry=inv[ident];accepted=load_bound(dict(path=entry['reference'],sha256=entry['reference_expected']))
        if ident in refs:
            ref=refs[ident];raw=ref['map']
            if ref['policy']:scorer=lambda v:score_scoped(ref['accepted'],ref['policy'],v,row['source'])
            else:scorer=lambda v:normal_score(raw,v,accepted['beats_seconds'],ident in old_ids and 'music_map' not in accepted)
        else:
            raw,tail,unknown=adapt_extra(accepted,row['source']);scorer=lambda v:score_extra(raw,v,tail,unknown)
        bank_path=Path(row['selected']['path']).parent/'candidate-bank.json';bank=json.loads(bank_path.read_text());out=[]
        for rank,candidate in enumerate(bank):
            try:
                scored=scorer(candidate['prediction'])
                record=dict(rank=rank,name=candidate['name'],selection_score=candidate['score'],
                            scores=six_scores(scored),gates=scored['gates'],passed=scored['all_gates_pass'],
                            valid=True,beat_counts=scored['beat_counts'],bar_counts=scored['bar_counts'])
            except (ValueError,TypeError,KeyError,IndexError) as error:
                record=dict(rank=rank,name=candidate['name'],valid=False,error=f'{type(error).__name__}: {error}',passed=False)
            out.append(record)
        valid=[c for c in out if c['valid']]
        def quality(c):return (int(c['passed']),sum(c['gates'].values()),sum(v or 0 for v in c['scores']))
        best=max(valid,key=quality) if valid else None
        best_bpm=max(valid,key=lambda c:c['scores'][0] or 0) if valid else None
        results.append(dict(id=ident,title=row['title'],selected=out[0],best_complete_candidate=best,
                            best_bpm_candidate=best_bpm,candidates=out,bank_sha256=digest(bank_path)))
        print(ident,'selected',out[0].get('scores'),'best',best['name'] if best else None,
              'invalid',sum(not c['valid'] for c in out),flush=True)
    record=dict(kind='oracle_diagnostic_not_inference',scope='all saved candidates; includes nonselected pulse families',
                reference_used_only_for_diagnosis=True,automatic_predictions_changed=False,
                prediction_manifest_sha256=digest(a.run/'predictions/manifest.json'),rows=results)
    (a.output/'candidate-diagnosis.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
