"""Evaluation separation and qualification tests with constructed clocks only."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import score_joint_guide_pilot as scorer

QUAL = {'clock_timing': True, 'bar_timing': True, 'meter': True, 'grouping': True}


def clock(n=6, d=8, bpm=80., *, duration=18., sample_rate=48000, shift=0., grouping=None):
    return {'schema_version': 1,
        'source': {'sha256': '0' * 64, 'sample_rate': sample_rate, 'sample_frames': round(duration * sample_rate)},
        'clock_knots': [{'pulse': -12., 'source_seconds': -12 * 60 / bpm + shift},
                        {'pulse': 96., 'source_seconds': 96 * 60 / bpm + shift}],
        'quarters_per_pulse': {'numerator': 1, 'denominator': 1},
        'meter_events': [{'pulse': -12., 'numerator': n, 'denominator': d,
                          'grouping': grouping, 'bar_action': 'continue'}],
        'bar_anchor_pulse': 0., 'shared_origin_id': None, 'support_seconds': [[0., duration]],
        'accepted': False, 'reference_qualification': deepcopy(QUAL)}


def known(reference=None):
    return {'primary': {'map': reference or clock(), 'qualification': deepcopy(QUAL)},
            'hypotheses': [], 'expected_guide_unit': Fraction(1, 2)}


def joint(proposal=None, **extra):
    return {'status': 'unaccepted_joint_map_hypothesis', 'map': proposal, **extra}


def bind_json(path, value):
    scorer.save(path, value)
    return scorer.binding(path)


def completed_ledger(root, outputs=None):
    inference = bind_json(root / 'inference.json', {'purpose': 'constructed scorer test only'})
    config = bind_json(root / 'prediction-configuration.json', {'cases': [{'id': 'probe'}], 'inference_manifest': inference})
    if outputs is None:
        outputs = {'existing_unhinted': {'execution': 'saved_native_clock'},
                   'guide_only': {'status': 'unresolved_unit_native_candidate'},
                   'joint_only': joint(clock()), 'guide_joint': joint(clock())}
    bindings = {name: bind_json(root / (name + '.json'), outputs[name]) for name in scorer.METHODS}
    ledger = {'configuration': config, 'complete': True, 'references_opened': False,
              'scoring_performed': False, 'rows': [{'id': 'probe', 'outputs': bindings}]}
    path = root / 'prediction-manifest.json'; scorer.save(path, ledger)
    return path, ledger, inference


def evaluation(root, inference, ref=None):
    reference = {'id': 'probe', 'reference_map': ref or clock(), 'description': 'constructed clock',
                 'guide_simulation': {'first_stable_note_unit': 'eighth_note'}, 'expected_behavior': 'structural_probe'}
    bound = bind_json(root / 'hidden-reference.json', reference)
    path = root / 'evaluation.json'
    scorer.save(path, {'inference_manifest': inference, 'methods': list(scorer.METHODS),
        'timing_tolerances_seconds': list(scorer.TOLERANCES),
        'cases': [{'id': 'probe', 'reference_kind': 'constructed_decoder_fixture', 'reference': bound}]})
    return path


def owner_entry(root):
    reference = clock(sample_rate=44100)
    window = {'seconds': [0., 13.5], 'sample_rate': 44100, 'start_frame': 0, 'end_frame_exclusive': 595350}
    audio = {'sha256': reference['source']['sha256']}
    meter = {'numerator': 6, 'denominator': 8}
    view = bind_json(root / 'source-view.json', {'map': reference})
    approval = bind_json(root / 'bar-owner.json', {'choice': 'A', 'source_audio': audio,
        'approved_source_window': window, 'approved_bar_events_seconds': [0., 2.25, 4.5, 6.75, 9., 11.25]})
    clarification = bind_json(root / 'meter-owner.json', {'source_audio': audio, 'reviewed_source_window': window,
        'clarified_reference_expectation': {'expected_meter': meter}})
    expectation = bind_json(root / 'expectation.json', {'source_audio': audio, 'reviewed_source_window': window,
        'owner_confirmed_meter': meter, 'owner_interpreted_tap_note_unit': {'quarters_per_tap': {'numerator': 1, 'denominator': 2}}})
    return {'id': 'owner-probe', 'reference_kind': 'owner_reviewed_supplied_map', 'source_map_view': view,
        'owner_bar_decision': approval, 'owner_meter_clarification': clarification, 'reference_expectations': expectation,
        'owner_review_halfopen_window': window, 'closed_metric_support_seconds': [0., 595349 / 44100],
        'endpoint_representation_seconds': 1 / 44100,
        'qualification': {**QUAL, 'grouping': False}, 'qualification_scope': 'supplied-map agreement only'}


class JointGuideScorerTests(unittest.TestCase):
    def test_incomplete_ledger_rejects_before_evaluation_or_label_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest, ledger, inference = completed_ledger(root)
            evaluation_path = evaluation(root, inference)
            ledger['complete'] = False; scorer.save(manifest, ledger)
            reads = []; original = scorer.read_json
            def track(path):
                reads.append(Path(path)); return original(path)
            with patch.object(scorer, 'read_json', side_effect=track):
                with self.assertRaisesRegex(ValueError, 'complete=True'):
                    scorer.score_pilot(manifest, evaluation_path, root / 'scores')
            self.assertEqual(reads, [manifest]); self.assertFalse((root / 'scores').exists())

    def test_completed_flag_cannot_hide_missing_case_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest, ledger, inference = completed_ledger(root)
            eval_path = evaluation(root, inference)
            del ledger['rows'][0]['outputs']['guide_joint']; scorer.save(manifest, ledger)
            with patch.object(scorer, 'load_reference_case', side_effect=AssertionError('label opened')):
                with self.assertRaisesRegex(ValueError, 'four frozen'):
                    scorer.score_pilot(manifest, eval_path, root / 'scores')
            manifest, ledger, inference = completed_ledger(root)
            config = scorer.read_json(ledger['configuration']['path']); config['cases'].append({'id': 'missing'})
            ledger['configuration'] = bind_json(root / 'prediction-configuration.json', config)
            scorer.save(manifest, ledger)
            with self.assertRaisesRegex(ValueError, 'cover its frozen'):
                scorer.load_completed_predictions(manifest)

    def test_changed_prediction_hash_rejects_before_evaluation_file_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest, ledger, inference = completed_ledger(root)
            eval_path = evaluation(root, inference)
            scorer.save(root / 'guide_joint.json', joint(clock(3, 4)))
            reads = []; original = scorer.read_json
            with patch.object(scorer, 'read_json', side_effect=lambda path: (reads.append(Path(path)), original(path))[1]):
                with self.assertRaisesRegex(ValueError, 'bound artifact changed'):
                    scorer.score_pilot(manifest, eval_path, root / 'scores')
            self.assertNotIn(eval_path, reads); self.assertNotIn(root / 'hidden-reference.json', reads)

    def test_reference_opened_inference_claim_blocks_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest, ledger, _ = completed_ledger(root)
            ledger['references_opened'] = True; scorer.save(manifest, ledger)
            with self.assertRaisesRegex(ValueError, 'reference-free'):
                scorer.load_completed_predictions(manifest)

    def test_four_arm_end_to_end_preserves_unsupported_and_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = {'existing_unhinted': {'execution': 'saved_native_clock'}, 'guide_only': {'status': 'native_clock'},
                'joint_only': joint(clock(shift=.02)),
                'guide_joint': joint(clock(), guide={'inferred_unit_quarters': {'numerator': 1, 'denominator': 2}}, score_components=None)}
            manifest, _, inference = completed_ledger(root, outputs)
            eval_path = evaluation(root, inference); before = scorer.binding(root / 'hidden-reference.json')
            report = scorer.score_pilot(manifest, eval_path, root / 'scores')
            self.assertTrue(report['complete']); self.assertEqual(report['summary']['case_count'], 1)
            methods = report['summary']['cases'][0]['methods']
            self.assertEqual(methods['existing_unhinted']['prediction_state'], 'unsupported_full_music_map')
            self.assertIsNone(methods['guide_only']['reference_coverage_fraction'])
            self.assertEqual(methods['joint_only']['timing_profiles']['10ms']['bar_boundary_scores']['f1'], 0)
            self.assertEqual(methods['joint_only']['timing_profiles']['20ms']['bar_boundary_scores']['f1'], 1)
            self.assertTrue(methods['guide_joint']['guide_unit']['chosen_matches_expected'])
            self.assertIsNone(report['summary']['overall_product_pass'])
            self.assertEqual(scorer.binding(root / 'hidden-reference.json'), before)
            with self.assertRaises(FileExistsError):
                scorer.score_pilot(manifest, eval_path, root / 'scores')

    def test_budget_no_map_retains_failure_and_never_becomes_zero_accuracy(self):
        result = scorer.evaluate_method('joint_only', {'status': 'budget_exceeded_nodes', 'map': None,
            'resources': {'search_nodes': 80000}}, known(), scorer.TOLERANCES)
        self.assertEqual(result['prediction_state'], 'budget_exceeded')
        self.assertEqual(result['evaluation_status'], 'absent_prediction')
        self.assertEqual(result['coverage']['reference_coverage_fraction'], 0)
        compact = scorer.compact_method(result)
        self.assertTrue(all(p['bar_boundary_scores'] is None for p in compact['timing_profiles'].values()))
        self.assertEqual(result['inference_resources']['search_nodes'], 80000)

    def test_known_map_with_partial_support_does_not_get_full_coverage(self):
        proposal = clock(); proposal['support_seconds'] = [[0., 9.]]
        result = scorer.evaluate_method('joint_only', joint(proposal), known(), scorer.TOLERANCES)
        self.assertAlmostEqual(result['coverage']['reference_coverage_fraction'], .5)
        self.assertEqual(result['coverage']['uncovered_reference_intervals'], [[9., 18.]])
        scores = scorer.compact_method(result)['timing_profiles']['20ms']['bar_boundary_scores']
        self.assertLess(scores['recall'], 1)

    def test_source_mismatch_blocks_scores_without_alignment(self):
        proposal = clock(); proposal['source']['sha256'] = '1' * 64
        result = scorer.evaluate_method('joint_only', joint(proposal), known(), scorer.TOLERANCES)
        self.assertEqual(result['prediction_state'], 'blocked_source_mismatch')
        self.assertEqual(result['evaluation_status'], 'blocked_source_identity_or_sample_clock_mismatch')
        self.assertEqual(scorer.compact_method(result)['timing_profiles'], {})

    def test_ambiguity_preserves_all_conditional_comparisons_without_oracle_winner(self):
        reference = {'primary': None, 'hypotheses': [
            {'map': clock(3, 4, grouping=[1, 1, 1]), 'qualification': QUAL},
            {'map': clock(6, 8, grouping=[3, 3]), 'qualification': QUAL}], 'expected_guide_unit': None}
        result = scorer.evaluate_method('guide_joint', joint(clock(6, 8, grouping=[3, 3])), reference, scorer.TOLERANCES)
        self.assertEqual(result['evaluation_status'], 'unscored_ambiguous_reference')
        self.assertIsNone(result['primary_accuracy_metrics']); self.assertIsNone(result['metrics'])
        self.assertFalse(result['best_reference_hypothesis_selected'])
        self.assertEqual(len(result['conditional_hypothesis_comparisons']), 2)
        self.assertTrue(all(row['diagnostic_only'] for row in result['conditional_hypothesis_comparisons']))

    def test_exact_label_disagreement_stays_distinct_from_unknown_equivalence(self):
        # Both maps contain one bar every2.25s, yet their literal labels differ.
        result = scorer.evaluate_method('joint_only', joint(clock(2, 4, bpm=160 / 3)), known(), scorer.TOLERANCES)
        compact = scorer.compact_method(result)
        self.assertFalse(compact['declared_meter_labels']['declared_signature_sets_match'])
        self.assertTrue(compact['unknown_cross_notation_present'])
        self.assertFalse(compact['known_3_4_6_8_disagreement'])
        self.assertEqual(compact['timing_profiles']['20ms']['bar_boundary_scores']['f1'], 1)
        self.assertEqual(compact['declared_meter_labels']['emitted_meter_events'][0]['numerator'], 2)
        self.assertIsNone(compact['overall_product_pass'])

    def test_later_unreviewed_meter_change_is_retained_but_not_scored_in_owner_window(self):
        ref = clock(sample_rate=44100); ref['support_seconds'] = [[0., 595349 / 44100]]
        proposal = clock(sample_rate=44100)
        proposal['meter_events'].append({'pulse': 18., 'numerator': 4, 'denominator': 4,
                                         'grouping': [1, 1, 1, 1], 'bar_action': 'continue'})
        before = deepcopy(proposal)
        result = scorer.evaluate_method('guide_joint', joint(proposal), known(ref), scorer.TOLERANCES)
        labels = result['declared_meter_labels']
        self.assertEqual([(e['numerator'], e['denominator']) for e in labels['emitted_meter_events']], [(6, 8), (4, 4)])
        self.assertTrue(labels['declared_signature_sets_match'])
        self.assertEqual([(e['numerator'], e['denominator']) for e in labels['scoped_active_emitted_meter_intervals']], [(6, 8)])
        self.assertEqual(labels['comparison_support_seconds'], [[0., 595349 / 44100]])
        self.assertEqual(labels['status'], 'compared_active_labels')
        self.assertFalse(result['metrics']['declared_notation_comparison']['unknown_cross_notation_present'])
        self.assertEqual(proposal, before)

    def test_active_meter_in_supported_interval_includes_earlier_declaration(self):
        ref = clock(); ref['support_seconds'] = [[3., 6.]]
        proposal = clock()
        proposal['meter_events'].append({'pulse': 3., 'numerator': 3, 'denominator': 4,
                                         'grouping': [1, 1, 1], 'bar_action': 'continue'})
        labels = scorer.declared_meter_labels(proposal, known(ref))
        self.assertFalse(labels['declared_signature_sets_match'])
        self.assertEqual(labels['scoped_active_emitted_meter_intervals'][0]['declared_event_pulse'], 3.)
        self.assertEqual(labels['scoped_active_emitted_meter_intervals'][0]['support_seconds'], [[3., 6.]])

    def test_guide_unit_must_be_explicit_and_score_ties_are_not_unique(self):
        reference = known()
        implicit = scorer.emitted_guide_unit_assessment('guide_joint', {'map': clock(), 'guide': {'bpm': 160}}, reference)
        self.assertEqual(implicit['status'], 'no_explicit_unit_emitted')
        result = {'guide': {'inferred_unit_quarters': {'numerator': 1, 'denominator': 1}},
            'score_components': {'total': 10.}, 'alternatives': [{'guide_unit_quarters': {'numerator': 1, 'denominator': 2},
                'score_components': {'total': 10.}}]}
        explicit = scorer.emitted_guide_unit_assessment('guide_joint', result, reference)
        self.assertFalse(explicit['chosen_matches_expected']); self.assertTrue(explicit['expected_in_explicit_tied_units'])
        self.assertFalse(explicit['reference_used_for_unit_choice'])
        result['score_components'] = None
        self.assertEqual(scorer.emitted_guide_unit_assessment('guide_joint', result, reference)['status'], 'compared_explicit_unit')

    def test_owner_halfopen_window_excludes_unheard_bar_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); entry = owner_entry(root)
            original = scorer.read_bound(entry['source_map_view'])
            reference = scorer.load_reference_case(entry)
            result = scorer.evaluate_method('joint_only', joint(clock(sample_rate=44100)), reference, scorer.TOLERANCES)
            self.assertEqual(result['metrics']['reference_expected_geometry']['bar_event_count'], 6)
            self.assertEqual(len(result['metrics']['reference_expected_geometry']['fully_supported_bar_indices']), 5)
            self.assertEqual(len(result['metrics']['reference_expected_geometry']['partly_supported_bar_indices']), 1)
            self.assertEqual(scorer.compact_method(result)['timing_profiles']['20ms']['reference_bar_event_count'], 6)
            self.assertEqual(reference['primary']['map']['support_seconds'], [[0., 595349 / 44100]])
            self.assertAlmostEqual(reference['review_scope']['endpoint_representation_microseconds'], 22.675736961451248)
            self.assertFalse(reference['primary']['qualification']['grouping'])
            self.assertEqual(scorer.read_bound(entry['source_map_view']), original)
            self.assertFalse(reference['review_scope']['full_song_approval'])

    def test_owner_window_cannot_expand_or_use_nearby_floating_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = owner_entry(Path(directory)); entry['closed_metric_support_seconds'][1] = 13.5
            with self.assertRaisesRegex(ValueError, 'last reviewed native sample'):
                scorer.load_reference_case(entry)

    def test_malformed_map_preserves_invalid_state(self):
        result = scorer.evaluate_method('joint_only', joint({'clock_knots': [], 'support_seconds': []}), known(), scorer.TOLERANCES)
        self.assertEqual(result['prediction_state'], 'invalid_map_declaration')
        self.assertEqual(result['evaluation_status'], 'invalid_prediction')
        self.assertIsNone(result['overall_product_pass'])


if __name__ == '__main__':
    unittest.main()
