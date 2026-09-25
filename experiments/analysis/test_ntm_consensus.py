import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import numpy as np
import soundfile as sf
from ntm_consensus import assess_sources, verify_consensus
from ntm_full_pipeline import process


def evidence(name, offset=-.1, strong=True, correlation=.8, count=9, identity=None):
    return {'source_member':name,'source_sha256':identity or name,'source_sample_rate':1000,
            'project_origin':{'file_zero_in_project_seconds':0},'qualified_constant_offset':strong,
            'windows':[{'mix_start_frame':int(t*1000),'stem_minus_mix_frames':round(-offset*1000),
                        'normalized_correlation':correlation} for t in np.linspace(8,208,count)]}


class ConsensusTests(unittest.TestCase):
    def test_two_distinct_families_require_additional_windows(self):
        initial=assess_sources([evidence('01 Kick.wav'),evidence('02 Bass.wav')])
        self.assertTrue(initial['passed_initial'])
        self.assertFalse(verify_consensus(initial,[])['passed'])
        result=verify_consensus(initial,[evidence('01 Kick.wav',count=8),evidence('02 Bass.wav',count=8)])
        self.assertTrue(result['passed']);self.assertEqual(result['offset_seconds'],-.1)
        self.assertFalse(result['strict_timing_verified'])

    def test_multiple_drum_mics_and_duplicate_audio_are_not_independent_votes(self):
        for rows in [[evidence('Kick.wav'),evidence('Snare.wav'),evidence('Room.wav')],
                     [evidence('Kick.wav',identity='same'),evidence('Bass.wav',identity='same')]]:
            self.assertFalse(assess_sources(rows)['passed_initial'])

    def test_coherent_weak_source_conflict_vetoes_strong_majority(self):
        rows=[evidence('Kick.wav'),evidence('Bass.wav'),evidence('Guitar.wav',offset=-.12,strong=False,correlation=.12)]
        result=assess_sources(rows)
        self.assertFalse(result['passed_initial']);self.assertIn('source_disagreement',result['reasons'])
        self.assertIsNone(result['offset_seconds'])

    def test_partial_span_and_additional_window_shift_fail(self):
        short=evidence('Bass.wav')
        for i,w in enumerate(short['windows']):
            if i<2 or i>6:w['normalized_correlation']=0
        self.assertFalse(assess_sources([evidence('Kick.wav'),short])['passed_initial'])
        initial=assess_sources([evidence('Kick.wav'),evidence('Bass.wav')])
        result=verify_consensus(initial,[evidence('Kick.wav',count=8),evidence('Bass.wav',offset=-.12,count=8)])
        self.assertFalse(result['passed']);self.assertEqual(result['offset_seconds'],-.1)

    def test_musical_family_agreement_does_not_override_conflicting_mic(self):
        result=assess_sources([evidence('Kick.wav'),evidence('Snare.wav',offset=-.13),evidence('Bass.wav')])
        self.assertFalse(result['passed_initial'])

    def test_end_to_end_auto_accepts_agreement_and_preserves_single_source_for_review(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rate=4000;rng=np.random.default_rng(901)
            sources=[rng.normal(0,.04,rate*40).astype('float32') for _ in range(2)]
            master=sum(sources);master=np.r_[master[400:],np.zeros(400,dtype='float32')]
            mp=root/'master.wav';sf.write(mp,np.repeat(master[:,None],2,axis=1),rate,subtype='FLOAT')
            for number in [1,2]:
                arc=root/f'{number}.zip';names=['01 Kick.wav','02 Bass.wav'][:number]
                project='<REAPER_PROJECT\n TEMPO 120 4 4 0\n PLAYRATE 1 1 0.5 2\n <TEMPOENVEX\n >\n'
                with zipfile.ZipFile(arc,'w') as z:
                    for name,x in zip(names,sources):
                        buffer=io.BytesIO();sf.write(buffer,x,rate,format='WAV',subtype='FLOAT');z.writestr(name,buffer.getvalue())
                        project+=f' <TRACK\n  <ITEM\n   POSITION 0\n   SOFFS 0\n   PLAYRATE 1\n   LENGTH 40\n   <SOURCE WAVE\n    FILE "{name}"\n   >\n  >\n >\n'
                    z.writestr('Project.rpp',project+'>\n')
                out=root/f'out-{number}';out.mkdir()
                result=process(arc,mp,out,title='Consensus synthetic',reserve=0,review_policy='multisource-v1')
                if number==1:
                    self.assertEqual(result['status'],'ready_for_manual_alignment_review',result.get('reason'))
                    self.assertFalse((out/'acceptance.json').exists());self.assertTrue((out/'_work').exists())
                    self.assertFalse(result['alignment']['automatic_gate_passed'])
                else:
                    self.assertEqual(result['status'],'automatically_accepted_alignment',result.get('reason'))
                    self.assertTrue(result['source_consensus']['passed']);self.assertAlmostEqual(result['alignment']['offset_seconds'],-.1)
                    a=json.loads((out/'acceptance.json').read_text());self.assertFalse(a['human_alignment_accepted']);self.assertFalse(a['absolute_timing_verified'])
                    self.assertFalse((out/'_work').exists());self.assertTrue(arc.exists())
                    self.assertTrue(json.loads((out/'review-data.json').read_text())['automatic_alignment_accepted'])


if __name__=='__main__':unittest.main()
