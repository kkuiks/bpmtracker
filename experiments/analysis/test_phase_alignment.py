"""Timing, abstention and immutable-source contracts on synthetic evidence."""
from copy import deepcopy
import unittest
import numpy as np

from complete_song_clock import rebuild_clock
from phase_alignment import AttackConfig, PhaseConfig, BANDS, extract_attacks, propose_phase, shifted_clock


def calibration():
    return {'synthetic_only':True,'reference_music_used':False,
            'bands':{b:{'eligible':True,'bias_seconds':0.} for b in BANDS}}


def attacks(times):
    return {'bands':{b:{'seconds':list(times),'strength':[2.]*len(times),'rise_seconds':[.001]*len(times)} for b in BANDS}}


class PhaseAlignmentTests(unittest.TestCase):
    def test_silence_does_not_create_attacks_or_shift(self):
        evidence=extract_attacks(np.zeros(48000),48000)
        self.assertTrue(all(not b['seconds'] for b in evidence['bands'].values()))
        result=propose_phase(np.arange(60)*.5,evidence,calibration())
        self.assertEqual(result['applied_shift_seconds'],0.)

    def test_native_sample_timing_of_sharp_transients(self):
        for rate in (16000,44100,48000):
            with self.subTest(rate=rate):
                source=np.zeros(rate,dtype=np.float32);target=round(.25137*rate);source[target]=1
                evidence=extract_attacks(source,rate)
                self.assertEqual(evidence['source_frames'],len(source));self.assertEqual(evidence['source_origin_seconds'],0)
                # The high-detail filter has negligible onset pre-ringing; its
                # sample-bin onset must remain within two milliseconds.
                times=evidence['bands']['detail_under1ms']['seconds']
                self.assertTrue(times);self.assertLess(min(abs(t-target/rate) for t in times),.002)

    def test_common_delay_is_recovered_without_tempo_or_reference_input(self):
        truth=2+np.arange(96)*.5;prediction=truth+.021
        evidence=attacks(truth);before=deepcopy(evidence)
        result=propose_phase(prediction,evidence,calibration())
        self.assertAlmostEqual(result['applied_shift_seconds'],-.021,places=6)
        self.assertFalse(result['accepted']);self.assertFalse(result['reference_used_for_prediction'])
        self.assertEqual(evidence,before)

    def test_band_disagreement_abstains(self):
        beats=2+np.arange(96)*.5;evidence=attacks(beats)
        for band,offset in zip(BANDS,(-.02,.02,0)):
            evidence['bands'][band]['seconds']=(beats+offset).tolist()
        result=propose_phase(beats,evidence,calibration())
        self.assertEqual(result['applied_shift_seconds'],0.)

    def test_inconsistent_window_offsets_abstain(self):
        beats=2+np.arange(96)*.5
        true=beats+np.r_[np.full(48,-.025),np.full(48,.025)]
        result=propose_phase(beats,attacks(true),calibration())
        self.assertEqual(result['applied_shift_seconds'],0.)

    def test_dense_uninformative_attacks_and_search_edge_do_not_force_shift(self):
        beats=2+np.arange(60)*.5
        for times in (np.arange(0,35,.001),beats+.05):
            result=propose_phase(beats,attacks(times),calibration())
            self.assertEqual(result['applied_shift_seconds'],0.)

    def test_clock_shift_preserves_intervals_changes_and_original(self):
        original=rebuild_clock([5.],[.01,.5,.1],9.);before=deepcopy(original)
        result=shifted_clock(original,-.02,9.)
        self.assertEqual(result['coefficients'][1:],original['coefficients'][1:])
        self.assertEqual(result['knot_pulse_indices'],original['knot_pulse_indices'])
        self.assertAlmostEqual(result['segments'][1]['start_seconds'],original['segments'][1]['start_seconds']-.02)
        self.assertTrue(all(0<=v<9 for v in result['beats_seconds']))
        self.assertFalse(result['source_audio_modified']);self.assertEqual(result['source_origin_seconds'],0)
        self.assertEqual(original,before)

    def test_anchored_maps_and_reference_derived_calibration_are_rejected(self):
        clock=rebuild_clock([],[0.,.5],9.)
        for key,value in [('accepted',True),('anchor_checks',[{}]),('assistance',{'anchors':[]})]:
            with self.assertRaises(ValueError):shifted_clock({**clock,key:value},.01,9.)
        with self.assertRaises(ValueError):propose_phase([1,2,3],attacks([1,2,3]),{'synthetic_only':False})
        with self.assertRaises(ValueError):extract_attacks(np.zeros(100),48000,AttackConfig(hop_seconds=0))
        with self.assertRaises(ValueError):propose_phase([1,2,3],attacks([1,2,3]),calibration(),PhaseConfig(radius_seconds=float('nan')))


if __name__=='__main__':unittest.main()
