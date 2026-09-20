import base64
import io
import tempfile
import unittest
import hashlib
import json
import struct
from pathlib import Path
from unittest.mock import patch

import mido
from acquire_reference_corpus import (public_folder_entries, download, creator_midi_clock,
                                      validate_riff_size, recover_wav_tail)


def field(data):
    if len(data)>=128:raise ValueError('test field too long')
    return b'\x0a'+bytes([len(data)])+data


class AcquisitionTests(unittest.TestCase):
    def test_public_listing_decodes_exact_length_delimited_url(self):
        url='https://www.dropbox.com/scl/fo/test/file.mid?dl=0'
        key=base64.b64encode(b'FolderEntriesProps').decode()
        value=base64.b64encode(field(field(url.encode()))).decode()
        html=f'registerStreamedPrefetch("{key}", "{value}")'
        self.assertEqual(public_folder_entries(html),[{'name':'file.mid','url':url,'kind':'file'}])

    def test_oversized_response_leaves_no_partial_or_success_record(self):
        response=io.BytesIO(b'123456')
        response.headers={'Content-Length':'6','Content-Type':'application/octet-stream'}
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen',return_value=response):
            target=Path(directory)/'asset.mid'
            with self.assertRaises(ValueError):download('https://example.org/asset.mid',target,max_bytes=5)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_existing_file_is_preserved_without_network_access(self):
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen') as network:
            target=Path(directory)/'asset.mid';target.write_bytes(b'keep')
            with self.assertRaises(ValueError):download('https://example.org/asset.mid',target)
            self.assertEqual(target.read_bytes(),b'keep');network.assert_not_called()

    def test_note_free_tempo_track_and_explicit_pickup_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'map.mid';midi=mido.MidiFile(ticks_per_beat=480)
            track=mido.MidiTrack();midi.tracks.append(track)
            track.append(mido.MetaMessage('set_tempo',tempo=600000))
            track.append(mido.MetaMessage('time_signature',numerator=3,denominator=4))
            track.append(mido.MetaMessage('time_signature',numerator=3,denominator=4,time=960))
            track.append(mido.MetaMessage('set_tempo',tempo=500000,time=480))
            midi.save(path);result=creator_midi_clock(path,4.)
            self.assertEqual(result['source_origin_shift_seconds'],0)
            self.assertAlmostEqual(result['tempo_events'][1]['time_seconds'],1.8)
            self.assertEqual(len(result['bar_reset_candidates']),1)
            self.assertEqual(result['meter_events'][1]['tick'],960)
            self.assertAlmostEqual(result['beats_seconds'][4],2.3)

    def test_missing_tempo_is_not_silently_defaulted(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'missing.mid';midi=mido.MidiFile();midi.tracks.append(mido.MidiTrack());midi.save(path)
            with self.assertRaises(ValueError):creator_midi_clock(path,4.)

    def test_short_wav_requires_exact_range_and_preserves_original_transfer(self):
        complete=b'RIFF'+struct.pack('<I',36)+b'WAVE'+b'0'*32
        prefix=complete[:-8];response=io.BytesIO(complete[-8:])
        response.status=206;response.headers={'Content-Range':f'bytes {len(prefix)}-{len(complete)-1}/{len(complete)}'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'asset.wav';path.write_bytes(prefix)
            path.with_suffix('.wav.provenance.json').write_text(json.dumps({
                'source_url':'https://example.org/asset.wav','sha256':hashlib.sha256(prefix).hexdigest()}))
            with self.assertRaises(ValueError):validate_riff_size(path)
            with patch('urllib.request.urlopen',return_value=response):result=recover_wav_tail(path)
            self.assertEqual(path.read_bytes(),complete)
            self.assertEqual(Path(result['incomplete_transfer_preserved_at']).read_bytes(),prefix)
            self.assertEqual(result['recovered_tail_bytes'],8)

    def test_range_that_ends_early_resumes_at_received_byte_without_padding(self):
        complete=b'RIFF'+struct.pack('<I',36)+b'WAVE'+b'0'*32
        prefix=complete[:-8];first=io.BytesIO(complete[-8:-4]);second=io.BytesIO(complete[-4:])
        for response,start in ((first,len(prefix)),(second,len(prefix)+4)):
            response.status=206;response.headers={'Content-Range':f'bytes {start}-{len(complete)-1}/{len(complete)}'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'asset.wav';path.write_bytes(prefix)
            path.with_suffix('.wav.provenance.json').write_text(json.dumps({
                'source_url':'https://example.org/asset.wav','sha256':hashlib.sha256(prefix).hexdigest()}))
            with patch('urllib.request.urlopen',side_effect=[first,second]):result=recover_wav_tail(path)
            self.assertEqual(path.read_bytes(),complete)
            self.assertEqual([r['received_bytes'] for r in result['recovery_range_requests']],[4,4])


if __name__=='__main__':
    unittest.main()
