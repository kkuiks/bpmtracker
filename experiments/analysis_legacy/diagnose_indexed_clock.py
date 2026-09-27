"""C1 ideal timing-and-identity control for the unchanged current v1 fitter.

Both pulse times and quarter identities are reference supplied. These outputs
are oracle diagnostics, never automatic accuracy or deployable predictions.
"""
from collections import Counter
from copy import deepcopy
import argparse
import hashlib
import inspect
import os
import sys
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import resource
import time

import numpy as np

from ablate_clock_inputs import fit_prediction
from clock_candidates import tempo_events
from compare_clock_candidates import evaluate_tempo_map
from fit_clock import clock_time, fit_clock
from grid_metrics import indexed_grid_metrics
from music_map_contract import interpolate_clock
from music_map_reference_adapters import adapt_supplied_reference

COHORT = Path('data/runs/music-map-contract/2026-09-26-v1/prediction-capabilities.json')
CATALOG = Path('data/runs/status-audit/2026-09-25-v1/catalog-scored-audio.json')
QUALIFIED = Path('data/runs/status-audit/2026-09-26-reanalysis-v1/reference-review/qualified-v2/references.json')
FROZEN_V1 = {'entry_point': 'ablate_clock_inputs.fit_prediction',
    'min_events': 8, 'max_events': 2000, 'max_initial_segments': 12,
    'split_penalty_seconds_squared': .01, 'continuous_model_selection': False,
    'downbeat_input': [], 'meter_scoring': False,
    'settings_basis': 'unchanged run_crossed_benchmark.reconstruct_model -> ablate_clock_inputs.fit_prediction -> fit_clock defaults',
    'no_v2_no_tuning_no_budget_workaround': True}
SOURCES = ('diagnose_indexed_clock.py', 'ablate_clock_inputs.py', 'fit_clock.py',
    'run_beat_this.py', 'run_crossed_benchmark.py', 'clock_candidates.py',
    'compare_clock_candidates.py', 'grid_metrics.py', 'music_map_reference_adapters.py',
    'music_map_contract.py', 'musical_units.py')


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def binding(path, expected=None):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and digest != expected:
        raise ValueError(f'bound input changed: {path}')
    return {'path': str(path), 'sha256': digest}


def prepare_ideal_input(reference, track, *, retained_for_primary_scores):
    """Bind supplied pulse times to authored quarter identities, never predictions."""
    view = adapt_supplied_reference(reference, track,
        retained_for_primary_scores=retained_for_primary_scores)
    if view['map'] is None:
        return {'status': 'unavailable', 'reason': view['reason'], 'input': None,
                'reference_view_status': view['status']}
    clock_map = view['map']
    lo, hi = reference['evaluation_support_seconds']
    full_times = np.asarray(reference.get('beats_seconds', []), dtype=float)
    if (full_times.ndim != 1 or not np.isfinite(full_times).all() or
            np.any(np.diff(full_times) <= 0)):
        raise ValueError('reference quarter times must be finite and strictly increasing')
    keep = (full_times >= lo) & (full_times <= hi)
    times = full_times[keep]
    if not len(times):
        return {'status': 'unavailable', 'reason': 'no_reference_quarters_inside_declared_support', 'input': None}
    supplied = reference.get('quarter_indices')
    if supplied is not None:
        all_quarters = np.asarray(supplied, dtype=float)
        if all_quarters.shape != full_times.shape:
            raise ValueError('supplied quarter identity count differs from reference times')
        quarters = all_quarters[keep]
        identity_basis = 'explicit reference quarter_indices; validated against supplied continuous clock'
    else:
        inferred = np.array([interpolate_clock(clock_map['clock_knots'], float(t), inverse=True) for t in times])
        quarters = np.rint(inferred)
        if np.max(abs(inferred - quarters)) > 1e-7:
            raise ValueError('declared quarter events are not on their authored integer-quarter lattice')
        identity_basis = 'MIDI quarter coordinates from explicit authored tick/tempo map; only numerical integer recovery, no prediction matching'
    if (not np.isfinite(quarters).all() or np.any(np.diff(quarters) < 1) or
            np.any(quarters != np.rint(quarters))):
        raise ValueError('C1 requires explicit increasing integer quarter identities')
    expected = np.array([interpolate_clock(clock_map['clock_knots'], float(q)) for q in quarters])
    discrepancy = float(np.max(abs(expected - times)))
    if discrepancy > 1e-8:
        raise ValueError('reference times disagree with exact supplied quarter clock')
    return {'status': 'ready', 'reason': None, 'reference_view_status': view['status'],
        'input': {'times_seconds': times.tolist(), 'absolute_quarter_indices': quarters.tolist(),
            'relative_quarter_indices': (quarters - quarters[0]).tolist(),
            'absolute_quarter_origin': float(quarters[0]), 'identity_basis': identity_basis,
            'reference_clock_map': clock_map, 'reference_clock_parity_max_seconds': discrepancy,
            'original_reference_support_seconds': list(reference['evaluation_support_seconds']),
            'source_duration_seconds': clock_map['duration_seconds'],
            'oracle_input': True, 'substitutions': ['reference_quarter_timing', 'reference_quarter_identity'],
            'source_time_shift_applied': False,
            'index_rebasing': 'subtract known first absolute quarter index only for v1 API; same absolute source seconds retained',
            'bar_interpretation_used': False, 'bar_and_grouping_scores': 'withheld_C1_is_clock_only',
            'reference_view_scope': view['evidence_scope'], 'reference_qualification': view['reference_qualification']}}


