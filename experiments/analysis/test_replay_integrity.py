import json
from pathlib import Path
import tempfile
import unittest
from inspect_inputs import sha256
from replay_integrity import prediction_index,require_file_hash


class ReplayIntegrityTests(unittest.TestCase):
    def test_modified_prediction_cannot_be_reused_under_old_manifest(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'prediction.json';p.write_text(json.dumps({'beats':[1.,2.]}))
            manifest={'rows':[{'id':'song','model':'model','prediction_path':str(p),'prediction_sha256':sha256(p)}]}
            self.assertEqual(len(prediction_index(manifest)),1)
            p.write_text(json.dumps({'beats':[1.1,2.1]}))
            with self.assertRaisesRegex(ValueError,'changed'):prediction_index(manifest)
    def test_duplicate_identity_rejected_even_with_valid_files(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'prediction.json';p.write_text('{}')
            row={'id':'song','model':'model','prediction_path':str(p),'prediction_sha256':sha256(p)}
            with self.assertRaisesRegex(ValueError,'duplicate'):prediction_index({'rows':[row,row]})
    def test_changed_candidate_pool_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'prediction.json';p.write_text('{}');c=Path(name)/'candidates.json';c.write_text('{}')
            row={'id':'song','model':'model','prediction_path':str(p),'prediction_sha256':sha256(p),
                 'candidates_path':str(c),'candidates_sha256':sha256(c)}
            c.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'candidate pool'):prediction_index({'rows':[row]})

if __name__=='__main__':unittest.main()
