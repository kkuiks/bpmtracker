import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from build_interactive_review import build
from evaluate_review_session import evaluate
from inspect_inputs import sha256


class ReviewArtifactTests(unittest.TestCase):
    def fixture(self, base):
        audio = base/'source.wav'
        sf.write(audio, np.zeros(16000, dtype=np.float32), 8000)
        digest = sha256(audio)
        catalog = base/'catalog.json'
        catalog.write_text(json.dumps({'tracks':[{'id':'fixture','input':{'kind':'audio','path':str(audio),'sha256':digest},
            'reference':{'path':'LABEL_CANARY_MUST_NOT_APPEAR'},'duration_seconds':2}]}))
        prediction = {'beats_seconds':[.25,.75,1.25,1.75],'downbeats_seconds':[]}
        report = base/'report.json'
        report.write_text(json.dumps({'tracks':[{'id':'fixture','input_sha256':digest,'variants':{'official':prediction}}]}))
        return audio, catalog, report, digest

    def test_wrong_prediction_source_is_rejected_even_when_catalog_audio_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);_,catalog,report,_=self.fixture(base)
            value=json.loads(report.read_text());value['tracks'][0]['input_sha256']='different-master';report.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'prediction/source'):
                build([catalog],[report],[],base/'review')

    def test_review_keeps_original_audio_and_does_not_embed_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);_,catalog,report,digest=self.fixture(base)
            page=build([catalog],[report],[],base/'review')
            self.assertNotIn('LABEL_CANARY_MUST_NOT_APPEAR',page.read_text())
            self.assertEqual(sha256(base/'review/audio/fixture.wav'),digest)
            key=json.loads((base/'review/evaluation-key.json').read_text())
            self.assertEqual(key['tracks'][0]['choices']['choice-1']['method'],'official')

    def test_late_first_meter_does_not_certify_initial_meter_or_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);audio,_,_,digest=self.fixture(base)
            session={'source':{'sha256':digest,'sample_rate':8000,'sample_frames':16000,'source_frame_offset':0},
                'map':{'grid':[{'quarter_position':i,'source_seconds':.25+i*.5} for i in range(4)],
                       'meter_events':[{'quarter_position':2,'numerator':2,'denominator':4}]}}
            reference={'source_audio_sha256':digest,'beats_seconds':[.25,.75,1.25,1.75],
                'downbeats_seconds':[.25,1.25],'evaluation_support_seconds':[0,2],
                'meter_events':[{'time_seconds':.25,'numerator':4,'denominator':4},
                                {'time_seconds':1.25,'numerator':2,'denominator':4}]}
            result=evaluate(session,reference,audio)
            self.assertEqual(result['scores']['beats']['0.02']['f1'],1)
            self.assertEqual(result['meter_changes']['status'],'unresolved_prefix_meter')
            self.assertEqual(result['indexed_grid']['status'],'unanchored')
            session['source']['sha256']='wrong'
            with self.assertRaises(ValueError):evaluate(session,reference,audio)

    def test_same_meter_restatement_is_not_a_signature_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);audio,_,_,digest=self.fixture(base)
            session={'source':{'sha256':digest,'sample_rate':8000,'sample_frames':16000,'source_frame_offset':0},
                'map':{'grid':[{'quarter_position':i,'source_seconds':.25+i*.5} for i in range(4)],
                       'meter_events':[{'quarter_position':0,'numerator':4,'denominator':4}]}}
            reference={'source_audio_sha256':digest,'beats_seconds':[.25,.75,1.25,1.75],
                'downbeats_seconds':[.25],'evaluation_support_seconds':[0,2],
                'meter_events':[{'time_seconds':.25,'numerator':4,'denominator':4},
                                {'time_seconds':.75,'numerator':4,'denominator':4}]}
            result=evaluate(session,reference,audio)
            self.assertEqual(result['meter_changes']['false_negatives'],0)


if __name__=='__main__':unittest.main()
