"""Component diagnostics for declared music maps under reviewed policy v1.

``evaluate_music_maps(reference, prediction, reference_qualification=...)``
accepts the dictionaries documented by :mod:`music_map_contract`. Qualification
is explicit: Boolean ``bar_timing``, ``clock_timing``, ``meter`` and ``grouping``
flags apply to reference ``support_seconds``; omitted flags are false. Narrower
component-specific reference spans require separately scoped calls in v1.

The return value records validation/source compatibility, physical coverage,
render availability and per-tolerance diagnostics. It NEVER returns a product
pass/fail or estimates a source-time shift, scale, pulse unit, or musical origin.
An invalid/absent prediction remains a record with expected reference counts.
Unsupported components are unscored, not zero accuracy. Canonical-quarter event
metrics remain in grid_metrics and are not replaced by this comparison.

The only cross-signature decisions are the user-reviewed 4/4 <-> 8/4 allowance
when physical bars correspond, and the 3/4 versus 6/8 distinction. Grouping is
reported independently and does not veto the reviewed 4/4 <-> 8/4 allowance.
Other different signatures are unresolved. Same-signature agreement does not
assert unknown grouping. Indexed drift is deliberately not implemented here.

Boundary matching is ordered, one-to-one, at each explicitly named tolerance.
Full bars correspond only if BOTH endpoints match. Continuous errors compare
absolute source times at the same declared within-bar phase, over supported
phase intervals. No barwise offset is subtracted. Maxima and absolute integrals
are exact for the submitted piecewise-linear clocks, apart from float arithmetic.
Mean errors use uniform normalized bar phase, not uniform seconds or events.
"""
from bisect import bisect_left, bisect_right
from collections import Counter
import math
from numbers import Real

from music_map_contract import prepare_map, render_bars

POLICY_ID = 'reviewed-meter-cases-v1'
DEFAULT_TOLERANCES_SECONDS = (.01, .02, .03, .07)
_QUALIFICATION_KEYS = frozenset(('bar_timing', 'clock_timing', 'meter', 'grouping'))


def _tolerances(values):
    if not isinstance(values, (tuple, list)) or not values:
        raise ValueError('tolerances_seconds must be a nonempty list or tuple')
    normalized = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 0:
            raise ValueError('timing tolerances must be finite and positive')
        value = float(value)
        if value in normalized:
            raise ValueError('timing tolerances must be distinct')
        normalized.append(value)
    return normalized


def _qualification(value):
    if not isinstance(value, dict) or set(value) - _QUALIFICATION_KEYS:
        raise ValueError('reference_qualification must use documented component keys')
    if any(type(flag) is not bool for flag in value.values()):
        raise ValueError('reference qualification flags must be explicit Booleans')
    return {key: value.get(key, False) for key in sorted(_QUALIFICATION_KEYS)}


def _measure(intervals):
    return math.fsum(hi - lo for lo, hi in intervals)


def _union(intervals):
    result = []
    for lo, hi in sorted(intervals):
        if hi <= lo:
            continue
        if result and lo <= result[-1][1]:
            result[-1][1] = max(result[-1][1], hi)
        else:
            result.append([lo, hi])
    return result


def _intersection(left, right):
    result = []; i = j = 0
    while i < len(left) and j < len(right):
        lo, hi = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if hi > lo:
            result.append([lo, hi])
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return _union(result)


def _difference(intervals, covered):
    result = []
    for lo, hi in intervals:
        cursor = lo
        for a, b in covered:
            if b <= cursor:
                continue
            if a >= hi:
                break
            if a > cursor:
                result.append([cursor, min(a, hi)])
            cursor = max(cursor, b)
            if cursor >= hi:
                break
        if cursor < hi:
            result.append([cursor, hi])
    return result


def _time_epsilon(*values):
    """Roundoff allowance in source seconds; never a musical timing tolerance."""
    return 8 * max(math.ulp(value) for value in (*values, 1.))


def _time_close(a, b, tolerance):
    return abs(a - b) <= tolerance + _time_epsilon(a, b, tolerance)


def _contains(intervals, value, margin=0.):
    # Intervals themselves are never expanded, merged or healed. The ULP term
    # only stabilizes membership of rendered boundaries at a declared endpoint.
    return any(lo - margin - _time_epsilon(lo, value, margin) <= value <=
               hi + margin + _time_epsilon(hi, value, margin) for lo, hi in intervals)


