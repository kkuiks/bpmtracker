import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import mido
import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from prepare_multitrack_sample import prepare, read_tempo_map, validate_plan


class PrepareMultitrackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.midi = self.root / 'tempo.mid'
        m = mido.MidiFile(ticks_per_beat=960)
        t = mido.MidiTrack(); m.tracks.append(t)
        t.extend([mido.MetaMessage('set_tempo', tempo=500000),
                  mido.MetaMessage('time_signature', numerator=2, denominator=4),
                  mido.MetaMessage('set_tempo', tempo=500000, time=1920),
                  mido.MetaMessage('time_signature', numerator=4, denominator=4)])
        m.save(self.midi)
        self.project = self.root / 'source.rpp'
        self.project.write_text('synthetic reviewed layout\n')
        mono = np.zeros((64, 1)); mono[8] = .75
        stereo = np.zeros((64, 2)); stereo[8] = [-.5, -.5]; stereo[17, 1] = .5
        self.signals = {'01 Kick.wav': mono, '02 Snare.wav': mono, '03 Guitar.wav': stereo}
        self.archive = self.root / 'source.zip'
        self.write_archive()
        self.plan = {
            'id': 'fixture', 'group_id': 'one-recording', 'genre': 'synthetic',
            'source_page': 'https://example.invalid/fixture', 'layout_reviewed': True,
            'archive': {'path': str(self.archive), 'sha256': sha256(self.archive)},
            'tempo_midi': {'path': str(self.midi), 'sha256': sha256(self.midi)},
            'source_project': {'path': str(self.project), 'sha256': sha256(self.project)},
            'sample_rate': 8000, 'sample_frames': 64,
            'tracks': [{'member': name, 'role': 'drums' if i < 2 else 'music',
                        'position_frames': 0, 'source_offset_frames': 0,
                        'playback_rate': 1, 'gain': 1, 'pan': 0}
                       for i, name in enumerate(self.signals)]}

    def write_archive(self):
        with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, signal in self.signals.items():
                b = io.BytesIO(); sf.write(b, signal, 8000, format='WAV', subtype='PCM_24')
                z.writestr(name, b.getvalue())

    def plan_file(self):
        path = self.root / 'plan.json'
        path.write_text(json.dumps(self.plan))
        return path

    def test_impulses_stereo_and_common_gain_survive_round_trip(self):
        out = self.root / 'prepared'
        report = prepare(self.plan_file(), out, reserve_bytes=0)
        full, rate = sf.read(out/'full_mix.wav', always_2d=True)
        drums, _ = sf.read(out/'drums.wav', always_2d=True)
        g = 10 ** (-1/20) / 1.5
        self.assertEqual(rate, 8000)
        self.assertEqual(full.shape, (64, 2))
        self.assertAlmostEqual(report['common_gain'], g)
        np.testing.assert_allclose(drums[8], [1.5*g, 1.5*g], atol=4e-8)
        np.testing.assert_allclose(full[8], [g, g], atol=4e-8)
        np.testing.assert_allclose(full[17], [0, .5*g], atol=4e-8)
        self.assertEqual(np.flatnonzero(np.any(full != 0, axis=1)).tolist(), [8, 17])
        self.assertEqual(np.flatnonzero(np.any(drums != 0, axis=1)).tolist(), [8])
        self.assertLess(np.max(np.abs(drums)), 1.)
        catalog = json.loads((out/'catalog.json').read_text())
        self.assertEqual(len(catalog['tracks']), 1)
        self.assertIs(catalog['tracks'][0]['absolute_timing_verified'], False)
        self.assertNotIn('reference', catalog['tracks'][0])
        self.assertIs(catalog['tracks'][0]['target_evaluation_eligible'], False)
        self.assertEqual(catalog['tracks'][0]['benchmark_role'], 'diagnostic_only')

    def test_clock_only_midi_deduplicates_same_tempo_without_inventing_support(self):
        clock = read_tempo_map(self.midi)
        self.assertEqual(clock['raw_event_counts']['tempo'], 2)
        self.assertEqual(len(clock['tempo_events']), 1)
        self.assertEqual(clock['meter_events'][1]['time_seconds'], 1.)
        self.assertIsNone(clock['evaluation_support_seconds'])
        self.assertIs(clock['absolute_timing_verified'], False)

    def test_reject_reference_inputs_and_nontrivial_layout(self):
        for changes in ({'member': '../a.wav'}, {'member': 'Click.wav'}, {'role': 'reference'},
                        {'position_frames': 1}, {'source_offset_frames': 1},
                        {'playback_rate': .5}, {'gain': .5}, {'pan': -.5}):
            p = copy.deepcopy(self.plan); p['tracks'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_plan(p)

    def test_reject_different_source_length_without_silent_padding(self):
        self.signals['03 Guitar.wav'] = self.signals['03 Guitar.wav'][:-1]
        self.write_archive(); self.plan['archive']['sha256'] = sha256(self.archive)
        out = self.root / 'bad'
        with self.assertRaisesRegex(ValueError, 'Unequal geometry'):
            prepare(self.plan_file(), out, reserve_bytes=0)
        self.assertFalse((out/'catalog.json').exists())
        self.assertFalse(json.loads((out/'preparation.json').read_text())['complete'])

    def test_reject_overwrite_hash_change_and_space_exhaustion(self):
        out = self.root / 'exists'; out.mkdir()
        with self.assertRaisesRegex(ValueError, 'new directory'):
            prepare(self.plan_file(), out, reserve_bytes=0)
        with self.assertRaisesRegex(ValueError, 'space'):
            prepare(self.plan_file(), self.root/'no-space', reserve_bytes=10**30)
        self.plan['archive']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            prepare(self.plan_file(), self.root/'bad-hash', reserve_bytes=0)


if __name__ == '__main__':
    unittest.main()
