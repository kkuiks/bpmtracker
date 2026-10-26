"""Source-only preparation and prediction for the frozen L2 and fixed baseline."""
import argparse
from pathlib import Path
import sys, time, copy, hashlib
import numpy as np
import soundfile as sf
from experiments.variable_clock_composition_v1.sensors import event_peaks, pcm_flux, source_array
from experiments.metronome_reconstruction_v1.infer import make_evidence
from experiments.metronome_reconstruction_v1.hinted import prepare_audio_family
from experiments.beat_event_map_v1.source import prepare as prepare_map_sources
from experiments.beat_event_stability_v1.core import fit
from .common import ROOT, PRIMARY, POLICIES, read, write, digest, stamp, guard


def fixed_map(family, packet, duration):
    levels = [level for level in family.get('levels', []) if level['power'] == packet.get('power')]
    if not levels:
        return {'status': 'no_source_clock', 'duration_seconds': duration, 'events': [],
                'method': 'ORIGINAL_FIXED_UNIT'}
    best = max(levels, key=lambda r: r['best']['score'])['best']
    bpm = best['quarter_bpm']
    signature = best['time_signature']
    length = 60 / bpm * signature['numerator'] * 4 / signature['denominator']
    phase = best['offset_seconds'] % length
    if phase > 1e-8:
        phase -= length
    return {'format': 'bpmtracker-continuous-beat-map', 'version': 1, 'status': 'map',
            'duration_seconds': duration,
            'initial': {'bpm': bpm, 'numerator': signature['numerator'],
                        'denominator': signature['denominator'], 'bar_zero_source_seconds': phase},
            'events': [], 'method': 'ORIGINAL_FIXED_UNIT', 'confidence_does_not_mute': True,
            'numeric_tap_discarded': True, 'source_score': best['score']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--stage', choices=('prepare', 'predict'), required=True)
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--shards', type=int, default=1)
    args = parser.parse_args()
    run = args.run
    guard(run)
    rows = read(run / 'source-inputs.json')['samples'][args.shard::args.shards]
    cfg = read(ROOT / 'experiments/metronome_reconstruction_v1/config-tap-v2.json')
    tracker = None
    bundles = {}
    if args.stage == 'prepare' and any(not row.get('cache_path') for row in rows):
        import torch
        from beat_this.inference import Spect2Frames, Audio2Frames
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        tracker = {}
        if any('spectrogram_path' in row for row in rows):
            tracker['spectrogram'] = Spect2Frames(str(ROOT / 'data/models/final0.ckpt'), device='cpu', float16=False)
        if any('audio_path' in row and not row.get('cache_path') for row in rows):
            tracker['audio'] = Audio2Frames(str(ROOT / 'data/models/final0.ckpt'), device='cpu', float16=False)
    opened, forbidden = [], []
    active = [True]

    def hook(event, arguments):
        if event != 'open' or not active[0] or not isinstance(arguments[0], (str, bytes)):
            return
        path = arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0]
        mode = arguments[1] if isinstance(arguments[1], str) else ''
        if any(c in mode for c in 'wax+'):
            return
        if Path(path).suffix in ('.json', '.npz', '.wav', '.ckpt'):
            opened.append(path)
            if any(token in path for token in ('/references/', 'evaluation-index', 'catalog.json',
                                               '/annotations/', 'metrics.json', 'acceptance.json')):
                forbidden.append(path)
                raise RuntimeError('Forbidden source reference read')

    sys.addaudithook(hook)
    prepared_hashes = {}
    try:
        for row in rows:
            ident = row['id']
            started = time.perf_counter()
            if args.stage == 'prepare':
                targets = {key: run / directory / (ident + suffix) for key, directory, suffix in (
                    ('events', 'events', '.npz'), ('family', 'families', '.json'),
                    ('prepared', 'prepared-source', '.json'))}
                if any(p.exists() for p in targets.values()):
                    raise RuntimeError('Source overwrite forbidden')
                for path in targets.values():
                    path.parent.mkdir(parents=True, exist_ok=True)
                receipt = {'id': ident, 'source_only': True, 'reference_reads': False,
                           'fresh_neural_inference': not bool(row.get('cache_path'))}
                try:
                    if 'audio_path' in row:
                        signal, rate = sf.read(row['audio_path'], dtype='float32', always_2d=True)
                        if signal.shape != (row['sample_frames'], row['channels']) or rate != row['sample_rate']:
                            raise RuntimeError('Source audio geometry changed')
                        if row.get('cache_path'):
                            data = source_array(row['cache_path'])
                        else:
                            beat, down = tracker['audio'](signal, rate)
                            data = {'beat_logits': beat.cpu().numpy(), 'downbeat_logits': down.cpu().numpy(),
                                    'duration_seconds': row['duration_seconds'], 'fps': 50}
                        pt, pw = pcm_flux(signal, rate, row['duration_seconds'])
                        receipt['pcm_from_original_waveform'] = True
                        del signal
                    else:
                        import torch
                        path = row['spectrogram_path']
                        if path not in bundles:
                            bundles[path] = np.load(path, allow_pickle=False)
                        feature = bundles[path][row['spectrogram_key']]
                        identity = hashlib.sha256(str((feature.shape, feature.dtype.str)).encode()
                                                  + feature.tobytes(order='C')).hexdigest()
                        if identity != row['feature_sha256'] or feature.shape != (row['spectrogram_frames'], 128):
                            raise RuntimeError('Published feature identity changed')
                        beat, down = tracker['spectrogram'](torch.from_numpy(feature.astype(np.float32)))
                        data = {'beat_logits': beat.cpu().numpy(), 'downbeat_logits': down.cpu().numpy(),
                                'duration_seconds': row['duration_seconds'], 'fps': 50}
                        pt, pw = np.array([]), np.array([])
                        receipt['missing_pcm_not_fabricated'] = True
                    if abs(float(data['duration_seconds']) - row['duration_seconds']) > .08:
                        raise RuntimeError('Neural cache/audio duration mismatch')
                    t, w = event_peaks(data['beat_logits'])
                    bt, bw = event_peaks(data['downbeat_logits'])
                    events = {'times': t, 'weights': w, 'downbeat_times': bt,
                              'downbeat_weights': bw, 'pcm_times': pt, 'pcm_weights': pw,
                              'duration': np.array(row['duration_seconds'])}
                    if row.get('cache_family_path'):
                        family = read(row['cache_family_path'])
                        if family.get('config') != cfg:
                            raise RuntimeError('Cached family configuration differs')
                    else:
                        evidence = make_evidence(data['beat_logits'], data['downbeat_logits'], row['duration_seconds'], cfg)
                        family = prepare_audio_family(evidence, cfg)
                    bank = prepare_map_sources(events, family)
                    receipt['status'] = 'prepared'
                    receipt['source_pulses'] = len(bank['pulses'])
                    receipt['initial_units'] = len(bank['units'])
                except Exception as error:
                    if forbidden:
                        raise
                    events = {key: np.array([]) for key in ('times', 'weights', 'downbeat_times',
                              'downbeat_weights', 'pcm_times', 'pcm_weights')}
                    events['duration'] = np.array(row['duration_seconds'])
                    family = {'status': 'source_preparation_failed', 'levels': []}
                    bank = {'available': False, 'units': [], 'pulses': [], 'bars': []}
                    receipt.update(status='failed', error=f'{type(error).__name__}: {error}')
                np.savez_compressed(targets['events'], **events)
                write(targets['family'], family)
                write(targets['prepared'], bank)
                for path in targets.values():
                    prepared_hashes[str(path.resolve())] = digest(path)
                receipt['seconds'] = time.perf_counter() - started
                write(run / 'source-receipts' / (ident + '.json'), receipt)
                print('SOURCE', ident, receipt['status'], round(receipt['seconds'], 2), flush=True)
            else:
                with np.load(run / 'events' / (ident + '.npz'), allow_pickle=False) as data:
                    events = {key: data[key].copy() for key in data.files}
                bank = read(run / 'prepared-source' / (ident + '.json'))
                family = read(run / 'families' / (ident + '.json'))
                current, original = {}, {}
                for policy in POLICIES:
                    packet = read(run / 'encoded-units' / policy / (ident + '.json'))
                    key = packet.get('unit_id')
                    if key not in current:
                        current[key] = fit(events, bank, packet, PRIMARY)
                    fixed_packet = read(run / 'encoded-fixed-units' / policy / (ident + '.json'))
                    power = fixed_packet.get('power')
                    if power not in original:
                        original[power] = fixed_map(family, fixed_packet, row['duration_seconds'])
                    for method, result in ((PRIMARY, current[key]), ('ORIGINAL_FIXED_UNIT', original[power])):
                        target = run / 'predictions' / method / policy / (ident + '.json')
                        if target.exists():
                            raise RuntimeError('Prediction overwrite forbidden')
                        result = copy.deepcopy(result)
                        result['policy'] = policy
                        write(target, result)
                print('MAP', ident, 'L2 units', len(current), 'events',
                      len(current[next(iter(current))].get('events', [])),
                      'seconds', round(time.perf_counter() - started, 2), flush=True)
    finally:
        active[0] = False
        for bundle in bundles.values():
            bundle.close()
        write(run / 'worker-audit' / f'{args.stage}-{args.shard}.json', {
            'at_utc': stamp(), 'ids': [r['id'] for r in rows], 'actual_read_hook': True,
            'opened_data_paths': sorted(set(opened)), 'forbidden_reads': forbidden})
    if args.stage == 'prepare':
        write(run / 'source-before-tap-freeze' / f'{args.shard}.json', {'files': prepared_hashes})
    guard(run)


if __name__ == '__main__':
    main()
