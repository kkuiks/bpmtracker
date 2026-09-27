import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from inspect_inputs import sha256
from status_audit import METHODS, normalized_events, ntm_reference
from audit_status_references import increasing
from build_reference_review import review_questions


class StatusAuditTests(unittest.TestCase):
    def make_ntm(self, root):
        audio=root/'master.wav';sf.write(audio,np.zeros((48000,2),dtype=np.float32),48000,subtype='FLOAT')
        aligned={'tempo_events':[{'time_seconds':0,'master_seconds':-.1,'bpm_quarter':120,'microseconds_per_quarter':500000}],
            'meter_events':[{'time_seconds':0,'master_seconds':-.1,'numerator':4,'denominator':4}],
            'quarters':[{'source_seconds':i*.5,'master_seconds':i*.5-.1,'quarter_index':i,'accent':i%4==0}
                        for i in range(4)]}
        map_path=root/'tempo-aligned.json';map_path.write_text(json.dumps(aligned))
        acceptance={'status':'user_accepted_alignment','offset_seconds':-.1,
            'master':{'sha256':sha256(audio)},'aligned_map':{'sha256':sha256(map_path)},
            'full_song_listening_passed':True}
        (root/'acceptance.json').write_text(json.dumps(acceptance))
        return audio,map_path

    def test_owner_accepted_map_becomes_explicit_unshifted_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.make_ntm(root);output=root/'out';output.mkdir()
            record,reference,_=ntm_reference('sample',root,output)
            self.assertEqual(reference['beats_seconds'],[.4,.9])
            self.assertEqual(reference['quarter_indices'],[1.,2.])
            self.assertEqual(reference['tempo_events'][0]['time_seconds'],-.1)
            self.assertEqual(record['qualification_status'],'user_reviewed_tempo_map')
            self.assertFalse(reference['alignment_fitted_to_predictions'])

    def test_hash_change_rejects_owner_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,map_path=self.make_ntm(root);output=root/'out';output.mkdir()
            map_path.write_text(map_path.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'accepted map hash mismatch'):
                ntm_reference('sample',root,output)

    def test_duplicate_and_unordered_reference_events_are_rejected(self):
        with self.assertRaises(ValueError):
            normalized_events([{'time_seconds':1,'bpm_quarter':100},{'time_seconds':1,'bpm_quarter':101}],rate=True)

    def test_method_registry_separates_automatic_and_review(self):
        self.assertTrue(any(not method['automatic'] for method in METHODS))
        self.assertTrue(all('limits' in method for method in METHODS))

    def test_review_questions_do_not_claim_missing_downbeats(self):
        without=review_questions(0)
        self.assertFalse(any('accented' in question for question in without))
        self.assertTrue(any('cannot approve meter' in question for question in without))
        self.assertTrue(any('accented' in question for question in review_questions(4)))

    def test_strict_time_validation_rejects_duplicates_but_allows_negative_map_context(self):
        self.assertFalse(increasing([0.,0.]))
        self.assertFalse(increasing([-.1,.4]))
        self.assertTrue(increasing([-.1,.4],allow_negative=True))


if __name__=='__main__':unittest.main()
