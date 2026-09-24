import copy
import unittest

import numpy as np

from build_alignment_review import event_frame, quarter_events, render_clicks, waveform_checks


def clock():
    return {'ticks_per_quarter': 100, 'tempo_events': [
        {'tick': 0, 'time_seconds': 0., 'microseconds_per_quarter': 500000}],
        'meter_events': [{'tick': 0, 'numerator': 2, 'denominator': 4},
                         {'tick': 200, 'numerator': 4, 'denominator': 4}]}


class AlignmentReviewTests(unittest.TestCase):
    def test_preserve_pickup_and_explicit_meter_change(self):
        events = quarter_events(clock(), 4.)
        self.assertEqual([e['source_seconds'] for e in events], [0,.5,1,1.5,2,2.5,3,3.5])
        self.assertEqual([e['beat_in_bar'] for e in events], [1,2,1,2,3,4,1,2])
        self.assertEqual([e['accent'] for e in events], [True,False,True,False,False,False,True,False])

    def test_tempo_change_preserves_integrated_midi_time(self):
        c = clock(); c['tempo_events'].append({'tick': 250, 'time_seconds': 1.25, 'microseconds_per_quarter': 1000000})
        self.assertEqual([e['source_seconds'] for e in quarter_events(c, 3)], [0,.5,1,1.75,2.75])

    def test_reject_unsupported_meter_instead_of_guessing(self):
        for alteration in [{'denominator': 8}, {'tick': 225}]:
            c = copy.deepcopy(clock()); c['meter_events'][1].update(alteration)
            with self.assertRaises(ValueError):
                quarter_events(c, 4.)

    def test_positive_offset_means_later_master_click(self):
        e = [{'source_seconds': 1., 'quarter_index': 0, 'accent': True}]
        for delta, expected in [(0, 1000), (.1, 1100), (-.1, 900)]:
            audio, rows = render_clicks(e, delta, 1000, 2000)
            self.assertEqual(rows[0]['master_start_frame'], expected)
            self.assertEqual(np.flatnonzero(audio)[0], expected)
            self.assertEqual(len(audio), 2000)
        self.assertEqual(event_frame(1., .0005, 1000), 1001)

    def test_negative_start_clips_without_wrapping_to_end(self):
        events = [{'source_seconds': 0., 'quarter_index': 0, 'accent': False}]
        base, _ = render_clicks(events, 0., 8000, 1000)
        early, rows = render_clicks(events, -.01, 8000, 1000)
        np.testing.assert_array_equal(early[:120], base[80:200])
        self.assertEqual(rows[0]['render_status'], 'clipped')
        self.assertTrue(np.all(early[120:] == 0))
        gone, rows = render_clicks(events, -.03, 8000, 1000)
        self.assertEqual(rows[0]['render_status'], 'omitted'); self.assertFalse(np.any(gone))

    def test_out_of_bounds_tail_is_disclosed(self):
        events = [{'source_seconds': 1.99, 'quarter_index': 0, 'accent': True},
                  {'source_seconds': 2.1, 'quarter_index': 1, 'accent': False}]
        audio, rows = render_clicks(events, 0, 1000, 2000)
        self.assertEqual([r['render_status'] for r in rows], ['clipped', 'omitted'])
        self.assertEqual(len(audio), 2000)

    def test_waveform_offset_sign_is_independent_of_midi(self):
        rng = np.random.default_rng(31)
        # Random signal avoids periodic aliases; master occurs 87 ms before source.
        source = rng.normal(0, .05, (20000, 1)).astype('float32')
        master = np.r_[source[87:], np.zeros((87, 1), dtype='float32')]
        master = np.repeat(master, 2, axis=1)
        r = waveform_checks(master, 1000, source, 1000, -.087)
        for row in r['windows']:
            self.assertEqual(row['local_master_minus_source_seconds'], -.087)
            self.assertGreater(row['fixed_offset_correlations']['waveform_candidate'], .999)
            self.assertLess(abs(row['fixed_offset_correlations']['opposite_direction']), .05)
        self.assertFalse(r['absolute_timing_verified'])
        self.assertFalse(r['reference_or_model_used'])

    def test_silent_windows_do_not_invent_alignment_at_search_edge(self):
        source = np.zeros((20000, 1), dtype='float32')
        master = np.zeros((20000, 2), dtype='float32')
        r = waveform_checks(master, 1000, source, 1000, -.087)
        self.assertEqual(r['usable_windows'], 0)
        self.assertIsNone(r['local_offset_range_seconds'])
        self.assertIsNone(r['local_offset_spread_ms'])
        self.assertTrue(all(w['status'] == 'no_source_signal' for w in r['windows']))


if __name__ == '__main__':
    unittest.main()
