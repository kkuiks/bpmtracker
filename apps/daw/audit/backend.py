"""Opt-in audio/file audit using actual backend functions and generated media."""
from pathlib import Path
import importlib.util
import json
import math
import shutil
import tempfile
import unittest
import uuid
import numpy as np
import soundfile as sf
import soxr

app = Path(__file__).resolve().parents[1]
root = app.parents[1] / '.daw-state/audit-20261005'
spec = importlib.util.spec_from_file_location('daw_worker', app/'backend/worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class BackendAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix='backend-',dir=root))
        cls.assets = {}
        for name in ['mono48.wav','stereo44.wav','stereo44.mp3','stereo96.flac','한글 이름 with spaces.flac']:
            result=worker.decode({'output':str(cls.directory/'cache'),'files':[{'id':str(uuid.uuid4()),'path':str(root/'media'/name)}]})
            cls.assets[name]=result['assets'][0]
        (cls.directory/'assets.json').write_text(json.dumps(cls.assets,indent=2))

    def project(self, names=('mono48.wav','stereo44.wav')):
        assets=[self.assets[n] for n in names]
        return {'format':'joljak-project','version':1,'id':'audit','name':'Audit','sampleRate':48000,'masterGain':.8,'clickGain':.6,
            'assets':assets,'tracks':[{'id':str(i),'name':f'Track {i}','gain':.6,'pan':-.25 if i==0 else .3,'mute':False,'solo':False} for i in range(len(assets))],
            'clips':[{'id':str(i),'trackId':str(i),'assetId':a['id'],'start':.25+i*.125,'sourceStart':.4,'duration':3} for i,a in enumerate(assets)],
            'clocks':[{'id':'clock','clipId':'0','sourceStart':.4,'sourceEnd':3.4,'values':{'bpm':160,'numerator':4,'denominator':4,'offset':.137}}], 'analyses':[]}

    def test_01_codecs_and_unicode_paths(self):
        for name, a in self.assets.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(a['duration'],8.5 if '한글' not in name else 24,places=4)
                self.assertEqual(Path(a['pcmPath']).stat().st_size,a['frames']*a['channels']*4)
                self.assertEqual(Path(a['playbackPath']).stat().st_size,a['playbackFrames']*a['channels']*4)
                self.assertEqual(a['playbackFrames'],round(a['duration']*48000))
                self.assertEqual(Path(a['peaksPath']).stat().st_size,math.ceil(a['frames']/256)*8)

    def test_02_streaming_resample_matches_hq_reference(self):
        for name in ['stereo44.wav','stereo44.mp3','stereo96.flac']:
            with self.subTest(name=name):
                a=self.assets[name]; original=np.fromfile(a['pcmPath'],dtype='<f4').reshape(-1,a['channels'])
                expected=soxr.resample(original,a['sampleRate'],48000,quality='HQ')
                actual=np.fromfile(a['playbackPath'],dtype='<f4').reshape(-1,a['channels'])
                np.testing.assert_allclose(actual,expected,atol=2e-7,rtol=1e-5)

    def test_03_reject_corrupt_multichannel_and_wrong_relocation(self):
        for name in ['corrupt.wav','unsupported-4ch.wav']:
            with self.subTest(name=name),self.assertRaises(Exception):
                worker.decode({'output':str(self.directory/'rejected'),'files':[{'id':str(uuid.uuid4()),'path':str(root/'media'/name)}]})
        with self.assertRaisesRegex(ValueError,'geometry differs'):
            worker.decode({'output':str(self.directory/'relocation'),'files':[{'id':str(uuid.uuid4()),'path':str(root/'media'/'stereo44.wav'),'expected':self.assets['mono48.wav']}]})

    def test_04_mix_stems_click_share_origin_length_and_sample_values(self):
        p=self.project(); start=.12345; end=4.11234
        result=worker.export({'project':p,'options':{'start':start,'end':end,'mix':True,'stems':True,'click':True,'maps':True},'output':str(self.directory/'export')})
        signals={}
        for filename in result['files']:
            if filename.endswith('.wav'):
                data,rate=sf.read(filename,always_2d=True); self.assertEqual(rate,48000); self.assertEqual(len(data),round((end-start)*48000));signals[Path(filename).stem]=data
                self.assertEqual(sf.info(filename).subtype,'PCM_24')
        # Independent linear sum checks channel routing and per-file alignment.
        np.testing.assert_allclose(signals['Mixdown'],signals['01 Track 0']+signals['02 Track 1'],atol=3/2**23,rtol=0)
        expected=worker.click_block(worker.geometry(p),start+np.arange(result['frames'])/48000)*.8*.6
        np.testing.assert_allclose(signals['Click'],expected,atol=2/2**23,rtol=0)
        mapping=json.loads((self.directory/'export/Tempo Map.json').read_text())
        self.assertEqual(mapping['originProjectSeconds'],start);self.assertFalse(mapping['audioWasTimeStretched'])
        midi=(self.directory/'export/Tempo Map.mid').read_bytes();self.assertEqual(midi[:4],b'MThd');self.assertIn(b'\xff\x58\x04\x04\x02\x18\x08',midi)

    def test_05_pan_mute_solo_and_front_priority(self):
        p=self.project(names=('mono48.wav',));a=p['assets'][0];pcm=np.memmap(a['playbackPath'],dtype='<f4',mode='r',shape=(a['playbackFrames'],1));assets={a['id']:(a,pcm)}
        times=np.array([.3,.5]);p['masterGain']=1;p['tracks'][0].update(gain=1,pan=-1)
        actual=worker.mix_block(p,assets,times);expected=pcm[np.round((times-.25+.4)*48000).astype(int),0]
        np.testing.assert_allclose(actual[:,0],expected,atol=1e-8);np.testing.assert_allclose(actual[:,1],0,atol=1e-8)
        p['tracks'][0]['mute']=True;np.testing.assert_array_equal(worker.mix_block(p,assets,times),0)
        p['tracks'][0]['mute']=False;p['tracks'].append({'id':'silent','gain':1,'pan':0,'mute':False,'solo':True})
        np.testing.assert_array_equal(worker.mix_block(p,assets,times),0)
        p['tracks'].pop();p['clips'].append({**p['clips'][0],'id':'front','sourceStart':1})
        actual=worker.mix_block(p,assets,times);expected=pcm[np.round((times-.25+1)*48000).astype(int),0]
        np.testing.assert_allclose(actual[:,0],expected,atol=1e-8)

    def test_06_click_scopes_phase_accents_and_latest_priority(self):
        region={'id':'a','start':1,'end':3,'bpm':120,'numerator':4,'denominator':4,'phase':1.125}
        times=np.array([.5,1.125+.001,1.625+.001,3.001]);result=worker.click_block([region],times)
        self.assertEqual(result[0,0],0);self.assertEqual(result[-1,0],0)
        self.assertAlmostEqual(result[1,0],math.sin(2*math.pi*1600*.001)*math.exp(-.001/.006)*.32)
        self.assertAlmostEqual(result[2,0],math.sin(2*math.pi*1050*.001)*math.exp(-.001/.006)*.20)
        replacement={**region,'phase':1.2}; np.testing.assert_array_equal(worker.click_block([region,replacement],times),worker.click_block([replacement],times))

    def test_07_detached_clock_survives_audio_deletion(self):
        p=self.project(); geometry=worker.geometry(p);p['clocks'][0]['projectOrigin']=p['clips'][0]['start']-p['clips'][0]['sourceStart'];p['clips']=[]
        self.assertEqual(worker.geometry(p),geometry)

    def test_08_empty_output_request_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'output'):
            worker.export({'project':self.project(),'options':{'start':0,'end':1,'mix':False,'stems':False,'click':False,'maps':False},'output':str(self.directory/'empty-export')})

    def test_09_midi_metronome_interval_matches_edited_denominator(self):
        target=self.directory/'compound.mid'
        worker.write_midi(target,[{'id':'clock','start':0,'end':3,'phase':0,'bpm':120,'numerator':6,'denominator':8}],0,3)
        self.assertIn(b'\xff\x58\x04\x06\x03\x0c\x08',target.read_bytes())

    def test_10_midi_resumes_underlying_clock_after_overlap(self):
        target=self.directory/'overlap.mid'
        worker.write_midi(target,[{'id':'base','start':0,'end':4,'phase':0,'bpm':120,'numerator':4,'denominator':4},
            {'id':'override','start':1,'end':2,'phase':1,'bpm':150,'numerator':3,'denominator':4}],0,4)
        # Parse the exported MIDI independently and recover tempo-change seconds.
        data=target.read_bytes()[22:];index=0;tick=0;last_tick=0;time=0.;bpm=120.;changes=[]
        while index<len(data):
            delta=0
            while True:
                b=data[index];index+=1;delta=(delta<<7)|(b&127)
                if not b&128:break
            tick+=delta;self.assertEqual(data[index],255);index+=1;kind=data[index];index+=1
            length=0
            while True:
                b=data[index];index+=1;length=(length<<7)|(b&127)
                if not b&128:break
            message=data[index:index+length];index+=length
            if kind==81:
                time+=(tick-last_tick)/960*60/bpm;last_tick=tick;bpm=60_000_000/int.from_bytes(message,'big');changes.append((round(time,6),round(bpm)))
        self.assertEqual(changes,[(0,120),(1,150),(2,120)])

if __name__ == '__main__':
    unittest.main(verbosity=2)
