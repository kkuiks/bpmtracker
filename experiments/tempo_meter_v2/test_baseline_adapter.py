"""Focused controls for the newly added balanced-clock map adapter."""

from copy import deepcopy
from fractions import Fraction
import unittest

import numpy as np

from baseline_adapter import ControlConfig, METERS, complete_balanced_map


SOURCE = {"sha256": "a" * 64, "sample_rate": 100, "sample_frames": 2500}
CLOCK = {"pulse_index_span": [0., 40.], "knot_pulse_indices": [],
         "coefficients": [0., .5], "support_seconds": [0., 20.]}


def evidence():
    beat = np.full(1251, -6., dtype=np.float64)
    downbeat = np.full(1251, -6., dtype=np.float64)
    for t in np.arange(0., 20., .5):
        beat[round(t * 50)] = 10.
    for t in np.arange(0., 20., 2.):
        downbeat[round(t * 50)] = 10.
    return beat, downbeat


def replay():
    return {"id": "synthetic", "source_sha256": SOURCE["sha256"],
            "references_used_for_prediction": False,
            "method": {"selected_candidate_id": "frozen-1", "clock": deepcopy(CLOCK),
                       "prediction": {"beats_seconds": [i * .5 for i in range(41)]}}}


def ntm():
    times = [i * .5 for i in range(41)]
    return ({"id": "synthetic", "model": "beat_this", "source": SOURCE,
             "references_used_for_selection": False,
             "candidate_source": {"path": "unused-for-explicit-pool", "sha256": "b" * 64},
             "selections": {"balanced_evidence": {"candidate_id": "frozen-1",
                                                   "prediction": times}}},
            {"candidates": [{"id": "frozen-1", "clock": deepcopy(CLOCK),
                             "indexed_grid": [{"source_seconds": t} for t in times]}]})


class BalancedCompletionTest(unittest.TestCase):
    def test_replay_emits_map_without_changing_frozen_clock_or_beats(self):
        payload = replay()
        original = deepcopy(payload)
        beat, downbeat = evidence()
        config = ControlConfig(units=(Fraction(1),), meters=(METERS[2],))
        result = complete_balanced_map(payload, beat, downbeat, 50, SOURCE, config=config)
        self.assertEqual("proposed_map", result["status"])
        self.assertEqual([0., 20.], result["bar_starts_seconds"][::len(result["bar_starts_seconds"])-1])
        self.assertEqual({"numerator": 4, "denominator": 4},
                         {k: result["map"]["meter_events"][0][k] for k in ("numerator", "denominator")})
        self.assertEqual([{"pulse": 0., "source_seconds": 0.},
                          {"pulse": 40., "source_seconds": 20.}], result["map"]["clock_knots"])
        self.assertEqual(payload["method"]["prediction"]["beats_seconds"], result["beat_times_seconds"])
        self.assertEqual(original, payload)

    def test_ntm_pool_and_quarter_coordinate_conversion(self):
        payload, pool = ntm()
        beat, downbeat = evidence()
        config = ControlConfig(units=(Fraction(2),), meters=(METERS[5],))
        result = complete_balanced_map(payload, beat, downbeat, 50, SOURCE,
                                       candidate_pool=pool, config=config)
        self.assertEqual("proposed_map", result["status"])
        self.assertEqual("2", result["diagnostics"]["inferred_quarters_per_frozen_pulse"])
        self.assertEqual(80., result["map"]["clock_knots"][-1]["pulse"])
        self.assertEqual(20., result["map"]["clock_knots"][-1]["source_seconds"])
        self.assertEqual({"numerator": 1, "denominator": 1}, result["map"]["quarters_per_pulse"])

    def test_exact_physical_notation_alias_abstains(self):
        beat, downbeat = evidence()
        config = ControlConfig(units=(Fraction(1), Fraction(2)),
                               meters=(METERS[2], METERS[5]))
        result = complete_balanced_map(replay(), beat, downbeat, 50, SOURCE, config=config)
        self.assertEqual("unresolved", result["status"])
        self.assertEqual("ambiguous_unit_meter_or_phase", result["diagnostics"]["reason"])
        self.assertIsNone(result["map"])

    def test_missing_clock_and_weak_downbeats_abstain(self):
        beat, downbeat = evidence()
        missing = replay()
        missing["method"]["selected_candidate_id"] = None
        missing["method"]["clock"] = None
        result = complete_balanced_map(missing, beat, downbeat, 50, SOURCE)
        self.assertEqual("no_frozen_selected_clock", result["diagnostics"]["reason"])
        weak = complete_balanced_map(replay(), beat, np.full_like(downbeat, -6.), 50, SOURCE,
                                     config=ControlConfig(units=(Fraction(1),), meters=(METERS[2],)))
        self.assertEqual("weak_downbeat_evidence", weak["diagnostics"]["reason"])

    def test_rejects_reference_selection_source_mismatch_and_pool_mismatch(self):
        beat, downbeat = evidence()
        reference_assisted = replay()
        reference_assisted["references_used_for_prediction"] = True
        with self.assertRaises(ValueError):
            complete_balanced_map(reference_assisted, beat, downbeat, 50, SOURCE)
        with self.assertRaises(ValueError):
            complete_balanced_map(replay(), beat, downbeat, 50, {**SOURCE, "sha256": "b" * 64})
        reference_pool = replay()
        reference_pool["candidate_set"] = {"reference_used_for_prediction": True}
        with self.assertRaises(ValueError):
            complete_balanced_map(reference_pool, beat, downbeat, 50, SOURCE)
        payload, pool = ntm()
        with self.assertRaises(ValueError):
            complete_balanced_map(payload, beat, downbeat, 50,
                                  {**SOURCE, "sample_frames": 2499}, candidate_pool=pool)
        pool["candidates"][0]["indexed_grid"][3]["source_seconds"] += .01
        with self.assertRaises(ValueError):
            complete_balanced_map(payload, beat, downbeat, 50, SOURCE, candidate_pool=pool)


if __name__ == "__main__":
    unittest.main()
