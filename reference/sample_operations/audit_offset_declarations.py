"""One-pass audit of current formal references after explicit owner confirmation.

Reads accepted audio-relative declarations and saved working-project declarations.
Never reapplies offsets, decodes recordings, reads source ZIPs or changes maps.
"""
from pathlib import Path
from fractions import Fraction
import argparse
import csv
import hashlib
import io
import json
import math

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / 'data/samples'
OUTPUT = 'records/owner-review/20261010-reference-confirmation-v1'
TIME_KEYS = ('master_seconds', 'audio_seconds', 'time_seconds', 'project_seconds')


def load(path):
    return json.loads(path.read_text())


def event_time(event):
    if isinstance(event, (int, float)):
        return float(event)
    for key in TIME_KEYS:
        if key in event:
            return float(event[key])
    raise ValueError('Declaration has no accepted audio-relative time')


def intervals(value):
    if not value:
        return []
    return [value] if isinstance(value[0], (int, float)) else value


def value(event, kind):
    if kind == 'tempo':
        return float(next(event[k] for k in ('bpm_quarter', 'bpm', 'quarter_bpm') if k in event))
    return (event['numerator'], event['denominator'])


def label(event, kind):
    v = value(event, kind)
    if kind == 'meter':
        return f'{v[0]}/{v[1]}'
    fraction = Fraction(v).limit_denominator(4)
    # SMF storage precision is a display distinction; do not change the clock.
    if abs(60e6 / v - 60e6 / float(fraction)) <= 1.00001:
        return str(fraction)
    return f'{v:.6f}'


def declarations(ref, kind):
    raw_key = f'{kind}_declarations_audio_relative'
    events = ref.get(raw_key, ref.get(f'{kind}_events', []))
    if not events and kind == 'tempo' and ref.get('quarter_bpm'):
        events = [{'time_seconds': ref['first_beat_source_seconds'], 'bpm_quarter': ref['quarter_bpm']}]
    if not events and kind == 'meter' and isinstance(ref.get('meter'), dict):
        events = [{'time_seconds': ref['first_beat_source_seconds'], **ref['meter']}]
    if not events:
        raise ValueError('Accepted reference is missing ' + kind)
    return sorted(events, key=event_time), 'saved_daw_working_project' if raw_key in ref else 'accepted_reference'


def intersect(start, end, windows):
    return [[max(start, a), min(end, b)] for a, b in windows if min(end, b) > max(start, a) + 1e-9]


def subtract(windows, removed):
    result = [list(x) for x in windows]
    for a, b in removed:
        result = [part for x, y in result for part in ([x, min(y, a)], [max(x, b), y]) if part[1] > part[0] + 1e-9]
    return result


