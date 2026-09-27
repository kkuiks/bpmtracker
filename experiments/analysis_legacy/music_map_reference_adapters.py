"""Read-only adapters for agreement with retained supplied quarter-clock maps.

This view is not musical-reference admission and is not an independent timing
certification. No waveform, model prediction, fitted offset, or BPM hint is used.
"""
from bisect import bisect_right
from copy import deepcopy
from fractions import Fraction
import argparse
import hashlib
import json
import math
from pathlib import Path

from music_map_contract import prepare_map, render_bars

VIEW = 'supplied_map_agreement'
NUMERICAL_PARITY_SECONDS = 1e-8
ALLOWED_KINDS = {
    'authored_midi_quarter_clock', 'gmd_metronome_midi_clock',
    'creator_supplied_performance_midi_map', 'owner_accepted_producer_tempo_map',
}
DEFAULT_CATALOG = Path('data/runs/status-audit/2026-09-25-v1/catalog-scored-audio.json')
DEFAULT_QUALIFIED = Path('data/runs/status-audit/2026-09-26-reanalysis-v1/reference-review/qualified-v2/references.json')
DEFAULT_INVENTORY = Path('data/runs/status-audit/2026-09-25-v1/inventory.json')


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be finite')
    return float(value)


def _rate(event):
    bpm = _finite(event.get('bpm_quarter'), 'bpm_quarter')
    if bpm <= 0:
        raise ValueError('bpm_quarter must be positive')
    if event.get('microseconds_per_quarter') is not None:
        microseconds = _finite(event['microseconds_per_quarter'], 'microseconds_per_quarter')
        if microseconds <= 0 or not math.isclose(bpm, 60e6 / microseconds, rel_tol=1e-9, abs_tol=1e-7):
            raise ValueError('declared quarter tempo fields disagree')
        return 1e6 / microseconds
    return bpm / 60


def _declared_clock(reference):
    events = reference.get('tempo_events')
    if not isinstance(events, list) or not events:
        raise ValueError('explicit quarter tempo events required')
    if reference.get('explicit_initial_tempo') is False:
        raise ValueError('initial tempo is a default, not explicit source metadata')
    tpq = reference.get('ticks_per_quarter')
    if tpq is not None and (isinstance(tpq, bool) or not isinstance(tpq, int) or tpq <= 0):
        raise ValueError('positive integer ticks_per_quarter required')
    times, quarters, rates = [], [], []
    for event in events:
        seconds = _finite(event.get('time_seconds'), 'tempo source time')
        rate = _rate(event)
        if times and seconds <= times[-1]:
            raise ValueError('tempo event times must strictly increase')
        quarter = 0. if not times else quarters[-1] + (seconds - times[-1]) * rates[-1]
        if tpq is not None:
            tick = event.get('tick')
            if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
                raise ValueError('nonnegative explicit tempo tick required')
            declared = float(Fraction(tick, tpq))
            if not times and declared != 0:
                raise ValueError('initial authored quarter anchor must be explicit tick zero')
            if abs(declared - quarter) / rate > NUMERICAL_PARITY_SECONDS:
                raise ValueError('tempo ticks and source seconds disagree; no alignment fitted')
            quarter = declared
        elif reference.get('kind') != 'owner_accepted_producer_tempo_map':
            raise ValueError('quarter clock needs MIDI ticks or the accepted producer-map anchor')
        times.append(seconds); quarters.append(quarter); rates.append(rate)
    origin = reference.get('source_origin_shift_seconds')
    if origin is None or abs(_finite(origin, 'source_origin_shift_seconds') - times[0]) > NUMERICAL_PARITY_SECONDS:
        raise ValueError('initial tempo and declared source-map origin disagree')

    def quarter_at(seconds):
        seconds = _finite(seconds, 'source time')
        if seconds < times[0]:
            raise ValueError('event precedes declared clock anchor')
        index = bisect_right(times, seconds) - 1
        return quarters[index] + (seconds - times[index]) * rates[index]

    def event_quarter(event):
        seconds = _finite(event.get('time_seconds'), 'meter source time')
        quarter = quarter_at(seconds)
        if tpq is not None:
            tick = event.get('tick')
            if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
                raise ValueError('nonnegative explicit meter tick required')
            declared = float(Fraction(tick, tpq))
            rate = rates[bisect_right(times, seconds) - 1]
            if abs(declared - quarter) / rate > NUMERICAL_PARITY_SECONDS:
                raise ValueError('meter ticks and source seconds disagree; no alignment fitted')
            return declared
        return quarter

    return times, quarters, quarter_at, event_quarter


