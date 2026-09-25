import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from reanalyze_status_paths import BEAT_THIS_HASH, qualify_cache, score_methods, validate_model_config


class ReanalysisQualificationTests(unittest.TestCase):
    def fixture(self, root):
        audio = root / 'source.wav'
        sf.write(audio, np.zeros(8000, dtype=np.float32), 8000)
        logits = root / 'logits.npz'
        np.savez(logits, beat=np.zeros(50), downbeat=np.zeros(50), fps=np.array(50.))
        asset = {'input_path': str(audio), 'input_sha256': sha256(audio), 'geometry': {}}
        cache = {'model': 'beat_this', 'input_sha256': sha256(audio), 'duration_seconds': 1.,
            'model_configuration': {'checkpoint_sha256': BEAT_THIS_HASH, 'precision': 'float32', 'package_version': '1.1.0'},
            'logits_path': str(logits), 'logits_sha256': sha256(logits)}
        return asset, cache

    def test_exact_cache_qualifies_but_truncated_logits_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); asset, cache = self.fixture(root)
            source, beat, _ = qualify_cache(asset, cache)
            self.assertEqual(source['source_frame_offset'], 0)
            self.assertEqual(len(beat), 50)
            np.savez(cache['logits_path'], beat=np.zeros(20), downbeat=np.zeros(20), fps=np.array(50.))
            cache['logits_sha256'] = sha256(cache['logits_path'])
            with self.assertRaisesRegex(ValueError, 'full source duration'):
                qualify_cache(asset, cache)

    def test_wrong_checkpoint_or_source_is_never_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            asset, cache = self.fixture(Path(directory))
            cache['model_configuration']['checkpoint_sha256'] = 'wrong'
            with self.assertRaisesRegex(ValueError, 'checkpoint'):
                qualify_cache(asset, cache)
            cache['model_configuration']['checkpoint_sha256'] = BEAT_THIS_HASH
            asset['input_sha256'] = 'wrong'
            with self.assertRaisesRegex(ValueError, 'original audio'):
                qualify_cache(asset, cache)

    def test_prefix_inference_rejected_even_with_full_logits(self):
        with tempfile.TemporaryDirectory() as directory:
            asset, cache = self.fixture(Path(directory))
            cache['audio'] = {'sha256': asset['input_sha256'], 'sample_rate': 8000,
                'channels': 1, 'source_frames': 8000, 'analyzed_frames': 4000, 'source_frame_offset': 0}
            with self.assertRaisesRegex(ValueError, 'analyzed_frames'):
                qualify_cache(asset, cache)

    def test_different_decoded_bytes_need_source_bound_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); asset, cache = self.fixture(root)
            original = root / 'original.bin'; original.write_bytes(b'preserved encoded source')
            asset.update(input_path=str(original), input_sha256=sha256(original))
            cache['input_path'] = str(root / 'source.wav')
            with self.assertRaisesRegex(ValueError, 'decode mapping'):
                qualify_cache(asset, cache)
            mapping = root / 'report.json'
            mapping.write_text(json.dumps({'source': {'sha256': asset['input_sha256']},
                'decoded': {'sha256': cache['input_sha256'], 'file': 'source.wav', 'sample_frames': 8000,
                    'origin_policy': 'first decoded sample is zero; no additional start_time subtraction'}}))
            cache['mapping_path'] = str(mapping)
            source, _, _ = qualify_cache(asset, cache)
            self.assertIsNotNone(source['canonical_decode_mapping'])


class ReanalysisMetricTests(unittest.TestCase):
    def test_empty_capable_map_counts_changes_but_unsupported_downbeats_do_not(self):
        reference = {'beats_seconds': [0., 1., 2., 3.], 'downbeats_seconds': [0., 2.],
            'evaluation_support_seconds': [0., 3.],
            'tempo_events': [{'time_seconds': 0., 'bpm_quarter': 60.}, {'time_seconds': 2., 'bpm_quarter': 120.}]}
        methods = {'clock_candidates_selected': {'prediction': {'beats_seconds': [], 'downbeats_seconds': []}, 'clock': None},
            'official': {'prediction': {'beats_seconds': [0., 1., 2., 3.], 'downbeats_seconds': []}, 'clock': None}}
        scores = score_methods(reference, methods)
        candidate = scores['clock_candidates_selected']
        self.assertIsNone(candidate['downbeat_20ms'])
        self.assertEqual(candidate['downbeat_capability'], 'unsupported')
        self.assertEqual(candidate['tempo_changes_100ms']['full_change_scores']['false_negatives'], 1)
        self.assertEqual(scores['official']['downbeat_20ms']['f1'], 0)
        self.assertEqual(scores['official']['tempo_map_status'], 'unsupported_tempo_map')


if __name__ == '__main__':
    unittest.main()
