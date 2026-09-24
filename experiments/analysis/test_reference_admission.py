import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ReferenceAdmissionTests(unittest.TestCase):
    def test_unverified_timing_rejects_scoring_before_reading_other_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            catalog = base/'catalog.json'
            catalog.write_text(json.dumps({'tracks': [{'id': 'unverified', 'absolute_timing_verified': False}]}))
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('run_expansion_benchmark.py')),
                '--catalogs', str(catalog), '--checkpoint', str(base/'absent-checkpoint'),
                '--calibration', str(base/'absent-calibration'), '--output-dir', str(base/'output')],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('catalog explicitly lacks verified timing', result.stderr)
            self.assertFalse((base/'output').exists())


    def test_diagnostic_mix_rejected_even_if_its_clock_is_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            catalog = base/'catalog.json'
            catalog.write_text(json.dumps({'tracks': [{'id': 'rough-mix',
                'absolute_timing_verified': True, 'benchmark_role': 'diagnostic_only',
                'target_evaluation_eligible': False}]}))
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('run_expansion_benchmark.py')),
                '--catalogs', str(catalog), '--checkpoint', str(base/'absent-checkpoint'),
                '--calibration', str(base/'absent-calibration'), '--output-dir', str(base/'output')],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('cannot enter target benchmark scoring', result.stderr)
            self.assertFalse((base/'output').exists())


if __name__ == '__main__':
    unittest.main()
