import unittest
from status_reanalysis_metrics import tempo_rate_diagnostics


class RateDiagnosticsTests(unittest.TestCase):
    def reference(self):
        return {'tempo_events':[{'time_seconds':0,'bpm_quarter':120}], 'evaluation_support_seconds':[0,10]}
    def clock(self, rate=120, start=0, end=10):
        return {'segments':[{'start_seconds':start,'end_seconds':end,'pulse_rate_per_minute':rate}]}
    def test_half_rate_is_not_octave_corrected(self):
        score=tempo_rate_diagnostics(self.reference(),self.clock(60))
        self.assertEqual(score['time_weighted_mae_bpm'],60)
        self.assertEqual(score['half_rate_duration_fraction'],1)
        self.assertEqual(score['same_rate_duration_fraction'],0)
    def test_partial_span_does_not_become_full_coverage(self):
        score=tempo_rate_diagnostics(self.reference(),self.clock(start=2,end=8))
        self.assertEqual(score['covered_duration_fraction'],.6)
        self.assertEqual(score['uncovered_duration_seconds'],4)
    def test_change_errors_are_weighted_by_duration(self):
        ref=self.reference();ref['tempo_events'].append({'time_seconds':2,'bpm_quarter':180})
        score=tempo_rate_diagnostics(ref,self.clock())
        self.assertEqual(score['time_weighted_mae_bpm'],48)
    def test_absent_map_and_absent_reference_differ(self):
        self.assertEqual(tempo_rate_diagnostics(self.reference(),None)['status'],'no_tempo_map')
        self.assertEqual(tempo_rate_diagnostics({'tempo_events':None},None)['status'],'unscored_missing_tempo_reference')
    def test_nonfinite_rate_is_rejected(self):
        with self.assertRaises(ValueError):tempo_rate_diagnostics(self.reference(),self.clock(float('nan')))

if __name__=='__main__':unittest.main()
