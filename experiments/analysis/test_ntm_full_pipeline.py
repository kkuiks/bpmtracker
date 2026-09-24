import io
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
                               full_download, parse_rpp, process, project_origin, stem_selection)
from prepare_multitrack_sample import read_tempo_map
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

    def test_project_clock_mismatch_and_stretched_source_are_not_guessed(self):
        clock=read_tempo_map(self.midi());path=self.root/'source.rpp'
        path.write_text(rpp());self.assertEqual(project_origin([path],clock,'01 Kick.wav')['file_zero_in_project_seconds'],0)
        for text in [rpp(rate=.99),rpp(second_time=1.2),rpp(name='Other.wav')]:
            path.write_text(text)
            with self.assertRaises(Attention):project_origin([path],clock,'01 Kick.wav')

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
            z.writestr('Tempo.mid',midi.read_bytes());z.writestr('Project.rpp',rpp());z.writestr('01 Kick.wav',b.getvalue());z.writestr('unused.bin',b'UNUSED-SENTINEL')
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
        raw=archive.read_bytes().replace(b'UNUSED-SENTINEL',b'BROKEN-SENTINL!')
        bad=self.root/'bad.zip';bad.write_bytes(raw)
        badout=self.root/'bad-result';badout.mkdir()
        result=process(bad,mp,badout,title='Broken',reserve=0)
        self.assertEqual(result['status'],'needs_attention')
        self.assertFalse(result['archive_all_members_crc_passed'])
        self.assertFalse((badout/'tempo-aligned.json').exists())


if __name__=='__main__':unittest.main()