def _absolute_linear_mean(a, b):
    if a * b >= 0:
        return (abs(a) + abs(b)) / 2
    return (a * a + b * b) / (2 * (abs(a) + abs(b)))


def _fraction_within(a, b, tolerance):
    if a == b:
        return float(abs(a) <= tolerance)
    roots = sorted(((-tolerance - a) / (b - a), (tolerance - a) / (b - a)))
    return max(0., min(1., roots[1]) - max(0., roots[0]))


def continuous_clock_metrics(ideal, proposal):
    """Exact piecewise-linear comparison on shared, known quarter coordinates.

    Absolute-error maxima occur at the union of truth/prediction knots. Time
    weights follow the reference clock, with no sampling grid or time fitting.
    """
    support = ideal['original_reference_support_seconds']
    full_duration = support[1] - support[0]
    base = {'scope': 'oracle_shared_quarter_coordinate; supplied_map_agreement_only',
            'alignment_applied': False, 'reference_support_seconds': support,
            'source_duration_seconds': ideal['source_duration_seconds'],
            'reference_support_fraction_of_audio': full_duration / ideal['source_duration_seconds']}
    if proposal is None:
        return {**base, 'status': 'no_clock_output', 'covered_reference_duration_seconds': 0.,
                'reference_support_coverage_fraction': 0., 'uncovered_reference_duration_seconds': full_duration,
                'maximum_absolute_error_seconds': None}
    truth = ideal['reference_clock_map']['clock_knots']
    origin = ideal['absolute_quarter_origin']
    lo, hi = proposal['pulse_index_span']
    lower = max(float(lo) + origin, interpolate_clock(truth, support[0], inverse=True))
    upper = min(float(hi) + origin, interpolate_clock(truth, support[1], inverse=True))
    if not upper > lower:
        return {**base, 'status': 'no_shared_clock_domain', 'reference_support_coverage_fraction': 0.,
                'covered_reference_duration_seconds': 0., 'uncovered_reference_duration_seconds': full_duration,
                'maximum_absolute_error_seconds': None}
    points = sorted({lower, upper,
        *[float(k['pulse']) for k in truth if lower < k['pulse'] < upper],
        *[float(q) + origin for q in proposal['knot_pulse_indices'] if lower < float(q) + origin < upper]})
    quarters = np.asarray(points)
    expected = np.array([interpolate_clock(truth, float(q)) for q in quarters])
    actual = clock_time(quarters - origin, proposal['knot_pulse_indices'], proposal['coefficients'])
    errors = actual - expected
    if not np.isfinite(actual).all() or np.any(np.diff(actual) <= 0):
        raise ValueError('proposal is not a finite monotonic clock over declared shared coordinates')
    intervals = []
    weighted_abs = weighted_square = weighted_bpm = 0.
    thresholds = {.01: 0., .02: 0., .03: 0., .07: 0.}
    bpm_thresholds = {.1: 0., .5: 0., 1.: 0.}
    for i, (a, b) in enumerate(zip(points, points[1:])):
        duration = float(expected[i+1] - expected[i])
        e0, e1 = float(errors[i]), float(errors[i+1])
        weighted_abs += duration * _absolute_linear_mean(e0, e1)
        weighted_square += duration * (e0*e0 + e0*e1 + e1*e1) / 3
        truth_bpm = 60 * (b-a) / duration
        predicted_bpm = 60 * (b-a) / float(actual[i+1] - actual[i])
        bpm_error = abs(predicted_bpm - truth_bpm)
        weighted_bpm += duration * bpm_error
        for threshold in thresholds:
            thresholds[threshold] += duration * _fraction_within(e0, e1, threshold)
        for threshold in bpm_thresholds:
            bpm_thresholds[threshold] += duration * float(bpm_error <= threshold)
        intervals.append({'absolute_quarter_span': [a, b], 'reference_seconds': expected[i:i+2].tolist(),
            'predicted_seconds': actual[i:i+2].tolist(), 'signed_errors_seconds': [e0, e1],
            'reference_bpm_quarter': truth_bpm, 'predicted_bpm_quarter': predicted_bpm,
            'absolute_bpm_error': bpm_error})
    duration = float(expected[-1] - expected[0])
    return {**base, 'status': 'scored_on_exact_piecewise_union',
        'absolute_quarter_domain': [lower, upper], 'reference_time_domain_seconds': [float(expected[0]), float(expected[-1])],
        'predicted_time_domain_seconds': [float(actual[0]), float(actual[-1])],
        'covered_reference_duration_seconds': duration,
        'reference_support_coverage_fraction': min(1., duration / full_duration),
        'uncovered_reference_duration_seconds': max(0., full_duration - duration),
        'covered_reference_fraction_of_audio': duration / ideal['source_duration_seconds'],
        'maximum_absolute_error_seconds': float(np.max(abs(errors))),
        'reference_time_weighted_mae_seconds': weighted_abs / duration,
        'reference_time_weighted_rmse_seconds': math.sqrt(max(0., weighted_square / duration)),
        'first_signed_error_seconds': float(errors[0]), 'last_signed_error_seconds': float(errors[-1]),
        'last_minus_first_error_seconds': float(errors[-1] - errors[0]),
        'within_time_error_fraction': {str(k): v / duration for k, v in thresholds.items()},
        'reference_time_weighted_mae_bpm': weighted_bpm / duration,
        'within_absolute_bpm_fraction': {str(k): v / duration for k, v in bpm_thresholds.items()},
        'knot_union_count': len(points), 'intervals': intervals,
        'outside_physical_source_endpoint_seconds': [float(t) for t in (actual[0], actual[-1]) if t < 0 or t > ideal['source_duration_seconds']],
        'meter_grouping_and_real_recording_clock_certified': False}