def atomic(path, data):
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_bytes(data)
    temporary.replace(path)


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Record the requested one-pass audit and provenance')
    args = parser.parse_args()
    catalog_path = SAMPLES / 'catalog.json'
    original_catalog = catalog_path.read_bytes()
    catalog = json.loads(original_catalog)
    destination = SAMPLES / OUTPUT
    if args.write and (destination / 'offset-declaration-audit.json').exists():
        raise SystemExit('Audit receipt already exists; preserve the completed single pass')
    rows, findings = [], []
    for track in catalog['tracks']:
        if track['role'].startswith('auxiliary'):
            continue
        ref = load(SAMPLES / track['reference']['path'])
        duration = track['duration_seconds']
        frame_tolerance = 0.5 / track['sample_rate']
        no_grid = intervals(ref.get('free_time_seconds')) + intervals(ref.get('evaluation_scope', {}).get('no_grid_tail_seconds'))
        windows = subtract(intersect(0, duration, intervals(track['reference_support_seconds'])), no_grid)
        tempos, tempo_origin = declarations(ref, 'tempo')
        meters, meter_origin = declarations(ref, 'meter')
        row = {'id': track['id'], 'title': track['title'], 'reference_path': track['reference']['path'],
               'duration_seconds': duration, 'approved_support_seconds': windows,
               'approved_no_grid_seconds': no_grid,
               'additional_offset_applied_by_audit_seconds': 0,
               'declarations': [], 'inherited_start_states': [], 'short_initial_value_segments': []}
        for kind, events, origin in [('tempo', tempos, tempo_origin), ('meter', meters, meter_origin)]:
            for index, event in enumerate(events):
                start = event_time(event)
                if not math.isfinite(start):
                    raise ValueError('Non-finite declaration in ' + track['id'])
                next_time = event_time(events[index + 1]) if index + 1 < len(events) else None
                end = next_time if next_time is not None else max(start, duration)
                overlap = intersect(start, end, windows)
                same_next = index + 1 < len(events) and value(event, kind) == value(events[index + 1], kind)
                if start < -frame_tolerance and next_time is not None and next_time <= frame_tolerance:
                    classification = 'fully_before_audio_superseded'
                elif start >= duration - frame_tolerance:
                    classification = 'declaration_at_or_after_recording_end'
                elif not overlap:
                    classification = 'declaration_without_approved_grid_overlap'
                elif start < -frame_tolerance:
                    classification = 'pre_audio_declaration_with_audible_continuation'
                elif start < 0:
                    classification = 'within_half_source_frame_of_audio_start'
                else:
                    classification = 'audible_approved_declaration'
                item = {'kind': kind, 'event_index': index, 'label': label(event, kind),
                        'declaration_audio_seconds': start, 'next_declaration_audio_seconds': next_time,
                        'audible_approved_intervals': overlap, 'origin': origin,
                        'next_declaration_repeats_same_value': same_next, 'classification': classification}
                row['declarations'].append(item)
                if classification in {'fully_before_audio_superseded', 'declaration_at_or_after_recording_end', 'declaration_without_approved_grid_overlap'}:
                    findings.append({'id': track['id'], 'title': track['title'], **item})
            for a, b in windows:
                preceding = [e for e in events if event_time(e) <= a + frame_tolerance]
                if not preceding:
                    findings.append({'id': track['id'], 'title': track['title'], 'kind': kind,
                                     'classification': 'no_declared_initial_state_at_support_start', 'support_start_seconds': a})
                    continue
                current = preceding[-1]
                if event_time(current) < a - frame_tolerance:
                    row['inherited_start_states'].append({'kind': kind, 'label': label(current, kind),
                        'support_start_seconds': a, 'declaration_audio_seconds': event_time(current),
                        'state_preserved_inside_audio': True, 'origin': origin})
                # Ignore same-value redeclarations when deciding whether a short
                # initial segment represents a real tempo/signature change.
                changed = next((e for e in events if event_time(e) > a + frame_tolerance and value(e, kind) != value(current, kind)), None)
                if a <= frame_tolerance and event_time(current) < -frame_tolerance and changed:
                    stop = min(event_time(changed), b)
                    tempo = [e for e in tempos if event_time(e) <= a + frame_tolerance][-1]
                    meter = [e for e in meters if event_time(e) <= a + frame_tolerance][-1]
                    one_initial_bar = meter['numerator'] * 4 / meter['denominator'] * 60 / value(tempo, 'tempo')
                    if stop - a < one_initial_bar - frame_tolerance:
                        row['short_initial_value_segments'].append({'kind': kind, 'label': label(current, kind),
                            'retained_audio_seconds': [a, stop], 'next_value': label(changed, kind),
                            'one_initial_bar_seconds': one_initial_bar})
        bars = ref.get('downbeats_seconds', ref.get('bar_starts_seconds', ref.get('bar_events')))
        if bars is None:
            bars = [e for e in ref.get('quarter_events', []) if e.get('bar_start', e.get('accent'))]
        visible_bars = sorted(event_time(e) for e in bars if event_time(e) >= -frame_tolerance and event_time(e) < duration)
        first_bar = visible_bars[0] if visible_bars else None
        meter_at_zero = [e for e in meters if event_time(e) <= frame_tolerance]
        partial_bar = bool(windows and windows[0][0] <= frame_tolerance and meter_at_zero and
            event_time(meter_at_zero[-1]) < -frame_tolerance and first_bar is not None and first_bar > frame_tolerance)
        row['audio_start_is_inside_preserved_bar'] = partial_bar
        row['first_retained_bar_start_seconds'] = first_bar
        row['first_tempo_declaration_audio_seconds'] = event_time(tempos[0])
        row['first_meter_declaration_audio_seconds'] = event_time(meters[0])
        rows.append(row)
    counts = {classification: sum(f['classification'] == classification for f in findings) for classification in
        ['fully_before_audio_superseded', 'declaration_at_or_after_recording_end', 'declaration_without_approved_grid_overlap', 'no_declared_initial_state_at_support_start']}
    summary = {'formal_samples_audited': len(rows), 'findings': counts,
        'samples_with_pre_audio_declarations_preserved_as_initial_state': sum(any(x['declaration_audio_seconds'] < 0 for x in r['inherited_start_states']) for r in rows),
        'samples_starting_inside_preserved_bar': sum(r['audio_start_is_inside_preserved_bar'] for r in rows),
        'samples_with_sub_bar_initial_value_segment_before_real_change': sum(bool(r['short_initial_value_segments']) for r in rows),
        'samples_with_half_frame_negative_initial_declaration_only': sum(any(d['classification'] == 'within_half_source_frame_of_audio_start' for d in r['declarations']) for r in rows)}
    report = {'schema_version': 1, 'date_local': '2026-10-10', 'timezone': 'Asia/Seoul',
        'requested_scope': 'One pass over all currently confirmed formal tempo/meter declarations for offset clipping.',
        'membership_authority': 'catalog.json', 'confirmation_record': OUTPUT + '/confirmation.json',
        'time_policy': 'Accepted audio-relative coordinates; no second offset. Intersect declaration state intervals with audio and approved support; preserve state and bar phase at audio start.',
        'same_value_redeclarations_are_not_real_value_changes': True,
        'negative_times_alone_are_not_invalid_changes': True,
        'frame_boundary_tolerance': 'Half of one original sample frame; absolute times retained.',
        'audio_decode_source_zip_scan_recording_hash_playback_model_or_benchmark_performed': False,
        'references_modified_by_audit': False, 'summary': summary, 'findings': findings, 'tracks': rows}
    if args.write:
        if original_catalog != catalog_path.read_bytes():
            raise RuntimeError('Catalog changed during the requested audit')
        destination.mkdir(parents=True, exist_ok=True)
        audit_bytes = encoded(report)
        atomic(destination / 'offset-declaration-audit.json', audit_bytes)
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['id', 'title', 'reference_path', 'first_tempo_declaration_audio_seconds', 'first_meter_declaration_audio_seconds',
                         'first_retained_bar_start_seconds', 'audio_start_inside_preserved_bar', 'short_initial_real_change_segments', 'outside_declarations'])
        for row in rows:
            writer.writerow([row['id'], row['title'], row['reference_path'], row['first_tempo_declaration_audio_seconds'],
                row['first_meter_declaration_audio_seconds'], row['first_retained_bar_start_seconds'], row['audio_start_is_inside_preserved_bar'],
                json.dumps(row['short_initial_value_segments']), sum(f['id'] == row['id'] for f in findings)])
        csv_bytes = buffer.getvalue().encode('utf-8-sig')
        atomic(destination / 'offset-declaration-audit.csv', csv_bytes)
        inventory_path = SAMPLES / 'assets.json'
        inventory = load(inventory_path)
        for filename, data in [('offset-declaration-audit.json', audit_bytes), ('offset-declaration-audit.csv', csv_bytes)]:
            inventory['assets'].append({'path': OUTPUT + '/' + filename, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'category': 'owner_requested_offset_declaration_audit', 'retained': True, 'registered_owner_approved': True})
        unique = {a['path']: a for a in inventory['assets'] if a.get('retained') or a.get('copied')}
        inventory['unique_copied_files'] = len(unique)
        inventory['unique_copied_bytes'] = sum(a.get('bytes', 0) for a in unique.values())
        catalog['latest_offset_declaration_audit'] = {'date_local': '2026-10-10', 'record': OUTPUT + '/offset-declaration-audit.json', **summary}
        atomic(inventory_path, encoded(inventory))
        atomic(catalog_path, encoded(catalog))
    print(json.dumps({'summary': summary, 'findings': findings,
        'short_initial_segments': [{'id': r['id'], 'segments': r['short_initial_value_segments']} for r in rows if r['short_initial_value_segments']],
        'initial_partial_bars': [{'id': r['id'], 'first_bar_seconds': r['first_retained_bar_start_seconds']} for r in rows if r['audio_start_is_inside_preserved_bar']]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