def _prediction_event_supported(intervals, value, tolerance, source_duration):
    if _contains(intervals, value):
        return True
    # Only physical source edges admit clock-context guard events. A nearby
    # boundary inside an unsupported interior hole/prefix/tail is not predicted.
    return bool(intervals) and ((intervals[0][0] == 0 and value < 0 and
                                _time_close(value, 0., tolerance)) or
                               (intervals[-1][1] == source_duration and value > source_duration and
                                _time_close(value, source_duration, tolerance)))


def _bar_support(bar, support):
    return _intersection([[bar['start_seconds'], bar['end_seconds']]], support)


def _visible_bars(rendered, support):
    return [(index, bar) for index, bar in enumerate(rendered['bars']) if _bar_support(bar, support)]


def _coverage(reference, prediction):
    duration = reference['duration_seconds']; whole = [[0., duration]]
    ref = reference['support_seconds']; pred = prediction['support_seconds'] if prediction else []
    overlap = _intersection(ref, pred)
    return {'source_duration_seconds': duration,
        'reference_support_seconds': ref, 'prediction_support_seconds': pred,
        'reference_supported_duration_seconds': _measure(ref),
        'prediction_supported_duration_seconds': _measure(pred),
        'prediction_source_fraction': _measure(pred) / duration,
        'prediction_uncovered_source_intervals': _difference(whole, pred),
        'reference_evaluable_overlap_seconds': overlap,
        'reference_evaluable_overlap_duration_seconds': _measure(overlap),
        'reference_coverage_fraction': _measure(overlap) / _measure(ref) if ref else None,
        'uncovered_reference_intervals': _difference(ref, pred),
        'does_not_certify_correctness': True}


