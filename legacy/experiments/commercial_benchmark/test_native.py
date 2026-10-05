import tempfile
import unittest
from pathlib import Path

from .native import adapt
from experiments.analysis_legacy.music_map_contract import interpolate_clock,render_bars


def fixture(folder, *, period=1/48000, extra=''):
    smt=folder/'a.smt';track=folder/'a.xml'
    smt.write_text('''<MasterTrack><obj class="MTempoTrackEvent"><list>
      <obj class="MTempoEvent"><float name="PPQ" value="0"/><float name="BPM" value="120"/></obj>
      <obj class="MTempoEvent"><float name="PPQ" value="480"/><float name="BPM" value="60"/>'''+extra+'''</obj>
      <obj class="MTempoEvent"><float name="PPQ" value="1440"/><float name="BPM" value="90"/></obj>
      <obj class="MTempoEvent"><float name="PPQ" value="1440"/><float name="BPM" value="90"/></obj>
      </list></obj><obj class="MTimeSignatureEvent"><int name="Numerator" value="1"/><int name="Denominator" value="4"/></obj></MasterTrack>''')
    track.write_text('''<tracklist2><list name="track"><obj class="MAudioTrackEvent"><obj class="MListNode">
      <member name="Domain"><int name="Type" value="1"/></member><list><obj class="MAudioEvent">
      <float name="Start" value="0"/><float name="Length" value="144000"/>
      <obj class="PAudioClip"><member name="Domain"><float name="Period" value="'''+str(period)+'''"/></member>
      <obj class="FNPath"><string name="Name" value="s00.wav"/></obj><obj class="AudioFile">
      <int name="FrameCount" value="144000"/><float name="Rate" value="48000"/></obj></obj>
      </obj></list></obj></obj></list></tracklist2>''')
    row=dict(neutral_name='s00.wav',source=dict(sha256='0'*64,sample_rate=48000,sample_frames=144000))
    return smt,track,row


class NativeClockTests(unittest.TestCase):
    def test_step_integration_matches_independent_midi_clock_and_unknown_meter(self):
        # 120 BPM for one quarter, then 60 BPM for two quarters: MIDI's
        # microsecond-per-quarter interpretation yields 0, .5, 1.5, 2.5 sec.
        with tempfile.TemporaryDirectory() as tmp:
            args=fixture(Path(tmp));result=adapt(*args,ticks_per_quarter=480)
            for quarter,seconds in enumerate([0.,.5,1.5,2.5]):
                self.assertAlmostEqual(interpolate_clock(result['map']['clock_knots'],quarter),seconds,places=12)
            self.assertIsNone(result['map']['meter_events'])
            self.assertIsNone(result['map']['bar_anchor_pulse'])
            self.assertEqual(render_bars(result['map'])['status'],'missing_meter')
            self.assertEqual(result['native_tempo_receipt']['identical_duplicate_events'],1)
            self.assertFalse(result['reference_alignment_applied'])

    def test_rejects_native_rate_mismatch_before_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'sample clock mismatch'):
                adapt(*fixture(Path(tmp),period=1/44100),ticks_per_quarter=480)

    def test_unverified_ramp_is_not_silently_integrated_as_jump(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'ramp schema'):
                adapt(*fixture(Path(tmp),extra='<int name="Ramp" value="1"/>'),ticks_per_quarter=480)


if __name__=='__main__':unittest.main()
