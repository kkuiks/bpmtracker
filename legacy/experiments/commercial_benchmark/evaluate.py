"""Frozen physical-clock scoring with unsupported musical components explicit."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from .native import prepare_map
from .prepare import digest
from experiments.tempo_meter_v2.score_primary8 import (
    _rate_segments,_overlap,_step_value,_tempo_changes,quarter_beats)
from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters
from experiments.tempo_meter_v2.score_primary11 import change_gate
from experiments.analysis_legacy.grid_metrics import nearest_event_diagnostics,tempo_change_metrics


KEYS=('quarter_bpm_time_within_1','reviewed_meter_paired_bar_fraction_70ms',
      'declared_quarter_grid_f1_70ms','bar_boundary_f1_70ms',
      'tempo_change_f1_or_no_false_positives_500ms','meter_change_f1_or_no_false_positives_500ms')


def clock_duration(reference,prediction):
    total=sum(b-a for a,b in reference['support_seconds']);overlap=correct=error=0.
    rr,pr=_rate_segments(reference),_rate_segments(prediction)
    for lo,hi in _overlap(reference['support_seconds'],prediction['support_seconds']):
        points=sorted({lo,hi}|{t for a,b,_ in rr+pr for t in (a,b) if lo<t<hi})
        for a,b in zip(points,points[1:]):
            d=abs(_step_value(rr,(a+b)/2)-_step_value(pr,(a+b)/2));span=b-a
            overlap+=span;correct+=span*(d<=1);error+=span*d
    return dict(reference_seconds=total,overlap_seconds=overlap,coverage_fraction=overlap/total,
                quarter_bpm_within_1_reference_fraction=correct/total,
                quarter_bpm_mae_on_overlap=error/overlap if overlap else None)


def physical_score(reference,prediction,existing_scope, *, scoped_walker=False):
    reference=prepare_map(reference);prediction=prepare_map(prediction)
    if reference['source']!=prediction['source']:raise ValueError('source binding mismatch')
    scored=deepcopy(prediction)
    unknown=bool(existing_scope.get('unknown_outside_reference_support_excluded'))
    if unknown:
        scored['support_seconds']=[list(x) for x in _overlap(scored['support_seconds'],reference['support_seconds'])]
    duration=clock_duration(reference,scored)
    emitter=emitted_quarters if scoped_walker else quarter_beats
    beat=nearest_event_diagnostics(emitter(reference),emitter(scored),.07)
    rc=_tempo_changes(reference,reference['support_seconds'],minimum_change_bpm=1e-6)
    pc=_tempo_changes(scored,scored['support_seconds'],minimum_change_bpm=1e-6)
    if scoped_walker:
        lo,hi=reference['support_seconds'][0];pc=[e for e in pc if lo<e['source_seconds']<hi]
    changes=tempo_change_metrics(rc,pc,time_tolerance_seconds=.5,rate_tolerance_bpm=.1)['full_change_scores']
    scores=dict.fromkeys(KEYS)
    scores[KEYS[0]]=duration['quarter_bpm_within_1_reference_fraction']
    scores[KEYS[2]]=beat['f1'];scores[KEYS[4]]=change_gate(changes)
    gates={k:(v>=.9 if v is not None else None) for k,v in scores.items()}
    tail=existing_scope.get('free_time_seconds')
    if tail is None and existing_scope.get('free_tail_false_positives') is not None:
        tail=[reference['support_seconds'][-1][1],reference['duration_seconds']]
    tail_result=None;boundary=None
    if tail:
        lo,hi=tail;beats=emitted_quarters(prediction)
        extra=sum(lo<=t<hi for t in beats)
        extra_seconds=sum(max(0.,min(b,hi)-max(a,lo)) for a,b in prediction['support_seconds'])
        boundary=prediction['support_seconds'][-1][1]-lo
        gates['no_grid_in_free_ending']=not (extra or extra_seconds>1e-9)
        gates['grid_end_within_500ms']=abs(boundary)<=.5
        tail_result=dict(quarter_beats=extra,bar_starts=None,declared_map_support_seconds=extra_seconds)
    return dict(status='clock_scored_required_musical_components_unavailable',scores=scores,gates=gates,
                all_gates_pass=False,clock_gates_pass=all(v is True for k,v in gates.items() if k not in (KEYS[1],KEYS[3],KEYS[5])),
                unavailable_required_gates=[KEYS[i] for i in (1,3,5)],duration=duration,
                beat_counts={k:beat[k] for k in ('true_positives','false_positives','false_negatives')},
                tempo_change_counts={k:changes[k] for k in ('true_positives','false_positives','false_negatives')},
                free_tail_false_positives=tail_result,grid_end_error_seconds=boundary,
                unknown_outside_reference_support_excluded=unknown,
                reference_support_seconds=reference['support_seconds'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run.resolve()
    manifest=json.loads((run/'predictions/manifest.json').read_text())
    if not manifest['complete'] or manifest['references_available_to_runner'] or len(manifest['rows'])!=21:
        raise ValueError('all21 frozen native predictions required before reference reads')
    root=Path.cwd();prior=root/'data/runs/tempo-meter-v3/reviewed21-frozen-20260930-v1/evaluation'
    baseline=json.loads((prior/'scores.json').read_text());old={r['id']:r for r in baseline['rows']}
    bindings={r['id']:r for r in json.loads((run/'evaluation/reference-bindings.json').read_text())['rows']}
    out=run/'evaluation/cubase-pro15'
    if out.exists():raise FileExistsError(out)
    out.mkdir();rows=[];parity=[]
    for row in manifest['rows']:
        ident=row['id'];pred_path=Path(row['selected']['path'])
        if digest(pred_path)!=row['selected']['sha256']:raise ValueError('prediction changed')
        original=bindings[ident]
        if digest(original['reference'])!=original['reference_sha256'] or original['reference_sha256']!=old[ident]['reference_sha256']:
            raise ValueError('original reference provenance changed')
        ref_path=prior/(ident+'-reference.json');ref_payload=json.loads(ref_path.read_text());ref=ref_payload['map']
        if ref_payload['reference_binding']['sha256']!=original['reference_sha256']:raise ValueError('frozen adapted reference changed')
        prediction=json.loads(pred_path.read_text());scope=old[ident]['score'];walker=ident=='walker_he-will-hold-me-fast'
        score=physical_score(ref,prediction['map'],scope,scoped_walker=walker)
        oracle=physical_score(ref,ref,scope,scoped_walker=walker)
        if not oracle['clock_gates_pass']:raise ValueError('physical reference self-score failed: '+ident)
        # Establish that this partial-output adapter retains the exact frozen
        # physical gates for the original complete baseline predictions too.
        frozen_manifest=json.loads((prior.parent/'predictions/manifest.json').read_text())
        br=next(r for r in frozen_manifest['rows'] if r['id']==ident)
        bp=json.loads(Path(br['selected']['path']).read_text())
        comparator=physical_score(ref,bp['map'],scope,scoped_walker=walker)
        old_scores=scope['scores']
        alternatives=((KEYS[0],'quarter_bpm_within_1_reference_fraction'),(KEYS[2],'quarter_beat_f1_70ms'),(KEYS[4],'tempo_change_no_false_positives'))
        for key,alt in alternatives:
            expected=old_scores[key] if key in old_scores else old_scores[alt]
            actual=comparator['scores'][key]
            if actual is None or abs(actual-expected)>1e-10:raise ValueError('frozen physical scorer parity failed: '+ident+' '+key)
        parity.append(dict(id=ident,three_physical_scores_identical=True,reference_self_score_passed=True))
        (out/(ident+'-reference.json')).write_text(json.dumps(ref_payload,indent=2)+'\n')
        rows.append(dict(id=ident,title=row['title'],role=old[ident]['role'],score=score,
                         reference_support_seconds=ref['support_seconds'],prediction_sha256=row['selected']['sha256'],
                         native_analysis_seconds=row['native_analysis_seconds'],workflow_seconds=row['workflow_seconds']))
        print(ident,json.dumps(score['scores']),flush=True)
    results=dict(product=manifest['product'],scope='20 known finished recordings plus one auxiliary; vendor training overlap unknown',
                 prediction_manifest_sha256=digest(run/'predictions/manifest.json'),frozen_reference_scores_sha256=digest(prior/'scores.json'),
                 no_scoring_threshold_or_equivalence_change=True,unsupported_components_are_not_numeric_zero=True,rows=rows)
    (out/'scores.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    (out/'validation.json').write_text(json.dumps(dict(frozen_physical_scoring_parity=parity,all_passed=True),indent=2)+'\n')


if __name__=='__main__':main()