def _scores(tp, fp, fn):
    return {'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
        'precision': tp / (tp + fp) if tp + fp else None,
        'recall': tp / (tp + fn) if tp + fn else None,
        'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def _boundary_profile(reference_events, prediction_events, ref_support, pred_support, tolerance, source_duration):
    refs = [v for v in reference_events if _contains(ref_support, v)]
    # Context boundaries within tolerance may establish a boundary's identity;
    # unmatched context outside claimed support is never an extra in-song event.
    preds = [v for v in prediction_events if _contains(ref_support, v, tolerance)
             and _prediction_event_supported(pred_support, v, tolerance, source_duration)]
    core = {i for i, v in enumerate(preds) if _contains(ref_support, v) and _contains(pred_support, v)}
    pairs = []; i = j = 0
    while i < len(refs) and j < len(preds):
        error = preds[j] - refs[i]
        if _time_close(preds[j], refs[i], tolerance):
            pairs.append((i, j)); i += 1; j += 1
        elif preds[j] < refs[i]:
            j += 1
        else:
            i += 1
    used_ref = {i for i, _ in pairs}; used_pred = {j for _, j in pairs}
    false_predictions = sorted(core - used_pred)
    errors = [preds[j] - refs[i] for i, j in pairs]
    ambiguous = sum(bisect_right(preds, t + tolerance) - bisect_left(preds, t - tolerance) > 1 for t in refs)
    return {'status': 'scored' if refs or core else 'no_evaluable_events',
        'reference_event_count': len(refs), 'core_prediction_event_count': len(core),
        'matched_context_event_count': len(used_pred - core),
        'ambiguous_reference_event_count': ambiguous,
        'correspondence': 'ordered_one_to_one_without_time_alignment',
        'scores': _scores(len(pairs), len(false_predictions), len(refs) - len(pairs)),
        'matched_events': [{'reference_seconds': refs[i], 'prediction_seconds': preds[j],
                            'error_seconds': preds[j] - refs[i]} for i, j in pairs],
        'unmatched_reference_seconds': [t for i, t in enumerate(refs) if i not in used_ref],
        'unmatched_prediction_seconds': [preds[i] for i in false_predictions],
        'matched_absolute_max_seconds': max(map(abs, errors)) if errors else None,
        'matched_error_scope': 'conditional correspondence error, not indexed drift'}


def _pair_bars(refs, preds, tolerance):
    pairs = []; used_pred = set(); ambiguities = 0; next_prediction = 0
    starts = [bar['start_seconds'] for _, bar in preds]
    for ref_index, ref in refs:
        candidates = []
        epsilon = _time_epsilon(ref['start_seconds'], starts[0] if starts else 0., starts[-1] if starts else 0.)
        lower = max(next_prediction, bisect_left(starts, ref['start_seconds'] - tolerance - epsilon))
        upper = bisect_right(starts, ref['start_seconds'] + tolerance + epsilon)
        for slot in range(lower, upper):
            pred_index, pred = preds[slot]
            if (_time_close(pred['start_seconds'], ref['start_seconds'], tolerance) and
                    _time_close(pred['end_seconds'], ref['end_seconds'], tolerance)):
                candidates.append((slot, pred_index, pred))
        if len(candidates) > 1:
            ambiguities += 1
        if candidates:
            slot, pred_index, pred = candidates[0]
            pairs.append((ref_index, ref, pred_index, pred))
            used_pred.add(pred_index); next_prediction = slot + 1
    used_ref = {i for i, _, _, _ in pairs}
    return pairs, [i for i, _ in refs if i not in used_ref], [i for i, _ in preds if i not in used_pred], ambiguities


def _interpolate_phase(knots, value, inverse=False):
    x, y = ('source_seconds', 'phase') if inverse else ('phase', 'source_seconds')
    xs = [point[x] for point in knots]
    if value < xs[0] or value > xs[-1]:
        raise ValueError('phase interpolation outside declared bar')
    i = min(max(bisect_right(xs, value) - 1, 0), len(knots) - 2)
    a, b = knots[i], knots[i + 1]
    return a[y] + (value - a[x]) * (b[y] - a[y]) / (b[x] - a[x])


def _phase_support(bar, support):
    return [[_interpolate_phase(bar['phase_knots'], lo, inverse=True),
             _interpolate_phase(bar['phase_knots'], hi, inverse=True)]
            for lo, hi in _bar_support(bar, support)]


def _continuous_error(ref, pred, ref_support, pred_support):
    phase_support = _intersection(_phase_support(ref, ref_support), _phase_support(pred, pred_support))
    signed_integrals = []; absolute_integrals = []; errors = []
    for lo, hi in phase_support:
        phases = sorted({lo, hi, *(k['phase'] for k in ref['phase_knots'] if lo < k['phase'] < hi),
                         *(k['phase'] for k in pred['phase_knots'] if lo < k['phase'] < hi)})
        delta = [_interpolate_phase(pred['phase_knots'], p) - _interpolate_phase(ref['phase_knots'], p) for p in phases]
        errors.extend(delta)
        for a, b, x, y in zip(phases, phases[1:], delta, delta[1:]):
            width = b - a
            signed_integrals.append(width * (x + y) / 2)
            if x * y < 0:
                # Two exact triangles split at the affine error's zero crossing.
                absolute_integrals.append(width * (x*x + y*y) / (2 * (abs(x) + abs(y))))
            else:
                absolute_integrals.append(width * (abs(x) + abs(y)) / 2)
    measure = _measure(phase_support)
    absolute = math.fsum(absolute_integrals); signed = math.fsum(signed_integrals)
    return {'status': 'scored' if measure else 'no_shared_supported_phase',
        'phase_support': phase_support, 'supported_phase_measure': measure,
        'absolute_max_seconds': max(map(abs, errors)) if errors else None,
        'absolute_integral_seconds_times_bar_phase': absolute if measure else None,
        'signed_integral_seconds_times_bar_phase': signed if measure else None,
        'absolute_mean_seconds': absolute / measure if measure else None,
        'signed_mean_seconds': signed / measure if measure else None,
        'start_boundary_error_seconds': pred['start_seconds'] - ref['start_seconds'],
        'end_boundary_error_seconds': pred['end_seconds'] - ref['end_seconds'],
        'weighting': 'uniform declared within-bar phase over jointly supported phases',
        'alignment_applied': False}


def _notation_relation(ref, pred):
    a = (ref['numerator'], ref['denominator']); b = (pred['numerator'], pred['denominator'])
    if a == b:
        return 'same_written_meter'
    pair = frozenset((a, b))
    if pair == frozenset(((4, 4), (8, 4))):
        return 'reviewed_4_4_8_4_allowance_requires_bar_correspondence'
    if pair == frozenset(((3, 4), (6, 8))):
        return 'reviewed_3_4_6_8_distinct'
    return 'unresolved_other_cross_signature_pair'


def _group_relation(ref, pred):
    a, b = ref['grouping'], pred['grouping']
    if a is None or b is None:
        return 'unassessable_missing_grouping'
    # Integer cross-products preserve exact normalized grouping, without fitting.
    if len(a) != len(b) or any(x * sum(b) != y * sum(a) for x, y in zip(a, b)):
        return 'different_declared_grouping'
    return 'same_normalized_declared_grouping'


def _notation_timeline(refs, preds, common_support, qualification):
    comparisons = []; i = j = 0
    while i < len(refs) and j < len(preds):
        ri, ref = refs[i]; pi, pred = preds[j]
        overlap = _intersection([[max(ref['start_seconds'], pred['start_seconds']),
                                  min(ref['end_seconds'], pred['end_seconds'])]], common_support)
        if overlap:
            comparisons.append({'reference_bar_index': ri, 'prediction_bar_index': pi,
                'support_seconds': overlap,
                'notation_relation': _notation_relation(ref['meter'], pred['meter']) if qualification['meter'] else 'unscored_unverified_reference',
                'grouping_relation': _group_relation(ref['meter'], pred['meter']) if qualification['grouping'] else 'unscored_unverified_reference'})
        if ref['end_seconds'] <= pred['end_seconds']:
            i += 1
        else:
            j += 1
    return comparisons


def _render_summary(prepared, rendered):
    if prepared is None:
        return None
    return {'capability': prepared['capability'], 'render_status': rendered['status'],
        'unsupported_reason': rendered['unsupported_reason'],
        'analysis_condition': prepared['analysis_condition'],
        'shared_origin_id': prepared['shared_origin_id'],
        'full_declared_context_bar_count': len(rendered['bars'])}


def _bar_availability(visible, support):
    full = []; partial = []
    for index, bar in visible:
        # A single normalized interval must cover the bar. ULP endpoint
        # agreement cannot bridge a genuine gap between two support intervals.
        covered = any(lo - _time_epsilon(lo, bar['start_seconds']) <= bar['start_seconds'] and
                      hi + _time_epsilon(hi, bar['end_seconds']) >= bar['end_seconds'] for lo, hi in support)
        (full if covered else partial).append(index)
    return {'fully_supported_bar_indices': full, 'partly_supported_bar_indices': partial}


def evaluate_music_maps(reference, prediction, *, reference_qualification,
                        tolerances_seconds=DEFAULT_TOLERANCES_SECONDS):
    """Compare declared components, retaining unknowns, failures and coverage.

    Invalid map declarations are returned as records; invalid evaluator options
    raise ValueError. None represents an absent prediction. A source hash, native
    sample rate or sample-frame mismatch blocks all geometric scoring. The caller
    must establish source mapping before requesting a comparison.
    """
    tolerances = _tolerances(tolerances_seconds); qualified = _qualification(reference_qualification)
    result = {'schema_version': 1, 'policy_id': POLICY_ID, 'reference_qualification': qualified,
        'alignment_applied': False, 'numerical_boundary_rule': '8 ULP at max(timestamp magnitude, 1 second); support intervals never merged across gaps', 'canonical_quarter_metric': 'separate_existing_diagnostic_not_replaced',
        'product_success_threshold': None, 'overall_product_pass': None,
        'indexed_drift': {'status': 'not_implemented', 'reason': 'physical correspondence is not independently anchored indexed drift'},
        'timing_profiles': []}
    try:
        ref = prepare_map(reference); ref_render = render_bars(ref)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {**result, 'status': 'invalid_reference', 'reference_error': str(exc)}
    pred = pred_render = None; prediction_error = None
    prediction_status = 'absent_prediction' if prediction is None else 'valid_prediction'
    if prediction is not None:
        try:
            pred = prepare_map(prediction); pred_render = render_bars(pred)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            pred = pred_render = None; prediction_status = 'invalid_prediction'; prediction_error = str(exc)
    result.update(status='compared' if pred is not None else prediction_status,
        prediction_status=prediction_status, prediction_error=prediction_error,
        reference=_render_summary(ref, ref_render), prediction=_render_summary(pred, pred_render),
        coverage=_coverage(ref, pred))
    if pred is not None and any(ref['source'][key] != pred['source'][key] for key in ('sha256', 'sample_rate', 'sample_frames')):
        result.update(status='blocked_source_identity_or_sample_clock_mismatch', coverage=None,
                      source_mismatch_fields=[key for key in ('sha256', 'sample_rate', 'sample_frames') if ref['source'][key] != pred['source'][key]])
        return result
    if pred is None or ref['shared_origin_id'] is None or ref['shared_origin_id'] != pred['shared_origin_id']:
        result['indexed_drift'] = {'status': 'unanchored', 'reason': 'no explicitly shared semantic musical origin; no origin fitted'}
    ref_support = ref['support_seconds']; pred_support = pred['support_seconds'] if pred else []
    common_support = _intersection(ref_support, pred_support)
    refs = _visible_bars(ref_render, ref_support)
    preds = _visible_bars(pred_render, common_support) if pred_render else []
    ref_event_count = sum(_contains(ref_support, t) for t in ref_render['bar_events_seconds'])
    result['reference_expected_geometry'] = {'bar_event_count': ref_event_count, 'supported_full_or_partial_bar_count': len(refs),
                                           **_bar_availability(refs, ref_support)}
    result['prediction_available_geometry'] = {'supported_full_or_partial_bar_count': len(preds),
                                               **_bar_availability(preds, pred_support)}
    relations = _notation_timeline(refs, preds, common_support, qualified)
    notation_counts = dict(Counter(row['notation_relation'] for row in relations))
    grouping_counts = dict(Counter(row['grouping_relation'] for row in relations))
    result['declared_notation_comparison'] = {
        'status': 'scored_components' if relations else 'no_common_rendered_bar_support',
        'timeline': relations, 'notation_relation_counts': notation_counts, 'grouping_relation_counts': grouping_counts,
        'known_notation_disagreement': bool(notation_counts.get('reviewed_3_4_6_8_distinct')),
        'unknown_cross_notation_present': bool(notation_counts.get('unresolved_other_cross_signature_pair')),
        'grouping_does_not_veto_reviewed_4_4_8_4_allowance': True,
        'scope': 'overlapping physical intervals, not tempo/meter event-list identity or a full-map verdict'}
    for tolerance in tolerances:
        profile = {'tolerance_seconds': tolerance, 'reference_bar_event_count': ref_event_count,
                   'reference_full_or_partial_bar_count': len(refs)}
        if not qualified['bar_timing']:
            profile.update(status='unscored_unverified_reference_bar_timing', bar_boundaries=None, paired_bars=None)
        elif ref_render['status'] != 'rendered':
            profile.update(status='unsupported_reference_bar_geometry', bar_boundaries=None, paired_bars=None,
                           reason=ref_render['status'])
        elif pred_render is None or pred_render['status'] != 'rendered':
            profile.update(status=prediction_status if pred_render is None else 'unsupported_prediction_bar_geometry',
                reason=prediction_error if pred_render is None else pred_render['status'],
                bar_boundaries=None, paired_bars=None,
                unavailable_reference_bar_event_count=ref_event_count,
                unavailable_reference_bar_indices=[i for i, _ in refs])
        else:
            boundary = _boundary_profile(ref_render['bar_events_seconds'], pred_render['bar_events_seconds'],
                                         ref_support, pred_support, tolerance, ref['duration_seconds'])
            pairs, missing, extra, ambiguities = _pair_bars(refs, preds, tolerance)
            comparisons = []
            for ri, ref_bar, pi, pred_bar in pairs:
                comparison = {'reference_bar_index': ri, 'prediction_bar_index': pi,
                    'start_boundary_error_seconds': pred_bar['start_seconds'] - ref_bar['start_seconds'],
                    'end_boundary_error_seconds': pred_bar['end_seconds'] - ref_bar['end_seconds'],
                    'notation_relation': _notation_relation(ref_bar['meter'], pred_bar['meter']) if qualified['meter'] else 'unscored_unverified_reference',
                    'grouping_relation': _group_relation(ref_bar['meter'], pred_bar['meter']) if qualified['grouping'] else 'unscored_unverified_reference'}
                comparison['continuous_timing'] = (_continuous_error(ref_bar, pred_bar, ref_support, pred_support)
                    if qualified['clock_timing'] else {'status': 'unscored_unverified_reference_clock_timing'})
                comparisons.append(comparison)
            scored = [row['continuous_timing'] for row in comparisons if row['continuous_timing']['status'] == 'scored']
            phase_measure = math.fsum(row['supported_phase_measure'] for row in scored)
            summary = {'status': 'scored' if scored else ('unscored_unverified_reference_clock_timing' if not qualified['clock_timing'] else 'no_paired_supported_bars'),
                'scored_bar_count': len(scored), 'supported_phase_measure': phase_measure,
                'absolute_max_seconds': max((row['absolute_max_seconds'] for row in scored), default=None),
                'absolute_mean_seconds': (math.fsum(row['absolute_integral_seconds_times_bar_phase'] for row in scored) / phase_measure) if phase_measure else None,
                'weighting': 'uniform within-bar phase, summed over paired supported bars',
                'conditional_on_bar_correspondence': True, 'indexed_drift': False}
            profile.update(status='scored_components', bar_boundaries=boundary,
                paired_bars={'count': len(pairs), 'comparisons': comparisons,
                    'unmatched_reference_bar_indices': missing, 'unmatched_prediction_bar_indices': extra,
                    'ambiguous_reference_bar_count': ambiguities,
                    'continuous_timing_summary': summary,
                    'not_a_whole_song_success_rate': True})
        result['timing_profiles'].append(profile)
    return result
