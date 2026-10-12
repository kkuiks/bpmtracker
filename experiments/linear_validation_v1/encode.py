"""Reference-derived +/-3% unit proxies only after complete source preparation."""
import argparse
from pathlib import Path
from experiments.beat_event_map_v1.source import encode
from experiments.metronome_reconstruction_v1.hinted import encode_tap_level
from .common import read, write, digest, guard, stamp, POLICIES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run
    guard(run)
    inputs = read(run / 'source-inputs.json')['samples']
    frozen = {}
    for path in (run / 'source-before-tap-freeze').glob('*.json'):
        frozen.update(read(path)['files'])
    if len(frozen) != len(inputs) * 3 or any(digest(p) != sha for p, sha in frozen.items()):
        raise RuntimeError('Source preparation incomplete or changed before tap')
    rows = []
    for item in read(run / 'evaluation-index.json')['rows']:
        ident = item['id']
        ref = read(item['reference_path'])
        bank = read(run / 'prepared-source' / (ident + '.json'))
        family = read(run / 'families' / (ident + '.json'))
        packets, fixed_packets = [], []
        for policy in POLICIES:
            tap = ref['initial_bpm'] * int(policy[5:]) / 100
            packet = encode(bank, tap)
            fixed = (encode_tap_level(family['audio_base_bpm'], tap)
                     if family.get('audio_base_bpm') else {'status': 'no_source_clock', 'power': None})
            fixed = {'power': fixed.get('power'), 'status': fixed['status'], 'numeric_tap_discarded': True}
            packets.append(packet)
            fixed_packets.append(fixed)
            write(run / 'encoded-units' / policy / (ident + '.json'), packet)
            write(run / 'encoded-fixed-units' / policy / (ident + '.json'), fixed)
        rows.append({'id': ident, 'same_L2_unit': packets[0] == packets[1] == packets[2],
                     'same_original_unit': fixed_packets[0] == fixed_packets[1] == fixed_packets[2]})
    write(run / 'tap-encoder-audit.json', {'at_utc': stamp(), 'rows': rows,
          'source_prepared_before_any_tap': True, 'measured_human_taps': False,
          'no_meter_phase_or_future_reference_input': True})
    print('ENCODED', len(rows), 'same L2 units', sum(r['same_L2_unit'] for r in rows), flush=True)


if __name__ == '__main__':
    main()
