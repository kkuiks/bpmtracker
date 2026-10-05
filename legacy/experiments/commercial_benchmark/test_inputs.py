import struct
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
import numpy as np
import soundfile as sf

from .prepare import chunks,neutral_copy,digest,windows_path


class InputProtectionTests(unittest.TestCase):
    def test_native_windows_paths_have_valid_unc_and_drive_roots(self):
        self.assertEqual(PureWindowsPath(windows_path('/home/yooch/code/joljak/a b.wav','Ubuntu-24.04')).as_posix(),
                         '//wsl.localhost/Ubuntu-24.04/home/yooch/code/joljak/a b.wav')
        self.assertEqual(PureWindowsPath(windows_path('/mnt/d/a b.wav','Ubuntu-24.04')).as_posix(),'D:/a b.wav')
    def test_metadata_removed_with_sample_bytes_and_origin_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.wav';dest=Path(directory)/'s00.wav'
            sf.write(source,np.column_stack([np.linspace(-.9,.9,1001),np.zeros(1001)]),44100,subtype='PCM_24')
            payload=source.read_bytes();metadata=b'TEMPO=143; SIGNATURE=7/8; ORIGIN=99'
            body=payload[8:]+b'LIST'+struct.pack('<I',len(metadata))+metadata+b'\0'*(len(metadata)%2)
            source.write_bytes(b'RIFF'+struct.pack('<I',len(body))+body)
            before=digest(source);receipt=neutral_copy(source,dest)
            self.assertEqual(digest(source),before)
            self.assertEqual(receipt['removed_chunks'],['LIST'])
            self.assertTrue(receipt['pcm_bytes_unchanged'])
            np.testing.assert_array_equal(sf.read(source,dtype='int32')[0],sf.read(dest,dtype='int32')[0])
            self.assertEqual(sf.info(dest).frames,1001)
            self.assertEqual([c[0] for c in chunks(dest)],[b'fmt ',b'data'])
            resumed=neutral_copy(source,dest,resume=True)
            self.assertEqual(resumed,receipt)

    def test_resume_rejects_modified_working_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.wav';dest=Path(directory)/'s00.wav'
            sf.write(source,np.zeros(20),48000,subtype='PCM_16');neutral_copy(source,dest)
            data=bytearray(dest.read_bytes());data[-1]=1;dest.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'neutral WAV bytes differ'):
                neutral_copy(source,dest,resume=True)


if __name__=='__main__':unittest.main()
