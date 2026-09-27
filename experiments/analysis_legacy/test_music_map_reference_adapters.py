from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from music_map_reference_adapters import adapt_supplied_reference, compare_bar_parity, build_reference_views


def fixture(*, numerator=4, denominator=4, origin=0., support=None):
    support = [0., 7.] if support is None else support
    track = {'id': 'synthetic_reference', 'reference_tier': 'synthetic_authored_clock',
        'input': {'kind': 'audio', 'path': 'synthetic.wav', 'sha256': 'a' * 64},
        'sample_rate': 48000, 'sample_frames': 480000}
    length = 4 * numerator / denominator
    downbeats = []
    q = 0.
    while origin + q / 2 <= 7.:
        if origin + q / 2 >= support[0]:
            downbeats.append(origin + q / 2)
        q += length
    reference = {'kind': 'authored_midi_quarter_clock', 'ticks_per_quarter': 96,
        'explicit_initial_tempo': True, 'explicit_initial_meter': True,
        'source_audio_sha256': 'a' * 64, 'source_origin_shift_seconds': origin,
        'tempo_events': [{'tick': 0, 'time_seconds': origin, 'bpm_quarter': 120., 'microseconds_per_quarter': 500000}],
        'meter_events': [{'tick': 0, 'time_seconds': origin, 'numerator': numerator, 'denominator': denominator}],
        'evaluation_support_seconds': support, 'downbeats_seconds': downbeats}
    return reference, track


def adapt(reference, track):
    return adapt_supplied_reference(reference, track, retained_for_primary_scores=True)


