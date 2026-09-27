"""Closed-form musical-time cases; no equivalence decision is encoded here."""
from fractions import Fraction
import math
import unittest
from musical_units import MeterSpec, TempoSpec


class MusicalUnitsTests(unittest.TestCase):
    def test_quarter_and_dotted_quarter_tempo_describe_same_duration(self):
        quarter = TempoSpec(120, Fraction(1))
        dotted = TempoSpec(80, Fraction(3, 2))
        self.assertEqual(quarter.quarter_bpm, dotted.quarter_bpm)
        self.assertEqual(MeterSpec(6, 8).bar_seconds(dotted), 1.5)
        self.assertEqual(dotted.seconds_for_quarters(Fraction(3, 2)), .75)

    def test_equal_bar_lengths_do_not_imply_equal_grouping(self):
        tempo = TempoSpec(120, Fraction(1))
        three = MeterSpec(3, 4, (1, 1, 1))
        six = MeterSpec(6, 8, (3, 3))
        self.assertEqual(three.bar_seconds(tempo), six.bar_seconds(tempo))
        self.assertEqual(three.group_durations_seconds(tempo), (.5, .5, .5))
        self.assertEqual(six.group_durations_seconds(tempo), (.75, .75))
        self.assertNotEqual(three.group_offsets_quarters, six.group_offsets_quarters)

    def test_five_eighths_has_fractional_quarter_bar_and_unequal_groups(self):
        meter = MeterSpec(5, 8, (2, 3))
        self.assertEqual(meter.quarters_per_bar, Fraction(5, 2))
        self.assertEqual(meter.group_offsets_quarters, (Fraction(0), Fraction(1)))
        self.assertEqual(meter.group_durations_seconds(TempoSpec(120, 1)), (.5, .75))

    def test_denominator_scaling_preserves_explicit_physical_groups(self):
        a = MeterSpec(4, 4, (1, 1, 1, 1)); b = MeterSpec(4, 8, (1, 1, 1, 1))
        ta = TempoSpec(120, 1); tb = TempoSpec(60, 1)
        self.assertEqual(a.bar_seconds(ta), 2.)
        self.assertEqual(a.bar_seconds(ta), b.bar_seconds(tb))
        self.assertEqual(a.group_durations_seconds(ta), b.group_durations_seconds(tb))

    def test_double_rate_and_numerator_requires_explicit_group_assertion(self):
        a = MeterSpec(4, 4, (1, 1, 1, 1)); b = MeterSpec(8, 4, (2, 2, 2, 2))
        ta = TempoSpec(85, 1); tb = TempoSpec(170, 1)
        self.assertEqual(a.bar_seconds(ta), b.bar_seconds(tb))
        self.assertEqual(a.group_durations_seconds(ta), b.group_durations_seconds(tb))
        self.assertEqual(MeterSpec(8, 4).group_offsets_quarters, None)
        self.assertNotEqual(a.bar_seconds(ta), a.bar_seconds(tb))

    def test_unknown_grouping_is_preserved(self):
        for n, d in ((4, 4), (6, 8), (5, 8)):
            meter = MeterSpec(n, d)
            self.assertIsNone(meter.grouping)
            self.assertIsNone(meter.group_durations_seconds(TempoSpec(80, 1)))
            self.assertIsNone(meter.to_dict()['grouping_denominator_units'])

    def test_pickup_duration_is_signed_not_clipped_to_source_zero(self):
        self.assertEqual(TempoSpec(120, 1).seconds_for_quarters(Fraction(-3, 2)), -.75)

    def test_invalid_or_implicit_units_are_rejected(self):
        for rate in (0, -1, math.nan, math.inf, True):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                TempoSpec(rate, 1)
        for unit in (None, 0, -1, 1.5, True):
            with self.subTest(unit=unit), self.assertRaises(ValueError):
                TempoSpec(120, unit)
        with self.assertRaises(TypeError):
            TempoSpec(120)

    def test_invalid_meter_assertions_are_rejected(self):
        for args in ((0, 4), (3, 3), (True, 4), (4, 4, (1, 1)),
                     (4, 4, (0, 4)), (4, 4, (2., 2.)), (4, 4, ())):
            with self.subTest(args=args), self.assertRaises(ValueError):
                MeterSpec(*args)


if __name__ == '__main__':
    unittest.main()
