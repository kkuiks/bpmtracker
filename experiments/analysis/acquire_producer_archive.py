"""Inspect public producer archives and extract only explicitly chosen members.

Archive contents are never executed. Extracted names are flattened under a new
output directory, selected members must be unambiguous, and decoded byte counts
must match the listing. An external, locally pinned 7-Zip reader handles RAR.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess

from inspect_inputs import sha256


def parse_listing(text):
    marker = '----------\n'
    if marker not in text:
        raise ValueError('7-Zip technical listing has no member section')
    rows = []
    for block in text.split(marker, 1)[1].strip().split('\n\n'):
        values = {}
        for line in block.splitlines():
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                values[key] = value
        if 'Path' not in values:
            continue
        name = values['Path'].replace('\\', '/')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or any(ord(c) < 32 for c in name):
            raise ValueError('unsafe archive member path')
        if 'Symbolic Link' in values or 'Hard Link' in values:
            raise ValueError('archive links are not supported')
        if values.get('Folder') == '+' or values.get('Attributes', '').startswith('D'):
            continue
        size = int(values['Size'])
        if size < 0:
            raise ValueError('negative member size')
        rows.append({'name': values['Path'], 'output_name': path.name, 'size': size,
                     'crc': values.get('CRC'), 'encrypted': values.get('Encrypted') == '+'})
    if len(rows) != len({r['name'] for r in rows}):
        raise ValueError('duplicate archive members')
    return rows


def selected_members(rows, names, byte_budget):
    if not names or len(names) != len(set(names)):
        raise ValueError('unique explicit member names required')
    by_name = {r['name']: r for r in rows}
    if any(n not in by_name for n in names):
        raise ValueError('selected member absent from archive listing')
    selected = [by_name[n] for n in names]
    if len({r['output_name'] for r in selected}) != len(selected):
        raise ValueError('flattened destination names collide')
    if any(r['output_name'] in ('listing.txt', 'manifest.json') for r in selected):
        raise ValueError('member collides with acquisition metadata')
    if any(r.get('encrypted') for r in selected):
        raise ValueError('this extractor does not accept passwords for encrypted members')
    if sum(r['size'] for r in selected) > byte_budget:
        raise ValueError('selected decoded assets exceed byte budget')
    if any(Path(r['output_name']).suffix.lower() not in ('.mid', '.midi', '.wav', '.mp3', '.flac', '.txt', '.rtf') for r in selected):
        raise ValueError('only MIDI, audio and plain documentation assets are supported')
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--seven-zip', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--members', nargs='*')
    parser.add_argument('--max-bytes', type=int, default=600_000_000)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('new output required')
    listing = subprocess.run([str(args.seven_zip), 'l', '-slt', '--', str(args.archive)],
                             check=True, capture_output=True, text=True).stdout
    rows = parse_listing(listing)
    chosen = selected_members(rows, args.members, args.max_bytes) if args.members else []
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'listing.txt').write_text(listing)
    provenance = {'archive_path': str(args.archive), 'archive_sha256': sha256(args.archive),
                  'reader_path': str(args.seven_zip), 'reader_sha256': sha256(args.seven_zip),
                  'extractor_sha256': sha256(__file__), 'members': rows, 'selection': chosen,
                  'extraction': [], 'complete': not bool(chosen)}
    manifest = args.output_dir/'manifest.json'
    manifest.write_text(json.dumps(provenance, indent=2)+'\n')
    for member in chosen:
        destination = args.output_dir/member['output_name']
        partial = destination.with_name(destination.name+'.partial')
        command = [str(args.seven_zip), 'x', '-so', '-spd', '--', str(args.archive), member['name']]
        # Separate stderr from asset bytes; no member pathname becomes a shell command.
        with partial.open('xb') as output, (args.output_dir/(member['output_name']+'.extract.log')).open('wb') as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            count = 0
            try:
                while block := process.stdout.read(1024*1024):
                    count += len(block)
                    if count > member['size']:
                        raise ValueError('reader returned more than the selected member')
                    output.write(block)
                if process.wait() != 0 or count != member['size']:
                    raise ValueError('member CRC/read failure or incomplete extraction')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        partial.rename(destination)
        provenance['extraction'].append({'member': member['name'], 'path': str(destination),
                                         'bytes': count, 'sha256': sha256(destination)})
        manifest.write_text(json.dumps(provenance, indent=2)+'\n')
        print('EXTRACT', member['name'], count, flush=True)
    provenance['complete'] = True
    manifest.write_text(json.dumps(provenance, indent=2)+'\n')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
