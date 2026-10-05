"""Create a reproducible table and receipts for the frozen reviewed21 batch."""
import argparse
import csv
import json
from pathlib import Path

from .build_reviewed_review import six_scores
from .probe_resources import digest


def counts(score, name):
    value = score.get(name+'_change_counts')
    if value is None:
        return [0, score.get('false_'+name+'_changes_in_reference_scope',0), 0]
    return [value[k] for k in ('true_positives','false_positives','false_negatives')]


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run
    evaluation=json.loads((run/'evaluation/scores.json').read_text())
    predictions=json.loads((run/'predictions/manifest.json').read_text())
    lock=json.loads((run/'baseline-lock.json').read_text())
    inv=json.loads((run/'reference-inventory.json').read_text())
    integrity={name:digest(Path('experiments/tempo_meter_v3')/name)==value for name,value in lock['source_sha256'].items()}
    for name in ('structure_checkpoint','acoustic_checkpoint'):
        integrity[name]=digest(lock[name]['path'])==lock[name]['sha256']
    integrity['input_manifest']=digest(run/'source-inputs.json')==lock['input_sha256']
    for r in inv['rows']:
        integrity[r['id']+'_reference']=digest(r['reference'])==r['reference_expected']
        integrity[r['id']+'_audio']=digest(r['audio'])==r['audio_expected']
    assert all(integrity.values()),integrity
    (run/'preservation-check.json').write_text(json.dumps(integrity,indent=2)+'\n')
    durations=[r['source']['sample_frames']/r['source']['sample_rate'] for r in predictions['rows']]
    resources=dict(total_audio_seconds=sum(durations),total_analysis_seconds=sum(r['runtime_seconds'] for r in predictions['rows']),
                   rows=[{k:r.get(k) for k in ('id','runtime_seconds','cache_hit','peak_reserved_bytes','max_rss_bytes')} for r in predictions['rows']],
                   note='Sequential complete inference; some source-bound acoustic caches reused; no model fitting.')
    (run/'resources.json').write_text(json.dumps(resources,indent=2)+'\n')
    (run/'data-inventory.json').write_text(json.dumps(dict(finished_recordings=20,auxiliary=1,new_training=False,
                                                          initial_bpm='Owner-permitted reference initial scalar for pulse selection only'),indent=2)+'\n')
    full=[r for r in evaluation['rows'] if r['role']=='finished_recording_development'];aux=[r for r in evaluation['rows'] if r['role']!='finished_recording_development']
    rows=[]
    for r in evaluation['rows']:
        vals=six_scores(r['score']);tempo=counts(r['score'],'tempo');meter=counts(r['score'],'meter')
        rows.append(dict(id=r['id'],title=r['title'],role=r['role'],scores=vals,tempo_tp_fp_fn=tempo,meter_tp_fp_fn=meter,
                         passed=r['score']['all_gates_pass'],tail=r['score'].get('free_tail_false_positives'),
                         reference_support_seconds=r['reference_support_seconds']))
    summary=dict(finished_passed=sum(r['score']['all_gates_pass'] for r in full),finished_count=len(full),
                 auxiliary_passed=sum(r['score']['all_gates_pass'] for r in aux),auxiliary_count=len(aux),rows=rows)
    (run/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    with (run/'results.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['id','title','role','bpm_time_pct','meter_pct','beat_f1_pct','bar_f1_pct','tempo_change_pct','meter_change_pct','tempo_TP_FP_FN','meter_TP_FP_FN','pass'])
        for r in rows:w.writerow([r['id'],r['title'],r['role'],*[round(100*v,3) if v is not None else '' for v in r['scores']],'/'.join(map(str,r['tempo_tp_fp_fn'])),'/'.join(map(str,r['meter_tp_fp_fn'])),r['passed']])
    lines=['# Frozen current-model evaluation on 21 reviewed assets','',
           f"Finished recordings: **{summary['finished_passed']}/{len(full)} pass**. Auxiliary guitar clip: **{summary['auxiliary_passed']}/{len(aux)} pass**.",'',
           'The owner requested running the current model on all reviewed material before further model changes. Every source was freshly sent through the same frozen gate-2 v3 analyzer and checkpoint; acoustic caches were reused where hash-compatible. No training, per-song routing, inference adjustment, reference shift or new general equivalence policy was introduced. This is a known development/regression set, not unseen evaluation.','',
           'Initial BPM is the owner-permitted reference-derived scalar used only for discrete pulse-family selection. No meter, phase, later BPM or boundary labels enter inference. Godsmack display metadata is corrected to Bulletproof from the owner-acceptance catalog; the frozen input manifest retains an initial title typo, with unchanged audio ID/hash.','',
           '## Results','',
           'Percentages. BPM is approved duration within ±1 quarter BPM; meter is reviewed notation on paired bars; beat/bar use 70ms F1; tempo/meter changes use the frozen 500ms gates. Constant maps must have no false changes. A pass requires every score >=90% and applicable no-grid/end gates.','',
           '| Recording | BPM | Meter | Beat | Bar | Tempo change | Meter change | Pass |',
           '|---|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        lines.append('| '+r['title']+' | '+' | '.join('—' if v is None else f'{100*v:.1f}' for v in r['scores'])+' | '+('yes' if r['passed'] else 'no')+' |')
    lines+=['','Change counts below are TP / FP / FN; false positives remain penalized.','',
            '| Recording | Tempo TP/FP/FN | Meter TP/FP/FN |','|---|---|---|']
    for r in rows:lines.append('| '+r['title']+' | '+' / '.join(map(str,r['tempo_tp_fp_fn']))+' | '+' / '.join(map(str,r['meter_tp_fp_fn']))+' |')
    lines+=['','## Scope and listening','',
            'Open http://localhost:8975/review/index.html . All 21 assets are available at full length with source-only listening, source+model clicks, source+approved clicks, volume controls and notes. Six finished recordings with the lowest mean BPM/meter/beat/bar scores are marked for priority review. The error-window jumps are selected after scoring for listening only; they do not influence model predictions.','',
            'Walker retains its original scoped evaluator. Deadman and Opeth add the same explicit no-grid-tail and 500ms end-boundary checks to the normal variable-tempo/meter scoring. Their audible beat/bar scores include tail false positives. These boundaries were owner-approved at listening scale, not independently certified to milliseconds. RWC P002 and GuitarSet exclude unknown margins; missing predictions within the approved span still reduce scores. No unknown tail is treated as silent/no-grid truth. Red Miso is compared with the accepted large-scale 4/4 interpretation, not unavailable fine-meter annotations.','',
            'All 21 reference self-scores pass. Seven newly adapted clocks preserve accepted beat/bar event times within 1 microsecond arithmetic tolerance; this is adapter parity, not audio-ground-truth precision. Three scope regression tests cover unknown margins, explicit no-grid tails and missing valid-grid coverage. Existing v6/frozen outputs are unchanged.','',
            '## Reproduction','', '```bash',
            'python3 -m experiments.tempo_meter_v3.serve_gate_review --root '+str(run)+' --port 8975','```','',
            'Frozen sources and checkpoint hashes: `baseline-lock.json`, `source-snapshot/`. Current predictions: `predictions/manifest.json`. Full scores and adapted references: `evaluation/`. Compact table: `results.csv`, `summary.json`. Source/model/reference preservation: `preservation-check.json`. No source cleanup, code commit or push occurred.','']
    (run/'RESULTS.md').write_text('\n'.join(lines))
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'}))


if __name__=='__main__':main()
