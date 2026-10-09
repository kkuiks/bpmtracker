"""Four new compositions, six paired interventions; independent transport arithmetic."""
import argparse
from decimal import Decimal, localcontext, ROUND_HALF_UP
from fractions import Fraction
import math
from pathlib import Path
import numpy as np
import soundfile as sf
from .io import write

RATE = 32000
PARENTS = [(7093, Fraction(375, 4), Fraction(437, 4)),
           (7139, Fraction(485, 4), Fraction(275, 2)),
           (7211, Fraction(315, 2), Fraction(699, 4)),
           (7297, Fraction(735, 4), Fraction(204))]
CASES = ('steady', 'arrangement', 'weak', 'step', 'return', 'short')


def fractional_time(q, segments, lead):
    result, used = lead, Fraction(0)
    for bpm, length in segments:
        result += min(max(Fraction(q) - used, 0), length) * 60 / bpm
        used += length
    return result


def decimal_time(q, segments, lead):
    with localcontext() as context:
        context.prec = 50
        result = Decimal(lead.numerator) / Decimal(lead.denominator)
        target = Decimal(str(float(q)))
        used = Decimal(0)
        for bpm, length in segments:
            take = min(max(target - used, Decimal(0)), Decimal(length))
            result += take * Decimal(60) * Decimal(bpm.denominator) / Decimal(bpm.numerator)
            used += Decimal(length)
        return result


def sound(kind, pitch, gain, rng):
    # New voice recipes, not the prior step0 renderer/voice implementation.
    length = {'kick': .20, 'snare': .14, 'hat': .055, 'bass': .32, 'pluck': .42, 'pad': 1.65}[kind]
    t = np.arange(round(length * RATE)) / RATE
    f = 440 * 2 ** ((pitch - 69) / 12)
    if kind == 'kick':
        phase = 2 * np.pi * (45 * t + 65 * .025 * (1 - np.exp(-t / .025)))
        y = np.sin(phase) * np.exp(-t / .045)
    elif kind in ('snare', 'hat'):
        n = rng.normal(size=len(t))
        n = np.r_[0, np.diff(n)]
        y = n * np.exp(-t / (.022 if kind == 'snare' else .010))
        if kind == 'snare': y += .35 * np.sin(2 * np.pi * 185 * t) * np.exp(-t / .035)
    elif kind == 'pad':
        y = sum(np.sin(2 * np.pi * f * scale * t) / 3 for scale in (1, 1.002, 2))
        y *= (1 - np.exp(-t / .09)) * np.exp(-t / .65)
    else:
        y = np.sin(2 * np.pi * f * t + (1.7 if kind == 'pluck' else .35)
                   * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t / .08))
        y *= (1 - np.exp(-t / .003)) * np.exp(-t / (.10 if kind == 'bass' else .14))
    return gain * y


