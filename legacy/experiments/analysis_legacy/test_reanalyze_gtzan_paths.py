from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from inspect_inputs import sha256
from reanalyze_gtzan_paths import main, write_json, REPLAY_SOURCES
from replay_integrity import source_fingerprint


class AtomicReplayWriteTests(unittest.TestCase):
    def test_serialization_failure_preserves_previous_document(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'result.json'
            write_json(target, {'state': 'complete'})
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                write_json(target, {'not_json': float('nan')})
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_failed_atomic_replace_preserves_old_document_and_cleans_owned_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'result.json'
            write_json(target, {'old': True})
            before = target.read_bytes()
            with patch('reanalyze_gtzan_paths.os.replace', side_effect=OSError('interrupted replace')):
                with self.assertRaises(OSError):
                    write_json(target, {'new': True})
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob('.result.json.*.tmp')), [])


class GTZANReplayResumeTests(unittest.TestCase):
    def fixture(self, root):
        track_id = 'gtzan_test_00000'
        feature = root / 'feature.npy'; np.save(feature, np.zeros((100, 8), dtype=np.float32))
        reference = root / 'reference.json'
        write_json(reference, {'beats_seconds': [0., .5, 1., 1.5], 'downbeats_seconds': [0.],
            'evaluation_support_seconds': [0., 1.5], 'tempo_events': None})
        source_dir = root / 'source'; source_case = source_dir / track_id
        source_case.mkdir(parents=True)
        logits = source_case / 'logits.npz'
        np.savez(logits, beat=np.zeros(100), downbeat=np.zeros(100), fps=np.array(50.))
        prediction = {'beats_seconds': [0., .5, 1., 1.5], 'downbeats_seconds': [0.]}
        baseline = {'id': track_id, 'input_sha256': sha256(feature), 'reference_sha256': sha256(reference),
            'variants': {name: dict(prediction) for name in ('official_minimal', 'legacy_dbn', 'clock_pipeline')},
            'clock': None, 'clock_status': 'fallback_insufficient_events'}
        write_json(source_case / 'result.json', baseline)
        source_report = source_dir / 'report.json'
        write_json(source_report, {'complete': True, 'configuration': {'checkpoint_sha256': 'frozen-test-weights'},
            'tracks': [baseline]})
        track = {'id': track_id, 'genre': 'test', 'group_id': track_id, 'duration_seconds': 2.,
            'input': {'kind': 'spectrogram', 'path': str(feature), 'sha256': sha256(feature), 'fps': 50},
            'reference': {'path': str(reference), 'sha256': sha256(reference)}}
        catalog = root / 'catalog.json'; write_json(catalog, {'tracks': [track]})
        output = root / 'output'
        argv = ['reanalyze_gtzan_paths.py', '--catalog', str(catalog), '--source-report', str(source_report),
            '--output-dir', str(output), '--threads', '1']
        def reconstruct(*args, **kwargs):
            method = {'prediction': dict(prediction), 'clock': None, 'status': 'fallback_insufficient_events'}
            return {'clock_current': dict(method), 'clock_candidates_selected': dict(method),
                'candidate_set': {'candidates': [], 'selected_candidate_id': None}}
        with patch('sys.argv', argv), patch('reanalyze_gtzan_paths.reconstruct_model', side_effect=reconstruct), redirect_stdout(io.StringIO()):
            main()
        return {'argv': argv, 'output': output, 'track_id': track_id, 'feature': feature, 'reference': reference,
            'logits': logits, 'source_result': source_case / 'result.json',
            'prediction': output / track_id / 'predictions.json',
            'candidates': output / track_id / 'candidates.json'}

    def resume(self, fixture):
        with patch('sys.argv', fixture['argv'] + ['--resume']), redirect_stdout(io.StringIO()):
            main()

    def test_completed_resume_checks_inputs_and_skips_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(Path(directory))
            before = sha256(fixture['prediction'])
            with patch('reanalyze_gtzan_paths.reconstruct_model', side_effect=AssertionError('must not rerun')):
                self.resume(fixture)
            self.assertEqual(sha256(fixture['prediction']), before)
            report = json.loads((fixture['output'] / 'report.json').read_text())
            self.assertTrue(report['complete'])
            self.assertEqual(report['timing']['newly_executed_this_invocation'], 0)

    def test_completed_resume_rejects_each_live_input_or_saved_output_tamper(self):
        for field in ('feature', 'reference', 'logits', 'source_result', 'prediction', 'candidates'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = self.fixture(Path(directory))
                fixture[field].write_bytes(b'changed after completed replay')
                with patch('reanalyze_gtzan_paths.reconstruct_model', side_effect=AssertionError('must not rerun')):
                    with self.assertRaisesRegex(ValueError, 'missing or changed'):
                        self.resume(fixture)

    def test_completed_resume_rejects_mismatched_track_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(Path(directory))
            result_path = fixture['output'] / fixture['track_id'] / 'result.json'
            row = json.loads(result_path.read_text()); row['id'] = 'other-track'
            write_json(result_path, row)
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                self.resume(fixture)

    def test_transitive_dependency_change_rejects_resume_before_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.fixture(Path(directory))
            hashes = source_fingerprint(REPLAY_SOURCES)
            for dependency in ('legacy_dbn.py', 'run_beat_this.py', 'replay_integrity.py'):
                self.assertIn(dependency, hashes)
            hashes['legacy_dbn.py'] = 'different frozen decoder'
            with patch('reanalyze_gtzan_paths.source_fingerprint', return_value=hashes), redirect_stdout(io.StringIO()), patch('sys.stderr', io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.resume(fixture)


if __name__ == '__main__':
    unittest.main()
