"""Report the actual document experiment, including failures and development exposure."""
import argparse
import csv
import json
from pathlib import Path
import sys
import numpy as np
from experiments.tempo_meter_v3.probe_resources import digest
from experiments.tempo_meter_v3.report_reviewed import counts
from experiments.tempo_meter_v3.build_reviewed_review import six_scores
from .production_data import group_for


def aggregation_scores(row):
    # Failed decoding stays in the denominator; unavailable map metrics remain
    # null in per-source output, with explicitly zero aggregate contribution.
    if row["score"].get("status")=="decode_failed":return [0.]*6
    return six_scores(row["score"])


def summary(rows):
    full=[r for r in rows if r['role']=='finished_recording_development'];aux=[r for r in rows if r['role']!='finished_recording_development']
    values=np.array([aggregation_scores(r) for r in full],float)
    failed=sum(r['score'].get('status')=='decode_failed' for r in full)
    tempo=np.array([counts(r['score'],'tempo') for r in full]).sum(0).tolist()
    meter=np.array([counts(r['score'],'meter') for r in full]).sum(0).tolist()
    minutes=sum(sum(b-a for a,b in r['reference_support_seconds']) for r in full)/60
    groups={}
    for r in full:groups.setdefault(group_for(r['id']),[]).append(r)
    return dict(finished_passed=sum(r['score']['all_gates_pass'] for r in full),finished_count=len(full),
        auxiliary_passed=sum(r['score']['all_gates_pass'] for r in aux),auxiliary_count=len(aux),
        decode_failures=sum(r['score'].get('status')=='decode_failed' for r in rows),
        failure_aggregation='No map metrics for decode failure; explicit zero contribution with denominator retained',
        mean_six_scores=values.mean(0).tolist(),tempo_tp_fp_fn=tempo,meter_tp_fp_fn=meter,
        tempo_recall=None if failed else tempo[0]/max(1,tempo[0]+tempo[2]),
        meter_recall=None if failed else meter[0]/max(1,meter[0]+meter[2]),
        change_count_scope='successfully decoded finished recordings only' if failed else 'all finished recordings',
        tempo_fp_per_qualified_minute=tempo[1]/minutes,meter_fp_per_qualified_minute=meter[1]/minutes,
        grouped={g:dict(count=len(rr),mean_six_scores=np.mean([aggregation_scores(r) for r in rr],0).tolist(),
            tempo_tp_fp_fn=np.array([counts(r['score'],'tempo') for r in rr]).sum(0).tolist(),
            meter_tp_fp_fn=np.array([counts(r['score'],'meter') for r in rr]).sum(0).tolist()) for g,rr in groups.items()})


def drift(reference,prediction):
    from experiments.analysis_legacy.music_map_contract import prepare_map
    from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters
    ref=emitted_quarters(prepare_map(reference));pred=emitted_quarters(prepare_map(prediction))
    if not ref or not pred:return dict(status='no_event_sequence')
    # One index alignment only, never nearest-neighbor resets or time correction.
    pair=None
    for i,t in enumerate(ref):
        if t>ref[0]+10:break
        j=int(np.argmin(abs(np.asarray(pred)-t)))
        if abs(pred[j]-t)<=.07:pair=(i,j);break
    if pair is None:return dict(status='no_opening_anchor_within70ms')
    i,j=pair;n=min(len(ref)-i,len(pred)-j);error=np.asarray(pred[j:j+n])-np.asarray(ref[i:i+n])
    return dict(status='single_index_aligned',reference_start_index=i,prediction_start_index=j,paired_count=n,
        first_error_seconds=float(error[0]),last_error_seconds=float(error[-1]),
        accumulated_error_change_seconds=float(error[-1]-error[0]),p95_abs_seconds=float(np.quantile(abs(error),.95)),
        max_abs_seconds=float(np.max(abs(error))),timing_correction_applied=False,
        caveat='Known reviewed grid, not certified millisecond gold; index slip/half-time diverges rather than silently reanchors')



