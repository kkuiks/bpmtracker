"""Report all trained arms, including regressions, against the frozen baseline."""
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
    all_rows={'frozen':json.loads((a.baseline/'evaluation/scores.json').read_text())['rows']}
    for arm in ['A','B','C']:all_rows[arm]=json.loads((a.run/f'evaluation-{arm}'/'scores.json').read_text())['rows']
    baseline={r['id']:r for r in all_rows['frozen']};summaries={};matrix=[]
    for arm,rows in all_rows.items():
        full=[r for r in rows if r['role']=='finished_recording_development'];aux=[r for r in rows if r['role']!='finished_recording_development']
        summary=dict(finished_passed=sum(r['score']['all_gates_pass'] for r in full),finished_count=len(full),
                     auxiliary_passed=sum(r['score']['all_gates_pass'] for r in aux),auxiliary_count=len(aux),
                     mean_six_scores=[mean(six_scores(r['score'])[i] or 0 for r in full) for i in range(6)],
                     tempo_counts=[sum(counts(r['score'],'tempo')[i] for r in full) for i in range(3)],
                     meter_counts=[sum(counts(r['score'],'meter')[i] for r in full) for i in range(3)])
        if arm!='frozen':
            train=json.loads((a.run/f'train-{arm}/result.json').read_text());cal=json.loads((a.run/f'calibration-{arm}.json').read_text())
            pred=json.loads((a.run/f'predictions-{arm}/manifest.json').read_text())
            if not pred['complete']:raise ValueError('unfinished predictions')
            summary.update(training=train,meter_calibration=cal['selected'],
                           total_cached_inference_seconds=sum(r['runtime_seconds'] for r in pred['rows']),
                           rejected_candidate_count=sum(len(r['validity_guard']['rejected_before_selection']) for r in pred['rows']))
        summaries[arm]=summary
        for r in rows:
            before=six_scores(baseline[r['id']]['score']);after=six_scores(r['score'])
            delta=[100*((v or 0)-(b or 0)) for v,b in zip(after,before)]
            matrix.append(dict(arm=arm,id=r['id'],title=r['title'],role=r['role'],scores=after,delta_percentage_points=delta,
                               passed=r['score']['all_gates_pass'],tempo_tp_fp_fn=counts(r['score'],'tempo'),
                               meter_tp_fp_fn=counts(r['score'],'meter'),tail=r['score'].get('free_tail_false_positives'),
                               material_gain_metrics=[i for i,v in enumerate(delta) if v>=1],material_regression_metrics=[i for i,v in enumerate(delta) if v<=-1]))
    record=dict(scope='20 known development recordings plus auxiliary; no unseen accuracy',summaries=summaries,rows=matrix,
                material_delta_threshold_percentage_points=1,threshold_is_display_only=True,product_default_promoted=False)
    (a.run/'comparison-summary.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    with (a.run/'comparison.csv').open('w',newline='') as stream:
        w=csv.writer(stream);w.writerow(['model','id','title','role','BPM_pct','meter_pct','beat_F1_pct','bar_F1_pct','tempo_change_pct','meter_change_pct','pass','tempo_TP_FP_FN','meter_TP_FP_FN'])
        for r in matrix:w.writerow([r['arm'],r['id'],r['title'],r['role'],*[round(100*v,3) if v is not None else '' for v in r['scores']],r['passed'],'/'.join(map(str,r['tempo_tp_fp_fn'])),'/'.join(map(str,r['meter_tp_fp_fn']))])
    lines=['# Gate 3 learned-model comparison','',
           'The owner feedback was incorporated into a bounded, common-path comparison. This completes the A/B/C comparison checkpoint, not the remaining redesign or independent-source evaluation. No product default is promoted.','',
           '| Arm | Finished recordings passing | Auxiliary passing | Mean BPM / meter / beat / bar (%) |',
           '|---|---:|---:|---|']
    for arm,s in summaries.items():lines.append(f"| {arm} | {s['finished_passed']}/{s['finished_count']} | {s['auxiliary_passed']}/{s['auxiliary_count']} | "+' / '.join(f'{100*v:.1f}' for v in s['mean_six_scores'][:4])+' |')
    lines+=['','Every pass requires all six >=90% gates and applicable ending gates. Per-song scores, regressions, false changes and tail clicks are preserved in `comparison-summary.json` and `comparison.csv`. Macro means do not replace the individual gates.','',
            'Observed limits: all arms pass the same San Quentin and RWC P002 recordings. B reduces aggregate false meter changes from 296 to 99, but true detections fall from 3 to 1. C raises Deadman BPM-time from 16.22% to 68.08% without repairing its complete map. All three regress on Nocturne beat/bar scores. This trial does not support replacing the current model.','',
            '## Conditions and limits','',
            '- A: frozen Beat This features and a four-layer frame structure model. B: the same plus MERT-95M features, mean of the final four layers. C: two frame layers plus two observed-bar context layers; source-only downbeat proposals do not fix output bar boundaries.',
            '- Identical qualified 47/12 learning split, 800 updates, seed and checkpoint selection by held-out learning loss. Primary21 is excluded from weight fitting. Validation is rendered/synthetic weak data and is not representative unseen studio accuracy.',
            '- All three separate meter-change and tempo-change targets and mask unknown meter labels. The tempo-change head is an auxiliary learned output; the frozen clock fitter does not yet consume it as a boundary proposal.',
            '- Ten common meter-decoder settings were calibrated on held-out learning labels with their reference clocks. This isolates meter construction; its score is not end-to-end audio validation. It is a material limitation when transferring to noisy clocks.',
            '- Same source-only candidate generation, pulse-guide contract and selection structure. Invalid maps are rejected before final output. All musical model comparisons use one complete output per song, with no per-song routing or reference-based selection.',
            '- A/C source is preserved in `source-snapshot-AC/`. A later CLI-default-only correction points B at the valid MERT cache; training/model/predict functions did not change (`source-default-correction.json`).',
            '- MERT used the official fixed revision in `data/models/mert-v1-95m/`. Legacy positional-convolution weight_norm tensor names are remapped with strict full loading. The initial incomplete-load cache is invalid and unused; FP16 produced nonfinite features and was rejected. Valid features use FP32 and fresh cache `mert-v2`.',
            '- This is one bounded configuration per arm. A weak result does not rank all possible uses of MERT or hierarchical models. MERT is an extra feature encoder, not a standalone tempo/meter recognizer in this trial.',
            '- Some stages ran concurrently on the local MX450; cached inference and stage timings are not full cold-pipeline or native Windows measurements.',
            '', 'Official MERT source: [model card](https://huggingface.co/m-a-p/MERT-v1-95M). No external GPU or paid inference was used.','',
            '## Owner feedback and candidate audit','',
            'Seven recordings were reviewed by the owner (`owner-feedback.json`). Walker aligned downbeats but sounded offbeat between them; Juno and Red Miso are not accepted alternative answers. The frozen Walker [5,30)s quarter schedules agree within21.257ms, while the model emits6 versus13 reference bar starts. Its6/4 also differs from reference6/8 [3,3] musical pulse. Do not shift the accepted reference or equate quarter-click agreement with musical beat agreement.','',
            'The preceding audit evaluated339 frozen complete candidates. Eight unselected candidates fail validation. Even reference-informed selection from that fixed bank yields only the same2/20+1/1 complete passes. Better BPM-only alternatives exist; meter/bar generation and endings remain separate blockers. Oracle diagnosis is never reported as automatic accuracy. The old selected scores reproduce exactly.','',
            '## Review','',
            'Open http://localhost:8976/review/index.html . Select frozen/A/B/C at the same source position, compare full BPM and meter timelines and filter all change events. The default displayed new arm is chosen by learning validation loss, not primary21 score; it is not a product recommendation. The original reviewed output remains at8975.','',
            'The new page separates declared-meter/group clicks from quarter-note diagnostic clicks. For6/8 with explicit[3,3], group clicks are dotted quarters; absent grouping, the written denominator is used. Each model uses its own declared meter. The renderer does not substitute the reference meter into model output. Scores and maps remain the existing quarter-coordinate evaluation. Musical click preference or general equivalence is not silently made a new score gate. Notes are separate for each model.','',
            'Restart: `python3 -m experiments.tempo_meter_v3.serve_gate_review --root '+str(a.run)+' --port 8976`.','',
            '## Per-song core scores','',
            '| Recording | Arm | BPM | Meter | Beat | Bar | Tempo change | Meter change | Pass |',
            '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for ident in baseline:
        for r in [r for r in matrix if r['id']==ident]:lines.append('| '+r['title']+' | '+r['arm']+' | '+' | '.join('—' if v is None else f'{100*v:.1f}' for v in r['scores'])+' | '+('yes' if r['passed'] else 'no')+' |')
    lines+=['','Correction retained: the earlier same-observation v2 control passes1/4 complete maps, not2/4; Walker fails its two ending gates. Frozen generic13 remains10/13. Original offsets, source media, references and all frozen outputs remain preserved. No code commit or push occurred.','']
    (a.run/'RESULTS.md').write_text('\n'.join(lines))
    print(json.dumps({k:{n:s[n] for n in ['finished_passed','finished_count','auxiliary_passed','auxiliary_count']} for k,s in summaries.items()}))


if __name__=='__main__':main()
