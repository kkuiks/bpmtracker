"""Experimental declared music-map geometry, separate from reference admission.

A latent pulse becomes a quarter coordinate only through an explicit rational
unit declaration. Physical support, clock context, meter, and musical origin
remain separate. Nothing here estimates alignment from another map.
"""
from bisect import bisect_right
from copy import deepcopy
from fractions import Fraction
import math
from numbers import Integral, Real
import re

from musical_units import MeterSpec

SCHEMA_VERSION = 1
BAR_INDEX_EPSILON = 1e-9  # numerical integer-boundary check, not a timing target


def _real(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return float(value)


def _integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return int(value)


def normalize_support(intervals, duration):
    """Take an exact interval union; never heal even a tiny genuine gap."""
    if not isinstance(intervals, (list, tuple)):
        raise ValueError('support_seconds must be a list of intervals')
    values = []
    for interval in intervals:
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError('support interval must have two endpoints')
        lo, hi = (_real(x, 'support endpoint') for x in interval)
        if not 0 <= lo < hi <= duration:
            raise ValueError('support must lie within physical source duration')
        values.append((lo, hi))
    result = []
    for lo, hi in sorted(values):
        if result and lo <= result[-1][1]:
            result[-1][1] = max(result[-1][1], hi)
        else:
            result.append([lo, hi])
    return result


def prepare_map(raw):
    """Validate/normalize a declaration without consulting any reference.

    Required source fields are sha256, sample_rate and sample_frames. Clock
    knots use real latent-pulse coordinates. Negative source-time knots are
    permitted as declared clock context, while physical support stays >= 0.
    Unknown musical fields are None. A valid constructor is not qualification.
    """
    if not isinstance(raw, dict):
        raise ValueError('map must be an object')
    if isinstance(raw.get('schema_version'), bool) or raw.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('unsupported music-map schema')
    value = deepcopy(raw)
    source = value.get('source')
    if not isinstance(source, dict):
        raise ValueError('source identity and sample clock are required')
    digest = source.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
        raise ValueError('source sha256 is required')
    rate = _integer(source.get('sample_rate'), 'sample_rate')
    frames = _integer(source.get('sample_frames'), 'sample_frames')
    duration = frames / rate
    value['source'] = {**source, 'sha256': digest.lower(), 'sample_rate': rate,
                       'sample_frames': frames}
    value['duration_seconds'] = duration
    value['support_seconds'] = normalize_support(value.get('support_seconds', []), duration)
    knots = value.get('clock_knots', [])
    if not isinstance(knots, list) or len(knots) == 1:
        raise ValueError('clock_knots must be empty or contain at least two knots')
    normalized = []
    for knot in knots:
        if not isinstance(knot, dict):
            raise ValueError('clock knot must be an object')
        pulse = _real(knot.get('pulse'), 'clock pulse')
        seconds = _real(knot.get('source_seconds'), 'clock source_seconds')
        if normalized and (pulse <= normalized[-1]['pulse'] or
                           seconds <= normalized[-1]['source_seconds']):
            raise ValueError('clock pulse and source time must strictly increase')
        normalized.append({'pulse': pulse, 'source_seconds': seconds})
    value['clock_knots'] = normalized
    if value['support_seconds']:
        if not normalized:
            raise ValueError('declared clock support requires a clock')
        if (value['support_seconds'][0][0] < normalized[0]['source_seconds'] or
                value['support_seconds'][-1][1] > normalized[-1]['source_seconds']):
            raise ValueError('support exceeds declared clock domain; no implicit extrapolation')
    unit = value.get('quarters_per_pulse')
    if unit is not None:
        if not isinstance(unit, dict):
            raise ValueError('quarters_per_pulse must be a rational object or None')
        unit = Fraction(_integer(unit.get('numerator'), 'unit numerator'),
                        _integer(unit.get('denominator'), 'unit denominator'))
        value['quarters_per_pulse'] = {'numerator': unit.numerator, 'denominator': unit.denominator}
    else:
        value['quarters_per_pulse'] = None
    anchor = value.get('bar_anchor_pulse')
    value['bar_anchor_pulse'] = _real(anchor, 'bar anchor') if anchor is not None else None
    origin = value.get('shared_origin_id')
    if origin is not None and (not isinstance(origin, str) or not origin.strip()):
        raise ValueError('shared_origin_id must name a semantic identity or be None')
    value['shared_origin_id'] = origin
    events = value.get('meter_events')
    if events is not None:
        if not isinstance(events, list):
            raise ValueError('meter_events must be a list or None')
        normalized_events = []
        for event in events:
            if not isinstance(event, dict):
                raise ValueError('meter event must be an object')
            pulse = _real(event.get('pulse'), 'meter pulse')
            meter = MeterSpec(event.get('numerator'), event.get('denominator'), event.get('grouping'))
            if normalized_events and pulse <= normalized_events[-1]['pulse']:
                raise ValueError('meter events must strictly increase')
            action = event.get('bar_action', 'unspecified')
            if action not in ('continue', 'restart', 'unspecified'):
                raise ValueError('bar_action must be continue, restart or unspecified')
            normalized_events.append({'pulse': pulse, 'numerator': meter.numerator,
                'denominator': meter.denominator,
                'grouping': list(meter.grouping) if meter.grouping is not None else None,
                'bar_action': action})
        value['meter_events'] = normalized_events
    else:
        value['meter_events'] = None
    condition = value.get('analysis_condition', 'unspecified')
    if condition not in ('unspecified', 'unhinted', 'user_bpm_guided',
                          'reference_assisted_diagnostic', 'constructed_fixture', 'reference'):
        raise ValueError('unknown analysis_condition')
    value['analysis_condition'] = condition
    value['capability'] = {'clock': bool(normalized), 'quarter_unit_declared': unit is not None,
        'meter_declared': bool(events), 'bar_anchor_declared': anchor is not None,
        'shared_origin_declared': origin is not None,
        'grouping_declared_everywhere': bool(events) and all(e['grouping'] is not None for e in value['meter_events']),
        'reference_qualified_by_constructor': False}
    return value


def interpolate_clock(knots, position, *, inverse=False):
    """Linear interpolation in the declared domain; never extrapolate."""
    xkey, ykey = ('source_seconds', 'pulse') if inverse else ('pulse', 'source_seconds')
    position = _real(position, xkey)
    if len(knots) < 2:
        raise ValueError('clock is unavailable')
    xs = [k[xkey] for k in knots]
    if not xs[0] <= position <= xs[-1]:
        raise ValueError('position outside clock domain')
    i = min(max(0, bisect_right(xs, position) - 1), len(knots) - 2)
    a, b = knots[i], knots[i+1]
    fraction = (position - a[xkey]) / (b[xkey] - a[xkey])
    return a[ykey] + fraction * (b[ykey] - a[ykey])


def _signature(event):
    return event['numerator'], event['denominator'], event['grouping']


def render_bars(raw, *, max_bars=100000):
    """Render full declared bars, retaining clock-context guard boundaries.

    Bars outside physical support are context only, not claimed audio coverage.
    The evaluator must retain coverage holes and qualify reference components.
    Non-barline meter/reset interpretation is deliberately unsupported in v1.
    Returned phase knots describe the original clock, not a barwise refit.
    """
    value = prepare_map(raw)
    max_bars = _integer(max_bars, 'max_bars')
    base = {'bars': [], 'bar_events_seconds': [], 'alignment_applied': False,
            'shared_origin_id': value['shared_origin_id'],
            'capability': value['capability'], 'support_seconds': value['support_seconds']}
    for field, status in [('clock', 'missing_clock'), ('quarter_unit_declared', 'unresolved_pulse_unit'),
                          ('meter_declared', 'missing_meter'), ('bar_anchor_declared', 'missing_bar_anchor')]:
        if not value['capability'][field]:
            return {**base, 'status': status, 'unsupported_reason': status}
    knots = value['clock_knots']; events = value['meter_events']
    lower, upper = knots[0]['pulse'], knots[-1]['pulse']
    if events[0]['pulse'] > lower:
        return {**base, 'status': 'missing_initial_meter', 'unsupported_reason': 'clock begins before declared meter'}
    unit = Fraction(**value['quarters_per_pulse'])
    # Ignore exact repeated non-reset declarations without inventing a new bar.
    active = [events[0]]
    for event in events[1:]:
        if event['pulse'] > upper:
            break  # preserved in the declaration; outside this clock's defined domain
        if _signature(event) == _signature(active[-1]) and event['bar_action'] == 'continue':
            continue
        active.append(event)
    sections = []
    anchor = value['bar_anchor_pulse']
    for i, event in enumerate(active):
        meter = MeterSpec(event['numerator'], event['denominator'], event['grouping'])
        length = float(meter.quarters_per_bar / unit)
        if i:
            old = sections[-1]
            at = event['pulse']
            bar_index = (at - old['anchor']) / old['length']
            if abs(bar_index - round(bar_index)) > BAR_INDEX_EPSILON:
                return {**base, 'status': 'unsupported_nonbarline_meter_or_reset',
                        'unsupported_reason': 'explicit interpretation of partial-bar reset is required',
                        'unsupported_event': event}
            anchor = at
        sections.append({'lo': event['pulse'],
                         'hi': active[i+1]['pulse'] if i+1 < len(active) else upper,
                         'anchor': anchor, 'length': length, 'event': event, 'meter': meter})
    bars = []; boundaries = []
    for section in sections:
        lo, hi = max(lower, section['lo']), min(upper, section['hi'])
        if hi < lo:
            continue
        first = math.ceil((lo - section['anchor']) / section['length'] - BAR_INDEX_EPSILON)
        last = math.floor((hi - section['anchor']) / section['length'] + BAR_INDEX_EPSILON)
        if len(boundaries) + last - first + 1 > max_bars + len(sections):
            return {**base, 'status': 'render_budget_exceeded', 'unsupported_reason': 'declared max_bars exceeded'}
        positions = []
        for n in range(first, last+1):
            pulse = section['anchor'] + n * section['length']
            # Numerical near-endpoint clamping only; no timing alignment.
            if abs(pulse-lo) <= BAR_INDEX_EPSILON * section['length']:pulse = lo
            if abs(pulse-hi) <= BAR_INDEX_EPSILON * section['length']:pulse = hi
            if lower <= pulse <= upper:
                positions.append(pulse)
                boundaries.append(interpolate_clock(knots, pulse))
        for a, b in zip(positions, positions[1:]):
            if b <= a:
                continue
            interior = [k['pulse'] for k in knots if a < k['pulse'] < b]
            phase_knots = [{'phase': (p-a)/(b-a), 'source_seconds': interpolate_clock(knots, p)}
                           for p in [a, *interior, b]]
            offsets = section['meter'].group_offsets_quarters
            group_times = None if offsets is None else [interpolate_clock(knots, a+float(q/unit)) for q in offsets]
            event = section['event']
            bars.append({'start_seconds': phase_knots[0]['source_seconds'],
                'end_seconds': phase_knots[-1]['source_seconds'], 'start_pulse': a, 'end_pulse': b,
                'meter': {'numerator': event['numerator'], 'denominator': event['denominator'],
                          'grouping': event['grouping']},
                'phase_knots': phase_knots, 'group_times_seconds': group_times})
    return {**base, 'status': 'rendered', 'unsupported_reason': None,
            'bars': bars, 'bar_events_seconds': sorted(set(boundaries)),
            'clock_domain_seconds': [knots[0]['source_seconds'], knots[-1]['source_seconds']],
            'index_origin_used_for_alignment': False,
            'scope': 'full bars within declared clock domain; physical support is separate'}