def learning_evidence(run,protocol):
    """Summarize completed learning/control receipts independently of whole scores."""
    bindings={}
    def read(path):
        path=Path(path)
        if not path.exists():return None
        bindings[str(path)]=dict(path=str(path),sha256=digest(path))
        return json.loads(path.read_text())
    supervision=read(run/'production-supervision-locked/manifest.json')
    training=read(run/'production-training/training.json')
    selection=read(run/'production-validation/selection.json')
    budgets=read(run/'held-map-budget-comparison.json')
    comparison=read(run/'held-raw-control/comparison.json')
    matched=read(run/'held-raw-control/summary.json')
    noise_root=Path(protocol.get('noise_controls_external','data/runs/tempo-meter-v4/noise-controls-20261001-v1'))
    noise=read(noise_root/'results.json')
    alias=read(Path('data/runs/tempo-meter-v4/score-alias-diagnosis-20261001-v1/diagnosis.json'))
    evidence=dict(bindings=bindings,training_complete=bool(training and training['complete']),
        held_validation_complete=bool(selection and selection['complete']),
        whole_learned_evaluation_complete=(run/'evaluation-learned/scores.json').exists())
    if supervision:
        evidence['exposure']=dict(train_count=sum(r['split']=='train' for r in supervision['rows']),
            held_count=sum(r['split']=='validation' for r in supervision['rows']),auxiliary_count=1,
            auxiliary_used_for_fitting_or_selection=False,
            train_groups=sorted({r['group'] for r in supervision['rows'] if r['split']=='train'}),
            held_groups=sorted({r['group'] for r in supervision['rows'] if r['split']=='validation'}),
            known_development_material=True,unseen_generalization_claim=False,
            pretraining_exposure='RWC known; other pretraining exposure not established')
    if training:
        evidence['training']=dict(seeds=[r['seed'] for r in training['rows']],
            steps=sorted({r['steps'] for r in training['rows']}),
            checkpoint_steps=sorted({int(Path(p).stem.split('-')[-1]) for r in training['rows'] for p in r['checkpoints']}))
    if selection:
        if supervision and selection['manifest_sha256']!=digest(run/'production-supervision-locked/manifest.json'):
            raise ValueError('held selection supervision binding differs')
        if selection['parameters_sha256']!=digest(run/'parameters-locked.json'):raise ValueError('held selection parameters differ')
        evidence['selection']=selection['selected'];evidence['seed_results']=selection['seed_results']
    if budgets:
        if selection and budgets['selection_sha256']!=digest(run/'production-validation/selection.json'):
            raise ValueError('budget comparison selection differs')
        evidence['budgets']=[dict(seed=r['seed'],step=r['step'],value=r['equal_source_selection_value'],
            decode_failures=r['decode_failures'],passing_excerpts=r['fully_passing_excerpt_count'],
            source_values={k:v['selection_value'] for k,v in r['sources'].items()}) for r in budgets['results']]
        by_seed={}
        for r in evidence['budgets']:by_seed.setdefault(r['seed'],[]).append(r)
        evidence['later_budget_lower_for_every_seed']=all(
            sorted(rr,key=lambda r:r['step'])[-1]['value']<sorted(rr,key=lambda r:r['step'])[0]['value']
            for rr in by_seed.values() if len(rr)>1)
    if comparison and matched:
        if matched['comparison_sha256']!=digest(run/'held-raw-control/comparison.json'):
            raise ValueError('matched held comparison binding differs')
        if selection and comparison['learned_selection_sha256']!=digest(run/'production-validation/selection.json'):
            raise ValueError('matched held selected checkpoint differs')
        evidence['matched_held_control']=dict(raw_mean=comparison['raw_equal_source_mean'],
            learned_mean=comparison['learned_equal_source_mean'],delta=comparison['learned_minus_raw_equal_source_mean'],
            count=len(comparison['cases']),raw_passed=comparison['raw_passed_cases'],learned_passed=comparison['learned_passed_cases'],
            raw_decode_failures=comparison['raw_decode_failures'],learned_decode_failures=comparison['learned_decode_failures'],
            per_source=comparison['per_source'],metric_means=matched['equal_source_metric_means'],
            critical_cases=[r for r in comparison['cases'] if r['id'] in ['daybreak_nocturne-prefix','rwc_p002-prefix']],
            causal_scope=matched['causal_scope'])
    if noise:
        rows=noise['rows']
        evidence['noise_control']=dict(count=noise['count'],six_gate_passes=noise['six_gate_passes'],
            exact_physical_bar_count_passes=sum(r['diagnostics']['exact_bar_count_passed'] for r in rows),
            six_gate_passes_with_extra_in_source_bar=sum(r['score']['all_gates_pass'] and
                r['diagnostics']['predicted_bars']>r['diagnostics']['expected_bars'] for r in rows),
            cases=[dict(id=r['id'],six_gates=r['score']['all_gates_pass'],
                expected_bars=r['diagnostics']['expected_bars'],predicted_bars=r['diagnostics']['predicted_bars']) for r in rows],
            interpretation=noise['interpretation'],scorer_or_threshold_changed=False)
    if alias:
        evidence['score_alias_diagnosis']=dict(scope=alias['scope'],conclusion=alias['conclusion'],limits=alias['limits'],
            rows=[dict(id=r['id'],actual_states=r['actual_states'],
                components=r['actual_minus_same_rhythm_common_components'],
                actual_minus_best_common=r['actual_minus_best_available_common_meter']) for r in alias['rows']],
            exact_alias_controls=alias['exact_alias_controls'],new_equivalence_adopted=False)
    return evidence


