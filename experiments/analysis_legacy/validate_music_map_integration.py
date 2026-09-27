"""Replay frozen adapters through the component comparator without inference.

Self-comparisons are serialization checks, never model accuracy. Saved model
outputs retain their declared capabilities, including unresolved pulse units.
No reference field is supplied to an analyzer or prediction adapter here.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from music_map_metrics import evaluate_music_maps


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path, expected=None):
    path = Path(path)
    if expected is not None and digest(path) != expected:
        raise ValueError(f'input hash mismatch: {path}')
    return json.loads(path.read_text())


def run(reference_root, prediction_root, output_dir, owner_decisions):
    reference_root, prediction_root, output_dir = map(Path, (reference_root, prediction_root, output_dir))
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError('integration output must be new or empty')
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_report = read(reference_root / 'report.json')
    prediction_report = read(prediction_root / 'manifest.json')
    if not prediction_report['complete']:
        raise ValueError('prediction views are incomplete')
    decisions = read(owner_decisions)
    read(decisions['review_manifest_path'], decisions['review_manifest_sha256'])
    bindings = []
    references = {}
    self_rows = []
    for entry in reference_report['rows']:
        path = Path(entry['view_file'])
        view = read(path)
        bindings.append({'path': str(path), 'sha256': digest(path)})
        references[entry['id']] = view
        if view.get('map') is None:
            self_rows.append({'id': entry['id'], 'status': 'excluded_reference', 'reason': view.get('reason')})
            continue
        comparison = evaluate_music_maps(view['map'], view['map'],
                                         reference_qualification=view['reference_qualification'])
        if comparison['status'] != 'compared':
            raise AssertionError(f'self comparison invalid: {entry["id"]}')
        profiles = []
        for profile in comparison['timing_profiles']:
            row = {'tolerance_seconds': profile['tolerance_seconds'], 'status': profile['status']}
            if profile['status'] == 'scored_components':
                boundaries = profile['bar_boundaries']
                summary = profile['paired_bars']['continuous_timing_summary']
                if boundaries['scores']['f1'] != 1 or summary['absolute_max_seconds'] != 0:
                    raise AssertionError(f'self comparison loses declared geometry: {entry["id"]}')
                expected = entry.get('bar_parity', {}).get('reference_count')
                if expected is not None and boundaries['reference_event_count'] != expected:
                    raise AssertionError(f'reference event count changed: {entry["id"]}')
                row.update(reference_bar_count=boundaries['reference_event_count'],
                           maximum_self_error_seconds=summary['absolute_max_seconds'])
            profiles.append(row)
        self_rows.append({'id': entry['id'], 'status': view['status'], 'profiles': profiles,
                          'validation_only_not_accuracy': True})
    comparisons = []
    unavailable = []
    counts = Counter()
    for entry in prediction_report['rows']:
        key = f'{entry["id"]}::{entry["model"]}'
        if entry['status'] != 'adapted':
            unavailable.append({'case': key, 'status': entry['status'], 'reason': entry.get('error')})
            continue
        ref = references[entry['id']]
        for family, binding in entry['outputs'].items():
            bundle = read(binding['path'], binding['sha256'])
            bindings.append({'path': binding['path'], 'sha256': binding['sha256']})
            methods = bundle.get('methods', bundle.get('candidate_views', {}))
            for method, adapted in methods.items():
                item = {'case': key, 'family': family, 'method': method,
                        'prediction_status': adapted['status'], 'original_status': adapted.get('original_status')}
                if ref.get('map') is None:
                    item.update(status='reference_unavailable_for_map_comparison', reason=ref.get('reason'))
                else:
                    result = evaluate_music_maps(ref['map'], adapted['map'],
                                                 reference_qualification=ref['reference_qualification'])
                    if result['status'] != 'compared':
                        raise AssertionError(f'adapter source mismatch or invalid comparison: {key}/{family}/{method}')
                    if result['overall_product_pass'] is not None or result['alignment_applied']:
                        raise AssertionError('integration promoted a result or estimated alignment')
                    item.update(status=result['status'], coverage=result['coverage'],
                                reference_render_status=result['reference']['render_status'],
                                prediction_render_status=result['prediction']['render_status'],
                                timing_profiles=[{k: p.get(k) for k in ('tolerance_seconds', 'status', 'reason', 'reference_bar_event_count')}
                                                 for p in result['timing_profiles']])
                counts[(family, item['status'], item.get('prediction_render_status'))] += 1
                comparisons.append(item)
    result = {'scope': 'adapter/comparator integration validation; no new model performance estimate',
              'reference_self_checks': self_rows, 'saved_prediction_comparisons': comparisons,
              'unavailable_cases': unavailable,
              'summary': [{'family': key[0], 'status': key[1], 'prediction_render_status': key[2], 'count': count}
                          for key, count in sorted(counts.items(), key=lambda x: str(x[0]))],
              'inputs': bindings,
              'source_code': {name: digest(Path(__file__).with_name(name)) for name in
                              ('validate_music_map_integration.py', 'music_map_metrics.py', 'music_map_contract.py', 'musical_units.py')},
              'owner_decisions': {'path': str(owner_decisions), 'sha256': digest(owner_decisions)},
              'existing_references_or_predictions_modified': False,
              'new_model_inference_performed': False, 'reference_used_to_choose_prediction_unit': False}
    (output_dir/'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'reference_rows': len(self_rows), 'saved_method_views': len(comparisons),
                      'unavailable_cases': len(unavailable), 'summary': result['summary']}, ensure_ascii=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--prediction-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--owner-decisions', type=Path, required=True)
    args = parser.parse_args()
    run(args.reference_root, args.prediction_root, args.output_dir, args.owner_decisions)


if __name__ == '__main__':
    main()
