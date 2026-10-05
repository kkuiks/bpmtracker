"""Keep rejected interventions and oracle diagnoses separate from accuracy."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean
from .build_reviewed_review import six_scores
from .report_reviewed import counts
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);a=p.parse_args()
    models={name:json.loads((root/'evaluation/scores.json').read_text())['rows'] for name,root in [('frozen',a.baseline),('revised',a.run)]}
    before={r['id']:r for r in models['frozen']};summaries={};rows=[]
    for arm,items in models.items():
        full=[r for r in items if r['role']=='finished_recording_development'];aux=[r for r in items if r['role']!='finished_recording_development']
        summaries[arm]=dict(finished_passed=sum(r['score']['all_gates_pass'] for r in full),finished_count=len(full),
            auxiliary_passed=sum(r['score']['all_gates_pass'] for r in aux),auxiliary_count=len(aux),
            mean_six_scores=[mean(six_scores(r['score'])[i] or 0 for r in full) for i in range(6)],
            meter_tp_fp_fn=[sum(counts(r['score'],'meter')[i] for r in full) for i in range(3)],
            tempo_tp_fp_fn=[sum(counts(r['score'],'tempo')[i] for r in full) for i in range(3)])
        for row in items:
            new=six_scores(row['score']);old=six_scores(before[row['id']]['score'])
            rows.append(dict(arm=arm,id=row['id'],title=row['title'],role=row['role'],scores=new,
                delta_percentage_points=[100*((n or 0)-(o or 0)) for n,o in zip(new,old)],
                passed=row['score']['all_gates_pass'],meter_tp_fp_fn=counts(row['score'],'meter'),
                tempo_tp_fp_fn=counts(row['score'],'tempo'),tail=row['score'].get('free_tail_false_positives')))
    prediction=json.loads((a.run/'predictions/manifest.json').read_text());assert prediction['complete']
    result=dict(status='rejected_for_promotion',reason='No additional complete passing recording; material bar regressions including Walker and Circle.',
                scope='Known development cohort, 20 finished recordings and 1 auxiliary clip; no unseen validation.',
                summaries=summaries,rows=rows,legacy_candidates_reproduced=sum(r['legacy_candidates_reproduced'] for r in prediction['rows']),
                product_default_changed=False,reference_or_scoring_changed=False)
    (a.run/'comparison-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    with (a.run/'comparison.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['arm','id','title','BPM_pct','meter_pct','beat_F1_pct','bar_F1_pct','tempo_change_pct','meter_change_pct','passed','meter_TP_FP_FN'])
        for row in rows:w.writerow([row['arm'],row['id'],row['title'],*[round(100*x,4) if x is not None else '' for x in row['scores']],row['passed'],row['meter_tp_fp_fn']])
    lines=['# Reconstruction diagnosis and first common intervention','',
        '**Decision: do not promote this intervention.** The bounded diagnosis, common edit and full21 regression are complete. Both old and revised routes pass the same2/20 finished recordings plus1/1 auxiliary clip. Local gains do not compensate for material regressions. No product default, reference, offset or scoring threshold changed.','',
        '## Diagnosis','',
        'Four known cases cover stable4/4, compound6/8, genuine tempo changes and a one-bar2/4 change. `diagnosis-valid/results.json` is authoritative. Oracle arms receive exact reference quarter timing/tempo, but not meter labels or the approved ending boundary. The clock is extended to the full source, so an oracle-clock result still fails an unrecognized no-grid ending. Oracle results are never automatic performance.','',
        '| Recording | Condition | BPM | Meter | Beat | Bar | Tempo changes | Meter changes |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    diagnosis=json.loads((a.run/'diagnosis-valid/results.json').read_text())
    for row in diagnosis['rows']:
        lines.append('| '+row['id']+' | '+row['condition']+' | '+' | '.join('—' if x is None else f'{100*x:.1f}' for x in six_scores(row['score']))+' |')
    lines+=['',
        'Exact clocks alone leave major meter/bar errors. Removing learned rhythmic heads also worsens the four cases; the tail head was kept and this was not removal of every learned output. These controls establish separate clock and meter/phase problems, not that every learned feature is useful or that raw observations are sufficient.','',
        'The initial diagnosis used an unsupported analysis_condition enum. Preserve `diagnosis/` and `diagnosis-v2/` as failed harness evidence, not model accuracy. The valid rescore changes only this marker to the existing `reference_assisted_diagnostic` enum, and checks every map renders. No clock, meter, phase, support or observation changed during that correction.','',
        '## Controlled intervention and rejection','',
        'The existing unusual-bar-length penalty was charged once per bar; long bars amortize that cost per quarter. The first variant charged it per quarter of music. A controlled fixture still merged five missed downbeats in stable4/4 into24/4, so duration normalization alone was rejected. Its four-song results and exact source are preserved in `evaluation-probe/` and `first-attempt-source/`.','',
        'The fixed revised variant additionally clips negative boundary log-odds at-1 rather than-8; the positive ceiling, learned observations, model weights, all160 meter states and transition costs remain unchanged. It passed controlled constant4/4,6/8,7/8,31/4, one-bar2/4 and missing-downbeat tests. This is a bounded robustness hypothesis, not calibrated uncertainty. `revised-change-protocol.json` fixed it before the revised song predictions; no further parameter search followed the21 results.','',
        'All original clock candidates and their phases were held fixed. Every legacy candidate map reproduces before applying the new meter score. The new joint score can in principle change which clock is selected. Invalid candidate maps are retained as diagnostics and excluded from selection using the existing comparison guard. No song-specific inference branches or reference-based selection exist.','',
        '| Model | Finished passes | Auxiliary passes | Mean BPM / meter / beat / bar (%) | Meter TP / FP / FN |',
        '|---|---:|---:|---|---|']
    for arm,s in summaries.items():lines.append(f"| {arm} | {s['finished_passed']}/{s['finished_count']} | {s['auxiliary_passed']}/{s['auxiliary_count']} | "+' / '.join(f'{100*x:.1f}' for x in s['mean_six_scores'][:4])+' | '+' / '.join(map(str,s['meter_tp_fp_fn']))+' |')
    lines+=['',
        'Walker loses its prominent31/4 segment but substitutes incorrect4/4 and regresses in whole-song bar F1. Therefore removing implausible labels is not evidence of recovering the musical grid. Naysayer and Opeth gain bar accuracy, while Circle and Deadman regress. All gains, regressions, ending false positives and change errors remain in the full table/JSON. This does not establish that robust penalties never help; it rejects this tested global setting.','',
        '## Review and reproducibility','',
        'Open http://localhost:8977/review/index.html . Switch frozen/revised at the same position. Both are compared with the unchanged reference. The initial click mode is quarter-note per owner preference; declared-meter/group clicks remain available. The revised display is marked unadopted. Original review8975 and learned comparison8976 remain separate.','',
        'Start server: `python3 -m experiments.tempo_meter_v3.serve_gate_review --root '+str(a.run)+' --port 8977`.','',
        'Source-only audio entry: `experiments.tempo_meter_v3.reconstruct_audio` accepts one mix, optional initial BPM scalar, acoustic/structure checkpoints, feature cache and output path. It opens no song catalog or reference. An actual audio-entry check on Equilibrium reproduced the cached intervention map exactly. Acoustic features were cached, so the runtime is not a cold-pipeline benchmark.','',
        'The batch uses `reconstruct_cached --baseline <frozen-run> --output <new-path>`. Evaluation is a separate `evaluate_reviewed` call with the accepted inventory after the complete source-only batch is frozen. All63 previous learned comparisons remain unchanged. The initial BPM guide continues to select pulse family only.','',
        'Validation artifacts: `audio-route-parity.json`, `guide-controls.json`, `validation.json`, `browser-validation.json`, and `preservation-validation.json`. Unit tests are implementation checks, not musical accuracy.','',
        '## Next unresolved work','',
        'Separate bar phase and boundary evidence from authored meter labels. With an exact clock, Walker still chooses the wrong grouping; Equilibrium can retain wrong phase or false changes. A length preference cannot replace missing grouping evidence or well-calibrated boundary scoring. The next experiment should expose the scores of competing physical bar-boundary sequences and test their consistency on the four diagnostic cases, while retaining single-bar changes. Clock candidate ranking, joint refitting, no-grid endings and representative real-recording meter supervision remain unresolved. The proposed independent six-recording cohort has not been acquired or evaluated.','',
        '## Per-song scores','',
        '| Recording | Arm | BPM | Meter | Beat | Bar | Tempo change | Meter change | Pass |',
        '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for ident in before:
        for row in [r for r in rows if r['id']==ident]:
            lines.append('| '+row['title']+' | '+row['arm']+' | '+' | '.join('—' if x is None else f'{100*x:.1f}' for x in row['scores'])+' | '+('yes' if row['passed'] else 'no')+' |')
    (a.run/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summaries))


if __name__=='__main__':main()