class ReferenceAdapterTests(unittest.TestCase):
    def test_native_view_preserves_unknown_grouping_and_does_not_promote_truth(self):
        reference, track = fixture()
        before = deepcopy(reference)
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'adapted')
        self.assertEqual(result['bar_parity']['status'], 'passed')
        self.assertEqual(result['view'], 'supplied_map_agreement')
        self.assertFalse(result['reference_qualification']['grouping'])
        self.assertTrue(result['reference_qualification']['clock_timing'])
        self.assertIn('not_independent', result['evidence_scope'])
        self.assertIsNone(result['map']['shared_origin_id'])
        self.assertEqual(result['map']['clock_knots'][-1], {'pulse': 14., 'source_seconds': 7.})
        self.assertEqual(reference, before)

    def test_negative_accepted_anchor_retains_original_coordinate_and_exact_support(self):
        reference, track = fixture(origin=-.25, support=[.25, 6.75])
        reference['kind'] = 'owner_accepted_producer_tempo_map'
        reference.pop('ticks_per_quarter')
        for key in ('tempo_events', 'meter_events'):
            reference[key][0].pop('tick')
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'adapted')
        self.assertEqual(result['map']['clock_knots'][0], {'pulse': 0., 'source_seconds': -.25})
        self.assertEqual(result['map']['bar_anchor_pulse'], 0.)
        self.assertEqual(result['map']['support_seconds'], [[.25, 6.75]])
        self.assertEqual(result['map']['clock_knots'][-1]['source_seconds'], 6.75)
        self.assertEqual(result['bar_parity']['status'], 'passed')

    def test_step_tempo_uses_authored_quarter_ticks_not_equal_pulse_spacing(self):
        reference, track = fixture()
        reference['tempo_events'].append({'tick': 384, 'time_seconds': 2., 'bpm_quarter': 60., 'microseconds_per_quarter': 1000000})
        reference['downbeats_seconds'] = [0., 2., 6.]
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'adapted')
        self.assertEqual(result['map']['clock_knots'], [{'pulse': 0., 'source_seconds': 0.},
            {'pulse': 4., 'source_seconds': 2.}, {'pulse': 9., 'source_seconds': 7.}])
        self.assertEqual(result['bar_parity']['status'], 'passed')

    def test_five_eighth_bar_boundaries_are_independent_of_quarter_event_subset(self):
        reference, track = fixture(numerator=5, denominator=8)
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'adapted')
        self.assertEqual(result['bar_parity']['status'], 'passed')
        self.assertEqual(result['bar_parity']['adapted_first_seconds'], [0., 1.25, 2.5])
        self.assertIsNone(result['map']['meter_events'][0]['grouping'])

    def test_repeated_on_barline_declaration_keeps_unspecified_action(self):
        reference, track = fixture()
        reference['meter_events'].append({'tick': 384, 'time_seconds': 2., 'numerator': 4, 'denominator': 4})
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'adapted')
        self.assertEqual(len(result['map']['meter_events']), 2)
        self.assertEqual(result['map']['meter_events'][1]['bar_action'], 'unspecified')
        self.assertEqual(result['bar_parity']['status'], 'passed')

    def test_provisional_off_barline_reset_is_unsupported_not_repaired_or_unqualified(self):
        reference, track = fixture(numerator=3)
        reference['meter_events'].append({'tick': 192, 'time_seconds': 1., 'numerator': 3, 'denominator': 4})
        reference['bar_reset_candidates'] = [{'tick': 192, 'source_seconds': 1., 'reason': 'provisional pickup'}]
        reference['downbeats_seconds'] = [0., 1., 2.5, 4., 5.5, 7.]
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'unsupported')
        self.assertEqual(result['render_status'], 'unsupported_nonbarline_meter_or_reset')
        self.assertIsNotNone(result['map'])
        self.assertEqual(result['map']['meter_events'][1]['bar_action'], 'unspecified')
        self.assertTrue(result['reference_qualification']['bar_timing'])
        self.assertEqual(result['bar_parity']['status'], 'not_evaluated_renderer_unsupported')
        self.assertEqual(result['provenance']['original_bar_reset_candidates'], reference['bar_reset_candidates'])

    def test_late_declaration_is_provenance_not_added_eligible_tail(self):
        reference, track = fixture()
        reference['tempo_events'].append({'tick': 1536, 'time_seconds': 8., 'bpm_quarter': 60.})
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'adapted')
        self.assertEqual(result['map']['clock_knots'][-1]['source_seconds'], 7.)
        self.assertEqual(result['map']['support_seconds'], [[0., 7.]])
        self.assertEqual(len(result['provenance']['original_tempo_events']), 2)

    def test_owner_exclusion_and_click_only_units_cannot_be_admitted_by_present_fields(self):
        reference, track = fixture()
        result = adapt_supplied_reference(reference, track)
        self.assertEqual(result['status'], 'excluded')
        self.assertIsNone(result['map'])
        for kind in ('observed_creator_click_quarters', 'creator_click_wav_with_audited_source_mapping'):
            reference['kind'] = kind
            with self.subTest(kind=kind):
                result = adapt(reference, track)
                self.assertEqual(result['status'], 'excluded')
                self.assertIsNone(result['map'])

    def test_bad_source_and_inconsistent_ticks_are_unsupported_without_fitting(self):
        for issue in ('source', 'tick_time', 'tempo_fields', 'implicit_tempo', 'support'):
            reference, track = fixture()
            if issue == 'source':reference['source_audio_sha256'] = 'b' * 64
            elif issue == 'tick_time':reference['tempo_events'].append({'tick': 384, 'time_seconds': 2.1, 'bpm_quarter': 60.})
            elif issue == 'tempo_fields':reference['tempo_events'][0]['bpm_quarter'] = 110.
            elif issue == 'implicit_tempo':reference['explicit_initial_tempo'] = False
            else:reference['evaluation_support_seconds'] = [0., 11.]
            with self.subTest(issue=issue):
                result = adapt(reference, track)
                self.assertEqual(result['status'], 'unsupported')
                self.assertIsNone(result['map'])
                self.assertFalse(result['provenance']['alignment_fitted'])

    def test_parity_failure_does_not_rephase_map_or_choose_favorable_reference(self):
        reference, track = fixture()
        reference['downbeats_seconds'] = [.03, 2.03, 4.03, 6.03]
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'adapter_parity_failed')
        self.assertAlmostEqual(result['bar_parity']['maximum_absolute_error_seconds'], .03)
        self.assertEqual(result['map']['clock_knots'][0]['source_seconds'], 0.)
        self.assertFalse(result['bar_parity']['alignment_applied'])
        self.assertTrue(result['reference_qualification']['bar_timing'])

    def test_parity_does_not_match_equal_count_but_different_bar_phase(self):
        rendered = {'status': 'rendered', 'bar_events_seconds': [1., 3., 5.]}
        result = compare_bar_parity(rendered, [0., 2., 4.], [0., 6.])
        self.assertEqual(result['status'], 'mismatch')
        self.assertEqual(result['maximum_absolute_error_seconds'], 1.)

    def test_support_boundary_roundoff_is_not_a_missing_bar_or_a_widened_window(self):
        reference, track = fixture(support=[4., 7.])
        result = adapt(reference, track)
        self.assertEqual(result['status'], 'adapted')
        self.assertEqual(result['bar_parity']['status'], 'passed')
        self.assertEqual(result['map']['support_seconds'], [[4., 7.]])
        rendered = {'status': 'rendered', 'bar_events_seconds': [4. - 1e-9, 6.]}
        check = compare_bar_parity(rendered, [4., 6.], [4., 7.])
        self.assertEqual(check['status'], 'mismatch')
        self.assertEqual(check['adapted_count'], 1)

    def test_existing_evidence_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'kept.json').write_text('{}')
            with self.assertRaises(FileExistsError):
                build_reference_views(temp)
            self.assertEqual(Path(temp, 'kept.json').read_text(), '{}')


if __name__ == '__main__':
    unittest.main()
