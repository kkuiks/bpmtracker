"""Package source-verified audio and blinded musical-map candidates for local review.

No reference annotations are included in the browser bundle. Serve the output
directory with `python3 -m http.server --bind 127.0.0.1 --directory <dir> 8765`.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf

from inspect_inputs import sha256


def report_audio_hashes(report, visited=None):
    """Resolve preserved comparison provenance to the original inference input."""
    hashes = {}
    for row in report.get('tracks', []):
        digest = row.get('input_sha256') or row.get('source', {}).get('sha256')
        if digest:
            hashes[row['id']] = digest
    visited = set() if visited is None else visited
    config = report.get('configuration', {})
    for record in config.get('source_reports', config.get('reports', [])):
        path = Path(record['path'])
        if path in visited:
            continue
        visited.add(path)
        if sha256(path) != record['sha256']:
            raise ValueError('upstream inference report changed')
        for identifier, digest in report_audio_hashes(json.loads(path.read_text()), visited).items():
            if identifier in hashes and hashes[identifier] != digest:
                raise ValueError('reports disagree about source audio')
            hashes[identifier] = digest
    return hashes


def prediction_map(prediction, identifier, label):
    times = prediction['beats_seconds']
    return {'id': identifier, 'label': label, 'grid': [
        {'quarter_position': i, 'source_seconds': t} for i, t in enumerate(times)],
        'meter_events': [], 'status': 'unaccepted_quarter_hypothesis',
        'index_origin': 'first proposed pulse is local quarter zero; not aligned to reference'}


def candidate_map(candidate, identifier, label):
    return {'id': identifier, 'label': label, 'grid': candidate['indexed_grid'],
            'meter_events': [], 'status': candidate.get('status','unaccepted_quarter_hypothesis'),
            'full_song_map': candidate.get('full_song_map'),
            'source_support_seconds': candidate.get('source_support_seconds'),
            'unknown_bridges': candidate.get('unknown_bridges', []),
            'support_note': candidate.get('support_note', 'Only the displayed grid support has clicks; source audio is unchanged.'),
            'index_origin': 'candidate-local quarter coordinates; not aligned to reference'}


def build(catalogs, reports, candidate_reports, output_dir, track_ids=None):
    if output_dir.exists():
        raise ValueError('output must be a new directory')
    entries = {t['id']: t for p in catalogs for t in json.loads(p.read_text())['tracks']}
    rows = {}
    row_hashes = {}
    for path in reports:
        report = json.loads(path.read_text())
        hashes = report_audio_hashes(report)
        for row in report['tracks']:
            rows[row['id']] = row
            row_hashes[row['id']] = hashes.get(row['id'])
    extra = {}
    for path in candidate_reports:
        report = json.loads(path.read_text())
        hashes = report_audio_hashes(report)
        for row in report.get('tracks', []):
            if row.get('candidate_sets'):
                for model, candidate_location in row['candidate_sets'].items():
                    if isinstance(candidate_location, dict):
                        candidate_location = candidate_location['path']
                    candidate_path = Path(candidate_location)
                    if not candidate_path.is_file():
                        candidate_path = path.parent/candidate_location
                    extra.setdefault(row['id'], []).append({
                        'id': row['id'], 'model': model,
                        'audio_sha256': hashes.get(row['id']), 'candidate_path': str(candidate_path),
                        'candidate_set': json.loads(candidate_path.read_text())})
                continue
            candidate_path = path.parent/row['id']/'candidates.json'
            if candidate_path.is_file():
                row = {**row, 'candidate_set': json.loads(candidate_path.read_text()),
                       'candidate_path': str(candidate_path)}
            row = {**row, 'audio_sha256': hashes.get(row['id'])}
            extra.setdefault(row['id'], []).append(row)
    ids = track_ids or sorted(rows)
    output_dir.mkdir(parents=True)
    bundle = {'schema_version': 1, 'purpose': 'blinded human correction pilot; no reference labels', 'tracks': []}
    key = {'schema_version': 1, 'private_evaluation_key_not_embedded_in_ui': True, 'tracks': []}
    for track_id in ids:
        entry = entries[track_id]
        if entry['input']['kind'] != 'audio':
            continue
        source = Path(entry['input']['path'])
        if sha256(source) != entry['input']['sha256']:
            raise ValueError('source audio hash mismatch')
        if row_hashes.get(track_id) != entry['input']['sha256']:
            raise ValueError('prediction/source audio identity is missing or mismatched')
        audio, rate = sf.read(source, dtype='float32', always_2d=True)
        row = rows[track_id]
        variants = row.get('variants') or {name: method['prediction'] for name, method in row['methods'].items()}
        maps = [(name, prediction_map(pred, name, name), {'method': name})
                for name, pred in variants.items() if len(pred['beats_seconds']) >= 2]
        for name, map_value, identity in maps:
            method = row.get('methods', {}).get(name, {})
            for field in ('full_song_map','source_support_seconds','unknown_bridges','status'):
                if field in method:
                    map_value[field] = method[field]
        for i, record in enumerate(extra.get(track_id, [])):
            if record['audio_sha256'] != entry['input']['sha256']:
                raise ValueError('candidate/source audio identity is missing or mismatched')
            sets = record.get('candidate_set', record)
            provenance = sets.get('input_provenance', {})
            if provenance.get('audio') and provenance['audio']['sha256'] != entry['input']['sha256']:
                raise ValueError('candidate input provenance differs from the audio')
            if provenance.get('logits_path') and sha256(provenance['logits_path']) != provenance['logits_sha256']:
                raise ValueError('candidate logits changed')
            for j, candidate in enumerate(sets.get('candidates', [])):
                if len(candidate.get('indexed_grid', [])) >= 2:
                    name = f'candidate-{i}-{j}'
                    maps.append((name, candidate_map(candidate, name, name), {
                        'method': name, 'model': record.get('model', provenance.get('model_label')),
                        'candidate_id': candidate['id'], 'candidate_path': record.get('candidate_path'),
                        'candidate_sha256': sha256(record['candidate_path']) if record.get('candidate_path') else None}))
        # Fixed blinding order independent of accuracy. Evaluation key stays in a
        # separate file, never in the page or embedded payload.
        maps.sort(key=lambda item: hashlib.sha256(f'joljak-review-v1:{track_id}:{item[0]}'.encode()).digest())
        blind_maps = []
        correspondence = {}
        for i, (method, map_value, identity) in enumerate(maps):
            identifier = f'choice-{i+1}'
            map_value.update(id=identifier, label=f'후보 {i+1}')
            blind_maps.append(map_value)
            correspondence[identifier] = identity
        target = output_dir/'audio'/f'{track_id}{source.suffix}'
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        if sha256(target) != entry['input']['sha256']:
            raise ValueError('review copy changed')
        mono = np.max(np.abs(audio), axis=1)
        peaks = [float(np.max(part)) if len(part) else 0 for part in np.array_split(mono, 1200)]
        bundle['tracks'].append({'id': track_id, 'label': track_id, 'audio_url': str(target.relative_to(output_dir)),
            'source': {'sha256': entry['input']['sha256'], 'sample_rate': rate, 'sample_frames': len(audio),
                       'duration_seconds': len(audio)/rate, 'source_frame_offset': 0},
            'qualification': entry.get('review_qualification',
                '제작자 제공 instrumental 음원입니다. 별도 클릭·MIDI 지도와 원점 정합을 확인했으며, 기준 지도는 이 화면에 표시하지 않습니다.'
                if entry.get('dataset')=='forestry_producer_pilot' else
                '합성 MIDI 기반 회귀 표본입니다. 기준 지도와의 일치 여부는 검토 후 별도로 평가합니다.'),
            'waveform': peaks, 'maps': blind_maps})
        key['tracks'].append({'id': track_id, 'choices': correspondence})
    if not bundle['tracks']:
        raise ValueError('no reviewable audio tracks')
    base = Path(__file__).parent
    state_js = (base/'review_clock.mjs').read_text().replace('export ', '')
    payload = json.dumps(bundle, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    page = (base/'review_page.html').read_text().replace('__REVIEW_DATA__', payload).replace('__REVIEW_STATE__', state_js)
    (output_dir/'index.html').write_text(page, encoding='utf-8')
    (output_dir/'evaluation-key.json').write_text(json.dumps(key, indent=2)+'\n')
    (output_dir/'manifest.json').write_text(json.dumps({
        'generator_sha256': sha256(__file__), 'state_sha256': sha256(base/'review_clock.mjs'),
        'page_sha256': sha256(base/'review_page.html'), 'input_reports': [{'path': str(p), 'sha256': sha256(p)} for p in reports+candidate_reports],
        'tracks': [{'id': t['id'], 'source': t['source'], 'candidate_count': len(t['maps'])} for t in bundle['tracks']],
        'human_sessions_collected': 0, 'correction_time_improvement_measured': False,
        'reference_annotations_embedded': False}, indent=2)+'\n')
    return output_dir/'index.html'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalogs', nargs='+', type=Path, required=True)
    p.add_argument('--reports', nargs='+', type=Path, required=True)
    p.add_argument('--candidate-reports', nargs='*', type=Path, default=[])
    p.add_argument('--tracks', nargs='*')
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    print(build(args.catalogs, args.reports, args.candidate_reports, args.output_dir, args.tracks))


if __name__ == '__main__':
    main()
