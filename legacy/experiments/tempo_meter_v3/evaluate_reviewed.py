"""Evaluate frozen predictions against the 20 reviewed recordings and auxiliary clip.

Inference is unchanged. New adapters preserve audio-relative project clocks and
distinguish unknown annotation margins from explicitly approved no-grid tails.
"""
import argparse
from bisect import bisect_right
from copy import deepcopy
import json
from pathlib import Path
import sys

from .probe_resources import digest
from .evaluate_batch import load_bound, references


def adapt_extra(accepted, source):
    """Adapt accepted clocks, without applying project offsets a second time."""
    from experiments.analysis_legacy.music_map_contract import prepare_map
    duration = source['sample_frames'] / source['sample_rate']
    tail = None
    unknown = 'quarter_bpm' in accepted
    if unknown:
        lo, hi = accepted['support_seconds']
        start = accepted['first_beat_source_seconds']
        bpm = accepted['quarter_bpm']
        knots = [dict(pulse=0., source_seconds=start),
                 dict(pulse=(hi-start)*bpm/60, source_seconds=hi)]
        m = accepted['meter']
        meters = [dict(pulse=0., numerator=m['numerator'], denominator=m['denominator'],
                       grouping=None, bar_action='continue')]
    else:
        scope = accepted.get('evaluation_scope')
        lo, hi = scope['grid_support_seconds'] if scope else accepted['reviewed_audio_span_seconds']
        tail = scope['no_grid_tail_seconds'] if scope else None
        tempos = accepted['tempo_events']
        knots = []
        for i, event in enumerate(tempos):
            t = event['master_seconds']
            if t > duration:
                break
            q = 0. if not knots else knots[-1]['pulse'] + (t-knots[-1]['source_seconds'])*tempos[i-1]['bpm_quarter']/60
            knots.append(dict(pulse=q, source_seconds=t))
        tempo_times = [e['master_seconds'] for e in tempos]
        def q_at(t):
            i = max(0, bisect_right(tempo_times, t)-1)
            return knots[i]['pulse'] + (t-knots[i]['source_seconds'])*tempos[i]['bpm_quarter']/60
        meters = [dict(pulse=q_at(e['master_seconds']), numerator=e['numerator'],
                       denominator=e['denominator'], grouping=e.get('grouping'), bar_action='continue')
                  for e in accepted['meter_events'] if e['master_seconds'] <= duration]
        knots.append(dict(pulse=q_at(duration), source_seconds=duration))
        # A positive first event leaves an unannotated opening, not invented beats.
        lo = max(lo, knots[0]['source_seconds'])
    raw = dict(schema_version=1, source=source, clock_knots=knots,
               quarters_per_pulse=dict(numerator=1, denominator=1),
               bar_anchor_pulse=meters[0]['pulse'], meter_events=meters,
               support_seconds=[[lo, hi]], analysis_condition='reference', shared_origin_id=None)
    return prepare_map(raw), tail, unknown


def clip_support(raw, spans):
    value = deepcopy(raw)
    value['support_seconds'] = [[max(a,c), min(b,d)] for a,b in raw['support_seconds']
                                for c,d in spans if min(b,d)>max(a,c)]
    return value


def score_extra(reference, prediction, tail, unknown):
    from experiments.tempo_meter_v2.score_generic13 import normal_score
    from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters, emitted_bars
    from experiments.analysis_legacy.music_map_contract import prepare_map
    from experiments.analysis_legacy.grid_metrics import nearest_event_diagnostics
    candidate = prepare_map(prediction['map'])
    scored = clip_support(candidate, reference['support_seconds']) if unknown else candidate
    result = normal_score(reference, {'map': scored}, emitted_quarters(reference), False)
    result['unknown_outside_reference_support_excluded'] = unknown
    result['reference_support_seconds'] = reference['support_seconds']
    if tail:
        start, end = tail
        beats, bars = emitted_quarters(candidate), emitted_bars(candidate)
        for values, expected, key, counts in (
            (beats, emitted_quarters(reference), 'declared_quarter_grid_f1_70ms', 'beat_counts'),
            (bars, emitted_bars(reference), 'bar_boundary_f1_70ms', 'bar_counts')):
            metric = nearest_event_diagnostics(expected, values, .07)
            result['scores'][key] = metric['f1']
            result['gates'][key] = metric['f1'] is not None and metric['f1'] >= .9
            result[counts] = {k:metric[k] for k in ('true_positives','false_positives','false_negatives')}
        extra_beats = sum(start <= t < end for t in beats)
        extra_bars = sum(start <= t < end for t in bars)
        extra_support = sum(max(0., min(b,end)-max(a,start)) for a,b in candidate['support_seconds'])
        boundary_error = candidate['support_seconds'][-1][1]-start if candidate['support_seconds'] else None
        result['free_tail_false_positives'] = dict(quarter_beats=extra_beats, bar_starts=extra_bars,
                                                  declared_map_support_seconds=extra_support)
        result['grid_end_error_seconds'] = boundary_error
        result['gates']['no_grid_in_free_ending'] = not (extra_beats or extra_bars or extra_support > 1e-9)
        result['gates']['grid_end_within_500ms'] = boundary_error is not None and abs(boundary_error) <= .5
        result['all_gates_pass'] = result['all_gates_pass'] and all(result['gates'].values())
    return result