def compare_bar_parity(rendered, reference_downbeats, support, *, tolerance=NUMERICAL_PARITY_SECONDS):
    """Compare two unchanged event lists; no search, shift, or alternate labels."""
    if rendered.get('status') != 'rendered':
        return {'status': 'not_evaluated_renderer_unsupported', 'renderer_status': rendered.get('status'),
                'alignment_applied': False, 'tolerance_seconds': tolerance}
    if reference_downbeats is None:
        return {'status': 'unavailable_reference_bar_events', 'alignment_applied': False}
    lo, hi = support
    def inside(value):
        # Only floating-point boundary representation, not a musical tolerance:
        # interpolation can produce 3.9999999999999996 for an exact 4s boundary.
        lower_ulp = 8 * max(math.ulp(float(value)), math.ulp(float(lo)))
        upper_ulp = 8 * max(math.ulp(float(value)), math.ulp(float(hi)))
        return ((value >= lo or lo - value <= lower_ulp) and
                (value <= hi or value - hi <= upper_ulp))
    expected = [float(t) for t in reference_downbeats if inside(t)]
    actual = [float(t) for t in rendered['bar_events_seconds'] if inside(t)]
    same_count = len(expected) == len(actual)
    errors = [abs(a - b) for a, b in zip(expected, actual)] if same_count else []
    passed = same_count and all(error <= tolerance for error in errors)
    return {'status': 'passed' if passed else 'mismatch', 'reference_count': len(expected),
            'adapted_count': len(actual), 'maximum_absolute_error_seconds': max(errors, default=None),
            'tolerance_seconds': tolerance, 'alignment_applied': False,
            'support_boundary_comparison': '8_ulp_numerical_inclusion_only; original_support_and_events_unchanged',
            'reference_first_seconds': expected[:3], 'adapted_first_seconds': actual[:3],
            'reference_last_seconds': expected[-3:], 'adapted_last_seconds': actual[-3:]}