def score_ideal_clock(reference, ideal, proposal):
    continuous = continuous_clock_metrics(ideal, proposal)
    changes = tempo_events(proposal) if proposal else None
    output = {'continuous_clock': continuous,
        'tempo_changes_original_reference_support': evaluate_tempo_map(reference, changes, tempo_map_supported=True),
        'bar_and_meter': {'status': 'withheld_clock_only_control'},
        'automatic_accuracy_claim': False}
    if proposal is None:
        output['indexed_quarters'] = {'status': 'no_clock_output; fallback_reference_events_are_not_map_success'}
        return output
    absolute = ideal['absolute_quarter_indices']
    predicted = clock_time(ideal['relative_quarter_indices'], proposal['knot_pulse_indices'], proposal['coefficients'])
    truth_events = [{'index': q, 'time_seconds': t} for q, t in zip(absolute, ideal['times_seconds'])]
    predicted_events = [{'index': q, 'time_seconds': float(t)} for q, t in zip(absolute, predicted)]
    output['indexed_quarters'] = {str(t): indexed_grid_metrics(truth_events, predicted_events,
        origin_status='shared_explicit_origin', time_tolerance_seconds=t) for t in (.01, .02, .03, .07)}
    output['indexed_origin_scope'] = 'known only because C1 supplies reference timing and identity; no origin inference claim'
    return output


