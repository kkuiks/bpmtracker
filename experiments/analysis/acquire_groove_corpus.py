"""Acquire a metadata-selected GMD pilot using bounded public ZIP ranges.

These are human performances on an electronic drum kit, not complete songs.
MIDI clock timing and the publisher's audio alignment claim are kept distinct
from independently verified click WAVs. No analysis output selects examples.
"""
import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

from acquire_reference_corpus import creator_midi_clock
from inspect_inputs import sha256


URL = 'https://storage.googleapis.com/magentadata/datasets/groove/groove-v1.0.0.zip'
MIDI_SHA = '651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e'


class RemoteZip(io.RawIOBase):
    """Read a version-pinned archive without downloading unrelated members."""
    def __init__(self, url, byte_budget=450_000_000, opener=urllib.request.urlopen):
        self.url, self.opener, self.byte_budget = url, opener, byte_budget
        with opener(urllib.request.Request(url, method='HEAD'), timeout=45) as response:
            self.size = int(response.headers['Content-Length'])
            self.etag = response.headers['ETag']
        self.position = self.received = 0
        self.ranges = []

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError('invalid seek')
        target = (0 if whence == 0 else self.position if whence == 1 else self.size) + offset
        if target < 0:
            raise ValueError('negative seek')
        self.position = target
        return target

    def read(self, count=-1):
        count = max(0, min(self.size-self.position, count if count >= 0 else self.size))
        if not count:
            return b''
        if count > 80_000_000 or self.received+count > self.byte_budget:
            raise ValueError('bounded archive transfer budget exceeded')
        start, end = self.position, self.position+count-1
        request = urllib.request.Request(self.url, headers={
            'Range': f'bytes={start}-{end}', 'If-Match': self.etag, 'Accept-Encoding': 'identity'})
        with self.opener(request, timeout=45) as response:
            if (response.status != 206 or
                    response.headers.get('Content-Range') != f'bytes {start}-{end}/{self.size}' or
                    response.headers.get('ETag') != self.etag):
                raise ValueError('server did not certify requested range and archive identity')
            value = response.read(count+1)
        if len(value) != count:
            raise ValueError('truncated or oversized archive range')
        self.position += count
        self.received += count
        self.ranges.append({'start': start, 'end': end, 'sha256': hashlib.sha256(value).hexdigest()})
        return value


def select_rows(rows, count=12):
    """Balance performers first, then style/meter diversity; deterministic ties."""
    eligible = [r for r in rows if r['audio_filename'] and r['beat_type'] == 'beat'
                and 30 <= float(r['duration']) <= 180]
    selected = []
    drummers, styles, meters = collections.Counter(), collections.Counter(), collections.Counter()
    while len(selected) < count:
        pool = [r for r in eligible if r not in selected and drummers[r['drummer']] < 2]
        if not pool:
            raise ValueError('insufficient metadata-qualified examples')
        chosen = min(pool, key=lambda r: (drummers[r['drummer']],
            meters[r['time_signature']], styles[r['style'].split('/')[0]],
            hashlib.sha256(r['id'].encode()).hexdigest()))
        selected.append(chosen)
        drummers[chosen['drummer']] += 1
        styles[chosen['style'].split('/')[0]] += 1
        meters[chosen['time_signature']] += 1
    return selected


def main():
    import soundfile as sf
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata-zip', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--count', type=int, default=12)
    args = parser.parse_args()
    if args.output_dir.exists() or sha256(args.metadata_zip) != MIDI_SHA:
        parser.error('new output and official checksum-verified MIDI ZIP required')
    with zipfile.ZipFile(args.metadata_zip) as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read('groove/info.csv').decode())))
        selection = select_rows(rows, args.count)
        args.output_dir.mkdir(parents=True)
        def save(name, value):
            (args.output_dir/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
        save('selection.json', {'selected_before_audio_or_predictions': True, 'rows': selection,
            'policy': '30-180s beat performances with WAVs; maximum two per drummer; greedy performer, meter, genre balance; SHA256 ID tie break',
            'metadata_zip_sha256': MIDI_SHA, 'selector_sha256': sha256(__file__)})
        remote = RemoteZip(URL)
        tracks = []
        with zipfile.ZipFile(remote) as audio_archive:
            for row in selection:
                ident = 'gmd_'+row['id'].replace('/', '_')
                folder = args.output_dir/ident
                folder.mkdir()
                midi, audio = folder/'performance.mid', folder/'performance.wav'
                midi.write_bytes(archive.read('groove/'+row['midi_filename']))
                member = audio_archive.getinfo('groove/'+row['audio_filename'])
                if member.file_size > 80_000_000:
                    raise ValueError('audio member exceeds pilot size limit')
                audio.write_bytes(audio_archive.read(member))  # ZIP CRC checked by zipfile.
                info = sf.info(audio)
                reference = creator_midi_clock(midi, min(info.duration, float(row['duration'])))
                reference.update(kind='gmd_metronome_midi_clock',
                    evaluation_support_seconds=[0., min(info.duration, float(row['duration']))],
                    recorded_to_this_click_status='publisher explicitly states metronome-recorded performance',
                    source_alignment='publisher states audio/MIDI aligned within 2ms; not independently certified click waveform',
                    annotation_caveat='Human groove differs from metronome. MIDI ticks define clock; note attacks are not beat labels.',
                    quarter_unit='MIDI quarter, including denominator-8 meters; no octave tolerance',
                    source_audio_sha256=sha256(audio), midi_sha256=sha256(midi))
                reference_path = folder/'reference.json'
                reference_path.write_text(json.dumps(reference, indent=2)+'\n')
                tracks.append({'id': ident, 'dataset': 'groove_metronome_pilot',
                    'genre': row['style'], 'group_id': row['drummer'], 'original_split': row['split'],
                    'duration_seconds': info.duration, 'sample_rate': info.samplerate, 'sample_frames': info.frames,
                    'input': {'kind': 'audio', 'path': str(audio), 'sha256': sha256(audio)},
                    'reference': {'path': str(reference_path), 'sha256': sha256(reference_path)},
                    'midi_path': str(midi), 'source_metadata': row,
                    'source_page': 'https://magenta.withgoogle.com/datasets/groove',
                    'audio_archive_member': member.filename, 'audio_archive_crc32': member.CRC,
                    'license': 'CC-BY-4.0; Google LLC; Gillick et al. Learning to Groove, ICML 2019',
                    'role': 'new local diagnostic recordings, not complete studio songs or certified model holdout',
                    'model_overlap': 'not audited; upstream training overlap unknown',
                    'qualification_status': 'publisher_aligned_midi_clock_not_independent_click_wav_audit'})
                print(ident, row['style'], row['time_signature'], round(info.duration, 2), flush=True)
                save('catalog.partial.json', {'tracks': tracks, 'complete': False})
        save('archive-transfer.json', {'url': URL, 'etag': remote.etag, 'archive_bytes': remote.size,
            'downloaded_bytes': remote.received, 'ranges': remote.ranges,
            'integrity': 'pinned ETag, exact HTTP ranges, member ZIP CRC32, local SHA256; whole archive SHA256 NOT checked'})
        save('catalog.json', {'schema_version': 1, 'tracks': tracks, 'complete': True,
            'selection_sha256': sha256(args.output_dir/'selection.json'), 'source_origin_shift_seconds': 0})


if __name__ == '__main__':
    main()
