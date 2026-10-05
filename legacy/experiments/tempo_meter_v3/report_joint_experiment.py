"""Report a frozen diagnostic and paired all-source reconstruction experiment."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from .build_reviewed_review import six_scores
from .report_reviewed import counts
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True);a=p.parse_args();run=a.run
    paths={'frozen':a.baseline/'evaluation/scores.json','v2':run/'evaluation-v2-control/scores.json',
           **{arm:run/('evaluation-'+arm)/'scores.json' for arm in ('event','ranking','joint')}}
    rows=[];summaries={}
    for arm,path in paths.items():
        data=json.loads(path.read_text());full=[];aux=[]
        for r in data['rows']:
            vals=six_scores(r['score']);item=dict(arm=arm,id=r['id'],title=r['title'],role=r['role'],scores=vals,
                passed=r['score']['all_gates_pass'],tempo_tp_fp_fn=counts(r['score'],'tempo'),
                meter_tp_fp_fn=counts(r['score'],'meter'),tail=r['score'].get('free_tail_false_positives'))
            rows.append(item);(full if r['role']=='finished_recording_development' else aux).append(item)
        summaries[arm]=dict(finished_passed=sum(r['passed'] for r in full),finished_count=len(full),
                           auxiliary_passed=sum(r['passed'] for r in aux),auxiliary_count=len(aux),
                           finished_mean_six_scores=np.mean([r['scores'] for r in full],axis=0).tolist(),
                           all21_mean_six_scores=np.mean([r['scores'] for r in full+aux],axis=0).tolist(),
                           tempo_counts=np.sum([r['tempo_tp_fp_fn'] for r in full],axis=0).tolist(),
                           meter_counts=np.sum([r['meter_tp_fp_fn'] for r in full],axis=0).tolist(),
                           score_artifact_sha256=digest(path))
    baseline={r['id']:r for r in rows if r['arm']=='frozen'}
    for r in rows:
        r['delta_vs_frozen_pp']=[100*(v-u) for v,u in zip(r['scores'],baseline[r['id']]['scores'])]
    gate={}
    for arm in ('event','ranking','joint'):
        s=summaries[arm];b=summaries['frozen']
        checks=dict(old_complete_passes_preserved=all(r['passed'] for r in rows if r['arm']==arm and baseline[r['id']]['passed']),
            tempo_tp_preserved=s['tempo_counts'][0]>=b['tempo_counts'][0],meter_tp_preserved=s['meter_counts'][0]>=b['meter_counts'][0],
            tempo_fp_reduced=s['tempo_counts'][1]<b['tempo_counts'][1],meter_fp_reduced=s['meter_counts'][1]<b['meter_counts'][1],
            beat_macro_guard=s['finished_mean_six_scores'][2]>=b['finished_mean_six_scores'][2]-.02,
            bar_macro_guard=s['finished_mean_six_scores'][3]>=b['finished_mean_six_scores'][3]-.02)
        gate[arm]=dict(checks=checks,all_pass=all(checks.values()))
    audit=json.loads((run/'objective-audit/results.json').read_text())
    event=json.loads((run/'event-control-audit/results.json').read_text())
    diagnostic=dict(reference_paths_representable=sum(r['conditions']['actual']['representable'] for r in audit['rows']),
        actual_exact_labeled_paths=sum(r['conditions']['actual']['agreement']['exact_labeled_boundaries'] for r in audit['rows']),
        ideal_old_exact_labeled_paths=sum(r['conditions']['ideal']['agreement']['exact_labeled_boundaries'] for r in audit['rows']),
        ideal_event_exact_labeled_paths=sum(r['event_control_ideal_agreement']['exact_labeled_boundaries'] for r in event['rows']),
        count=len(audit['rows']))
    paired=[]
    for left,right in [('event','ranking'),('ranking','joint')]:
        l={r['id']:r for r in rows if r['arm']==left};r={r['id']:r for r in rows if r['arm']==right}
        paired.append(dict(before=left,after=right,rows=[dict(id=i,score_delta_pp=[100*(v-u) for v,u in zip(r[i]['scores'],l[i]['scores'])],
                 tempo_count_delta=np.subtract(r[i]['tempo_tp_fp_fn'],l[i]['tempo_tp_fp_fn']).tolist(),
                 meter_count_delta=np.subtract(r[i]['meter_tp_fp_fn'],l[i]['meter_tp_fp_fn']).tolist()) for i in l]))
    result=dict(scope='known development set; no unseen claims',summaries=summaries,development_gates=gate,
                objective_diagnosis=diagnostic,rows=rows,paired_controls=paired,product_default_promoted=False)
    (run/'comparison-summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    with (run/'comparison.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['arm','id','role','bpm','meter','beat','bar','tempo_change','meter_change','tempo_TP_FP_FN','meter_TP_FP_FN','pass'])
        for r in rows:w.writerow([r['arm'],r['id'],r['role'],*[100*x for x in r['scores']],r['tempo_tp_fp_fn'],r['meter_tp_fp_fn'],r['passed']])
    lines=['# Frozen observations: objective audit and bounded joint reconstruction','',
        '**Decision: reject this bounded setting for adoption.** No finished-recording pass is added (still 2/20), and Nocturne loses its two previously detected meter changes. Timing and false-positive gains do not compensate for that regression. References, offsets, full-song scopes, no-grid gates and previous outputs remain unchanged. No score-driven parameter sweep followed.','',
        '## Evidence and scope','',
        'The cohort contains twenty previously inspected finished recordings and one auxiliary GuitarSet clip. Every prediction arm was completed before its references were opened by the separate unchanged evaluator. The optional initial BPM scalar only chooses a pulse family from the original source bank; it never fits clock numbers. New ranking and joint arms retain that same family membership.','',
        '## Objective diagnosis','',
        f"All {diagnostic['reference_paths_representable']}/21 qualified reference paths fit the existing signature and phase state space. Under actual observations, {diagnostic['actual_exact_labeled_paths']}/21 exact labeled paths win. With ideal downbeat/meter observations and exact clocks, the old objective restores {diagnostic['ideal_old_exact_labeled_paths']}/21, while the event-reward control restores {diagnostic['ideal_event_exact_labeled_paths']}/21. These are oracle structural diagnostics, not recognition accuracy.",'',
        'Direct path sums reproduce DP scores. Exhaustive enumeration on a two-cell clock includes all 160 signatures, every legal pickup and every terminating path; the existing DP finds the maximum. This does not certify an unbounded joint clock search. The old ideal failure is a spurious 1/32 bar near the opening 2/4→4/4 transition in Sleeping With Sirens: a broad positive downbeat lobe supplies multiple rewards. Keeping only the strongest lattice reward within each positive lobe removes that manufactured duplication without banning any signature.','',
        'The diagnostic starts at the first complete reference quarter at/after qualified support start (possibly omitting less than a quarter), extends partial bars as context, and excludes qualified no-grid tails. Full-source evaluation below retains all existing coverage and ending penalties. Numerator/denominator labels are supplied in the ideal arm; this is not audio-only identification of grouping.','',
        'Actual-path score decompositions show lower boundary evidence on all eighteen nonmatching cases. Category evidence additionally disfavors the reference on Walker, Circle, Juno and Deadman. Thus wider search alone cannot repair the frozen score. A 20ms uniform downbeat delay retains exact lattice paths in four conditional controls; 40ms does not. Exact lattice failure is not automatically a 70ms event failure, but it exposes timing sensitivity.','',
        '## Learning target audit','',
        'The seven RWC rows have 2,801 tempo entries formed from adjacent CSV beat intervals, not direct production tempo automation. Executing both target functions confirms zero supervised RWC change frames. Tempo regression still supervises these interval-derived BPM values. Its causal impact on the shared model/ranking is unmeasured. No relabeling or retraining occurred. Validation contains five rendered BabySlakh sources and seven procedural sources, no actual RWC recording. See learning-target-audit.json.','',
        '## Fixed comparison','',
        'event: one positive reward per downbeat lobe, old ranking. ranking: same event decoder plus capped timing-loss/clock-complexity score, no refitting. joint: same score plus at most three alternating association/refit iterations on three source-ranked seeds. Beat associations allow missing quarters and reject offbeats outside a quarter-period gate; one event cannot match several model boundaries. Selected bar positions also participate in robust knot fitting. A constant clock competes with the retained-knot clock. No new knot locations, grouping model, repeated-section model, learned weights or ending rule are introduced.','',
        'Frozen parameters and acceptance conditions were saved in protocol.json with source-before-prediction before the all21 prediction run. A zero-refit ranking arm separates the new score from the effect of actual clock updates. v2 is unchanged reconstruction on the same fresh cached observations, not a rescore of the older generic13 10/13.','',
        '| Arm | Finished passes | Auxiliary | BPM / meter / beat / bar mean, finished only (%) | Tempo TP/FP/FN | Meter TP/FP/FN |',
        '|---|---:|---:|---|---|---|']
    for arm,s in summaries.items():
        lines.append(f"| {arm} | {s['finished_passed']}/20 | {s['auxiliary_passed']}/1 | "+' / '.join(f'{v*100:.2f}' for v in s['finished_mean_six_scores'][:4])+' | '+' / '.join(map(str,s['tempo_counts']))+' | '+' / '.join(map(str,s['meter_counts']))+' |')
    lines+=['','## Predeclared development gates','']
    for arm,g in gate.items():lines.append(f"- {arm}: {'passes' if g['all_pass'] else 'fails'}; failing conditions: "+(', '.join(k for k,v in g['checks'].items() if not v) or 'none')+'.')
    lines+=['','These are bounded development checks, not product accuracy thresholds. Compare against v2 as well as the weak v3 baseline; never deploy a reference-selected per-song hybrid. Most beat accuracy gain arises from the ranking change: 79.28→84.30%, followed by 84.51% after refitting (finished-only macro). Meter change TP drops 3→2, including Nocturne 2→0. The known-set v2 control passes 8/20 but detects none of the 64 true meter changes, so it is a stronger stability control, not a solution to changing meter.','',
            '## Next evidence needed','',
            'Do not expand encoder training or sweep penalties on this score table. The next bounded question is how to score observed bar boundaries and grouping so that real short changes beat stable or phase-shifted alternatives under exact clocks. Existing qualified production maps can provide field-specific supervision and producer/project-separated validation; their prior development exposure must remain disclosed. Joint clock refinement alone is insufficient here. The RWC instantaneous-BPM regression effect remains a separate unmeasured ablation.','',
            'All per-song gains and losses follow.','',
            '## Per-source six scores','',
            '| Recording | Arm | BPM | Meter | Beat | Bar | Tempo change | Meter change | Pass |',
            '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for ident in baseline:
        for r in [r for r in rows if r['id']==ident]:
            lines.append('| '+r['title']+' | '+r['arm']+' | '+' | '.join(f'{v*100:.2f}' for v in r['scores'])+' | '+('yes' if r['passed'] else 'no')+' |')
    lines+=['','## Reproduction and limitations','',
        'Use experiments/analysis/.venv/bin/python with OPENBLAS_NUM_THREADS=1, OMP_NUM_THREADS=4 and PYTHONDONTWRITEBYTECODE=1. Commands are recorded in commands.txt. All output paths must be new. Audio entry: experiments.tempo_meter_v3.joint_audio; cached comparison: run_joint_cached; scoring: evaluate_reviewed. The actual Equilibrium audio entry matches the cached joint map exactly with cached acoustic features; no cold runtime or native Windows claim follows.','',
        'The joint method is local and bounded. It keeps each seed\'s musical knot coordinates, although source-time knot positions and event associations change. It does not yet implement full subdivision/grouping ambiguity, automatic repetition constraints, new change-point proposals or calibrated uncertainty. No external GPU, paid inference, acquisition, source cleanup, commit or push was performed.','']
    (run/'RESULTS.md').write_text('\n'.join(lines))
    print(json.dumps(dict(summaries=summaries,gates=gate,diagnosis=diagnostic),indent=2))


if __name__=='__main__':main()
