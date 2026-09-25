"""Build a cohort-separated report of current Joljak analysis capability.

Consumes frozen predictions and references. It does not choose settings, repair
references, or recommend the next algorithmic step.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

import numpy as np

from inspect_inputs import sha256
from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_tempo_map

TOLERANCES=('10ms','20ms','30ms','70ms')


def write_json(path,value):
    with path.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')


def f1(metrics,name):
    return metrics.get('event_'+name,{}).get('f1')


BASE_METHOD_NAMES = {'official_minimal': 'official_minimal', 'legacy_dbn': 'legacy_dbn',
                     'clock_pipeline': 'legacy_dbn_clock'}
CROSS_METHOD_NAMES = {'official': 'official', 'common_minimal': 'common_minimal',
                      'clock_current': 'meter_free_clock',
                      'clock_candidates_selected': 'clock_candidates_selected'}


def load_references(catalog):
    result = {}
    for record in catalog['tracks']:
        path = Path(record['reference']['path'])
        if sha256(path) != record['reference']['sha256']:
            raise ValueError('reference hash changed: ' + record['id'])
        result[record['id']] = json.loads(path.read_text())
    return result


def method_row(record, reference, *, cohort, evaluation_set, method, source_method,
               prediction, clock, status, metrics, tempo_map_supported,
               downbeat_supported=True, clock_metrics=None):
    changes = evaluate_tempo_map(reference, tempo_events(clock) if clock else None,
                                 tempo_map_supported=tempo_map_supported)
    support = clock.get('support_seconds') if clock else None
    row = {'id': record['id'], 'cohort': cohort, 'evaluation_set': evaluation_set,
           'reference_tier': record.get('reference_tier', record.get('qualification_status')),
           'group_id': record.get('group_id'), 'reference_sha256': record['reference']['sha256'],
           'method': method, 'source_method': source_method, 'model': method.split('__')[0],
           'path': method.split('__', 1)[1], 'method_status': status,
           'prediction_count': len(prediction['beats_seconds']),
           'downbeat_output_status': ('implemented' if downbeat_supported else 'unsupported'),
           'downbeat_reference_status': ('available' if reference.get('downbeats_seconds') is not None else 'unavailable'),
           'tempo_map_supported': tempo_map_supported, 'tempo_map_produced': clock is not None,
           'tempo_map_status': changes['tempo_map_status'],
           'support_start': support[0] if support else None, 'support_end': support[1] if support else None,
           'evaluation_support_start': reference['evaluation_support_seconds'][0],
           'evaluation_support_end': reference['evaluation_support_seconds'][1],
           'meter_output_status': 'unsupported_in_this_path',
           'full_tempo_meter_map_status': 'not_evaluated_no_integrated_meter_and_musical_origin',
           'quarter_rate_mae': (clock_metrics or {}).get('quarter_rate_mae'),
           'median_predicted_to_reference_rate_ratio': (clock_metrics or {}).get('median_predicted_to_reference_rate_ratio'),
           'covered_reference_pulse_fraction': (clock_metrics or {}).get('covered_reference_pulse_fraction')}
    for label in TOLERANCES:
        event = metrics['event_' + label]
        downbeat = metrics.get('downbeat_' + label) if downbeat_supported else None
        for prefix, value in (('', event), ('downbeat_', downbeat)):
            for metric in ('f1', 'precision', 'recall'):
                row[prefix + metric + '_' + label] = (value or {}).get(metric)
        row['missing_beats_' + label] = event.get('false_negatives', event.get('reference_count', 0) - event.get('matched_count', 0))
        row['extra_beats_' + label] = event.get('false_positives', event.get('estimated_count', 0) - event.get('matched_count', 0))
        errors = event.get('matched_event_errors') or {}
        absolute = event.get('matched_absolute_error_ms_p50_p95')
        row['matched_error_p50_ms_' + label] = (errors['absolute_median_seconds'] * 1000 if errors else absolute[0] if absolute else None)
        row['matched_error_p95_ms_' + label] = (errors['absolute_p95_seconds'] * 1000 if errors else absolute[1] if absolute else None)
    for label in ('100ms', '500ms'):
        metric = changes['tempo_changes_' + label]
        score = metric.get('full_change_scores')
        row['tempo_changes_' + label + '_status'] = metric['status']
        for short, long in (('tp', 'true_positives'), ('fp', 'false_positives'), ('fn', 'false_negatives')):
            row['tempo_changes_' + label + '_' + short] = score[long] if score is not None else None
    return row


def crossed_rows(report, catalog, references=None):
    records = {t['id']: t for t in catalog['tracks']}
    references = load_references(catalog) if references is None else references
    rows = []
    for track in report['tracks']:
        record = records[track['id']]
        for source_method, value in track['methods'].items():
            model, path = source_method.split('__', 1)
            supported = path in ('clock_current', 'clock_candidates_selected')
            rows.append(method_row(record, references[track['id']], cohort=track['cohort'],
                evaluation_set='two_model_crossed', method=model + '__' + CROSS_METHOD_NAMES[path],
                source_method=source_method, prediction=value['prediction'], clock=value.get('clock'),
                status=value['status'], metrics=value['metrics'], tempo_map_supported=supported,
                downbeat_supported=path != 'clock_candidates_selected'))
    return rows


def base_rows(report, catalog, references=None):
    records = {t['id']: t for t in catalog['tracks']}
    references = load_references(catalog) if references is None else references
    rows = []
    for track in report['tracks']:
        for source_method, name in BASE_METHOD_NAMES.items():
            scores = track['scores'][source_method]['annotated_span']
            metrics = {}
            for label, value in zip(TOLERANCES, (.01, .02, .03, .07)):
                metrics['event_' + label] = scores['beats_seconds'][str(value)]
                metrics['downbeat_' + label] = scores['downbeats_seconds'][str(value)] if scores['downbeats_seconds'] is not None else None
            is_clock = source_method == 'clock_pipeline'
            rows.append(method_row(records[track['id']], references[track['id']], cohort=track['dataset'],
                evaluation_set='beat_this_base', method='beat_this__' + name, source_method=source_method,
                prediction=track['variants'][source_method], clock=track['clock'] if is_clock else None,
                status=track['clock_status'] if is_clock else 'implemented_event_decoder', metrics=metrics,
                tempo_map_supported=is_clock, clock_metrics=track.get('clock_metrics') if is_clock else None))
    return rows


def aggregate(rows):
    result = {}
    for cohort in sorted({r['cohort'] for r in rows}):
        selected = [r for r in rows if r['cohort'] == cohort]
        methods = {}
        for method in sorted({r['method'] for r in selected}):
            subset = [r for r in selected if r['method'] == method]
            item = {'track_count': len(subset),
                'mean_f1': {name: float(np.mean([r['f1_' + name] for r in subset])) for name in TOLERANCES},
                'mean_downbeat_f1': {name: (float(np.mean([r['downbeat_f1_' + name] for r in subset if r.get('downbeat_f1_' + name) is not None]))
                    if any(r.get('downbeat_f1_' + name) is not None for r in subset) else None) for name in TOLERANCES},
                'downbeat_track_count': sum(r.get('downbeat_f1_20ms') is not None for r in subset),
                'downbeat_output_status': subset[0].get('downbeat_output_status', 'unspecified'),
                'empty_predictions': sum(not r['prediction_count'] for r in subset),
                'tempo_maps_produced': sum(r['tempo_map_produced'] for r in subset),
                'tempo_map_supported': subset[0].get('tempo_map_supported'),
                'tempo_map_failure_count': sum(r.get('tempo_map_status') == 'failed_no_tempo_map' for r in subset),
                'status_counts': {status: sum(r['method_status'] == status for r in subset)
                                 for status in sorted({r['method_status'] for r in subset})}}
            for label in ('100ms', '500ms'):
                eligible = [r for r in subset if r['tempo_changes_' + label + '_tp'] is not None]
                item['tempo_changes_' + label] = ({
                    **{key: sum(r['tempo_changes_' + label + '_' + key] for r in eligible) for key in ('tp', 'fp', 'fn')},
                    'eligible_tracks': len(eligible),
                    'reference_change_count': sum(r['tempo_changes_' + label + '_tp'] + r['tempo_changes_' + label + '_fn'] for r in eligible),
                    'failed_map_tracks_included': sum(r.get('tempo_map_status') == 'failed_no_tempo_map' for r in eligible)} if eligible else None)
            methods[method] = item
        result[cohort] = {'distinct_audio_count': len({r['id'] for r in selected}), 'methods': methods,
            'reference_tiers': sorted({r.get('reference_tier') for r in selected if r.get('reference_tier')}),
            'group_count': len({r.get('group_id') for r in selected if r.get('group_id')}),
            'group_count_warning': 'Catalog grouping identifiers, not an independently validated number of musicians or unseen compositions.'}
    return result


def normalize_bt_coverage(manifest, incident):
    attempted = {row['input'] for row in incident.get('reproductions', [])}
    rows = []
    for row in manifest['rows']:
        normalized = dict(row)
        normalized['original_status'] = row['status']
        if row['status'] == 'frontend_runtime_failure':
            normalized['status'] = 'blocked_by_shared_frontend_failure'
        normalized['frontend_failure_reproduced_on_this_input'] = row['id'] in attempted
        rows.append(normalized)
    counts = {status: sum(row['status'] == status for row in rows) for status in sorted({row['status'] for row in rows})}
    return {'rows': rows, 'counts': counts,
        'documented_frontend_attempt_count': len(incident.get('reproductions', [])),
        'documented_frontend_distinct_input_count': len(attempted),
        'interpretation': 'Blocked coverage is inferred from a reproduced shared frontend failure; it is not a claim that every blocked input was separately executed.'}


def beat_this_summary(report, excluded_ids=frozenset()):
    included=[row for row in report['tracks'] if row['id'] not in excluded_ids]
    output={}
    for cohort in sorted({row['dataset'] for row in included}):
        selected=[row for row in included if row['dataset']==cohort];methods={}
        for method in ('official_minimal','legacy_dbn','clock_pipeline'):
            methods[BASE_METHOD_NAMES[method]]={'track_count':len(selected),'macro_f1':{name:float(np.mean([
                row['scores'][method]['annotated_span']['beats_seconds'][str(value)]['f1'] for row in selected]))
                for name,value in zip(TOLERANCES,(.01,.02,.03,.07))}}
            eligible=[row for row in selected if row['scores'][method]['annotated_span']['downbeats_seconds'] is not None]
            methods[BASE_METHOD_NAMES[method]]['downbeat_track_count']=len(eligible)
            methods[BASE_METHOD_NAMES[method]]['macro_downbeat_f1']={name:(float(np.mean([
                row['scores'][method]['annotated_span']['downbeats_seconds'][str(value)]['f1'] for row in eligible])) if eligible else None)
                for name,value in zip(TOLERANCES,(.01,.02,.03,.07))}
        output[cohort]={'distinct_audio_count':len(selected),'methods':methods,
            'clock_fallback_count':sum(row['clock_status'].startswith('fallback') for row in selected),
            'clock_review_count':sum('requires_review' in row['clock_status'] for row in selected)}
    return output


def owner_review_decisions(path,catalog):
    if path is None:
        return {'items':[]},set()
    data=json.loads(path.read_text());records={t['id']:t for t in catalog['tracks']};rejected=set()
    if data.get('model_predictions_included') is not False:
        raise ValueError('owner reference review must be prediction-blind')
    for item in data.get('items',[]):
        track_id=item['id']
        if track_id not in records:
            raise ValueError(f'unknown owner-review id: {track_id}')
        record=records[track_id]
        if item.get('audio_sha256')!=record['input']['sha256'] or item.get('reference_sha256')!=record['reference']['sha256']:
            raise ValueError(f'owner-review hash mismatch: {track_id}')
        if item['decision']=='reject_current_reference_for_accuracy_scoring':
            rejected.add(track_id)
        else:
            raise ValueError(f'unsupported owner-review decision: {item["decision"]}')
    return data,rejected


def gtzan_summary(report):
    methods={}
    for variant in ('official_minimal','legacy_dbn','clock_pipeline'):
        rows=[t['scores'][variant]['annotated_span']['beats_seconds'] for t in report['tracks']]
        # Python's str(.03) matches the stored keys and avoids presenting this
        # supplementary corpus as an exact tempo-map benchmark.
        methods[BASE_METHOD_NAMES[variant]]={'track_count':len(rows),'macro_f1':{
            name:float(np.mean([row[str(value)]['f1'] for row in rows]))
            for name,value in zip(TOLERANCES,(.01,.02,.03,.07))}}
        methods[BASE_METHOD_NAMES[variant]]['clock_fallback_count']=sum(
            t['clock_status'].startswith('fallback') for t in report['tracks']) if variant=='clock_pipeline' else None
    genres={}
    for genre in sorted({t['genre'] for t in report['tracks']}):
        selected=[t for t in report['tracks'] if t['genre']==genre]
        genres[genre]={'count':len(selected),'official_minimal_f1_70ms':float(np.mean([
            t['scores']['official_minimal']['annotated_span']['beats_seconds']['0.07']['f1'] for t in selected]))}
    return {'scope':'supplementary human beat labels without local waveform or exact tempo map',
        'track_count':len(report['tracks']),'methods':methods,'genres':genres}


def existing_experiments():
    paths={
        'tempo_prior':'data/runs/tempo-prior/comparison-v1/summary.json',
        'phase_alignment':'data/runs/phase-alignment/review-v1/summary.json',
        'meter_development':'data/runs/clock-ablation/bar70-v2/report.json',
        'meter_probe':'data/runs/clock-ablation/probe-bars-v1/report.json',
        'short_changes':'data/runs/clock-ablation/short-change-v2b/report.json',
        'light_completion':'data/runs/one-song/light-completion-v4/report.json',
        'corpus_expansion':'data/runs/corpus-expansion/review-v2/summary.json',
        'observed_click':'data/runs/corpus-expansion/forestry-click1-v1/report.json',
        'reference_semantics':'data/runs/reference-audit/babyslakh-v1/report.json',
        'producer_predictions':'data/runs/corpus-expansion/daybreak3-predictions-v1/predictions-report.json',
    }
    output={}
    for key,name in paths.items():
        path=Path(name);output[key]={'path':name,'sha256':sha256(path),'data':json.loads(path.read_text())}
    return output


def bounded_findings(experiments):
    prior=experiments['tempo_prior']['data'];key='conditional_completion/forestry_producer_pilot/combined'
    strongest=prior['comparisons']['2.0'][key]['methods']['soft_prior']
    phase=experiments['phase_alignment']['data']
    meter=experiments['meter_development']['data']
    bar=[]
    for method in ('fixed','variable'):
        values=[row['methods'][method]['meter_change_scores'] for row in meter['tracks']
                if row['methods'][method]['meter_change_scores'] is not None]
        bar.append({'method':method,'eligible_tracks':len(values),
            'reference_changes':sum(v['reference_change_count'] for v in values),
            'predicted_changes':sum(v['predicted_change_count'] for v in values),
            'matched_changes_500ms':sum(v['matched_count'] for v in values)})
    short=experiments['short_changes']['data'];short_rows=[]
    for condition in short['configuration']['conditions']:
        name=condition['name']
        for variant in ('v1','v2'):
            scores=[row['conditions'][name]['variants'][variant]['metrics']['tempo_changes_100ms']['full_change_scores']
                    for row in short['tracks']]
            short_rows.append({'condition':name,'variant':variant,
                **{k:sum(v[k] for v in scores) for k in ('true_positives','false_positives','false_negatives')}})
    light=experiments['light_completion']['data'];light_rows={}
    for name,metrics in light['metrics'].items():
        light_rows[name]={'event_f1_20ms':metrics['event_20ms']['f1'],'event_f1_70ms':metrics['event_70ms']['f1'],
            'tempo_changes_100ms':metrics['tempo_changes_100ms']['full_change_scores'],
            'tempo_changes_500ms':metrics['tempo_changes_500ms']['full_change_scores']}
    return {'soft_prior_strong_light':{**strongest,'default_promoted':prior['default_promoted'],
                'scope':'one development song conditional completion'},
        'phase_alignment':{'default_promoted':phase['default_promoted'],'human_listening_performed':phase['human_listening_performed'],
            'decision_counts':phase['decision_counts']},
        'meter_change_diagnostic':bar,
        'short_change_oracle_diagnostic':short_rows,
        'light_full_song_comparison':light_rows}


def review_queue(reference_audit,catalog):
    records={t['id']:t for t in catalog['tracks']};base={
        'musical_quarter_intent_not_independently_verified','tick_zero_musical_phase_not_independently_verified',
        'synthesized_arrangement_not_recorded_studio_band'}
    output=[]
    for track in reference_audit['tracks']:
        extra=[flag for flag in track['qualification']['review_flags'] if flag not in base]
        if extra:
            record=records[track['id']]
            output.append({'id':track['id'],'audio_path':record['input']['path'],
                'reference_path':record['reference']['path'],'flags':extra,
                'question':'Does the rendered music follow the supplied quarter-grid and intended bar phase throughout the scored span?',
                'model_predictions_must_not_inform_answer':True})
    if len(output)>3:raise ValueError('review queue exceeds agreed batch size')
    return output


def _percent(value):
    return 'N/A' if value is None else f'{100 * value:.2f}%'


def comparison_markdown(cohorts):
    lines = []
    for cohort, item in cohorts.items():
        lines.extend([f'### {cohort} ({item["distinct_audio_count"]} audio assets)', '',
            '| Method | Beat 10ms | Beat 20ms | Beat 30ms | Beat 70ms | Downbeat 20ms | Downbeat 70ms | Tempo maps | Failed maps | Empty beats |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|'])
        for method, values in item['methods'].items():
            maps = f"{values['tempo_maps_produced']}/{values['track_count']}" if values['tempo_map_supported'] else 'unsupported'
            lines.append('| ' + method + ' | ' + ' | '.join(_percent(values['mean_f1'][t]) for t in TOLERANCES) +
                ' | ' + _percent(values['mean_downbeat_f1']['20ms']) + ' | ' + _percent(values['mean_downbeat_f1']['70ms']) +
                f" | {maps} | {values['tempo_map_failure_count']} | {values['empty_predictions']} |")
        lines.extend(['', '| Method | Eligible tracks | Reference changes | 100ms TP/FP/FN | 500ms TP/FP/FN | Missing-map tracks included |',
                      '|---|---:|---:|---:|---:|---:|'])
        for method, values in item['methods'].items():
            x, y = values['tempo_changes_100ms'], values['tempo_changes_500ms']
            if x is None:
                label = 'unsupported' if not values['tempo_map_supported'] else 'reference unavailable'
                lines.append(f'| {method} | N/A | N/A | {label} | {label} | N/A |')
            else:
                lines.append(f"| {method} | {x['eligible_tracks']}/{values['track_count']} | {x['reference_change_count']} | " +
                    '/'.join(str(x[k]) for k in ('tp', 'fp', 'fn')) + ' | ' +
                    '/'.join(str(y[k]) for k in ('tp', 'fp', 'fn')) + f" | {x['failed_map_tracks_included']} |")
        lines.append('')
    return lines


def build_markdown(summary):
    inv = summary['inventory']; bt = summary['beat_transformer_coverage']
    lines = ['# Joljak corrected status evidence', '',
        'This report recalculates evaluation and reporting from preserved predictions. It does not change audio, references, model output, decoder settings, or reconstruction algorithms.', '',
        '## Scope and interpretation', '',
        f"- {inv['audio_asset_count']} audio assets were inventoried. {inv['score_admitted_audio_count']} supplied references passed structural checks; {inv['retained_audio_reference_count']} remain admitted under the declared reference policy after owner exclusions.",
        '- Retained does not mean every reference received human listening or independent millisecond certification. Reference tiers and scored support remain explicit in the CSV.',
        '- The owner-approved NTM maps remain user-reviewed comparison references. Historical strict-timing flags and all original accepted offsets are preserved.',
        '- Beat-event F1 measures matching events inside annotated spans. It is not the fraction of songs with a correct BPM, meter, or full-song map.',
        '- Missing maps from a map-capable method retain every eligible missed reference change. Event-only methods are unsupported for map evaluation. Missing reference labels are unscored.',
        '- Candidate clocks do not output downbeats in this comparison: their downbeat result is N/A, not measured 0%. Exact meter and common musical origin are not integrated in these paths.', '',
        '## Compared paths', '',
        '- `official_minimal` / `official`: model baseline event output. `legacy_dbn`: legacy meter-constrained event decoding.',
        '- `legacy_dbn_clock`: legacy DBN events followed by the preserved clock fitter. This is the broad Beat This base comparison.',
        '- `meter_free_clock`: meter-free pulses followed by the same preserved fitter. This is a different path, measured here only on the common crossed subset.',
        '- `clock_candidates_selected`: the preserved candidate generator and automatic selector; empty or partial outputs remain visible.', '',
        f"## Beat This base paths: {summary['beat_this_retained']['track_count']} retained references", '']
    lines.extend(comparison_markdown(summary['beat_this_retained']['cohorts']))
    lines.extend([f"## Two-model comparison: {bt['common_comparison_count']} reusable cases", '',
        f"Coverage: {bt['counts']}. The shared frontend incident documents {bt['documented_frontend_attempt_count']} attempts on {bt['documented_frontend_distinct_input_count']} distinct inputs; blocked coverage is not a count of separately observed crashes.", ''])
    lines.extend(comparison_markdown(summary['crossed']['cohorts']))
    lines.extend(['## Bounded historical experiments', '',
        'These prior experiments retain their original conditions and source reports; they are not newly measured full-corpus results.', ''])
    bounded = summary['bounded_findings']
    for name, value in bounded['light_full_song_comparison'].items():
        c = value['tempo_changes_100ms']; total = c['true_positives'] + c['false_negatives']
        lines.append(f"- Light {name}: event F1 20ms {_percent(value['event_f1_20ms'])}, 70ms {_percent(value['event_f1_70ms'])}; exact changes 100ms {c['true_positives']}/{total}.")
    prior = bounded['soft_prior_strong_light']; c = prior['changes_100ms']
    lines.append(f"- Strong soft prior on the conditional Light completion: 20ms {_percent(prior['event_20ms'])}; exact 100ms changes {c['true_positives']}/{c['true_positives'] + c['false_negatives']}. No default promoted.")
    for row in bounded['meter_change_diagnostic']:
        lines.append(f"- Historical {row['method']} bar grouping: {row['matched_changes_500ms']}/{row['reference_changes']} matched changes within 500ms, {row['predicted_changes']} proposed changes. Exact meter denominator remains unresolved.")
    lines.extend(['- Short-change reference-pulse fits remain oracle diagnostics; phase correction remains an experimental option.', '',
                  '## GTZAN supplementary feature evaluation', '',
                  f"{summary['gtzan']['track_count']} distinct feature/annotation pairs; no local waveform, exact tempo-map, or listening validation is implied.", '',
                  '| Method | F1 10ms | F1 20ms | F1 30ms | F1 70ms |', '|---|---:|---:|---:|---:|'])
    for method, values in summary['gtzan']['methods'].items():
        lines.append('| ' + method + ' | ' + ' | '.join(_percent(values['macro_f1'][t]) for t in TOLERANCES) + ' |')
    lines.extend(['', '## Owner reference review', ''])
    for row in summary['owner_reference_review']['items']:
        lines.append(f"- {row['id']}: excluded from primary accuracy scoring. {row['owner_observation_ko']}")
    lines.append(f"- Pending in the original reference-review queue: {len(summary['reference_review_queue'])}.")
    lines.extend(['', '## Execution and evidence limits', '',
        '- No inference was performed by this report builder. Runtime values in summary.json are timings recorded in the source runs, not new end-to-end performance measurements.',
        '- Current whole-process memory consumption was not measured by this reaggregation. Frozen model runs retain their own narrower memory evidence.',
        '- The base and crossed subsets cover different paths. Historical prior, phase, partial-region, and bar experiments are not proof of full-corpus support.',
        '- Per-track results: `per-track-method.csv`; rejected-reference diagnostics: `rejected-reference-diagnostics.csv`; normalized model coverage: `beat-transformer-coverage.json`.',
        '- No evaluated path establishes the complete automatic full-song tempo-plus-meter contract or a zero-human-correction song success rate.', '',
        '## Research history', ''])
    for stage in summary['research_history']:
        lines.append(f"- {stage['stage']}: {stage['finding']}")
    lines.extend(['', 'Current state and limitations only; no improvement priority or next development direction is selected.', ''])
    return '\n'.join(lines)


def write_rows(path, rows, fallback_fields=()):
    fields = list(rows[0]) if rows else list(fallback_fields)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit-root', type=Path, required=True)
    p.add_argument('--beat-this-report', type=Path, required=True)
    p.add_argument('--cross-report', type=Path, required=True)
    p.add_argument('--bt-manifest', type=Path, required=True)
    p.add_argument('--gtzan-report', type=Path, required=True)
    p.add_argument('--reference-decisions', type=Path)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    if args.output_dir.exists(): p.error('output directory must be new')
    inventory = json.loads((args.audit_root / 'inventory.json').read_text())
    reference_audit_path = args.audit_root / 'reference-audit.json'
    reference_audit = json.loads(reference_audit_path.read_text())
    if not reference_audit['complete'] or reference_audit['counts']['invalid']:
        p.error('reference audit incomplete or structurally invalid')
    catalog = json.loads((args.audit_root / 'catalog-scored-audio.json').read_text())
    references = load_references(catalog)
    decisions, rejected_ids = owner_review_decisions(args.reference_decisions, catalog)
    beat_this = json.loads(args.beat_this_report.read_text())
    cross = json.loads(args.cross_report.read_text())
    bt_manifest = json.loads(args.bt_manifest.read_text())
    gtzan = json.loads(args.gtzan_report.read_text())
    if not beat_this['complete'] or not cross['complete'] or not gtzan['complete']:
        p.error('input benchmark incomplete')
    if {row['id'] for row in beat_this['tracks']} != set(references):
        p.error('base report does not cover exactly the supplied catalog')
    for report in (beat_this, cross):
        for track in report['tracks']:
            record = next(row for row in catalog['tracks'] if row['id'] == track['id'])
            if track['reference_sha256'] != record['reference']['sha256']:
                p.error('prediction-report reference hash mismatch: ' + track['id'])
    base = base_rows(beat_this, catalog, references)
    crossed = crossed_rows(cross, catalog, references)
    rejected = [row for row in base + crossed if row['id'] in rejected_ids]
    retained_base = [row for row in base if row['id'] not in rejected_ids]
    retained_cross = [row for row in crossed if row['id'] not in rejected_ids]
    rows = retained_base + retained_cross
    experiments = existing_experiments()
    queue = [item for item in review_queue(experiments['reference_semantics']['data'], catalog) if item['id'] not in rejected_ids]
    incident_path = args.audit_root / 'beat-transformer-frontend-runtime-failure.json'
    coverage = normalize_bt_coverage(bt_manifest, json.loads(incident_path.read_text()))
    coverage.update({'manifest_path': str(args.bt_manifest), 'manifest_sha256': sha256(args.bt_manifest),
                     'runtime_failure_report': str(incident_path), 'runtime_failure_report_sha256': sha256(incident_path),
                     'common_comparison_count': len({row['id'] for row in retained_cross})})
    retained_count = len({row['id'] for row in retained_base})
    summary = {'schema_version': 2, 'kind': 'corrected_current_status_from_preserved_predictions',
        'correction_policy': {
            'prediction_values_changed': False, 'references_changed': False, 'model_inference_performed': False,
            'missing_capable_maps': 'All eligible reference changes count as false negatives; constant-reference failures retain failed map status.',
            'unsupported_methods': 'No tempo-map score for event-only methods; no downbeat score for candidate paths without downbeat output.',
            'retained_reference_meaning': 'Admitted under the declared reference policy, not universal human or millisecond certification.',
            'cohort_denominator': 'Each method retains every admitted track in its evaluation set. Capability and reference availability determine metric eligibility.',
            'original_results_preserved': True},
        'inventory': {**{k: inventory[k] for k in ('audio_asset_count', 'unique_audio_hash_count', 'score_admitted_audio_count',
            'prediction_only_audio_count', 'gtzan_annotation_count', 'gtzan_scored_feature_count', 'gtzan_excluded')},
            'retained_audio_reference_count': retained_count},
        'reference_audit': {'path': str(reference_audit_path), 'sha256': sha256(reference_audit_path),
            'counts': reference_audit['counts'], 'meaning': 'Structural checks, not musical semantic certification',
            'prediction_results_used': reference_audit['prediction_results_used']},
        'beat_this_supplied_reference_diagnostic': {'report_path': str(args.beat_this_report),
            'report_sha256': sha256(args.beat_this_report), 'track_count': len(beat_this['tracks']),
            'status': 'Includes owner-rejected references; not the primary aggregate',
            'cohorts': beat_this_summary(beat_this)},
        'beat_this_retained': {'track_count': retained_count, 'excluded_owner_rejected_ids': sorted(rejected_ids),
            'cohorts': aggregate(retained_base)},
        'beat_transformer_coverage': coverage,
        'crossed': {'report_path': str(args.cross_report), 'report_sha256': sha256(args.cross_report),
            'cohorts': aggregate(retained_cross)},
        'gtzan': gtzan_summary(gtzan), 'reference_review_queue': queue,
        'owner_reference_review': {'path': str(args.reference_decisions) if args.reference_decisions else None,
            'sha256': sha256(args.reference_decisions) if args.reference_decisions else None,
            'rejected_from_primary_scoring': sorted(rejected_ids), 'items': decisions.get('items', [])},
        'existing_experiments': {k: {'path': v['path'], 'sha256': v['sha256']} for k, v in experiments.items()},
        'bounded_findings': bounded_findings(experiments),
        'source_run_timing_seconds': {'meaning': 'Recorded in source runs; not measured during this reaggregation',
            'beat_this_base_inference_and_input_load_sum': sum(row['timing_seconds']['inference_and_input_load'] for row in beat_this['tracks']),
            'beat_this_base_total_sum': sum(row['timing_seconds']['total'] for row in beat_this['tracks']),
            'crossed_reconstruction_and_scoring_total_sum': sum(row['elapsed_seconds'] for row in cross['tracks'])},
        'artifact_row_counts': {'retained_base': len(retained_base), 'retained_crossed': len(retained_cross),
            'primary_csv': len(rows), 'rejected_reference_diagnostic_csv': len(rejected)},
        'measurement_limits': [
            'This reaggregation does not claim new full-corpus meter-free/candidate inference.',
            'Prior, phase, meter, and partial-region experiments retain historical scope; no missing run is treated as completed.',
            'Missing-map constant references have zero missed change events but remain failed output cases.',
            'No current whole-process memory or zero-human-correction song success rate is established.'],
        'research_history': [
            {'stage': 'Preserve legacy work and redefine the target', 'finding': 'Historical BPM and web-DAW code became regression evidence; the product target became automatic musical clocks for live multitrack preparation.'},
            {'stage': 'Freeze Beat This and source time', 'finding': 'Official final0 inference and canonical source timing were reproduced; circle exposed half-rate and delayed-change failures.'},
            {'stage': 'Separate pulses, tempo fitting, and bars', 'finding': 'Removing whole-song bar constraints fixed targeted false tempo changes, while exact meter-change recovery remained unresolved.'},
            {'stage': 'Expand public development evidence', 'finding': 'GTZAN and BabySlakh showed cohort- and tolerance-dependent gains.'},
            {'stage': 'Cross independent models and reconstructors', 'finding': 'Beat Transformer and candidate clocks delivered targeted gains and major regressions; no default was promoted.'},
            {'stage': 'Complete one song and test priors/phase', 'finding': 'Full-song clicks became reviewable; rate drift could improve while exact change timing or phase remained wrong.'},
            {'stage': 'Expand metronome and creator cohorts', 'finding': 'GMD, Walker, Forestry, and Daybreak separated missing candidates, wrong selection, and reference-origin uncertainty.'},
            {'stage': 'Prepare owner-reviewed production references', 'finding': 'Four NTM Master/map pairs were aligned and preserved; the broad base evaluation uses legacy DBN clock reconstruction.'},
            {'stage': 'Critically recheck the consolidated report', 'finding': 'Corrected missing-map denominators, unsupported downbeats, method identities, reference wording, coverage states and per-track output.'}],
        'target_distance': [
            {'capability': 'automatic beat evidence', 'status': 'implemented and measured; cohort and tolerance limitations remain'},
            {'capability': 'quarter-level selection', 'status': 'experimental candidates; errors and empty/partial outputs remain'},
            {'capability': 'exact tempo changes', 'status': 'measured on declared references with capable failures retained'},
            {'capability': 'automatic meter including changes', 'status': 'separate experimental 2/3/4-pulse grouping; integrated exact meter map unresolved'},
            {'capability': 'zero-human-correction success rate', 'status': 'not established; no validated full-map contract'}],
        'conclusion_boundary': 'Current status only; no improvement priority or next-step recommendation.'}
    args.output_dir.mkdir(parents=True)
    write_rows(args.output_dir / 'per-track-method.csv', rows)
    write_rows(args.output_dir / 'rejected-reference-diagnostics.csv', rejected, list(rows[0]))
    write_json(args.output_dir / 'summary.json', summary)
    write_json(args.output_dir / 'beat-transformer-coverage.json', coverage)
    write_json(args.output_dir / 'reference-review-queue.json', {'items': queue, 'maximum_batch_size': 3})
    write_json(args.output_dir / 'source-provenance.json', {'report_builder_sha256': sha256(__file__),
        'metric_adapter_sha256': sha256(Path(__file__).with_name('compare_clock_candidates.py')),
        'inputs': [{'path': str(path), 'sha256': sha256(path)} for path in
            (args.beat_this_report, args.cross_report, args.bt_manifest, args.gtzan_report, reference_audit_path)],
        'reference_hashes': {row['id']: row['reference']['sha256'] for row in catalog['tracks']}})
    (args.output_dir / 'STATUS.md').write_text(build_markdown(summary), encoding='utf-8')
    escaped = html.escape((args.output_dir / 'STATUS.md').read_text())
    (args.output_dir / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Joljak corrected status audit</title><style>body{font:15px/1.55 system-ui;max-width:1300px;margin:30px auto;padding:0 20px}pre{white-space:pre-wrap}</style><pre>' + escaped + '</pre>', encoding='utf-8')
    print(json.dumps({'output': str(args.output_dir), 'rows': len(rows), 'rejected_diagnostic_rows': len(rejected), 'review_items': len(queue)}, ensure_ascii=False))


if __name__ == '__main__': main()
