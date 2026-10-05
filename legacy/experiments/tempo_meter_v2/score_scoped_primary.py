"""Score an owner-reviewed metronomic span with an explicit click-free ending.

This is a separate experimental scorer. It preserves the frozen eleven-song
scorer and counts predicted beats/bars in the physical free ending as false
positives. The shared bar-map evaluator alone ignores those extra events.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import json
import math
from pathlib import Path

from .score_primary8 import (_meter_changes, _reviewed_paired_meter_fraction,
                             _source_geometry, _tempo_changes, digest,
                             duration_diagnostics, read_bound)
from experiments.analysis_legacy.music_map_contract import (
    interpolate_clock, prepare_map, render_bars)
from experiments.analysis_legacy.grid_metrics import nearest_event_diagnostics
from experiments.analysis_legacy.music_map_metrics import evaluate_music_maps


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'data/corpus/primary-references-v5/catalog.json'
QUALIFICATION = {'bar_timing': True, 'clock_timing': True,
                 'meter': True, 'grouping': True}


def reference_raw(accepted: dict, source: dict) -> dict:
    """Use the accepted source-time clock only within its reviewed span."""
    start, end = accepted['support_seconds'][0]
    bpm = accepted['tempo_events'][0]['bpm_quarter']
    quarter_count = (end-start)*bpm/60
    raw = {'schema_version': 1, 'source': source,
           'clock_knots': [{'pulse': 0., 'source_seconds': start},
                           {'pulse': quarter_count, 'source_seconds': end}],
           'quarters_per_pulse': {'numerator': 1, 'denominator': 1},
           'bar_anchor_pulse': 0.,
           'meter_events': [{'pulse': 0., 'numerator': 6, 'denominator': 8,
                             'grouping': [3, 3], 'bar_action': 'continue'}],
           'support_seconds': [[start, end]], 'analysis_condition': 'reference',
           'shared_origin_id': None}
    prepared = prepare_map(raw)
    bars = render_bars(prepared)
    if bars['status'] != 'rendered' or len(bars['bars']) != len(accepted['downbeats_seconds']):
        raise ValueError('accepted scoped bar geometry failed')
    if any(abs(item['start_seconds']-expected) > 1e-8
           for item, expected in zip(bars['bars'], accepted['downbeats_seconds'])):
        raise ValueError('accepted downbeat timing differs from rendered bars')
    if abs(bars['bar_events_seconds'][-1]-end) > 1e-8:
        raise ValueError('closing bar boundary differs from free-time start')
    return prepared


def emitted_quarters(prepared: dict | None) -> list[float]:
    """Physical click events use half-open support, excluding a closing boundary."""
    if prepared is None:
        return []
    knots = prepared['clock_knots']
    if len(knots) < 2:
        return []
    unit_declared = prepared['quarters_per_pulse']
    if unit_declared is None:
        return []
    unit = Fraction(unit_declared['numerator'], unit_declared['denominator'])
    first = math.ceil(knots[0]['pulse']*float(unit)-1e-9)
    last = math.floor(knots[-1]['pulse']*float(unit)+1e-9)
    duration = prepared['duration_seconds']
    result = []
    for quarter in range(first,last+1):
        pulse = quarter/float(unit)
        time = interpolate_clock(knots,pulse)
        if 0 <= time < duration and any(lo-1e-9 <= time < hi-1e-9
                                            for lo,hi in prepared['support_seconds']):
            result.append(time)
    return result


def emitted_bars(prepared: dict | None) -> list[float]:
    if prepared is None:
        return []
    rendered = render_bars(prepared)
    if rendered['status'] != 'rendered':
        return []
    duration = prepared['duration_seconds']
    return [t for t in rendered['bar_events_seconds']
            if 0 <= t < duration and any(lo-1e-9 <= t < hi-1e-9
                                       for lo,hi in prepared['support_seconds'])]



def quarter_coordinate_map(prepared: dict | None) -> dict | None:
    """Normalize a declared latent pulse to quarters for duration/change scores."""
    if prepared is None:
        return None
    unit = prepared['quarters_per_pulse']
    if unit is None:
        return None
    ratio = float(Fraction(unit['numerator'], unit['denominator']))
    if ratio == 1.:
        return prepared
    value = deepcopy(prepared)
    for knot in value['clock_knots']:
        knot['pulse'] *= ratio
    for event in value['meter_events'] or []:
        event['pulse'] *= ratio
    if value['bar_anchor_pulse'] is not None:
        value['bar_anchor_pulse'] *= ratio
    value['quarters_per_pulse'] = {'numerator': 1, 'denominator': 1}
    return prepare_map(value)


def score_scoped(accepted: dict, policy: dict, prediction: dict | None,
                 source: dict) -> dict:
    """Score the approved span and require abstention in the free ending."""
    reference = reference_raw(accepted, source)
    start, end = accepted['support_seconds'][0]
    free_start, physical_end = policy['free_time_seconds']
    if abs(end-free_start) > 1e-8 or abs(physical_end-source['sample_frames']/source['sample_rate']) > 1e-8:
        raise ValueError('policy and accepted reference time scopes disagree')
    ref_quarters = accepted['beats_seconds']
    ref_bars = accepted['downbeats_seconds']
    if len(emitted_quarters(reference)) != len(ref_quarters) or len(emitted_bars(reference)) != len(ref_bars):
        raise ValueError('reference audible-event parity failed')
    raw = prediction.get('map') if prediction else None
    prepared = None
    error = None
    if raw is not None:
        try:
            prepared = prepare_map(raw)
            identity = prepared['source']
            if any(identity[key] != source[key] for key in ('sha256','sample_rate','sample_frames')):
                raise ValueError('prediction source identity/sample clock mismatch')
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            prepared = None
            error = f'{type(exc).__name__}: {exc}'
    beats = emitted_quarters(prepared)
    bars = emitted_bars(prepared)
    beat_score = nearest_event_diagnostics(ref_quarters,beats,.07)
    bar_score = nearest_event_diagnostics(ref_bars,bars,.07)
    tail_beats = len([t for t in beats if free_start <= t < physical_end])
    tail_bars = len([t for t in bars if free_start <= t < physical_end])
    tail_map_seconds = (sum(max(0.,min(hi,physical_end)-max(lo,free_start))
                            for lo,hi in prepared['support_seconds']) if prepared else 0.)
    no_grid = prepared is not None and not (tail_beats or tail_bars or tail_map_seconds > 1e-9)
    boundary_error = (prepared['support_seconds'][-1][1]-end
                      if prepared and prepared['support_seconds'] else None)
    boundary_gate = (boundary_error is not None and abs(boundary_error) <= .5)

    normalized = quarter_coordinate_map(prepared)
    duration = duration_diagnostics(reference,normalized)
    map_score = (evaluate_music_maps(reference,prepared,reference_qualification=QUALIFICATION)
                 if prepared else None)
    meter = (_reviewed_paired_meter_fraction(map_score)
             if map_score and map_score['status'] == 'compared' else 0.)
    tempo_changes = [item for item in _tempo_changes(normalized,normalized['support_seconds'],
                                                     minimum_change_bpm=1e-6)
                     if start < item['source_seconds'] < end] if normalized else []
    meter_changes = [item for item in _meter_changes(prepared,prepared['support_seconds'])
                     if start < item['source_seconds'] < end] if prepared else []
    scores = {'quarter_bpm_within_1_reference_fraction': duration['quarter_bpm_within_1_reference_fraction'],
              'reviewed_meter_bar_fraction_70ms': meter,
              'quarter_beat_f1_70ms': beat_score['f1'],
              'bar_start_f1_70ms': bar_score['f1'],
              'tempo_change_no_false_positives': float(not tempo_changes),
              'meter_change_no_false_positives': float(not meter_changes)}
    gates = {key: value is not None and value >= .9 for key,value in scores.items()}
    gates['no_grid_in_free_ending'] = no_grid
    gates['grid_end_within_500ms'] = boundary_gate
    return {'status': 'scored' if prepared else 'prediction_map_unavailable',
            'prediction_error': error,
            'reference_support_seconds': [start,end],
            'free_time_seconds': [free_start,physical_end],
            'scores': scores, 'gates': gates, 'all_gates_pass': all(gates.values()),
            'beat_counts': {key:beat_score[key] for key in ('true_positives','false_positives','false_negatives')},
            'bar_counts': {key:bar_score[key] for key in ('true_positives','false_positives','false_negatives')},
            'free_tail_false_positives': {'quarter_beats': tail_beats,'bar_starts': tail_bars,
                                          'declared_map_support_seconds': tail_map_seconds},
            'grid_end_error_seconds': boundary_error,
            'false_tempo_changes_in_reference_scope': len(tempo_changes),
            'false_meter_changes_in_reference_scope': len(meter_changes),
            'shared_map_evaluator_bar_events_not_used_for_tail_false_positives': True,
            'reference_oracle_control': bool(prediction and prediction.get('reference_oracle_control'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prediction',type=Path,required=True,
                        help='saved source-only prediction JSON; no inference runs here')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    catalog = json.loads(CATALOG.read_text())
    if catalog.get('track_count') != 12 or catalog['tracks'][-1]['id'] != 'walker_he-will-hold-me-fast':
        raise ValueError('scoped primary v5 registry mismatch')
    track = catalog['tracks'][-1]
    source = _source_geometry(track)
    accepted = read_bound(track['accepted_tempo_map'])
    policy = read_bound(track['scoring_policy'])
    read_bound(track['owner_acceptance'])
    prediction = json.loads(args.prediction.read_text())
    result = score_scoped(accepted,policy,prediction,source)
    result['track_id'] = track['id']
    result['catalog_sha256'] = digest(CATALOG)
    result['accepted_map_sha256'] = track['accepted_tempo_map']['sha256']
    result['prediction_sha256'] = digest(args.prediction)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'track_id':result['track_id'],'all_gates_pass':result['all_gates_pass'],
                      'scores':result['scores'],'free_tail_false_positives':result['free_tail_false_positives']},indent=2))


if __name__ == '__main__':
    main()