def run_case(reference, ideal):
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    proposal, fallback, status = fit_prediction({'beats_seconds': ideal['times_seconds'], 'downbeats_seconds': []},
                                               pulse_indices=ideal['relative_quarter_indices'])
    elapsed = time.perf_counter() - started
    return {'status': 'clock_generated' if proposal is not None else 'no_clock_output',
        'fitter_status': status, 'proposal': proposal, 'returned_event_prediction': fallback,
        'fallback_copies_reference_input': proposal is None,
        'fit_seconds': elapsed, 'fit_started_at_utc': started_utc, 'input_is_reference_oracle': True, 'automatic_accuracy_claim': False,
        'actual_fitter_parameters': proposal['parameters'] if proposal else None}


def run(output, *, cohort_path=COHORT, catalog_path=CATALOG, qualified_path=QUALIFIED):
    output = Path(output)
    if output.exists():
        raise FileExistsError('C1 output must be a new directory; original snapshots are preserved')
    signature = inspect.signature(fit_clock)
    if {key: signature.parameters[key].default for key in ('min_events', 'split_penalty', 'continuous_selection')} != {'min_events': 8, 'split_penalty': .01, 'continuous_selection': False}:
        raise ValueError('frozen v1 fitter defaults changed; no automatic setting workaround')
    cohort_doc, catalog_doc, qualified_doc = (read(p) for p in (cohort_path, catalog_path, qualified_path))
    cohort = cohort_doc['proposed_fixed_diagnostic_cohort']
    if len(cohort) != 15 or Counter(r['role'] for r in cohort) != {'core': 12, 'guard': 3}:
        raise ValueError('expected the frozen 12-core/3-guard diagnostic cohort')
    catalog = {r['id']: r for r in catalog_doc['tracks']}
    qualified = {r['id']: r for r in qualified_doc['tracks']}
    prepared = []
    for selected in cohort:
        track_id = selected['id']; track = catalog[track_id]; q = qualified[track_id]
        ref_binding = binding(track['reference']['path'], track['reference']['sha256'])
        if ref_binding['sha256'] != selected['reference']['sha256'] or ref_binding['sha256'] != q['reference']['sha256']:
            raise ValueError('cohort reference differs from qualified/catalog identity')
        if selected['reference_record_sha256'] != binding(qualified_path)['sha256']:
            raise ValueError('cohort qualified-reference ledger changed')
        reference = read(ref_binding['path'])
        ideal = prepare_ideal_input(reference, track, retained_for_primary_scores=q['retained_for_primary_scores'])
        prepared.append({'id': track_id, 'role': selected['role'], 'reason_selected': selected['reason_selected_before_stage2_execution'],
            'source': track['input'], 'sample_rate': track['sample_rate'], 'sample_frames': track['sample_frames'],
            'reference': ref_binding, 'reference_tier': q['reference_tier'],
            'existing_reference_caveats': selected.get('reference_caveats'), 'prepared': ideal})
    output.mkdir(parents=True)
    for case in prepared:
        save(output / 'inputs' / f"{case['id']}.json", case)
    manifest = {'schema_version': 1, 'control': 'C1_ideal_reference_timing_and_quarter_identity',
        'phase': 'frozen_before_any_real_cohort_fitter_execution', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'runtime_environment': {'python': sys.version, 'numpy': np.__version__, 'OPENBLAS_NUM_THREADS': os.environ.get('OPENBLAS_NUM_THREADS'), 'OMP_NUM_THREADS': os.environ.get('OMP_NUM_THREADS')},
        'diagnostic_only': True, 'automatic_accuracy_claim': False,
        'fitter': FROZEN_V1, 'cohort': binding(cohort_path), 'catalog': binding(catalog_path),
        'qualified_references': binding(qualified_path), 'source_audio_rehashed': False,
        'source_hashes': {name: binding(Path(__file__).with_name(name)) for name in SOURCES},
        'inputs': [binding(output / 'inputs' / f"{case['id']}.json") for case in prepared],
        'cohort_rows': [{'id': case['id'], 'role': case['role'], 'status': case['prepared']['status']} for case in prepared],
        'policy': 'Exact supplied step-clock and quarter identities replace both acoustic timing and indexing. No locked reference change points, no bar input, no guide BPM, no refit of alignment, no extended support.'}
    save(output / 'manifest.json', manifest)
    report = {'manifest': binding(output / 'manifest.json'), 'complete': False,
              'automatic_accuracy_claim': False, 'rows': []}
    save(output / 'report.json', report)
    for case in prepared:
        track_id = case['id']; ready = case['prepared']
        row = {'id': track_id, 'role': case['role'], 'reference_tier': case['reference_tier'],
               'input': binding(output / 'inputs' / f'{track_id}.json'), 'diagnostic_only': True}
        if ready['status'] != 'ready':
            row.update({'status': 'unavailable', 'reason': ready['reason']})
        else:
            reference = read(case['reference']['path'])
            binding(case['reference']['path'], case['reference']['sha256'])
            started = time.perf_counter()
            before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            try:
                result = run_case(reference, ready['input'])
                save(output / 'outputs' / f'{track_id}.json', result)
                if result['proposal'] is not None and result['actual_fitter_parameters'] != {'min_events': 8, 'split_penalty_seconds_squared': .01, 'continuous_model_selection': False}:
                    raise ValueError('fitter returned parameters outside frozen v1 settings')
                row.update({'status': result['status'], 'fitter_status': result['fitter_status'],
                    'fit_seconds': result['fit_seconds'], 'output': binding(output / 'outputs' / f'{track_id}.json')})
                metrics = score_ideal_clock(reference, ready['input'], result['proposal'])
                save(output / 'metrics' / f'{track_id}.json', metrics)
                row['metrics'] = binding(output / 'metrics' / f'{track_id}.json')
                row['continuous_max_error_seconds'] = metrics['continuous_clock']['maximum_absolute_error_seconds']
                row['reference_support_coverage_fraction'] = metrics['continuous_clock']['reference_support_coverage_fraction']
            except Exception as exc:
                row.update({'status': 'error', 'reason': f'{type(exc).__name__}: {exc}'})
            row['elapsed_seconds'] = time.perf_counter() - started
            row['memory_measurement'] = 'process_high_water_RSS_KiB_on_Linux; not per-fit allocation'
            row['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            row['peak_rss_increase_kib'] = max(0, row['peak_rss_kib'] - before_rss)
        report['rows'].append(row)
        report['counts'] = dict(Counter(r['status'] for r in report['rows']))
        report['complete'] = len(report['rows']) == len(prepared)
        save(output / 'report.json', report)
        print(track_id, row['status'], row.get('fitter_status', row.get('reason', '')), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cohort', type=Path, default=COHORT)
    args = parser.parse_args(argv)
    report = run(args.output, cohort_path=args.cohort)
    print(json.dumps({'complete': report['complete'], 'counts': report['counts']}, indent=2))


if __name__ == '__main__':
    main()
