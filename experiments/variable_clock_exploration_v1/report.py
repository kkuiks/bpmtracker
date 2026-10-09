"""Compare retained Original, inspect frozen results and create standalone plots."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import html
import json
from pathlib import Path

import numpy as np

from tools.project_storage import ROOT, RUNS, SAMPLES
from .evaluate import aggregate, read, reference, score, write


def original_path(run,row):
    ident,role=row['id'],row['role'];bench=RUNS/'metronome_benchmark_v1'
    if role=='prospective_constructed':return run/'original-prospective'/f'{ident}.json'
    if role=='formal_fixed':return RUNS/'metronome_reconstruction_v1/20261005-tap26-v2/audio_family_control/predictions'/f'{ident}.json'
    if role=='generated_fixed':return bench/'20261007-generated58-frozen-v1/predictions/audio_only'/f'{ident}.json'
    if role.startswith('gtzan_'):
        name='20261007-gtzan-development280-frozen-v1' if role=='gtzan_development' else '20261007-gtzan-validation87-frozen-v1'
        return bench/name/'predictions/audio_only'/f'{ident}.json'
    return RUNS/'variable_tempo_step0/20261007-step0-v1/original/predictions/audio_only'/f'{ident}.json'


def original_map(prediction,duration):
    regions=[]
    if prediction.get('period_seconds'):
        p=prediction['period_seconds'];bpm=prediction['quarter_bpm']
        regions=[{'start':0.,'end':duration,'bpm':bpm,'bpm_continuous':bpm,
                  'period':p,'nominal_period':p,'nominal_phase':prediction['offset_seconds']%p}]
    return {'regions':regions,'boundaries':[],'unknown_intervals_seconds':[]}


def baseline(run,index,sources):
    rows=[];maps={}
    for row in index:
        duration=sources[row['id']]['duration_seconds'];path=original_path(run,row)
        if not path.exists():raise ValueError(f'Missing frozen Original baseline: {path}')
        p=original_map(read(path),duration);maps[row['id']]=p
        rows.append({'id':row['id'],'role':row['role'],'score':score(p,reference(row,duration),duration)})
    groups=defaultdict(list)
    for row in rows:groups[row['role']].append(row)
    write(run/'original-baseline-evaluation.json',{'rows':rows,'summaries':{k:aggregate(v) for k,v in groups.items()},
                                                 'retained_predictions_not_refit':True,
                                                 'prospective_original_new_fit_is_separate':True})
    return rows,maps,{k:aggregate(v) for k,v in groups.items()}


def time_only_counts(predicted,true):
    candidates=sorted((abs(p['time']-r['time']),i,j) for i,p in enumerate(predicted) for j,r in enumerate(true)
                      if abs(p['time']-r['time'])<=.5)
    a=set();b=set();errors=[]
    for error,i,j in candidates:
        if i not in a and j not in b:a.add(i);b.add(j);errors.append(error)
    return {'tp':len(errors),'fp':len(predicted)-len(errors),'fn':len(true)-len(errors),
            'matched_errors':errors,'rate_values_not_checked':True}


def diagnostics(run,index,sources,configs):
    result={}
    for config in configs:
        rows=[]
        for row in index:
            if row['role'] not in ('real_variable','synthetic_prior_evaluation','prospective_constructed'):continue
            path=run/'frozen-predictions'/config/f"{row['id']}.json"
            if not path.exists():continue
            p=read(path);ref=reference(row,sources[row['id']]['duration_seconds'])
            boundaries=[x for x in p['boundaries'] if x['kind']=='rate_change']
            counts=time_only_counts(boundaries,ref['changes'])
            targets=[]
            for seg in ref['segments']:
                clock=next((z for z in p.get('source_clock_alternatives',[]) if seg['start_seconds']<=z['time']<seg['end_seconds']
                            and any(abs(c['bpm']/seg['quarter_bpm']-1)<=.01 for c in z['clocks'])),None)
                targets.append(bool(clock))
            rows.append({'id':row['id'],'role':row['role'],'time_only_boundaries':counts,
                         'rate_candidate_present_at_some_center_in_segment':sum(targets),
                         'reference_segment_denominator':len(targets),
                         'candidate_center_recall_does_not_establish_full_support':True})
        result[config]=rows
    write(run/'supplementary-diagnostics.json',{'primary_scores_unchanged':True,
                                             'time_only_boundary_is_not_complete_change_accuracy':True,'rows':result})
    return result


def controls_audit(run):
    expected={'fixed_clean':[120.],'fixed_fractional':[131.25],'fixed_frame_noise':[120.],
              'fixed_missing_pulses':[120.],'fixed_clutter':[120.],'fixed_unrepresentable_120_1':[120.],
              'same_rate_phase_reset':[120.],'step_return':[120.,144.,120.],
              'short_four_quarters':[130.,140.,130.],'octave_step':[160.,80.],
              'small_quarter_bpm_step':[120.,120.25]}
    rows=[]
    for name in ('observation-controls-v1.json','observation-controls-phasor.json','observation-controls-abstain.json'):
        for row in read(run/name)['rows']:
            collapsed=[]
            for value in row['rates']:
                if not collapsed or abs(value-collapsed[-1])>1e-8:collapsed.append(value)
            wanted=expected[row['case']]
            matches=len(wanted)==len(collapsed) and all(abs(a-b)<1e-8 for a,b in zip(wanted,collapsed))
            rows.append({**row,'expected_nominal_rates':wanted,'proposed_nominal_rate_sequence':collapsed,
                         'nominal_rate_sequence_matches':matches,
                         'change_count_match_alone_is_not_clock_success':True})
    write(run/'observation-controls-rate-audit.json',{'rows':rows,'not_real_music_accuracy':True})
    return rows


def verify(run):
    frozen=read(run/'predictor-freeze.json')['sources_sha256'];checks=[]
    for name,hash_value in frozen.items():
        path=run/name if name.endswith('.json') else Path(__file__).parent/name
        checks.append({'name':f'freeze:{name}','passed':hashlib.sha256(path.read_bytes()).hexdigest()==hash_value})
    receipt=read(run/'frozen-predictions/receipt.json')
    checks.append({'name':'all_source_predictions_saved_before_evaluation','passed':receipt['completed'] and not receipt['reference_files_read']})
    sentinel=read(run/'source-isolation-controls.json')
    checks.extend({'name':k,'passed':v} for k,v in sentinel.items())
    replay=read(run/'prospective-source-replay.json')
    checks.append({'name':'twelve_prospective_sources_match_isolated_sensor_replay','passed':replay['all_exact'] and len(replay['rows'])==12})
    source=read(run/'source-inputs.json')['samples'];evaluation=read(run/'evaluation-index.json')['rows']
    checks.append({'name':'all_499_input_ids_and_all_reference_rows_preserved','passed':len(source)==499 and len(evaluation)==499})
    checks.append({'name':'reserved_groups_unconsumed','passed':read(run/'protocol.json')['reserved_groups_consumed']==0})
    value={'checks':checks,'passed':all(r['passed'] for r in checks),'execution_contract_only':True,
           'not_musical_accuracy_or_daw_runtime':True}
    write(run/'execution-review.json',value)
    if not value['passed']:raise ValueError('Frozen execution review failed')
    return value


def plots(run,index,sources,baseline_maps,configs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output=run/'figures';output.mkdir(exist_ok=True)
    names={r['id']:r['title'] for r in read(SAMPLES/'catalog.json')['tracks']}
    selected=['Original']+[c for c in configs if c.startswith(('affine_mdl','phasor_transport','phasor_abstain')) and c.endswith('-neural')]
    for row in index:
        if row['role']!='real_variable':continue
        duration=sources[row['id']]['duration_seconds'];ref=reference(row,duration)
        fig,axes=plt.subplots(len(selected),1,figsize=(13,2.35*len(selected)),sharex=True,layout='constrained')
        for ax,config in zip(np.atleast_1d(axes),selected):
            p=baseline_maps[row['id']] if config=='Original' else read(run/'frozen-predictions'/config/f"{row['id']}.json")
            for seg in ref['segments']:
                ax.plot([seg['start_seconds'],seg['end_seconds']],[seg['quarter_bpm']]*2,color='#333333',lw=2)
            for region in p['regions']:
                ax.plot([region['start'],region['end']],[region['bpm']]*2,color='#2479b7',lw=1.5)
            for a,b in p.get('unknown_intervals_seconds',[]):ax.axvspan(a,b,color='#dba954',alpha=.25)
            for boundary in ref['changes']:ax.axvline(boundary['time'],color='#777777',lw=.6,ls=':')
            ax.set_ylabel('BPM');ax.set_title(config,loc='left',fontsize=9);ax.grid(alpha=.2)
            ax.set_ylim(25,405)
        axes[-1].set_xlabel('Original audio time (seconds)');axes[-1].set_xlim(0,duration)
        fig.suptitle(names.get(row['id'],row['id'])+' — gray: accepted reference; blue: native pulse proposal; amber: UNKNOWN')
        fig.savefig(output/f"{row['id']}.png",dpi=140);fig.savefig(output/f"{row['id']}.svg")
        plt.close(fig)


def table(summaries,role):
    lines=['| Method | Native rate <=1% | Octave-equivalent rate <=1% | Nominal native segments | Quarter F1@70ms | Changes TP/FP/FN | Fixed inputs with changes |',
           '| --- | ---: | ---: | ---: | ---: | --- | --- |']
    for config,groups in summaries.items():
        if role not in groups or 'native_rate_within_1_percent_macro' not in groups[role]:continue
        s=groups[role];b=s['boundary_native']
        lines.append(f"| {config} | {s['native_rate_within_1_percent_macro']:.2%} | {s['octave_rate_within_1_percent_macro']:.2%} | {s['nominal_native_rate_majority_segments']}/{s['reference_segments']} | {s['quarter_macro_f1_70ms']:.2%} | {b['tp']}/{b['fp']}/{b['fn']} | {s['fixed_inputs_with_rate_changes']}/{s['fixed_inputs']} |")
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run
    if not read(run/'frozen-predictions/receipt.json')['completed']:raise ValueError('Prediction incomplete')
    evaluation=read(run/'frozen-evaluation.json');sources={r['id']:r for r in read(run/'source-inputs.json')['samples']}
    index=read(run/'evaluation-index.json')['rows'];original_rows,original_maps,original_summary=baseline(run,index,sources)
    summaries={'Original_constant':original_summary,**evaluation['summaries']}
    write(run/'comparison-summary.json',summaries)
    extra=diagnostics(run,index,sources,evaluation['summaries']);control=controls_audit(run);review=verify(run)
    plots(run,index,sources,original_maps,evaluation['summaries'])
    lines=['# Variable clock exploration after Step 0 — 2026-10-08','',
           'Five source-only experiment arms and an unchanged constant-clock baseline. These are exploratory pulse-clock proposals, not adopted automatic variable-tempo or meter functionality.',
           '', 'The predictor never receives source identity, reference BPM, meter, boundary or phase. It consumes retained official sensor logits, optional source attack timings, and strict source-silence information. No neural training or reference shift was performed.',
           '', '## Frozen selection and scope','',
           'Configuration selection used 40 deterministic GTZAN development inputs and the ten variants of constructed parent 5100 only. All final penalty scales were 32. The sparse-tick abstention threshold was .65. Real variable maps, remaining development, already-used validation and the twelve prospective constructed inputs were excluded from selection. No predictor retuning followed frozen evaluation.',
           '', 'There are 499 input IDs: prior Step 0 36, generated fixed 58, original formal/auxiliary fixed 26, GTZAN development 280 and already-used validation 87, and new constructed 12. These IDs are not 499 independent songs; the vocabulary probe duplicates an existing constructed waveform across cohorts. Reserved 98 groups were not consumed.',
           '', 'Four fresh parent groups contain eight variable and four fixed musical inputs. They were declared before calibration and first real scoring, and use the existing analytic renderer family. They do not establish unseen real-song generalization or unique perceptual quarter notation.',
           '', '## Experimental mechanisms','',
           '- Affine MDL compresses locally counted beat-event coordinates with piecewise lines.',
           '- Multiscale selects consistent local line witnesses across 2/4/8/16/32/64-second views.',
           '- Transport additionally uses intersections of independently fitted source lines to propose boundaries; phase continuity remains an assumption.',
           '- Phasor transport tests all 2221 rational rates locally before assigning event coordinates per clock.',
           '- Phasor abstention retains sparse-tick hypotheses as UNKNOWN rather than definite changes.',
           '- Attack variants snap neural event timestamps to nearby source-derived multiband attacks with one common rule; these attacks are not producer clicks.',
           '', 'The project-relative experiment novelty is the comparison and combination of these mechanisms. Local-periodicity ideas are established in [PLPDP research](https://arxiv.org/abs/2308.10355); [metric-level analysis](https://arxiv.org/abs/2210.06817) motivates separating literal quarter-rate agreement from metrical alternatives. No world-first claim is made.',
           '', '## Metrics and limits','',
           'Native rate agreement uses the returned rational BPM and a 1% diagnostic tolerance. Nominal majority recovery requires the nearest denominator-four reference BPM over at least half its actual segment. Octave-equivalent scores are separate diagnostics. Boundary TP requires time within .5 seconds and exact nominal before/after rates; a shared-octave diagnostic remains separate. Quarter F1 uses unchanged reference events at 20/70ms. UNKNOWN consumes coverage and event recall; missed cases remain in all denominators. These are diagnostic metrics, not product acceptance thresholds.',
           '', 'Real maps are known owner-reviewed development references, not independent producer-clock milliseconds. GTZAN supplies approximately fixed coarse annotations, not certified producer false-change truth. Circle retains 4/2; BabySlakh Track00008 is rate-only because audio origin is unresolved. The source-only model does not infer or certify meter.',
           '', '## Real variable recordings','',table(summaries,'real_variable')]
    for role in ('prospective_constructed','synthetic_prior_evaluation','formal_fixed','generated_fixed','gtzan_development','gtzan_used_validation'):
        lines+=['',f'## {role}','',table(summaries,role)]
    lines+=['','## Control and execution evidence','',
            f"Observation controls have {len(control)} case/method outcomes. Change-count matches alone are not clock passes: the rate audit preserves false harmonic short-section interpretations and missed short excursions. Source-isolation sentinel and reference-field rejection passed; all twelve fresh neural results exactly match isolated source-only replay. Frozen execution review passed {len(review['checks'])} checks. These are workflow/constructed observations, not musical accuracy.",
            '', 'One calibration aggregation was initiated before the additional arm completed. Its intermediate files are retained as before-completeness-review artifacts; the final aggregation ran after all 750 calibration predictions completed and changed the provisional abstention penalty from 16 to 32. Only the complete result was frozen.',
            '', '## Evidence','',
            '`comparison-summary.json`, `frozen-evaluation.json`, `supplementary-diagnostics.json`, `observation-controls-rate-audit.json`, `execution-review.json`, `predictor-freeze.json`, per-source predictions and standalone PNG/SVG trajectory figures. Original inputs, approved references, old runs and the application estimator remain unchanged.']
    for row in index:
        if row['role']=='real_variable':lines+=['',f"![{row['id']}](figures/{row['id']}.png)"]
    (run/'report.md').write_text('\n'.join(lines)+'\n')
    flat=[]
    for config,rows in {'Original_constant':original_rows,**evaluation['rows']}.items():
        for row in rows:
            s=row['score']
            flat.append({'method':config,'id':row['id'],'role':row['role'],
                         'native_rate_within_1_percent':s.get('native_rate_within_1_percent_time_fraction'),
                         'quarter_f1_70ms':s.get('quarter_event_f1',{}).get('70',{}).get('f1'),
                         'change_tp':s.get('boundary_native',{}).get('tp'),'change_fp':s.get('boundary_native',{}).get('fp'),
                         'change_fn':s.get('boundary_native',{}).get('fn')})
    with (run/'results.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    body='<h1>Variable clock exploration — 2026-10-08</h1><p>Frozen exploratory source-only comparisons. Gray: reference; blue: native pulse proposal; amber: UNKNOWN.</p>'
    for row in index:
        if row['role']=='real_variable':body+=f'<h2>{html.escape(row["id"])}</h2><img src="figures/{row["id"]}.png" style="width:100%;max-width:1300px">'
    body+='<h2>All cohort summaries</h2><pre>'+html.escape(json.dumps(summaries,indent=2))+'</pre>'
    (run/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Variable clock exploration</title><style>body{font:16px system-ui;max-width:1400px;margin:30px auto;padding:20px}pre{white-space:pre-wrap;font-size:13px}</style>'+body)
    print('REPORT',run/'report.md',flush=True)


if __name__=='__main__':main()