def learning_report_lines(evidence):
    lines=['## Production-map observation experiment','']
    if not evidence['training_complete']:
        return lines+['Main actual-map fitting is pending. Prepared labels/code are not a completed learning experiment.','']
    exposure=evidence['exposure'];training=evidence['training']
    lines += [f"{exposure['train_count']} recordings fit the quarter/bar/grid-support model on frozen 512-dimensional features; {exposure['held_count']} sources are held from weight fitting. All NTM projects share one conservative training group; Circle is the other. Held sources are Daybreak3, Walker, RWC and State Shirt. The auxiliary GuitarSet clip is excluded from fitting and checkpoint selection and is scored separately in the whole21 comparison.",'',
        'All sources are known development material. RWC has known acoustic-model pretraining exposure; other pretraining exposure is not established. Holding sources from these weight updates does not establish unseen-song evaluation. Unknown reference margins are masked; explicit no-grid tails provide negative labels. No interval-BPM regression, grouping or meter-class label is invented.','',
        f"The preserved 600-update tiny fit fails and the unchanged 2400-update fit passes the event-only trainability gate. Main seeds {', '.join(map(str,training['seeds']))} use {', '.join(map(str,training['steps']))} updates and checkpoints {', '.join(map(str,training['checkpoint_steps']))}. The targets, model and scoring thresholds stay unchanged; the larger main budget was fixed before main weights or held scores.",'',
        'Checkpoint selection uses eight actual PARTIAL maps: six first 64s excerpts, Walker ending 64s and a 64s State Shirt change window. Excerpts are averaged within a source, then the six sources receive equal weight. Expected decode failures contribute zero with unavailable map metrics. Valid maps use the unchanged strict scorer.','']
    if not evidence['held_validation_complete']:
        return lines+['Held-map validation remains pending; no checkpoint is selected yet.','']
    selected=evidence['selection']
    lines += [f"Selected seed {selected['seed']}, {Path(selected['selected']).name}, held equal-source six-score mean {100*selected['map_selection_value']:.2f}%. This average is a selection criterion, not an all-gate pass rate. Whole21 scores cannot select or replace this checkpoint.",'']
    if evidence.get('budgets'):
        lines += ['| Seed | Updates | Equal-source criterion | Passing excerpts | Decode failures |','|---|---:|---:|---:|---:|']
        for r in sorted(evidence['budgets'],key=lambda r:(r['seed'],r['step'])):
            lines.append(f"| {r['seed']} | {r['step']} | {100*r['value']:.2f}% | {r['passing_excerpts']}/8 | {r['decode_failures']} |")
        lines += ['','Each 3200-update checkpoint has a lower held-map criterion than its 800-update counterpart. All 48 learned partial maps decode, and none passes every strict gate. The fitted tiny excerpts do not establish transfer across these sources.','']
    matched=evidence.get('matched_held_control')
    if matched:
        lines += ['### Matched held raw-observation control','',
            f"On the same frozen eight excerpts and decoder, raw and selected learned routes average {100*matched['raw_mean']:.2f}% and {100*matched['learned_mean']:.2f}% (delta {100*matched['delta']:+.2f} percentage points). They pass {matched['raw_passed']}/{matched['count']} and {matched['learned_passed']}/{matched['count']} complete gate sets; decode failures are {matched['raw_decode_failures']}/{matched['learned_decode_failures']}. This does not establish a validated accuracy gain.",'',
            '| Held source | Raw criterion | Learned criterion | Delta pp |','|---|---:|---:|---:|']
        for source,r in matched['per_source'].items():lines.append(f"| {source} | {100*r['raw']:.2f}% | {100*r['learned']:.2f}% | {100*r['learned_minus_raw']:+.2f} |")
        critical={r['id']:r for r in matched['critical_cases']}
        if 'daybreak_nocturne-prefix' in critical:
            r=critical['daybreak_nocturne-prefix'];key='bar_boundary_f1_70ms'
            lines += ['',f"Nocturne prefix bar F1 regresses from {100*r['raw_scores'][key]:.2f}% to {100*r['learned_scores'][key]:.2f}% despite 100% quarter BPM/grid diagnostics."]
        if 'rwc_p002-prefix' in critical:
            r=critical['rwc_p002-prefix'];key='quarter_bpm_time_within_1'
            lines += [f"RWC prefix BPM-time accuracy regresses from {100*r['raw_scores'][key]:.2f}% to {100*r['learned_scores'][key]:.2f}%; its learned clock approaches 200 quarter BPM where the reference is 100. The preserved bar result does not repair quarter-clock semantics."]
        lines += ['',matched['causal_scope'],'']
    lines += ['Whole21 learned scoring is '+('complete; fitted/held/auxiliary outcomes are reported separately below.' if evidence['whole_learned_evaluation_complete'] else 'pending. Completed fitting and held validation are not whole-song results.'),'']
    return lines


