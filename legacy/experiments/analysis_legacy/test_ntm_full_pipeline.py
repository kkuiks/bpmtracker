import io
import copy
from argparse import Namespace
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import mido
import numpy as np
import soundfile as sf

from ntm_full_pipeline import (Attention, archive_rows, cleanup_owned, clock_events,
                               full_download, parse_rpp, process, project_origin, stem_selection, run, main, constant_rpp_clock)
from prepare_multitrack_sample import read_tempo_map
from ntm_alignment import alignment_signal, coherent_review_proposal
from inspect_inputs import sha256


class FakeResponse(io.BytesIO):
    def __init__(self, value, headers, status=200):
        super().__init__(value); self.headers=headers; self.status=status


def rpp(name='01 Kick.wav', rate=1, second_time=1):
    return f'''<REAPER_PROJECT
  <TEMPOENVEX
    PT 0 120 1 262146
    PT {second_time} 120 1 262148
  >
  <TRACK
    <ITEM
      POSITION 0
      SOFFS 0
      LENGTH 40
      PLAYRATE {rate}
      <SOURCE WAVE
        FILE "{name}"
      >
    >
  >
>
'''


class NtmPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_cli_defaults_to_owner_review_without_acquisition(self):
        with patch('sys.argv',['ntm_full_pipeline.py','--slug','new-song']), \
             patch('ntm_full_pipeline.run',return_value={'status':'ready_for_owner_alignment_review'}) as mocked, \
             patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(),0)
        self.assertEqual(mocked.call_args.args[0].review_policy,'owner-review-v1')

    def test_accepted_job_is_preserved_without_reprocessing(self):
        out=self.root/'accepted';out.mkdir()
        approval=out/'acceptance.json';approval.write_text('{"human_alignment_accepted":true}')
        (out/'report.json').write_text(json.dumps({'status':'user_accepted_alignment',
            'retained_outputs':{'acceptance.json':{'sha256':sha256(approval)}}}))
        args=Namespace(slug='accepted',output_root=str(self.root),resume=True)
        with patch('ntm_full_pipeline.process',side_effect=AssertionError('accepted map must not be reprocessed')):
            self.assertEqual(run(args)['status'],'already_complete')

    def midi(self):
        path=self.root/'tempo.mid';m=mido.MidiFile(ticks_per_beat=100)
        t=mido.MidiTrack();m.tracks.append(t)
        t.extend([mido.MetaMessage('set_tempo',tempo=500000),mido.MetaMessage('time_signature',numerator=2,denominator=4),
                  mido.MetaMessage('time_signature',numerator=4,denominator=4,time=200)])
        m.save(path);return path

    def test_full_download_reads_entire_archive_without_selective_ranges(self):
        body=b'complete source archive';seen=[]
        def fetch(request,timeout):
            seen.append(request);return FakeResponse(body,{'Content-Length':str(len(body)),'ETag':'fixed'})
        with patch('ntm_full_pipeline.urllib.request.urlopen',side_effect=fetch):
            result=full_download('https://example.invalid/source.zip?private=secret',self.root/'source.zip',reserve=0)
        self.assertEqual((self.root/'source.zip').read_bytes(),body)
        self.assertIsNone(seen[0].get_header('Range'))
        self.assertTrue(result['complete'])
        self.assertNotIn('secret',(self.root/'source.zip.transfer.json').read_text())

    def test_resume_requires_exact_range_and_same_archive_version(self):
        dest=self.root/'source.zip';(self.root/'source.zip.partial').write_bytes(b'ab')
        (self.root/'source.zip.transfer.json').write_text(json.dumps({'complete':False,'bytes':6,'etag':'fixed'}))
        def fetch(request,timeout):
            self.assertEqual(request.get_header('Range'),'bytes=2-')
            return FakeResponse(b'cdef',{'Content-Range':'bytes 2-5/6','ETag':'different'},206)
        with patch('ntm_full_pipeline.urllib.request.urlopen',side_effect=fetch),self.assertRaisesRegex(Attention,'identity_changed'):
            full_download('https://example.invalid/a',dest,reserve=0)
        self.assertEqual((self.root/'source.zip.partial').read_bytes(),b'ab')

    def test_unknown_length_and_disk_floor_stop_before_payload_write(self):
        for headers in [{},{'Content-Length':'20'}]:
            with patch('ntm_full_pipeline.urllib.request.urlopen',return_value=FakeResponse(b'x'*20,headers)),self.assertRaises(Attention):
                full_download('https://example.invalid/a',self.root/'a',reserve=10**30)
        self.assertFalse((self.root/'a.partial').exists())

    def test_archive_paths_and_links_are_rejected(self):
        for name in ['../escape.wav','C:/escape.mid','/absolute.mid']:
            z=io.BytesIO()
            with zipfile.ZipFile(z,'w') as f:f.writestr(name,b'x')
            z.seek(0)
            with zipfile.ZipFile(z) as f,self.assertRaises(Attention):archive_rows(f)

    def test_source_selection_does_not_choose_click_as_audio_alignment(self):
        rows=[zipfile.ZipInfo(name) for name in ['01 Kick click.wav','02 Kick.wav','03 Kick Sample.wav','04 Snare.wav','05 Guitar.wav']]
        self.assertEqual([r.filename for r in stem_selection(rows)],['02 Kick.wav','04 Snare.wav'])

    def test_source_pool_adds_amped_guitar_voice_room_and_bass_without_reference_audio(self):
        names=['01 Kick.wav','02 Snare.wav','03 Rhy Gtr DI.wav','04 Rhy Gtr Amp.wav',
               '05 Rhy Gtr EVH.wav','06 Vox 1.wav','07 Vox ADT Print.wav','08 Room Close.wav',
               '09 Bass DI.wav','10 Bass Drops.wav','11 Click.wav']
        chosen=[r.filename for r in stem_selection([zipfile.ZipInfo(n) for n in names])]
        self.assertEqual(chosen,['01 Kick.wav','02 Snare.wav','04 Rhy Gtr Amp.wav','05 Rhy Gtr EVH.wav','06 Vox 1.wav','08 Room Close.wav','09 Bass DI.wav'])

    def test_silent_and_antiphase_sources_are_distinguished(self):
        signal,info=alignment_signal(np.zeros((20,2),dtype='float32'))
        self.assertIsNone(signal);self.assertEqual(info['status'],'silent_source')
        x=np.array([0,.2,-.5,.1],dtype='float32');signal,info=alignment_signal(np.column_stack([x,-x]))
        np.testing.assert_array_equal(signal,x)
        self.assertEqual(info['channel_policy'],'highest_energy_after_cancellation')

    def test_coherent_weak_evidence_is_only_a_review_proposal(self):
        r={'qualified_constant_offset':False,'windows':[
            {'mix_start_frame':i*20000,'stem_minus_mix_frames':100+(i%3),
             'normalized_correlation':.12 if 1<=i<=7 else 0.} for i in range(9)]}
        proposal=coherent_review_proposal(r,48000)
        self.assertEqual(proposal['consistent_windows'],7)
        self.assertFalse(proposal['automatic_gate_passed'])
        self.assertFalse(r['qualified_constant_offset'])
        noisy=copy.deepcopy(r)
        for i,w in enumerate(noisy['windows']):w['stem_minus_mix_frames']=i*1000
        self.assertIsNone(coherent_review_proposal(noisy,48000))
        weak=copy.deepcopy(r)
        for w in weak['windows']:w['normalized_correlation']=.049
        self.assertIsNone(coherent_review_proposal(weak,48000))

    def test_project_clock_mismatch_and_stretched_source_are_not_guessed(self):
        clock=read_tempo_map(self.midi());path=self.root/'source.rpp'
        path.write_text(rpp());self.assertEqual(project_origin([path],clock,'01 Kick.wav')['file_zero_in_project_seconds'],0)
        for text in [rpp(rate=.99),rpp(second_time=1.2),rpp(name='Other.wav')]:
            path.write_text(text)
            with self.assertRaises(Attention):project_origin([path],clock,'01 Kick.wav')

    def test_signatureless_points_preserve_tempo_changes_and_existing_meter(self):
        midi=self.midi()
        m=mido.MidiFile(midi)
        m.tracks[0].insert(-1,mido.MetaMessage('set_tempo',tempo=400000,time=200))
        m.save(midi);clock=read_tempo_map(midi)
        text=rpp().replace('    PT 1 120 1 262148',
            '    PT 0.5 120 1\n    PT 1 120 1 262148\n    PT 2 150 1\n    PT 3 150 1')
        path=self.root/'source.rpp';path.write_text(text)
        _,points=parse_rpp(text)
        self.assertEqual([p['bpm'] for p in points],[120,120,120,150,150])
        self.assertEqual([(p['numerator'],p['denominator']) for p in points],[(2,4),(0,0),(4,4),(0,0),(0,0)])
        self.assertEqual(project_origin([path],clock,'01 Kick.wav')['file_zero_in_project_seconds'],0)

    def test_actual_ramps_and_malformed_points_still_fail(self):
        for row,reason in [('PT 0 120 0','rpp_tempo_ramp_requires_review'),
                           ('PT 0 120 0 262146','rpp_tempo_ramp_requires_review'),
                           ('PT 0 120','invalid_rpp_tempo_point'),
                           ('PT 0 nan 1','invalid_rpp_tempo_point'),
                           ('PT 0 0 1','invalid_rpp_tempo_point'),
                           ('PT -1 120 1','invalid_rpp_tempo_point'),
                           ('PT 0 120 1 invalid','invalid_rpp_tempo_point')]:
            with self.subTest(row=row),self.assertRaisesRegex(Attention,reason):
                parse_rpp('<REAPER_PROJECT\n<TEMPOENVEX\n'+row+'\n>\n>\n')

    def test_constant_project_clock_requires_explicit_values_and_keeps_exact_bpm(self):
        p=self.root/'constant.rpp'
        text=rpp().replace('  <TEMPOENVEX\n    PT 0 120 1 262146\n    PT 1 120 1 262148\n  >',
                           '  TEMPO 170 4 4 0\n  PLAYRATE 1 1 0.5 2\n  <TEMPOENVEX\n  >')
        p.write_text(text);clock=constant_rpp_clock(p)
        self.assertIsNone(clock['midi_sha256'])
        self.assertEqual(clock['tempo_events'][0]['bpm_quarter'],170)
        quarters,_=clock_events(clock,300)
        self.assertAlmostEqual(quarters[800]['source_seconds'],800*60/170,places=10)
        self.assertEqual(project_origin([p],clock,'01 Kick.wav')['file_zero_in_project_seconds'],0)
        for bad in [text.replace('TEMPO 170 4 4 0',''),text.replace('TEMPO 170','TEMPO nan'),
                    text.replace('170 4 4','170 4 3'),text.replace('PLAYRATE 1 1','PLAYRATE .9 1'),rpp()]:
            p.write_text(bad)
            with self.assertRaises(Attention):constant_rpp_clock(p)

    def test_compound_meter_preserves_quarters_but_renders_denominator_beats(self):
        clock=read_tempo_map(self.midi())
        clock['meter_events']=[{'tick':0,'time_seconds':0,'numerator':7,'denominator':8}]
        quarters,pulses=clock_events(clock,2.)
        self.assertEqual([r['source_seconds'] for r in quarters],[0,.5,1,1.5])
        self.assertEqual([r['source_seconds'] for r in pulses],[0,.25,.5,.75,1,1.25,1.5,1.75])
        self.assertTrue(pulses[0]['accent']);self.assertTrue(pulses[7]['accent'])

    def test_cleanup_preserves_foreign_files_and_symlinks(self):
        work=self.root/'work';work.mkdir();(work/'owned').write_bytes(b'a');(work/'foreign').write_bytes(b'b')
        with self.assertRaises(Attention):cleanup_owned(work,{'owned'})
        self.assertTrue((work/'owned').exists());(work/'foreign').unlink()
        (work/'link').symlink_to(self.root/'outside')
        with self.assertRaises(Attention):cleanup_owned(work,{'owned','link'})
        (work/'link').unlink();self.assertEqual(cleanup_owned(work,{'owned'})[0]['bytes'],1)
        self.assertFalse(work.exists())

    def test_end_to_end_keeps_inputs_and_rejects_corrupt_unused_member(self):
        midi=self.midi();rng=np.random.default_rng(55);rate=4000
        source=rng.normal(0,.06,(rate*40,1)).astype('float32')
        master=np.r_[source[400:],np.zeros((400,1),dtype='float32')]
        mp=self.root/'master.wav';sf.write(mp,np.repeat(master,2,axis=1),rate,subtype='FLOAT')
        b=io.BytesIO();sf.write(b,source,rate,format='WAV',subtype='FLOAT')
        archive=self.root/'source.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_STORED) as z:
            z.writestr('Tempo.mid',midi.read_bytes());z.writestr('Project.rpp',rpp().replace('    PT 1 120 1 262148','    PT 0.5 120 1\n    PT 1 120 1 262148\n    PT 39 120 1'));z.writestr('01 Kick.wav',b.getvalue());z.writestr('unused.bin',b'UNUSED-SENTINEL')
        original_hash=sha256(archive);master_hash=sha256(mp)
        out=self.root/'result';out.mkdir()
        report=process(archive,mp,out,title='Synthetic',reserve=0)
        self.assertEqual(report['status'],'ready_for_listening_review',report.get('reason'))
        self.assertAlmostEqual(report['alignment']['offset_seconds'],-.1)
        self.assertEqual(sha256(archive),original_hash);self.assertEqual(sha256(mp),master_hash)
        self.assertFalse((out/'_work').exists());self.assertFalse(report['absolute_timing_verified'])
        self.assertTrue(report['archive_all_members_crc_passed'])
        ownedout=self.root/'owned-result';ownedout.mkdir();work=ownedout/'_work';work.mkdir()
        ownedzip=work/'source.zip';shutil.copyfile(archive,ownedzip)
        (work/'source.zip.transfer.json').write_text('{}')
        ownedreport=process(ownedzip,mp,ownedout,title='Owned archive',reserve=0,own_archive=True)
        self.assertEqual(ownedreport['status'],'ready_for_listening_review')
        self.assertFalse(work.exists());self.assertTrue(archive.exists())
        self.assertIn('source.zip',{p['name'] for p in ownedreport['deleted_temporary_files']})
        # A listening-only candidate must remain visibly separate and retain its inputs.
        low=copy.deepcopy(report['audits'][0]);low['qualified_constant_offset']=False
        low['eligible_windows']=0;low['stem_minus_mix_frames']=None
        for i,w in enumerate(low['windows']):w['normalized_correlation']=.12 if 1<=i<=7 else 0.
        manual=self.root/'manual';manual.mkdir()
        with patch('ntm_full_pipeline.audit',return_value=low):
            manual_report=process(archive,mp,manual,title='Manual review',reserve=0)
        self.assertEqual(manual_report['status'],'ready_for_manual_alignment_review')
        self.assertFalse(manual_report['alignment']['automatic_gate_passed'])
        self.assertFalse(json.loads((manual/'review-data.json').read_text())['automatic_gate_passed'])
        self.assertFalse(json.loads((manual/'tempo-aligned.json').read_text())['target_evaluation_eligible'])
        self.assertTrue((manual/'review.html').exists());self.assertTrue((manual/'_work').exists())
        self.assertEqual(manual_report['audits'][0]['configuration']['minimum_correlation'],.2)
        # Explicit retry verifies the same full archive and reuses the canonical decode.
        retry=self.root/'retry';retry.mkdir();(retry/'_work').mkdir()
        ownedzip=retry/'_work/source.zip';shutil.copyfile(archive,ownedzip)
        master_copy=retry/'master-original.wav';shutil.copyfile(mp,master_copy)
        (retry/'.pipeline-owner.json').write_text(json.dumps({'pipeline_version':1}))
        insufficient=copy.deepcopy(low)
        for w in insufficient['windows']:w['normalized_correlation']=0.
        with patch('ntm_full_pipeline.audit',return_value=insufficient):
            failed=process(ownedzip,master_copy,retry,title='Retry',reserve=0,own_archive=True)
        self.assertEqual(failed['status'],'needs_attention')
        ownedzip.write_bytes(ownedzip.read_bytes()+b'changed')
        with self.assertRaisesRegex(Attention,'resume_input_hash_mismatch'):
            process(ownedzip,master_copy,retry,title='Retry',reserve=0,own_archive=True,resume_from=failed)
        shutil.copyfile(archive,ownedzip)
        args=Namespace(slug='retry',output_root=str(self.root),resume=True,title=None,review_policy='legacy-single-source')
        with patch('ntm_full_pipeline.decode_master',side_effect=AssertionError('must reuse decode')), \
             patch('zipfile.ZipFile.testzip',side_effect=AssertionError('must reuse identical archive CRC proof')), \
             patch('ntm_full_pipeline.space'):
            retried=run(args)
        self.assertEqual(retried['status'],'ready_for_listening_review')
        self.assertTrue(retried['resumed_without_network_acquisition'])
        self.assertFalse((retry/'_work').exists())
        # An explicit constant RPP without MIDI produces the same review workflow.
        constant_zip=self.root/'constant.zip'
        constant_rpp=rpp().replace('  <TEMPOENVEX\n    PT 0 120 1 262146\n    PT 1 120 1 262148\n  >',
                                  '  TEMPO 170 4 4 0\n  PLAYRATE 1 1 0.5 2\n  <TEMPOENVEX\n  >')
        with zipfile.ZipFile(constant_zip,'w') as z:
            z.writestr('Project.rpp',constant_rpp);z.writestr('01 Kick.wav',b.getvalue())
        constant_out=self.root/'constant';constant_out.mkdir()
        constant_report=process(constant_zip,mp,constant_out,title='Constant without MIDI',reserve=0)
        self.assertEqual(constant_report['status'],'ready_for_listening_review',constant_report.get('reason'))
        self.assertFalse(constant_report['clock_provenance']['supplied_midi'])
        self.assertFalse((constant_out/'tempo-original.mid').exists())
        rd=json.loads((constant_out/'review-data.json').read_text())
        self.assertTrue((constant_out/rd['clock_asset']).is_file())
        self.assertIsNone(rd['midi_sha256'])
        raw=archive.read_bytes().replace(b'UNUSED-SENTINEL',b'BROKEN-SENTINL!')
        bad=self.root/'bad.zip';bad.write_bytes(raw)
        badout=self.root/'bad-result';badout.mkdir()
        result=process(bad,mp,badout,title='Broken',reserve=0)
        self.assertEqual(result['status'],'needs_attention')
        self.assertFalse(result['archive_all_members_crc_passed'])
        self.assertFalse((badout/'tempo-aligned.json').exists())


if __name__=='__main__':unittest.main()