def check_extra_parity(raw, accepted):
    from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters, emitted_bars
    from experiments.analysis_legacy.grid_metrics import nearest_event_diagnostics
    lo, hi = raw['support_seconds'][0]
    if 'quarter_bpm' in accepted:
        beats = accepted['beat_times_seconds']; bars = accepted['bar_starts_seconds']
    else:
        beats = [e['master_seconds'] for e in accepted['quarter_events']]
        bars = [e['master_seconds'] for e in accepted['quarter_events'] if e['accent']]
    receipt = {}
    for label, expected, rendered in [('beats', beats, emitted_quarters(raw)), ('bars', bars, emitted_bars(raw))]:
        expected = [t for t in expected if lo-1e-9 <= t < hi-1e-9]
        score = nearest_event_diagnostics(expected, rendered, 1e-6)
        if score['false_positives'] or score['false_negatives']:
            raise ValueError(f'accepted {label} parity failed: {score}')
        receipt[label] = dict(count=len(expected), tolerance_seconds=1e-6, passed=True)
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    root = Path.cwd(); sys.path.insert(0, str(root/'experiments/analysis_legacy'))
    from experiments.tempo_meter_v2.score_generic13 import normal_score
    from experiments.tempo_meter_v2.score_scoped_primary import score_scoped
    manifest = json.loads(a.manifest.read_text()); inventory = json.loads(a.inventory.read_text())
    rows = manifest['rows']; inv = {r['id']:r for r in inventory['rows']}
    if not manifest['complete'] or manifest['references_available_to_runner'] or set(inv) != {r['id'] for r in rows}:
        raise ValueError('complete frozen prediction/inventory identity required')
    if a.output.exists(): raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    catalog = json.loads((root/'data/corpus/primary-references-v6/catalog.json').read_text())
    old_ids = {r['id'] for r in catalog['tracks']}
    refs = references(root, [r for r in rows if r['id'] in old_ids or r['id']=='wage_war'])
    names = {r['id']:r['title'] for r in json.loads((root/'data/runs/reference-audit/ntm-three-owner-acceptance-20260930-v1/accepted-catalog-v1.json').read_text())['rows']}
    results = []
    for row in rows:
        ident = row['id']; entry = inv[ident]
        if row['source']['sha256'] != entry['audio_expected']: raise ValueError('audio identity mismatch')
        binding = dict(path=entry['reference'], sha256=entry['reference_expected'])
        accepted = load_bound(binding); pred = load_bound(row['selected']); parity = None
        if ident in refs:
            ref = refs[ident]; raw = ref['map']
            if ref['policy']:
                score = lambda v:score_scoped(ref['accepted'], ref['policy'], v, row['source'])
            else:
                # Preserve the canonical frozen-v6 source-start equivalence contract.
                eq = ident in old_ids and 'music_map' not in accepted
                score = lambda v:normal_score(raw, v, accepted['beats_seconds'], eq)
        else:
            raw, tail, unknown = adapt_extra(accepted, row['source'])
            parity = check_extra_parity(raw, accepted)
            score = lambda v:score_extra(raw, v, tail, unknown)
        oracle = score({'map':raw})
        if not oracle['all_gates_pass']: raise ValueError('reference self-score failed: '+ident)
        result = score(pred)
        (a.output/(ident+'-reference.json')).write_text(json.dumps(dict(map=raw, reference_binding=binding),indent=2)+'\n')
        results.append(dict(id=ident, title=names.get(ident,row['title']), role=entry['role'], score=result,
                            reference_self_score_passed=True, adapter_event_parity=parity,
                            reference_sha256=binding['sha256'], prediction_sha256=row['selected']['sha256'],
                            scope_note=entry.get('scope_note'), reference_support_seconds=raw['support_seconds']))
        print(ident, result['all_gates_pass'], json.dumps(result['scores']), flush=True)
    record = dict(scope='20 reviewed development recordings plus one auxiliary clip; not unseen',
                  prediction_manifest_sha256=digest(a.manifest), inventory_sha256=digest(a.inventory),
                  new_general_equivalence_policy_applied=False, rows=results)
    (a.output/'scores.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__': main()