def adapt_supplied_reference(reference, track, *, retained_for_primary_scores=False,
                             reference_binding=None, admission_evidence=None):
    """Return a declaration view or an explicit excluded/unsupported result.

    ``track`` is an existing audio catalog record with its preserved sample
    clock. Eligibility must be supplied from the owner-qualified audit ledger;
    the presence of tempo/meter fields alone never admits a reference.
    """
    base = {'id': track.get('id'), 'view': VIEW, 'status': 'excluded',
            'evidence_scope': 'agreement_with_declared_supplied_map_not_independent_musical_or_sample_truth',
            'map': None, 'reference_qualification': None,
            'provenance': {'reference': deepcopy(reference_binding or track.get('reference')),
                'source': deepcopy(track.get('input')), 'reference_tier': track.get('reference_tier'),
                'admission_evidence': deepcopy(admission_evidence),
                'retained_for_existing_primary_scores': retained_for_primary_scores,
                'reference_modified': False, 'prediction_used': False, 'alignment_fitted': False}}
    if not retained_for_primary_scores:
        return {**base, 'reason': 'reference_not_retained_or_source_only; preserve_owner_rejection_and_pending_status'}
    if reference.get('kind') not in ALLOWED_KINDS:
        return {**base, 'reason': 'not_an_admitted_authored_quarter_clock; click_only_and_provisional_units_excluded'}
    if not reference.get('meter_events') or reference.get('downbeats_seconds') is None:
        return {**base, 'reason': 'complete_declared_meter_and_bar_events_required_for_this_view'}
    try:
        source = track.get('input') or {}
        if source.get('kind') != 'audio' or reference.get('source_audio_sha256') != source.get('sha256'):
            raise ValueError('reference and catalog source audio identity disagree')
        support = reference.get('evaluation_support_seconds')
        if not isinstance(support, list) or len(support) != 2:
            raise ValueError('original reference support pair required')
        lo, hi = (_finite(x, 'support endpoint') for x in support)
        times, quarters, quarter_at, event_quarter = _declared_clock(reference)
        if not times[0] <= lo < hi:
            raise ValueError('reference support is outside original clock anchor')
        knots = [{'pulse': q, 'source_seconds': t} for t, q in zip(times, quarters) if t <= hi]
        if knots[-1]['source_seconds'] < hi:
            knots.append({'pulse': quarter_at(hi), 'source_seconds': hi})
        if len(knots) < 2:
            raise ValueError('reference support does not contain a positive clock domain')
        meters = []
        for event in reference['meter_events']:
            # A provisional pickup-reset candidate is not a certified restart.
            # Existing explicit bar_action is honored if a source actually has it.
            meters.append({'pulse': event_quarter(event), 'numerator': event['numerator'],
                'denominator': event['denominator'], 'grouping': deepcopy(event.get('grouping')),
                'bar_action': event.get('bar_action', 'unspecified')})
        if not math.isclose(meters[0]['pulse'], 0., rel_tol=0, abs_tol=1e-9):
            raise ValueError('initial bar anchor is not explicit source-map quarter zero')
        raw = {'schema_version': 1, 'view': VIEW,
            'source': {'path': source.get('path'), 'sha256': source.get('sha256'),
                       'sample_rate': track.get('sample_rate'), 'sample_frames': track.get('sample_frames')},
            'clock_knots': knots, 'quarters_per_pulse': {'numerator': 1, 'denominator': 1},
            'bar_anchor_pulse': meters[0]['pulse'], 'shared_origin_id': None,
            'meter_events': meters, 'support_seconds': [deepcopy(support)], 'analysis_condition': 'reference'}
        adapted = prepare_map(raw)
        qualification = {'clock_timing': True, 'bar_timing': True, 'meter': True,
                         'grouping': all(event['grouping'] is not None for event in meters)}
        # Qualification here is limited to declared-map agreement. An unsupported
        # renderer does not revoke or strengthen the reference's original evidence.
        adapted['reference_qualification'] = qualification
        adapted['evidence_scope'] = base['evidence_scope']
        provenance = {**base['provenance'], 'reference_kind': reference['kind'],
            'unit_basis': 'explicit MIDI ticks_per_quarter and bpm_quarter' if reference.get('ticks_per_quarter') else 'owner-accepted normalized producer MIDI/RPP quarter-clock metadata',
            'anchor_basis': {'quarter': 0, 'source_seconds': times[0],
                'source_origin_shift_seconds': reference.get('source_origin_shift_seconds'),
                'meaning': 'declared source-map anchor, not a shared semantic music origin'},
            'support_policy': 'exact original evaluation_support_seconds; no tail extension',
            'terminal_knot_basis': 'evaluate explicitly active step tempo at the original support end; no observed-click fitting',
            'original_tempo_events': deepcopy(reference['tempo_events']),
            'original_meter_events': deepcopy(reference['meter_events']),
            'original_bar_reset_candidates': deepcopy(reference.get('bar_reset_candidates', [])),
            'original_quarter_indices_present': reference.get('quarter_indices') is not None,
            'annotation_caveat': reference.get('annotation_caveat'),
            'historical_absolute_timing_verified': False if reference['kind'] == 'owner_accepted_producer_tempo_map' else None,
            'original_recording_click_error_bound_inferred': False}
        rendered = render_bars(adapted)
        parity = compare_bar_parity(rendered, reference['downbeats_seconds'], support)
        status = 'adapted' if rendered['status'] == 'rendered' else 'unsupported'
        reason = None if status == 'adapted' else rendered.get('unsupported_reason')
        if parity['status'] == 'mismatch':
            status, reason = 'adapter_parity_failed', 'declared geometry does not reproduce saved bar events; no reference repair applied'
        return {**base, 'status': status, 'reason': reason, 'map': adapted,
            'reference_qualification': qualification, 'provenance': provenance,
            'render_status': rendered['status'], 'unsupported_event': rendered.get('unsupported_event'),
            'bar_parity': parity}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        return {**base, 'status': 'unsupported', 'reason': str(exc)}


def _read_json(path):
    return json.loads(Path(path).read_text())


def _binding(path, expected=None):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f'bound artifact changed: {path}')
    return {'path': str(path), 'sha256': digest}