def notes(seed, case):
    roots = (40 + seed % 7, 45 + seed % 7, 43 + seed % 7, 38 + seed % 7)
    result = []
    for q in range(72):
        beat, bar = q % 4, q // 4
        root = roots[(bar // 2) % 4]
        altered = case == 'arrangement' and 24 <= q < 48
        weak = case == 'weak' and 24 <= q < 48
        if not weak:
            if altered:
                if beat == 0: result.append((Fraction(q), 'kick', 36, .75))
                if beat == 2: result.append((Fraction(q), 'snare', 38, .55))
                for sub in (0, 1, 2, 3):
                    result.append((Fraction(q) + Fraction(sub, 4), 'hat', 42, .055 if sub else .10))
            else:
                result.append((Fraction(q), 'kick' if beat in (0, 2) else 'snare', 36, .8 if beat == 0 else .48))
                result.append((Fraction(q), 'hat', 42, .13))
                result.append((Fraction(q) + Fraction(1, 2), 'hat', 42, .075))
            result.append((Fraction(q) + (Fraction(1, 2) if beat == 3 else 0), 'bass', root, .23))
        elif beat == 0:
            result.append((Fraction(q), 'bass', root, .08))
        if beat == 0:
            for pitch in (root + 24, root + 28, root + 31):
                result.append((Fraction(q), 'pad', pitch, .065))
        if beat in (1, 3):
            result.append((Fraction(q) + Fraction(1, 2), 'pluck', root + 36 + (bar % 3) * 2, .065 if weak else .12))
    return result


def main():
    p = argparse.ArgumentParser(); p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    plan = [{'parent_seed': seed, 'initial_bpm': float(base), 'changed_bpm': float(alt),
             'split': 'development' if i < 2 else 'prospective', 'cases': list(CASES)}
            for i, (seed, base, alt) in enumerate(PARENTS)]
    write(a.output / 'construction-plan.json', {'parents': plan, 'total_inputs': 24,
          'declared_before_observation_and_selection': True, 'same_clock_arrangement_intervention': True,
          'distinct_voice_recipe_from_previous_renderer': True, 'not_real_music_generalization': True})
    sources, evaluation, hints, verification = [], [], [], []
    for index, (seed, base, alt) in enumerate(PARENTS):
        lead = Fraction((137, 291, 83, 397)[index], 1000)
        for case in CASES:
            ident = f'mcc_{seed}_{case}'
            segments = [(base, 72)] if case in ('steady', 'arrangement', 'weak') else (
                [(base, 36), (alt, 36)] if case == 'step' else
                [(base, 26), (alt, 19), (base, 27)] if case == 'return' else
                [(base, 32), (alt, 4), (base, 36)])
            duration = float(fractional_time(72, segments, lead)) + 1.2
            frames = math.ceil(duration * RATE); audio = np.zeros(frames); marker = np.zeros(frames)
            rng = np.random.default_rng(seed); ledger = []; errors = []
            for q, kind, pitch, gain in notes(seed, case):
                exact = fractional_time(q, segments, lead) * RATE
                frame = (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
                independent = int((decimal_time(q, segments, lead) * RATE).to_integral_value(rounding=ROUND_HALF_UP))
                errors.append(abs(frame - independent))
                y = sound(kind, pitch, gain, rng); end = min(frames, frame + len(y))
                audio[frame:end] += y[:end - frame]
                ledger.append({'quarter': float(q), 'frame': frame, 'voice': kind, 'pitch': pitch})
            audio *= .82 / max(np.max(np.abs(audio)), 1e-12)
            quarter = [float(decimal_time(q, segments, lead)) for q in range(72)]
            down = quarter[::4]
            for q in range(72): marker[round(fractional_time(q, segments, lead) * RATE)] = .8
            expected = [int((decimal_time(q, segments, lead) * RATE).to_integral_value(rounding=ROUND_HALF_UP)) for q in range(72)]
            if max(errors) > 1 or max(abs(np.flatnonzero(marker) - expected)) > 1:
                raise ValueError('Independent new-corpus transport verification failed')
            folder = a.output / 'inputs' / ident; folder.mkdir(parents=True)
            sf.write(folder / 'music.wav', audio, RATE, subtype='PCM_24')
            sf.write(folder / 'transport-marker.wav', marker, RATE, subtype='PCM_24')
            write(folder / 'event-ledger.json', {'events': ledger})
            tempo = []; q0 = 0
            for bpm, length in segments:
                tempo.append({'quarter': q0, 'time_seconds': float(decimal_time(q0, segments, lead)), 'bpm_quarter': float(bpm)})
                q0 += length
            support = [[float(lead), float(decimal_time(72, segments, lead))]]
            reference = {'id': ident, 'tempo_events': tempo, 'meter_events': [{'time_seconds': float(lead), 'numerator': 4, 'denominator': 4}],
                         'quarter_beats_seconds': quarter, 'downbeats_seconds': down, 'support_seconds': support,
                         'absolute_audio_origin_verified': True, 'coordinate_bound_ms': 1000 / RATE,
                         'independent_real_producer_clock': False, 'perceptual_quarter_uniqueness_certified': False}
            refpath = a.output / 'references' / f'{ident}.json'; write(refpath, reference)
            sources.append({'id': ident, 'audio_path': str((folder / 'music.wav').resolve()), 'sample_rate': RATE,
                            'sample_frames': frames, 'channels': 1, 'duration_seconds': frames / RATE})
            evaluation.append({'id': ident, 'reference_path': str(refpath.resolve()), 'kind': 'authored',
                               'role': 'new_development' if index < 2 else 'new_prospective', 'support_seconds': support,
                               'parent_group': str(seed), 'variant': case})
            hints.append({'id': ident, 'initial_bpm': float(base), 'bpm_unit_quarters': 1.,
                          'scope': 'initial_audio_section', 'origin': 'constructed_assumed_initial_information'})
            verification.append({'id': ident, 'event_frame_error': max(errors), 'marker_frame_error': 0,
                                 'independent_fraction_decimal_coordinate_paths': True})
            print('RENDER', ident, flush=True)
    write(a.output / 'source-inputs.json', {'samples': sources})
    write(a.output / 'evaluation-index.json', {'rows': evaluation})
    write(a.output / 'initial-information.json', {'rows': hints, 'actual_human_inputs_collected': False})
    write(a.output / 'coordinate-verification.json', {'rows': verification, 'all_passed': True, 'formal_enrollment_changed': False})


if __name__ == '__main__': main()
