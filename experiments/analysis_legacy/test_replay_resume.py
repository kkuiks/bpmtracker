"""Interruption/resume tests using temporary prediction ledgers and mocked inference."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from inspect_inputs import sha256
from replay_integrity import merge_prediction_rows, prediction_index
import reanalyze_status_paths as core_runner
import reanalyze_status_regions as region_runner


class PredictionLedgerResumeTests(unittest.TestCase):
    def row(self, root, track_id):
        path=root/(track_id+'.json');path.write_text(json.dumps({'id':track_id,'model':'beat_this'}))
        return {'id':track_id,'model':'beat_this','status':'predictions_saved',
            'prediction_path':str(path),'prediction_sha256':sha256(path)}

    def test_first_checkpoint_of_resume_keeps_unvisited_prediction_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);previous=[self.row(root,'a'),self.row(root,'b'),self.row(root,'c')]
            before=deepcopy(previous)
            current=[{**previous[0],'postprocessing_execution':'reused'}]
            checkpoint=merge_prediction_rows(current,previous)
            self.assertEqual([r['id'] for r in checkpoint],['a','b','c'])
            self.assertEqual(set(prediction_index({'rows':checkpoint})),{('a','beat_this'),('b','beat_this'),('c','beat_this')})
            self.assertEqual(previous,before)

    def test_second_interrupted_resume_still_retains_all_saved_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);previous=[self.row(root,'a'),self.row(root,'b')]
            first=merge_prediction_rows([dict(previous[0])],previous)
            second=merge_prediction_rows([{**previous[1],'postprocessing_execution':'reused'}],first)
            self.assertEqual([r['id'] for r in second],['b','a'])
            self.assertEqual(len(prediction_index({'rows':second})),2)

    def test_unselected_case_keeps_its_existing_hash_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);previous=[self.row(root,'a'),self.row(root,'b')]
            current=[{'id':'a','model':'beat_this','status':'cached_not_selected_this_invocation'},dict(previous[1])]
            checkpoint=merge_prediction_rows(current,previous)
            bound=prediction_index({'rows':checkpoint})
            self.assertEqual(bound[('a','beat_this')]['prediction_sha256'],previous[0]['prediction_sha256'])
            self.assertEqual(len(bound),2)

    def test_failed_score_state_does_not_erase_published_prediction_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);previous=[self.row(root,'a')]
            failed={'id':'a','model':'beat_this','status':'reanalysis_failed','reason':'reference changed'}
            checkpoint=merge_prediction_rows([failed],previous)
            self.assertEqual(checkpoint[0]['status'],'reanalysis_failed')
            self.assertEqual(checkpoint[0]['reason'],'reference changed')
            self.assertEqual(len(prediction_index({'rows':checkpoint})),1)

    def test_region_interruption_after_second_prediction_keeps_resumable_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'old';old.mkdir();core=root/'core';core.mkdir();out=root/'out'
            review=old/'reference-review-batch1-v2';review.mkdir()
            (review/'owner-decisions.json').write_text(json.dumps({'model_predictions_included':False,'items':[]}))
            reference=root/'reference.json';reference.write_text('{}')
            source=root/'source.wav';source.write_bytes(b'synthetic-source-identity')
            logits=root/'logits.npz';logits.write_bytes(b'synthetic-logit-identity')
            source_info={'path':str(source),'sha256':sha256(source),'logits_path':str(logits),
                'logits_sha256':sha256(logits),'duration_seconds':1.,'native_frame_rate':50.}
            catalog=[];ledger=[]
            for track_id in ('a','b'):
                catalog.append({'id':track_id,'input':{'sha256':sha256(source)},
                    'reference':{'path':str(reference),'sha256':sha256(reference)}})
                prediction=core/(track_id+'.json')
                prediction.write_text(json.dumps({'id':track_id,'model':'beat_this','source':source_info,
                    'methods':{'common_minimal':{'prediction':{'beats_seconds':[.1,.6]}}}}))
                ledger.append({'id':track_id,'cohort':'synthetic','model':'beat_this',
                    'evaluation_admission':'admitted_reference','status':'predictions_saved',
                    'prediction_path':str(prediction),'prediction_sha256':sha256(prediction)})
            (old/'catalog-scored-audio.json').write_text(json.dumps({'tracks':catalog}))
            (core/'manifest.json').write_text(json.dumps({'complete':True,'rows':ledger}))
            generated={'candidates':[],'regions':[],'selection_status':'insufficient_evidence','selected_candidate_id':None}
            arguments=['regions','--core-dir',str(core),'--old-root',str(old),'--output-dir',str(out),'--threads','1']
            with patch.object(region_runner,'load_logits',return_value=(np.array([0.]),np.array([0.]),50.)), \
                 patch.object(region_runner,'generate_region_candidates',return_value=generated) as build, \
                 patch.object(region_runner,'score_regions',side_effect=[{},KeyboardInterrupt('interrupt after publish'),{},{}]), \
                 redirect_stdout(io.StringIO()):
                with patch('sys.argv',arguments),self.assertRaises(KeyboardInterrupt):region_runner.main()
                partial=json.loads((out/'manifest.json').read_text())
                self.assertFalse(partial['complete'])
                self.assertEqual(len(prediction_index(partial)),2)
                self.assertTrue(all('status' in row for row in partial['rows']))
                with patch('sys.argv',arguments+['--resume']):region_runner.main()
                finished=json.loads((out/'manifest.json').read_text())
                self.assertTrue(finished['complete'])
                self.assertTrue(all(row['status']=='predictions_saved' for row in finished['rows']))
                self.assertEqual(build.call_count,2)

    def test_real_core_scoring_failure_can_resume_without_reconstructing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'old';old.mkdir();out=root/'out'
            review=old/'reference-review-batch1-v2';review.mkdir()
            (review/'owner-decisions.json').write_text(json.dumps({'model_predictions_included':False,'items':[]}))
            reference=root/'reference.json';reference.write_text('{}')
            catalog={'tracks':[{'id':'sample','input':{'sha256':'source'},
                'reference':{'path':str(reference),'sha256':sha256(reference)}}]}
            (old/'catalog-scored-audio.json').write_text(json.dumps(catalog))
            (old/'inventory.json').write_text(json.dumps({'audio':[{'id':'sample','cohort':'synthetic',
                'input_sha256':'source','reference_tier':'synthetic_authored_clock'}]}))
            result=root/'cached-result.json';result.write_text('{}')
            cache={'model':'beat_this','result_path':str(result)}
            source={'sha256':'source'}
            method={'prediction':{'beats_seconds':[0.,.5],'downbeats_seconds':[0.]},
                    'clock':None,'status':'official','capabilities':{'tempo_map':False,'downbeat':True}}
            prediction={'id':'sample','model':'beat_this','source':source,
                'cache':{'result_sha256':sha256(result)},'methods':{'official':method}}
            arguments=['replay','--old-root',str(old),'--output-dir',str(out),'--threads','1']
            with patch.object(core_runner,'caches_from_sources',return_value={('sample','beat_this'):cache}), \
                 patch.object(core_runner,'qualify_cache',return_value=(source,np.array([]),np.array([]))), \
                 patch.object(core_runner,'build_predictions',return_value=(prediction,{'candidates':[]})) as build, \
                 patch.object(core_runner,'score_methods',side_effect=[ValueError('synthetic scoring failure'),{}]), \
                 redirect_stdout(io.StringIO()):
                with patch('sys.argv',arguments):core_runner.main()
                first=json.loads((out/'manifest.json').read_text())
                failed=next(r for r in first['rows'] if r['model']=='beat_this')
                self.assertEqual(failed['status'],'reanalysis_failed')
                self.assertEqual(len(prediction_index(first)),1)
                before_hash=failed['prediction_sha256']
                with patch('sys.argv',arguments+['--resume']):core_runner.main()
                second=json.loads((out/'manifest.json').read_text())
                resumed=next(r for r in second['rows'] if r['model']=='beat_this')
                self.assertEqual(resumed['status'],'predictions_saved')
                self.assertEqual(resumed['prediction_sha256'],before_hash)
                self.assertEqual(build.call_count,1)
                self.assertTrue(second['all_available_selected_caches_completed'])


if __name__=='__main__':unittest.main()