def build_reference_views(output, *, catalog_path=DEFAULT_CATALOG,
                          qualified_path=DEFAULT_QUALIFIED, inventory_path=DEFAULT_INVENTORY):
    """Generate new view files; refuses to overwrite an existing evidence run."""
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'output directory must be empty: {output}')
    catalog, qualified, inventory = (_read_json(p) for p in (catalog_path, qualified_path, inventory_path))
    evidence = {'catalog': _binding(catalog_path), 'qualified_references': _binding(qualified_path),
                'inventory': _binding(inventory_path), 'adapter': _binding(__file__),
                'contract': _binding(Path(__file__).with_name('music_map_contract.py')),
                'musical_units': _binding(Path(__file__).with_name('musical_units.py')),
                'owner_decisions': _binding(qualified['owner_decisions']['path'], qualified['owner_decisions']['sha256'])}
    if evidence['catalog']['sha256'] != qualified['catalog']['sha256']:
        raise ValueError('qualified audit refers to a different catalog')
    qualified_by_id = {t['id']: t for t in qualified['tracks']}
    rows = []
    for track in catalog['tracks']:
        item = qualified_by_id[track['id']]
        if track['input']['sha256'] != item['audio']['sha256']:
            raise ValueError('qualified source identity differs from catalog')
        geometry = item['audio_geometry']
        if (track['sample_rate'], track['sample_frames']) != (geometry['sample_rate'], geometry['frames']):
            raise ValueError('qualified source sample clock differs from catalog')
        reference_binding = _binding(track['reference']['path'], track['reference']['sha256'])
        if reference_binding['sha256'] != item['reference']['sha256']:
            raise ValueError('qualified reference differs from catalog')
        reference = _read_json(track['reference']['path'])
        result = adapt_supplied_reference(reference, track,
            retained_for_primary_scores=item['retained_for_primary_scores'],
            reference_binding=reference_binding,
            admission_evidence={'qualified_references': evidence['qualified_references'],
                                'owner_decision': item.get('owner_decision')})
        if reference.get('acceptance_path'):
            result['provenance']['owner_acceptance'] = _binding(reference['acceptance_path'], reference['acceptance_sha256'])
            acceptance = _read_json(reference['acceptance_path'])
            result['provenance']['accepted_map'] = _binding(acceptance['aligned_map']['path'], acceptance['aligned_map']['sha256'])
            result['provenance']['historical_strict_flags'] = {key: acceptance.get(key) for key in ('absolute_timing_verified', 'target_evaluation_eligible')}
            result['provenance']['accepted_offset_seconds'] = acceptance['offset_seconds']
        rows.append(result)
    present = {row['id'] for row in rows}
    for item in inventory['audio']:
        if item['id'] not in present:
            rows.append({'id': item['id'], 'status': 'excluded', 'view': VIEW, 'map': None,
                'reason': 'source_only_pending_or_missing_qualified_reference',
                'provenance': {'source': {'path': item['input_path'], 'sha256': item['input_sha256']},
                               'reference_tier': item['reference_tier'], 'reference_modified': False}})
    output.mkdir(parents=True, exist_ok=True)
    for row in rows:
        (output / f"{row['id']}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n')
    from collections import Counter
    report = {'view': VIEW, 'evidence_scope': 'supplied_map_agreement_not_musical_truth_promotion',
        'evidence': evidence, 'source_audio_rehashed': False,
        'source_identity_policy': 'Preserved source hash and decoded sample clock cross-checked between catalog and qualified audit.',
        'counts': dict(Counter(row['status'] for row in rows)), 'row_count': len(rows),
        'rows': [{'id': row['id'], 'status': row['status'], 'reason': row.get('reason'),
                  'render_status': row.get('render_status'), 'bar_parity': row.get('bar_parity'),
                  'view_file': str(output / f"{row['id']}.json")} for row in rows]}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG)
    parser.add_argument('--qualified', type=Path, default=DEFAULT_QUALIFIED)
    parser.add_argument('--inventory', type=Path, default=DEFAULT_INVENTORY)
    args = parser.parse_args(argv)
    report = build_reference_views(args.output, catalog_path=args.catalog,
        qualified_path=args.qualified, inventory_path=args.inventory)
    print(json.dumps({'row_count': report['row_count'], 'counts': report['counts']}, indent=2))


if __name__ == '__main__':
    main()