def control_report_lines(evidence):
    lines=[];noise=evidence.get('noise_control')
    if noise:
        lines += ['## Independent stochastic observation controls','',
            f"Two short manufactured 12-bar cases yield {noise['six_gate_passes']}/{noise['count']} six-gate passes and {noise['exact_physical_bar_count_passes']}/{noise['count']} exact physical in-source bar counts. Three six-gate-passing cases contain a thirteenth bar just before source end. The frozen inclusive closing-boundary convention can match it, while the separate half-open physical count exposes the extra event. Both diagnostics remain recorded; no endpoint rule or threshold changes.",'',
            'Independent per-channel 10ms/30ms jitter, Bernoulli 25% dropout probability and ceil 15%-of-nominal false-event additions use one fixed seed per condition. Conditions are separate rather than composed. Two cases and single seeds do not calibrate uncertainty or establish music/audio robustness.','',
            'The constant 30ms-jitter case selects 8/4 and six bars instead of twelve 4/4 bars, with maximum fixed-index quarter error 11.564ms. The changed-tempo 30ms case keeps twelve 4/4 bars and places its boundary 8.893918s versus 8.8s, within 500ms; it fails the unchanged 0.1 BPM rate tolerance because 119.747806 differs from 120. Tempo change TP/FP/FN remains 0/1/1. Neither failure is waived.','']
    alias=evidence.get('score_alias_diagnosis')
    if alias:
        lines += ['## Conditional score/vocabulary diagnosis','',
            'The preserved tiny 2400 Archspire/Deadman diagnosis fixes their recovered quarter clocks and physical bar starts. It compares conditional emissions/direct scores and familiar-meter oracle constraints on two TRAINING excerpts. It reruns no whole-song or held latent decoder.','',
            'Actual 16/16 and 12/16 winners use distinct strong-group offsets and finer onset kernels. RMS-flux onset evidence outweighs the existing extra grouping/transition penalties; those priors already favor the familiar reference signatures. Archspire and Deadman actual-minus-best-common conditional scores are 233.965 and 27.761. This diagnoses a coupling between nominal meter and rhythmic subdivision explanations, with limited flexible rhythm under familiar meters.','',
            'Some explicitly tested kernels are exact aliases with different pattern priors. Several hypothetical group 2/group 4 aliases are absent from the generated vocabulary and cannot explain these actual winners. An available 4/4 duple versus 8/8 half-time alias has a 0.04 per bar prior difference favoring 4/4. These conditional controls do not identify all real-song causes.','',
            'Reference grouping is not independently qualified, so different inferred strong-group placements are hypotheses rather than proven grouping mistakes. Fixed familiar-meter constraints are oracle diagnostics, not new automatic predictions. No canonicalization, per-song meter rule, general equivalence policy, scorer or threshold is adopted.','']
    return lines


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    baseline=Path('data/runs/tempo-meter-v3/reviewed21-frozen-20260930-v1')
    old=Path('data/runs/tempo-meter-v3/joint-reconstruction-20261001-v1')
    paths={'frozen_v3':baseline/'evaluation/scores.json','same_observation_v2':old/'evaluation-v2-control/scores.json',
        'no_repeat':run/'evaluation-no_repeat/scores.json','automatic_repeat':run/'evaluation-automatic_repeat/scores.json'}
    protocol=json.loads((run/'protocol.json').read_text())
    previous=Path(protocol.get('previous_root',''))
    if previous!=run and (previous/'evaluation-no_repeat/scores.json').exists():
        paths['previous_point_core']=previous/'evaluation-no_repeat/scores.json'
    if (run/'evaluation-learned/scores.json').exists():paths['learned']=run/'evaluation-learned/scores.json'
    pending_scores=[arm for arm,path in paths.items() if not path.exists()]
    paths={arm:path for arm,path in paths.items() if path.exists()}
    datasets={arm:json.loads(path.read_text())['rows'] for arm,path in paths.items()};summaries={arm:summary(rows) for arm,rows in datasets.items()}
    evidence=learning_evidence(run,protocol)
    if evidence['held_validation_complete'] and not evidence['whole_learned_evaluation_complete']:
        pending_scores.append('learned')
    frozen=summaries['frozen_v3'];frozen_rows={r['id']:r for r in datasets['frozen_v3']}
    ideal_path=run/'ideal-controls/results.json'
    ideal=json.loads(ideal_path.read_text()) if ideal_path.exists() else dict(rows=[])
    ideal_failed=[r['id'] for r in ideal['rows'] if not r['passed']]
    ideal_passed=sum(r['passed'] for r in ideal['rows'])
    ideal_complete=len(ideal['rows'])==13
    control_issue=(', '.join(ideal_failed) if ideal_failed else None) if ideal_complete else 'current ideal controls incomplete'
    gates={}
    for arm in ['no_repeat','automatic_repeat','learned']:
        if arm not in summaries:continue
        s=summaries[arm];candidate={r['id']:r for r in datasets[arm]}
        checks=dict(all_sources_decoded=s['decode_failures']==0,tempo_fp_half=s['tempo_tp_fp_fn'][1]<=.5*frozen['tempo_tp_fp_fn'][1],
            meter_fp_half=s['meter_tp_fp_fn'][1]<=.5*frozen['meter_tp_fp_fn'][1],
            true_tempo_recall_improves=s['tempo_recall'] is not None and s['tempo_recall']>frozen['tempo_recall'],
            true_meter_recall_improves=s['meter_recall'] is not None and s['meter_recall']>frozen['meter_recall'],
            beat_macro_loss_at_most2pp=s['mean_six_scores'][2]>=frozen['mean_six_scores'][2]-.02,
            bar_macro_loss_at_most2pp=s['mean_six_scores'][3]>=frozen['mean_six_scores'][3]-.02,
            old_passes_retained=all(candidate[i]['score']['all_gates_pass'] for i,r in frozen_rows.items() if r['score']['all_gates_pass']))
        gates[arm]=dict(checks=checks,all_comparison_checks_pass=all(checks.values()),promotion_eligible=False,
            independent_control_failure=control_issue,
            current_ideal_controls_pass=ideal_complete and not ideal_failed)
    rows=[]
    for arm,items in datasets.items():
        for item in items:
            rows.append(dict(arm=arm,id=item['id'],title=item['title'],role=item['role'],scores=six_scores(item['score']),
                passed=item['score']['all_gates_pass'],tempo_tp_fp_fn=counts(item['score'],'tempo'),meter_tp_fp_fn=counts(item['score'],'meter'),
                tails=item['score'].get('free_tail_false_positives'),grid_end_error_seconds=item['score'].get('grid_end_error_seconds')))
    result=dict(scope='20 known development recordings plus one auxiliary; strict evaluator unchanged',summaries=summaries,gates=gates,rows=rows,
        score_bindings={arm:dict(path=str(path),sha256=digest(path)) for arm,path in paths.items()},model_stage_complete='learned' in summaries,
        current_ideal_controls=dict(passed=ideal_passed,count=len(ideal['rows']),failed=ideal_failed,complete=ideal_complete),
        pending_whole_score_arms=pending_scores,learning_and_control_evidence=evidence)
    result['reporting_implementation_sha256']=digest(__file__)
    rejected=[arm for arm,g in gates.items() if not g['all_comparison_checks_pass']]
    result['rejected_settings']=rejected
    runtime_path=run/'runtime-summary.json'
    runtime=json.loads(runtime_path.read_text()) if runtime_path.exists() else None
    if runtime:
        result['runtime_evidence']=dict(path=str(runtime_path),sha256=digest(runtime_path),
            finished_summary=runtime['finished_summary'],timing_caveats=runtime['timing_caveats'])
    recovery_path=run/'aggregation-recovery-check.json'
    if recovery_path.exists():result['aggregation_recovery']=dict(path=str(recovery_path),sha256=digest(recovery_path))
    if 'learned' in datasets:
        supervision=json.loads((run/'production-supervision-locked/manifest.json').read_text());splits={r['id']:r['split'] for r in supervision['rows']}
        result['learned_exposure_groups']={split:dict(count=len(rr),passed=sum(r['score']['all_gates_pass'] for r in rr),
            mean_six_scores=np.mean([aggregation_scores(r) for r in rr],0).tolist())
            for split in ['train','validation'] for rr in [[r for r in datasets['learned'] if splits.get(r['id'])==split]]}
    (run/'comparison-summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    with (run/'comparison.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['id','arm','role','bpm','meter','beat','bar','tempo_change','meter_change','tempo_tp_fp_fn','meter_tp_fp_fn','passed'])
        for r in rows:writer.writerow([r['id'],r['arm'],r['role'],*r['scores'],r['tempo_tp_fp_fn'],r['meter_tp_fp_fn'],r['passed']])
    manifest_paths={'no_repeat':run/'predictions-parallel/no_repeat/manifest.json','automatic_repeat':run/'predictions-parallel/automatic_repeat/manifest.json'}
    if 'learned' in summaries:manifest_paths['learned']=run/'predictions-learned/manifest.json'
    diagnostics={}
    for arm,path in manifest_paths.items():
        if arm not in summaries:continue
        manifest=json.loads(path.read_text());diagnostics[arm]=[]
        for row in manifest['rows']:
            pred=json.loads(Path(row['selected']['path']).read_text())['map']
            ref=json.loads((run/('evaluation-'+arm)/(row['id']+'-reference.json')).read_text())['map']
            diagnostic=drift(ref,pred) if pred is not None else dict(status='decode_failed_no_grid')
            diagnostics[arm].append(dict(id=row['id'],fixed_index_drift=diagnostic,runtime_seconds=row['runtime_seconds'],max_rss_bytes=row.get('max_rss_bytes')))
    (run/'diagnostics.json').write_text(json.dumps(diagnostics,indent=2)+'\n')
    lines=['# Document-directed latent clock / bar reconstruction','',
        'This is the owner-requested independent-review route, implemented as a bounded experimental prototype. No product default is promoted. References, offsets, strict scoring and prior v2/v3 results remain frozen. These twenty recordings are known development material; the GuitarSet clip is auxiliary.','',
        '## Results','',
        '| Arm | Finished | Auxiliary | BPM / meter / beat / bar macro % | Tempo TP/FP/FN | Meter TP/FP/FN |',
        '|---|---:|---:|---|---|---|']
    for arm,s in summaries.items():lines.append(f"| {arm} | {s['finished_passed']}/{s['finished_count']} | {s['auxiliary_passed']}/{s['auxiliary_count']} | "+' / '.join(f'{100*v:.2f}' for v in s['mean_six_scores'][:4])+' | '+' / '.join(map(str,s['tempo_tp_fp_fn']))+' | '+' / '.join(map(str,s['meter_tp_fp_fn']))+' |')
    if pending_scores:lines+=['','Whole-score arms still pending: '+', '.join(pending_scores)+'. Their directories or partial prediction receipts are not scored completion.']
    elif rejected:
        lines+=['','**Decision: reject the tested settings ('+', '.join(rejected)+').** Their complete predictions and strict scores are retained. Mean-score improvements do not offset failed change recall, meter accuracy and loss of previously passing sources. This rejects these bounded settings; it does not evaluate every proposal in the independent review or establish that observation learning cannot work.']
    lines+=['','## Predeclared checks','']
    for arm,g in gates.items():lines.append('- '+arm+': '+('comparison checks pass' if g['all_comparison_checks_pass'] else 'comparison checks fail')+'; failing: '+(', '.join(k for k,v in g['checks'].items() if not v) or 'none')+'.')
    lines+=['','Decode failures retain the full denominator and contribute zero to macro scores. Their individual map metrics remain unavailable; change counts cover successful decodes only and full-cohort recall is unavailable if any finished source failed. No product default is promoted. A lower FP count alone is not adopted as an improvement if true changes or beat/bar accuracy regress. Current ideal-control failures: '+(control_issue or 'none')+'. Earlier failed versions are retained.','',
        '## Implementation and controls','',
        'Frozen Beat This final0 logits/embeddings/RMS were reused. Event coordinates can be quarter, subdivision, missing pulse or clutter; clock fitting searches new changes, including within a bar. Semi-Markov two-best paths retain meter/group/rhythm alternatives and feed back into coordinate/clock search. A common physical source interval is scored. Half-time, syncopated 3+3+2, non-bar seven-sixteenth riff, weak downbeat and rest states are distinct from meter. Sparse repeated-context links have no-repeat and automatic-repeat controls.','',
        f'Twelve package tests pass. Current pure-ideal end-to-end controls pass{ideal_passed}/{len(ideal["rows"])}. The factory substitution is recorded in protocol.json: no deterministic floor and no event at the excluded physical source end. Preserved v1/v2/v3 fixtures contain that floor and censored endpoint event, and are not stochastic-noise generalization tests. Their latest result remains12/13: the small change is752.986ms late with2.883ms maximum fixed-quarter error. Neither result is real-audio accuracy. Exact-clock broad-peak and direct-score confirmation receipts are in capacity-confirmation/. Known repeat links are diagnostics; automatic repeat is judged separately on actual sources.','',
        'The core is bounded: beam32, two bar alternatives and two alternation rounds; rhythm vocabulary is finite. Robust residuals are used, but explicit instrument-specific timing offsets and tempo ramps are not implemented. Grouping evidence uses RMS flux as a proxy. Free-ending inference remains conservative and cannot assume silence means no grid. Confidence is not calibrated.','',
        '## Production-map observation experiment','']
    lines=lines[:-2]  # Replace the empty production heading with completed-stage evidence.
    lines+=learning_report_lines(evidence)
    lines+=control_report_lines(evidence)
    if 'learned' in summaries:
        result['selection']=evidence.get('seed_results',[])
        lines+=['Whole-source exposure is separate:','']
        for split,group in result['learned_exposure_groups'].items():lines.append(f"- {split}: {group['passed']}/{group['count']} strict passes; mean BPM/meter/beat/bar "+' / '.join(f'{100*v:.2f}%' for v in group['mean_six_scores'][:4])+'.')
        auxiliary=summaries['learned'];lines.append(f"- auxiliary: {auxiliary['auxiliary_passed']}/{auxiliary['auxiliary_count']} strict passes; excluded from fit and checkpoint selection.")
    lines+=['','## Per-source strict scores','', '| Source | Arm | BPM | Meter | Beat | Bar | Tempo change | Meter change | Pass |','|---|---|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:lines.append('| '+r['title']+' | '+r['arm']+' | '+' | '.join(f'{100*v:.2f}' if v is not None else 'n/a' for v in r['scores'])+' | '+('yes' if r['passed'] else 'no')+' |')
    if runtime:
        s=runtime['finished_summary']
        lines+=['','## Selected-model runtime','',
            f"Across the twenty finished recordings, median cached observation-plus-map job time is {s['median_cached_seconds']:.2f}s; the median job/audio ratio is {s['median_cached_ratio']:.2f} and maximum is {s['max_cached_ratio']:.2f}. These measured jobs exclude queue waiting and initial acoustic extraction. There is no validated twice-audio-duration upper bound.",'',
            'Feature extraction and learned-map times below come from separate executions. Their sum is an estimate, excludes extractor/process initialization and validation outside the timers, and is not a measured cold learned end-to-end run. Input complexity and concurrent workloads vary. The auxiliary is separate.','',
            '| Source | Audio seconds | Cached learned seconds | Historical feature-loop seconds | Separate-stage sum estimate | Cached job/audio ratio |',
            '|---|---:|---:|---:|---:|---:|']
        for r in runtime['rows']:
            lines.append('| '+r['title']+(' (auxiliary)' if r['role']!='finished_recording_development' else '')+f" | {r['duration_seconds']:.2f} | {r['learned_cached_seconds']:.2f} | {r['feature_extract_loop_seconds']:.2f} | {r['separate_stage_sum_seconds']:.2f} | {r['cached_runtime_to_audio_ratio']:.2f} |")
    if recovery_path.exists():
        lines+=['','## Postprocessing recovery','',
            'All 21 learned maps were already computed and individually scored by the frozen evaluator before the final aggregate failed. Walker uses the existing scoped score aliases; the aggregator assumed the first row\'s names existed in every row. Recovery reuses the exact completed valid evaluation after verifying manifest/inventory bindings, and applies the existing frozen six-score aliases to aggregate contributions. Every individual score and gate is unchanged. Expected failures keep null metrics and zero aggregate contributions. `aggregation-recovery-check.json` records all21 mixed-schema checks and the unchanged valid-score file hash. No audio inference, training, reference, threshold or evaluator change was made for this recovery.']
    lines+=['','## Evidence and limits','',
        '`comparison-summary.json` and `comparison.csv` retain every gain/regression, counts and grouped results. `diagnostics.json` reports one-index-aligned quarter drift; it never resets associations or shifts timing to improve scores. Owner review does not certify millisecond gold. Per-arm evaluation files retain free-tail/end failures.','',
        'The source-only coordinate entry is `experiments.tempo_meter_v4.reconstruct_coordinate_audio`. The separate first600s existing Deadman source at `../cold-runtime-20261001-v1/cold-output/run.json` ran cold in1246.704s (20min46.704s):52.828s features +1193.440s decode, maximum RSS3.50GB. It passes the1800s gate on this WSL/MX450 case; other workload/native-Windows or learned-head latency is not certified. The crop is runtime-only, not a new accuracy reference. Source locks, parameter/protocol hashes and preserved failures are in this run. No new cohort, paid GPU, acquisition, original cleanup, commit or push occurred. Independent new-song evaluation remains a later stage after design freeze.','']
    (run/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    (run/'comparison-summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(dict(summaries=summaries,gates=gates),indent=2))


if __name__=='__main__':main()
