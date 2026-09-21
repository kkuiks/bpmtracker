"""Verify a constant frame offset between a stem and a corresponding mix.

Uses waveform correlation only, never beat predictions, BPM or reference clicks.
The input audio is not shifted or stretched. An accepted audit certifies a
source-to-source offset in sampled windows, not original metronome provenance.
"""
import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from inspect_inputs import sha256


@dataclass(frozen=True)
class AlignmentConfig:
    windows: int = 9
    window_seconds: float = 5.
    maximum_offset_seconds: float = 8.
    minimum_correlation: float = .2
    minimum_agreeing_windows: int = 7
    maximum_frame_spread: int = 2


def correlations(longer, shorter):
    """Normalized sliding waveform correlation, computed with NumPy FFT."""
    longer, shorter = np.asarray(longer, float), np.asarray(shorter, float)
    if len(longer) < len(shorter) or len(shorter) < 2:
        raise ValueError('correlation window geometry invalid')
    shorter = shorter-shorter.mean()
    size = 1 << (len(longer)+len(shorter)-2).bit_length()
    cross = np.fft.irfft(np.fft.rfft(longer, size)*np.fft.rfft(shorter[::-1], size), size)
    cross = cross[len(shorter)-1:len(longer)]
    sums = np.r_[0., np.cumsum(longer)]
    squares = np.r_[0., np.cumsum(longer*longer)]
    energy = squares[len(shorter):]-squares[:-len(shorter)]-(sums[len(shorter):]-sums[:-len(shorter)])**2/len(shorter)
    denominator = np.sqrt(np.maximum(energy, 0)*np.sum(shorter*shorter))
    return cross/np.maximum(denominator, 1e-20)


def audit(mix, stem, rate, config=None):
    config = config or AlignmentConfig()
    if mix.ndim != 1 or stem.ndim != 1 or not np.isfinite(mix).all() or not np.isfinite(stem).all():
        raise ValueError('finite mono source waveforms required')
    window = round(config.window_seconds*rate)
    margin = round(config.maximum_offset_seconds*rate)
    first = margin
    last = min(len(mix), len(stem))-window-margin
    if last <= first:
        raise ValueError('sources too short for distributed alignment audit')
    hop = max(1, round(rate/1000))
    rows = []
    for start in np.linspace(first, last, config.windows).astype(int):
        # Centered bins are unnecessary: both source waveforms use identical bins.
        start = start//hop*hop
        stop = start+window//hop*hop
        chunk_start = (start-margin)//hop*hop
        chunk_stop = (stop+margin)//hop*hop
        target = mix[start:stop]
        source = stem[chunk_start:chunk_stop]
        small_target = target.reshape(-1, hop).mean(axis=1)
        small_source = source.reshape(-1, hop).mean(axis=1)
        coarse = correlations(small_source, small_target)
        candidate = chunk_start+int(np.argmax(coarse))*hop
        refine_start = max(0, candidate-3*hop)
        refine_stop = min(len(stem), candidate+3*hop+len(target))
        fine = correlations(stem[refine_start:refine_stop], target)
        peak = int(np.argmax(fine))
        rows.append({'mix_start_frame': int(start), 'window_frames': len(target),
                     'stem_minus_mix_frames': int(refine_start+peak-start),
                     'normalized_correlation': float(fine[peak])})
    eligible = [r for r in rows if r['normalized_correlation'] >= config.minimum_correlation]
    offsets = [r['stem_minus_mix_frames'] for r in eligible]
    spread = max(offsets)-min(offsets) if offsets else None
    accepted = len(eligible) >= config.minimum_agreeing_windows and spread <= config.maximum_frame_spread
    return {'configuration': asdict(config), 'windows': rows, 'eligible_windows': len(eligible),
            'eligible_frame_spread': spread, 'qualified_constant_offset': bool(accepted),
            'stem_minus_mix_frames': int(round(np.median(offsets))) if accepted else None,
            'reference_click_or_model_used': False,
            'qualification': 'Constant waveform correspondence in distributed windows; no audio mutation or time scaling.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mix', required=True, type=Path)
    parser.add_argument('--stem', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--maximum-frame-spread', type=int, default=2,
                        help='Declared source alignment tolerance; wider audits must retain their uncertainty')
    args = parser.parse_args()
    if args.output.exists() or args.maximum_frame_spread < 0:
        parser.error('new output and nonnegative frame tolerance required')
    mix, rate = sf.read(args.mix, dtype='float32', always_2d=True)
    stem, stem_rate = sf.read(args.stem, dtype='float32', always_2d=True)
    if rate != stem_rate:
        parser.error('equal native sample rates required; no inferred resampling')
    result = audit(mix.mean(axis=1), stem.mean(axis=1), rate,
                   AlignmentConfig(maximum_frame_spread=args.maximum_frame_spread))
    result.update(sample_rate=rate, mix={'path': str(args.mix), 'sha256': sha256(args.mix), 'frames': len(mix)},
                  stem={'path': str(args.stem), 'sha256': sha256(args.stem), 'frames': len(stem)},
                  auditor_sha256=sha256(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
