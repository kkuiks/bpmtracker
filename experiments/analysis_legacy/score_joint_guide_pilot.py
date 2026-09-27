"""Evaluate a frozen joint-guide pilot only after every prediction is persisted.

The completion/integrity gate runs before the evaluation manifest or any label
file is opened. Unsupported native-clock controls are not converted into music
maps using references. Conditional hypotheses never select their own truth.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
import argparse
import hashlib
import json
import math
from pathlib import Path

from music_map_metrics import evaluate_music_maps
from music_map_contract import prepare_map, interpolate_clock

METHODS = ('existing_unhinted', 'guide_only', 'joint_only', 'guide_joint')
MAP_METHODS = frozenset(('joint_only', 'guide_joint'))
TOLERANCES = (.01, .02, .03, .07)
DEFAULT_EVALUATION = Path('data/runs/joint-guide-pilot/2026-09-26-v1/pilot-evaluation-manifest-v1.json')


def read_json(path):
    return json.loads(Path(path).read_text())


def binding(path):
    path = Path(path)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def read_bound(record):
    if not isinstance(record, dict) or not {'path', 'sha256'} <= record.keys():
        raise ValueError('artifact binding requires path and sha256')
    if binding(record['path'])['sha256'] != record['sha256']:
        raise ValueError('bound artifact changed: ' + str(record['path']))
    return read_json(record['path'])


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def load_completed_predictions(manifest_path):
    """Never open an evaluation/label path before this gate has fully passed."""
    document = read_json(manifest_path)
    if document.get('complete') is not True:
        raise ValueError('prediction manifest must be complete=True before opening evaluation references')
    if document.get('references_opened') is not False or document.get('scoring_performed') is not False:
        raise ValueError('prediction ledger must declare reference-free, unscored inference')
    rows = document.get('rows')
    if not isinstance(rows, list) or not rows:
        raise ValueError('completed prediction ledger has no case rows')
    ids = [row.get('id') for row in rows]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError('prediction case IDs must be unique nonempty strings')
    for row in rows:
        if not isinstance(row.get('outputs'), dict) or not set(METHODS) <= row['outputs'].keys():
            raise ValueError('completed case is missing one of the four frozen method outputs')
    configuration = read_bound(document.get('configuration'))
    configured_ids = [case['id'] for case in configuration.get('cases', [])]
    if len(configured_ids) != len(ids) or set(configured_ids) != set(ids):
        raise ValueError('prediction ledger does not cover its frozen configuration')
    outputs = {}
    artifact_bindings = [binding(manifest_path), document['configuration']]
    for row in rows:
        outputs[row['id']] = {}
        for method in METHODS:
            value = read_bound(row['outputs'][method])
            if not isinstance(value, dict):
                raise ValueError('prediction output must be a JSON object')
            outputs[row['id']][method] = value
            artifact_bindings.append(row['outputs'][method])
    # Protect the all-complete decision from a concurrent ledger replacement.
    if binding(manifest_path) != artifact_bindings[0]:
        raise ValueError('prediction ledger changed during completion validation')
    return document, configuration, outputs, artifact_bindings


def _unit(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'numerator', 'denominator'}:
        raise ValueError('emitted guide unit must be an explicit rational')
    for item in value.values():
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError('emitted guide unit must be positive integer ratio')
    return Fraction(value['numerator'], value['denominator'])


def _unit_record(value):
    return None if value is None else {'numerator': value.numerator, 'denominator': value.denominator}


def _fixture_unit(reference):
    name = reference.get('guide_simulation', {}).get('first_stable_note_unit')
    return {'eighth_note': Fraction(1, 2), 'quarter_note': Fraction(1),
            'dotted_quarter_note': Fraction(3, 2), 'half_note': Fraction(2)}.get(name)


def load_reference_case(entry):
    """Called only after the completed-prediction gate by score_pilot."""
    if entry['reference_kind'] == 'constructed_decoder_fixture':
        ref = read_bound(entry['reference'])
        if ref.get('id') != entry['id']:
            raise ValueError('fixture reference ID differs from frozen evaluation case')
        primary = ref.get('reference_map')
        if primary is None:
            hypotheses = ref.get('reference_hypotheses')
            if not isinstance(hypotheses, list) or len(hypotheses) < 2:
                raise ValueError('ambiguous fixture must retain multiple explicit hypotheses')
            return {'status': 'ambiguous_multiple_compatible_hypotheses', 'kind': entry['reference_kind'],
                'description': ref.get('description', entry['id']), 'primary': None,
                'hypotheses': [{'map': value, 'qualification': value['reference_qualification']} for value in hypotheses],
                'expected_behavior': ref.get('expected_behavior'), 'expected_guide_unit': None,
                'group': 'synthetic_ambiguity_control', 'bindings': [entry['reference']],
                'evidence_scope': 'constructed ambiguous decoder input; no unique correctness target or oracle best truth'}
        return {'status': 'known_constructed_map', 'kind': entry['reference_kind'],
            'description': ref.get('description', entry['id']),
            'primary': {'map': primary, 'qualification': primary['reference_qualification']}, 'hypotheses': [],
            'expected_behavior': ref.get('expected_behavior'), 'expected_guide_unit': _fixture_unit(ref),
            'group': 'synthetic_weak_evidence_control' if str(ref.get('expected_behavior', '')).startswith('insufficient_') else 'synthetic_structural_probe',
            'bindings': [entry['reference']],
            'evidence_scope': 'known manufactured decoder fixture; no acoustic-model or real-music accuracy claim'}
    if entry['reference_kind'] != 'owner_reviewed_supplied_map':
        raise ValueError('unsupported evaluation reference kind')
    keys = ('source_map_view', 'owner_bar_decision', 'owner_meter_clarification', 'reference_expectations')
    view, bar, clarification, expectation = [read_bound(entry[key]) for key in keys]
    reference = deepcopy(view.get('map'))
    if reference is None:
        raise ValueError('supplied source-map view is unavailable')
    window = entry['owner_review_halfopen_window']
    source = reference['source']; sr = source['sample_rate']
    if sr != window['sample_rate'] or not (0 <= window['start_frame'] < window['end_frame_exclusive'] <= source['sample_frames']):
        raise ValueError('owner-review window and source sample clock disagree')
    expected_halfopen = [window['start_frame'] / sr, window['end_frame_exclusive'] / sr]
    closed = [window['start_frame'] / sr, (window['end_frame_exclusive'] - 1) / sr]
    if window['seconds'] != expected_halfopen or entry['closed_metric_support_seconds'] != closed:
        raise ValueError('closed metric support must end at the last reviewed native sample')
    if entry['endpoint_representation_seconds'] != 1 / sr:
        raise ValueError('native-sample endpoint disclosure differs from source clock')
    if (bar.get('choice') != 'A' or bar['approved_source_window']['seconds'] != expected_halfopen or
            bar['approved_source_window']['start_frame'] != window['start_frame'] or
            bar['approved_source_window']['end_frame_exclusive'] != window['end_frame_exclusive']):
        raise ValueError('bar approval does not cover the declared evaluation window')
    if (clarification['reviewed_source_window']['seconds'] != expected_halfopen or
            expectation['reviewed_source_window']['seconds'] != expected_halfopen):
        raise ValueError('meter clarification is not scoped to the same reviewed window')
    if any(record['source_audio']['sha256'] != source['sha256'] for record in (bar, clarification, expectation)):
        raise ValueError('owner records and map refer to different source audio')
    expected_meter = expectation['owner_confirmed_meter']
    if expected_meter != clarification['clarified_reference_expectation']['expected_meter']:
        raise ValueError('owner meter expectations disagree')
    active = [event for event in reference['meter_events'] if event['pulse'] <= 0]
    if not active or {k: active[-1][k] for k in ('numerator', 'denominator')} != expected_meter:
        raise ValueError('supplied initial meter differs from owner clarification; no reference repair permitted')
    if not any(lo <= closed[0] < closed[1] <= hi for lo, hi in reference['support_seconds']):
        raise ValueError('owner window cannot extend the original reference support')
    qualification = entry['qualification']
    if qualification != {'clock_timing': True, 'bar_timing': True, 'meter': True, 'grouping': False}:
        raise ValueError('GMD qualification must remain supplied-clock agreement with unknown grouping')
    original_support = deepcopy(reference['support_seconds'])
    reference['support_seconds'] = [closed]
    reference['reference_qualification'] = qualification
    geometry = evaluate_music_maps(reference, None, reference_qualification=qualification,
                                  tolerances_seconds=TOLERANCES)
    if geometry.get('reference_expected_geometry', {}).get('bar_event_count') != len(bar['approved_bar_events_seconds']):
        raise ValueError('metric reference includes an unheard or unapproved bar event')
    return {'status': 'owner_window_supplied_map_agreement', 'kind': entry['reference_kind'],
        'description': 'GMD 6/8 · 실제 사용자 탭 약160',
        'primary': {'map': reference, 'qualification': qualification}, 'hypotheses': [],
        'expected_guide_unit': _unit(expectation['owner_interpreted_tap_note_unit']['quarters_per_tap']),
        'expected_behavior': 'conditional agreement with owner-reviewed bar/meter interpretation; not full-song or new precision certification',
        'group': 'actual_audio_owner_reviewed_window', 'bindings': [entry[key] for key in keys],
        'evidence_scope': entry['qualification_scope'],
        'review_scope': {'original_halfopen_seconds': expected_halfopen, 'source_frame_range': [window['start_frame'], window['end_frame_exclusive']],
            'closed_metric_support_seconds': closed, 'endpoint_representation_seconds': 1 / sr,
            'endpoint_representation_microseconds': 1e6 / sr,
            'original_reference_support_unchanged': original_support, 'unheard_right_endpoint_scored': False,
            'full_song_approval': False, 'new_absolute_timing_bound': None, 'grouping_qualified': False,
            'clock_comparison_is_conditional_supplied_map_agreement': True}}


def emitted_guide_unit_assessment(method, result, reference):
    """Read explicit chosen/tied units only; never derive one from BPM or truth."""
    if method != 'guide_joint':
        return {'status': 'not_an_explicit_joint_guide_unit_output', 'inferred_from_reference': False}
    guide = result.get('guide') or {}
    if guide.get('inferred_unit_quarters') is None:
        return {'status': 'no_explicit_unit_emitted', 'inferred_from_reference': False}
    try:
        chosen = _unit(guide['inferred_unit_quarters'])
        tied = {chosen}
        score_components = result.get('score_components')
        if score_components is not None and not isinstance(score_components, dict):
            raise ValueError('emitted score components must be an object or null')
        total = (score_components or {}).get('total')
        if isinstance(total, (int, float)) and math.isfinite(total):
            for alternative in result.get('alternatives', []):
                components = alternative.get('score_components')
                if components is not None and not isinstance(components, dict):
                    raise ValueError('alternative score components must be an object or null')
                value = (components or {}).get('total')
                if isinstance(value, (int, float)) and math.isfinite(value) and abs(value - total) <= 1e-9:
                    unit = _unit(alternative.get('guide_unit_quarters'))
                    if unit is not None:
                        tied.add(unit)
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        return {'status': 'invalid_emitted_unit_metadata', 'reason': str(exc), 'inferred_from_reference': False}
    expected = reference['expected_guide_unit']
    return {'status': 'compared_explicit_unit' if expected is not None else 'unscored_ambiguous_or_missing_reference_unit',
        'chosen_unit_quarters': _unit_record(chosen), 'explicit_retained_score_tied_units': [_unit_record(u) for u in sorted(tied)],
        'expected_unit_quarters': _unit_record(expected),
        'chosen_matches_expected': chosen == expected if expected is not None else None,
        'expected_in_explicit_tied_units': expected in tied if expected is not None else None,
        'reference_used_for_unit_choice': False, 'inferred_from_reference': False,
        'comparison_does_not_certify_unique_interpretation': True,
        'source_only_guide_window': result.get('guide_window')}


def prediction_state(method, result):
    if method not in MAP_METHODS:
        return 'unsupported_full_music_map'
    proposal = result.get('map')
    status = str(result.get('status', 'unknown'))
    if proposal is not None:
        if not isinstance(proposal, dict):
            return 'invalid_map_declaration'
        return 'empty_map_declaration' if not proposal.get('clock_knots') or not proposal.get('support_seconds') else 'map_returned'
    if status.startswith('budget_exceeded'):
        return 'budget_exceeded'
    if status == 'execution_error':
        return 'execution_error'
    if status == 'no_guide_supplied':
        return 'guide_unavailable'
    if any(word in status for word in ('ambiguous', 'unresolved', 'insufficient', 'no_supported')):
        return 'unresolved_or_abstained'
    return 'no_map_output'


def _support_intersection(left, right):
    return [[max(a, c), min(b, d)] for a, b in left for c, d in right if max(a, c) < min(b, d)]


def _active_meter_intervals(prepared, support):
    """Project declared active labels into physical support without alignment."""
    knots = prepared['clock_knots']; events = prepared.get('meter_events') or []
    if not knots:
        return []
    lower, upper = knots[0]['pulse'], knots[-1]['pulse']
    rows = []
    for index, event in enumerate(events):
        start = max(lower, event['pulse'])
        end = min(upper, events[index + 1]['pulse'] if index + 1 < len(events) else upper)
        if start >= end:
            continue
        span = [[interpolate_clock(knots, start), interpolate_clock(knots, end)]]
        active = _support_intersection(span, support)
        if active:
            rows.append({'declared_event_pulse': event['pulse'], 'support_seconds': active,
                         **{key: event[key] for key in ('numerator', 'denominator', 'grouping')}})
    return rows


def declared_meter_labels(proposal, reference):
    """Keep all declarations, but compare labels only on qualified shared time."""
    events = proposal.get('meter_events', []) if isinstance(proposal, dict) else []
    emitted = [{key: event.get(key) for key in ('pulse', 'numerator', 'denominator', 'grouping')}
               for event in events if isinstance(event, dict)] if isinstance(events, list) else []
    primary = reference.get('primary')
    expected = ([{key: event.get(key) for key in ('pulse', 'numerator', 'denominator', 'grouping')}
                 for event in primary['map'].get('meter_events', [])]
                if primary is not None and primary['qualification'].get('meter') is True else None)
    result = {'emitted_meter_events': emitted, 'qualified_reference_meter_events': expected,
        'raw_event_lists_scope': 'complete declarations retained for inspection; events outside qualified reference time are not label errors',
        'signature_comparison_scope': 'active labels within intersection of prediction support and qualified reference support; positive-duration intervals only',
        'reference_support_seconds': primary['map'].get('support_seconds') if primary else None,
        'comparison_support_seconds': [], 'scoped_active_emitted_meter_intervals': [],
        'scoped_active_reference_meter_intervals': [], 'declared_signature_sets_match': None,
        'signature_set_match_does_not_check_change_times': True,
        'different_labels_do_not_resolve_unapproved_cross_notation_equivalence': True}
    if proposal is None or expected is None:
        return {**result, 'status': 'no_prediction_or_qualified_unique_reference_meter'}
    try:
        pred = prepare_map(proposal); ref = prepare_map(primary['map'])
        if any(pred['source'][key] != ref['source'][key] for key in ('sha256', 'sample_rate', 'sample_frames')):
            return {**result, 'status': 'blocked_source_identity_or_sample_clock_mismatch'}
        support = _support_intersection(ref['support_seconds'], pred['support_seconds'])
        active_pred = _active_meter_intervals(pred, support)
        active_ref = _active_meter_intervals(ref, support)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {**result, 'status': 'invalid_map_declaration', 'reason': str(exc)}
    pred_set = {(v['numerator'], v['denominator']) for v in active_pred}
    ref_set = {(v['numerator'], v['denominator']) for v in active_ref}
    return {**result, 'status': 'compared_active_labels' if pred_set and ref_set else 'no_common_active_meter_support',
        'comparison_support_seconds': support, 'scoped_active_emitted_meter_intervals': active_pred,
        'scoped_active_reference_meter_intervals': active_ref,
        'declared_signature_sets_match': pred_set == ref_set if pred_set and ref_set else None}


def evaluate_method(method, result, reference, tolerances):
    row = {'method': method, 'prediction_state': prediction_state(method, result),
        'reported_prediction_status': result.get('status', result.get('execution', 'not_reported')),
        'full_music_map_capability': method in MAP_METHODS,
        'metrics': None, 'conditional_hypothesis_comparisons': [],
        'guide_unit': emitted_guide_unit_assessment(method, result, reference),
        'inference_resources': result.get('resources'), 'inference_diagnostics': result.get('diagnostics'),
        'runner_elapsed_seconds': result.get('runner_elapsed_seconds'),
        'inferred_map_is_accepted': (result.get('map') or {}).get('accepted') if isinstance(result.get('map'), dict) else None,
        'declared_meter_labels': declared_meter_labels(result.get('map'), reference),
        'overall_product_pass': None}
    if method not in MAP_METHODS:
        row.update(evaluation_status='unscored_unsupported_full_music_map',
            coverage={'status': 'unscored_unsupported_full_music_map', 'reference_coverage_fraction': None},
            reason='Existing and guide-only paths retain unresolved musical units/meter; evaluator supplies neither from labels.',
            selected_candidate_id=result.get('selected_candidate_id'),
            tied_selected_candidate_ids=result.get('tied_selected_candidate_ids'))
        return row
    proposal = result.get('map')
    if reference['primary'] is None:
        row.update(evaluation_status='unscored_ambiguous_reference', coverage=None,
            ambiguity_response='no_map_submitted' if proposal is None else 'hypothesis_submitted_on_nonunique_input',
            primary_accuracy_metrics=None, best_reference_hypothesis_selected=False)
        for index, hypothesis in enumerate(reference['hypotheses']):
            row['conditional_hypothesis_comparisons'].append({'hypothesis_index': index,
                'diagnostic_only': True, 'not_primary_accuracy_or_an_oracle_winner': True,
                'metrics': evaluate_music_maps(hypothesis['map'], proposal,
                    reference_qualification=hypothesis['qualification'], tolerances_seconds=tolerances)})
        return row
    known = reference['primary']
    metrics = evaluate_music_maps(known['map'], proposal, reference_qualification=known['qualification'],
                                 tolerances_seconds=tolerances)
    row.update(metrics=metrics, evaluation_status=metrics['status'], coverage=metrics.get('coverage'))
    if metrics.get('prediction_status') == 'invalid_prediction':
        row['prediction_state'] = 'invalid_map_declaration'
    if metrics['status'] == 'blocked_source_identity_or_sample_clock_mismatch':
        row['prediction_state'] = 'blocked_source_mismatch'
    return row


def compact_method(row):
    metrics = row.get('metrics')
    profiles = {}
    if metrics:
        for profile in metrics.get('timing_profiles', []):
            label = f"{round(profile['tolerance_seconds'] * 1000)}ms"
            boundary = profile.get('bar_boundaries') or {}
            paired = profile.get('paired_bars') or {}
            continuous = paired.get('continuous_timing_summary') or {}
            profiles[label] = {'status': profile['status'], 'reference_bar_event_count': profile['reference_bar_event_count'],
                'bar_boundary_scores': boundary.get('scores'), 'paired_bar_count': paired.get('count'),
                'continuous_max_seconds': continuous.get('absolute_max_seconds'),
                'continuous_mean_seconds': continuous.get('absolute_mean_seconds'),
                'continuous_scope': 'conditional on both bar endpoints corresponding; no fitted alignment'}
    return {'prediction_state': row['prediction_state'], 'evaluation_status': row['evaluation_status'],
        'reported_prediction_status': row['reported_prediction_status'],
        'reference_coverage_fraction': (row.get('coverage') or {}).get('reference_coverage_fraction'),
        'timing_profiles': profiles,
        'notation_relation_counts': (metrics or {}).get('declared_notation_comparison', {}).get('notation_relation_counts'),
        'known_3_4_6_8_disagreement': (metrics or {}).get('declared_notation_comparison', {}).get('known_notation_disagreement'),
        'unknown_cross_notation_present': (metrics or {}).get('declared_notation_comparison', {}).get('unknown_cross_notation_present'),
        'declared_meter_labels': row.get('declared_meter_labels'),
        'guide_unit': row.get('guide_unit'), 'overall_product_pass': None}


def summarize(cases):
    groups = sorted({case.get('reference_group', 'reference_error') for case in cases})
    return {'case_count': len(cases), 'aggregate_accuracy_not_pooled': True, 'overall_product_pass': None,
        'by_reference_group': {group: {'case_count': sum(case.get('reference_group', 'reference_error') == group for case in cases),
            'method_states': {method: dict(Counter(case['methods'][method]['prediction_state']
                for case in cases if case.get('reference_group', 'reference_error') == group)) for method in METHODS}}
            for group in groups},
        'cases': [{'id': case['id'], 'description': case.get('description', case['id']),
            'reference_status': case['reference_status'], 'reference_group': case.get('reference_group'),
            'methods': {method: compact_method(case['methods'][method]) for method in METHODS}} for case in cases]}


def korean_summary(summary):
    lines = ['# 제한된 가이드·공동 추론 실험: 평가 결과', '',
        '예측 저장 완료와 파일 해시를 확인한 뒤 정답을 열었습니다. 합성 활성값 시험과 실제 GMD 청취 구간을 섞어 평균 정확도를 만들지 않았습니다. 제품 합격 판정은 하지 않습니다.', '',
        '기존 경로와 가이드 선택 경로는 완성 음악 지도 미지원으로 남깁니다. 빈 출력·근거 부족·계산 한도·실행 오류도 모든 사례에 기록합니다.', '',
        '| 사례 | 경로 | 출력 상태 | 참조 구간 포함률 | 마디 경계 F1@20ms | 대응 마디 안 최대 오차 |',
        '|---|---|---|---:|---:|---:|']
    for case in summary['cases']:
        for method in ('joint_only', 'guide_joint'):
            row = case['methods'][method]; profile = row['timing_profiles'].get('20ms', {})
            coverage = row.get('reference_coverage_fraction'); score = (profile.get('bar_boundary_scores') or {}).get('f1')
            error = profile.get('continuous_max_seconds')
            cells = [case['id'], '공동 추론' if method == 'joint_only' else '가이드 + 공동 추론', row['prediction_state'],
                '평가 불가' if coverage is None else f'{coverage*100:.2f}%',
                '평가 불가' if score is None else f'{score*100:.2f}%',
                '평가 불가' if error is None else f'{error*1000:.3f}ms']
            lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', '표의 연속 오차는 시작·끝 경계가 대응된 마디에 한정됩니다. 낮은 오차만으로 누락 구간이나 틀린 박자가 해결됐다고 볼 수 없습니다. 10·20·30·70ms 전체 프로필, 박자 시간대 비교, 미지원·빈 결과는 곡별 JSON에 있습니다.', '',
        '실제 GMD 평가는 청취한 [0,13.5)초에 한정됩니다. 닫힌 구간 계산에는 마지막으로 들은 샘플인 13.499977324초까지 사용했습니다(끝점 표현 차이 22.675737µs). 마디·6/8 해석 확인과 별개로, 그룹 내부 정밀도나 원본 녹음 클릭의 밀리초 정확도가 새로 검증된 것은 아닙니다.', '',
        '여러 해석이 가능한 합성 대조군은 정답을 가장 잘 맞추는 해석을 골라 정확도로 보고하지 않습니다. 가이드 음표 단위도 모델이 직접 선언한 값만 비교하며, 평가자가 정답으로 보충하지 않습니다.', '']
    return '\n'.join(lines)


def score_pilot(prediction_manifest, evaluation_manifest, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError('evaluation output must be new; preserve prior snapshots')
    ledger, prediction_config, predictions, prediction_bindings = load_completed_predictions(prediction_manifest)
    # This is intentionally the FIRST evaluation-side file read in this entry point.
    evaluation = read_json(evaluation_manifest)
    entries = evaluation.get('cases', [])
    ids = [entry.get('id') for entry in entries]
    if len(ids) != len(predictions) or len(set(ids)) != len(ids) or set(ids) != set(predictions):
        raise ValueError('evaluation cases must cover the complete frozen prediction cohort exactly')
    if evaluation.get('methods') != list(METHODS):
        raise ValueError('evaluation method list differs from frozen four-arm comparison')
    if evaluation.get('timing_tolerances_seconds') != list(TOLERANCES):
        raise ValueError('pilot requires the frozen10/20/30/70ms profiles')
    inferred_manifest = prediction_config.get('inference_manifest')
    if inferred_manifest is not None and evaluation.get('inference_manifest') != inferred_manifest:
        raise ValueError('evaluation manifest does not bind the same inference cohort')
    config = {'schema_version': 1, 'evaluation_started_at_utc': datetime.now(timezone.utc).isoformat(),
        'prediction_manifest': prediction_bindings[0], 'prediction_configuration': ledger['configuration'],
        'evaluation_manifest': binding(evaluation_manifest),
        'gate': 'completeTrue, allcase/all4output bindings validated before first evaluation manifest or reference read',
        'sources': {name: binding(Path(__file__).with_name(name)) for name in
                    ('score_joint_guide_pilot.py', 'music_map_metrics.py', 'music_map_contract.py', 'musical_units.py')},
        'overall_product_pass': None, 'canonical_quarter_scores': 'not calculated; no quarter units invented for old methods'}
    output.mkdir(parents=True)
    save(output / 'configuration.json', config)
    report = {'configuration': binding(output / 'configuration.json'), 'complete': False,
              'scoring_began_after_all_predictions_persisted': True, 'cases': []}
    save(output / 'report.json', report)
    reference_bindings = []
    for entry in entries:
        case = {'id': entry['id'], 'methods': {}}
        try:
            reference = load_reference_case(entry)
            reference_bindings.extend(reference['bindings'])
            case.update(reference_status=reference['status'], reference_group=reference['group'],
                description=reference['description'], expected_behavior=reference['expected_behavior'],
                reference_evidence_scope=reference['evidence_scope'], reference_review_scope=reference.get('review_scope'))
            if reference['primary'] is not None:
                primary = reference['primary']
                expected = evaluate_music_maps(primary['map'], None,
                    reference_qualification=primary['qualification'], tolerances_seconds=TOLERANCES)
                case['reference_expected_geometry'] = expected.get('reference_expected_geometry')
                case['reference_qualification'] = primary['qualification']
            else:
                case['reference_expected_geometry'] = None
                case['unique_reference_hypothesis_selected'] = False
            for method in METHODS:
                case['methods'][method] = evaluate_method(method, predictions[entry['id']][method], reference, TOLERANCES)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            case.update(reference_status='reference_or_evaluation_error', error=f'{type(exc).__name__}: {exc}')
            for method in METHODS:
                case['methods'].setdefault(method, {'method': method,
                    'prediction_state': prediction_state(method, predictions[entry['id']][method]),
                    'reported_prediction_status': predictions[entry['id']][method].get('status'),
                    'evaluation_status': 'reference_or_evaluation_error', 'metrics': None,
                    'coverage': None, 'guide_unit': {'status': 'not_scored'}, 'overall_product_pass': None})
        save(output / 'cases' / (entry['id'] + '.json'), case)
        report['cases'].append(case)
        report['summary'] = summarize(report['cases'])
        save(output / 'report.json', report)
    for record in prediction_bindings + reference_bindings + [config['evaluation_manifest'], *config['sources'].values()]:
        if binding(record['path'])['sha256'] != record['sha256']:
            raise ValueError('frozen prediction/reference/evaluator changed during scoring')
    report['complete'] = True
    save(output / 'report.json', report)
    save(output / 'summary.json', report['summary'])
    (output / 'summary.ko.md').write_text(korean_summary(report['summary']))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--evaluation', type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = score_pilot(args.predictions, args.evaluation, args.output)
    print(json.dumps({'complete': report['complete'], 'case_count': len(report['cases'])}))


if __name__ == '__main__':
    main()
