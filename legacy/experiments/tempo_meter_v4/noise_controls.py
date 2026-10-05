"""Predeclared independent stochastic observation controls for the v4 route.

Manufactured event perturbations are diagnostics, not audio accuracy. This
runner owns no model/helper parameter selection and never changes a scorer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from .ideal_fixtures import fixture
from .latent_clock import time_at
from .observations import local_peaks, refined_times


CASES = (
    ('constant_four', {'signatures': [(4, 4)] * 12}),
    ('within_bar_tempo_change', {'signatures': [(4, 4)] * 12,
                               'tempo_changes': [(17., .6)]}),
)
CONDITIONS = (
    ('baseline', {'kind': 'none', 'seed': 2026100101}),
    ('jitter_10ms', {'kind': 'jitter', 'sigma_seconds': .010, 'seed': 2026100102}),
    ('jitter_30ms', {'kind': 'jitter', 'sigma_seconds': .030, 'seed': 2026100103}),
    ('dropout_25pct', {'kind': 'dropout', 'probability': .25, 'seed': 2026100104}),
    ('false_events_15pct', {'kind': 'false_events', 'rate': .15, 'seed': 2026100105}),
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def event_channels(clock, bars):
    """Exact in-source quarter/eighth/bar/group points before any corruption."""
    last = clock[-1, 0]
    channels = {'beat': [], 'down': [], 'onset': []}
    for q in np.arange(0., last, .5):
        channels['beat'].append(dict(quarter=float(q), seconds=float(time_at(clock, q)),
            height=.9 if q == round(q) else .15,
            role='quarter' if q == round(q) else 'weak_eighth'))
    for bar in bars:
        q = bar['q']
        channels['down'].append(dict(quarter=q, seconds=float(time_at(clock, q)),
                                      height=.99, role='bar_start'))
        offsets = np.cumsum([0, *bar['grouping'][:-1]]) * 4 / bar['d']
        for offset in offsets:
            point = float(q + offset)
            channels['onset'].append(dict(quarter=point,
                seconds=float(time_at(clock, point)), height=.95, role='group_onset'))
    return channels


def perturb_observations(ideal, clock, bars, condition, case_index):
    """Corrupt each input channel independently, without changing the clock."""
    points = event_channels(clock, bars)
    duration = ideal['duration']
    # Child streams distinguish quarter/eighth, downbeat and onset corruption.
    sequence = np.random.SeedSequence([condition['seed'], case_index])
    streams = sequence.spawn(3)
    fields = {name: np.zeros(len(ideal['times'])) for name in points}
    receipt = dict(condition=condition, case_seed_component=case_index,
                   independence='Separate SeedSequence child stream for each channel; '
                                'each input point draws independently',
                   gaussian_lobe_sigma_seconds=.020,
                   false_event_count_rule='ceil(rate * nominal channel count)',
                   outside_physical_support='removed, never clipped into support',
                   channels={})
    for channel, child in zip(points, streams):
        rng = np.random.default_rng(child)
        entries = []
        kind = condition['kind']
        for index, original in enumerate(points[channel]):
            delta = float(rng.normal(0, condition['sigma_seconds'])) if kind == 'jitter' else 0.
            sampled_drop = bool(rng.random() < condition['probability']) if kind == 'dropout' else False
            when = original['seconds'] + delta
            inside = 0. <= when < duration
            keep = inside and not sampled_drop
            entry = dict(original, input_index=index, perturbed_seconds=when,
                         timing_delta_seconds=delta, sampled_drop=sampled_drop,
                         outside_physical_support=not inside, kept=keep,
                         false_event=False)
            entries.append(entry)
        if kind == 'false_events':
            number = int(np.ceil(len(entries) * condition['rate']))
            # False detections use the channel's strong-event amplitude. Their
            # location is independent and uniform in the physical source domain.
            amplitude = {'beat': .9, 'down': .99, 'onset': .95}[channel]
            for index, when in enumerate(rng.uniform(0., duration, number)):
                entries.append(dict(input_index=None, quarter=None, seconds=None,
                    perturbed_seconds=float(when), timing_delta_seconds=None,
                    sampled_drop=False, outside_physical_support=False, kept=True,
                    false_event=True, height=amplitude, role='false_detection'))
        for entry in entries:
            if entry['kept']:
                lobe = entry['height'] * np.exp(-.5 *
                    ((ideal['times'] - entry['perturbed_seconds']) / .020) ** 2)
                fields[channel] = np.maximum(fields[channel], lobe)
        nominal = [entry for entry in entries if not entry['false_event']]
        roles = sorted({entry['role'] for entry in nominal})
        receipt['channels'][channel] = dict(
            nominal_count=len(nominal),
            dropped_count=sum(entry['sampled_drop'] for entry in nominal),
            outside_support_count=sum(entry['outside_physical_support'] for entry in nominal),
            kept_nominal_count=sum(entry['kept'] for entry in nominal),
            false_event_count=sum(entry['false_event'] for entry in entries),
            role_counts={role: dict(nominal=sum(e['role'] == role for e in nominal),
                                   kept=sum(e['role'] == role and e['kept'] for e in nominal))
                         for role in roles},
            points=entries)
    observed = dict(ideal, **fields)
    ix = np.unique(np.r_[local_peaks(fields['beat'], .2), local_peaks(fields['down'], .2)])
    # Match the ideal fixture frontend, including interpolation. Quarter and
    # downbeat jitter can intentionally create distinct adjacent observations.
    observed['events'] = refined_times(np.maximum(fields['beat'], fields['down']), ix, ideal['fps'])
    observed['event_strength'] = fields['beat'][ix]
    observed['event_down'] = fields['down'][ix]
    observed['logits'] = np.column_stack([
        np.log(np.clip(fields[name], 1e-5, 1-1e-5) /
               (1 - np.clip(fields[name], 1e-5, 1-1e-5)))
        for name in ('beat', 'down')])
    # No label or event provenance is supplied to inference.
    receipt['detected_combined_event_count'] = len(ix)
    return observed, receipt


def reference_map(clock, bars, source):
    """Render the unchanged known manufactured clock across source margins."""
    first_length = 4 * bars[0]['n'] / bars[0]['d']
    q_start = -first_length
    knots = [[q_start, float(time_at(clock, q_start))], *clock.tolist()]
    meter_events = []
    for bar in bars:
        signature = (bar['n'], bar['d'], tuple(bar['grouping']))
        if not meter_events or signature != (meter_events[-1]['numerator'],
                meter_events[-1]['denominator'], tuple(meter_events[-1]['grouping'])):
            meter_events.append(dict(pulse=bar['q'], numerator=bar['n'],
                denominator=bar['d'], grouping=bar['grouping'], bar_action='continue'))
    meter_events[0]['pulse'] = q_start
    return dict(schema_version=1, source=source,
        clock_knots=[dict(pulse=float(q), source_seconds=float(t)) for q, t in knots],
        quarters_per_pulse=dict(numerator=1, denominator=1),
        bar_anchor_pulse=0., meter_events=meter_events,
        support_seconds=[[0., source['sample_frames'] / source['sample_rate']]],
        analysis_condition='reference', shared_origin_id=None)


def fixed_index_quarter_diagnostic(reference, prediction):
    from experiments.analysis_legacy.music_map_contract import prepare_map
    from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters
    expected = np.asarray(emitted_quarters(prepare_map(reference)))
    actual = np.asarray(emitted_quarters(prepare_map(prediction['map'])))
    result = dict(policy='One nearest opening quarter anchor within 70ms, then '
                         'fixed index pairing; no resets, phase corrections or clock warps',
                  expected_count=len(expected), predicted_count=len(actual),
                  opening_anchor_passed=False, maximum_absolute_error_seconds=None)
    if not len(expected) or not len(actual):
        return result
    anchor = int(np.argmin(abs(actual - expected[0])))
    error = float(actual[anchor] - expected[0])
    result.update(predicted_opening_index=anchor, opening_error_seconds=error)
    if abs(error) > .07:
        return result
    count = min(len(expected), len(actual)-anchor)
    errors = actual[anchor:anchor+count] - expected[:count]
    result.update(opening_anchor_passed=True, paired_count=count,
        maximum_absolute_error_seconds=float(np.max(abs(errors))),
        final_paired_error_seconds=float(errors[-1]),
        unmatched_reference_count=len(expected)-count,
        unmatched_prediction_count=len(actual)-count,
        errors_seconds=errors.tolist())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parameters', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path.cwd() / 'experiments/analysis_legacy'))
    parameter_record = json.loads(args.parameters.read_text())
    parameters = parameter_record['selected']
    args.output.mkdir(parents=True, exist_ok=False)
    from . import coordinate_analyzer
    analyze = coordinate_analyzer.install()
    helper_names = coordinate_analyzer._BINDING
    root = Path(__file__).resolve().parents[2]
    scorer_paths = (
        'experiments/tempo_meter_v2/score_generic13.py',
        'experiments/tempo_meter_v2/score_primary8.py',
        'experiments/tempo_meter_v2/score_primary11.py',
        'experiments/tempo_meter_v2/score_scoped_primary.py',
        'experiments/analysis_legacy/music_map_contract.py',
        'experiments/analysis_legacy/grid_metrics.py',
        'experiments/analysis_legacy/music_map_metrics.py',
    )
    protocol = dict(
        scope='Two manufactured 12-bar observation cases; not actual audio or unseen accuracy',
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        cases=[dict(id=name, fixture=kwargs) for name, kwargs in CASES],
        conditions=[dict(id=name, **setting) for name, setting in CONDITIONS],
        independent_conditions=True, composed_noise=False, total_predictions=10,
        event_channels='Quarter and weak-eighth detector, downbeat detector, onset groups',
        noise_floor=False, physical_end_event_excluded=True,
        observation_rendering='Maximum 20ms Gaussian lobes per channel, 50fps; '
                              'input events derive from the perturbed detector fields',
        initial_scalar_bpm=120., beam=32, rounds=2, repetition='none',
        numeric_parameters=parameters, parameters_path=str(args.parameters.resolve()),
        parameters_sha256=digest(args.parameters),
        implementation_sha256={name: digest(Path(__file__).with_name(name))
                               for name in [*helper_names, 'noise_controls.py',
                                            'ideal_fixtures.py', 'fixtures.py']},
        scorer_sha256={name: digest(root / name) for name in scorer_paths},
        scorer_policy='Unchanged normal_score with owner_equivalence=False; '
                      'six >=90% gates, 70ms events, 500ms changes; no relaxation',
        parameter_selection_from_results=False, references_read_by_inference=False,
        prediction_freeze_before_scoring=True)
    # Persist seeds, costs and source versions BEFORE generating any prediction.
    save(args.output / 'protocol.json', protocol)
    rows = []
    references = {}
    started = time.perf_counter()
    for case_index, (case_name, kwargs) in enumerate(CASES):
        ideal, clock, bars = fixture(**kwargs)
        for condition_name, condition in CONDITIONS:
            ident = case_name + '-' + condition_name
            folder = args.output / ident
            folder.mkdir()
            observed, perturbations = perturb_observations(ideal, clock, bars,
                                                          condition, case_index)
            arrays = {name: value for name, value in observed.items()
                      if isinstance(value, np.ndarray)}
            observation_path = folder / 'observations.npz'
            np.savez_compressed(observation_path, **arrays)
            save(folder / 'perturbations.json', perturbations)
            # A synthetic observation digest is an explicit provenance marker,
            # not a claim that these manufactured inputs contain decoded audio.
            source = dict(sha256=digest(observation_path), sample_rate=48000,
                          sample_frames=int(round(ideal['duration'] * 48000)))
            references[ident] = (clock, bars, source)
            run_started = time.perf_counter()
            print('starting', ident, flush=True)
            try:
                selected, alternatives = analyze(observed, source, 120.,
                    parameters=parameters, beam=32, rounds=2, repetition='none')
            except ValueError as exc:
                if str(exc) not in {'insufficient source events', 'empty latent-coordinate beam',
                        'no valid latent clock', 'no coherent hypotheses', 'no terminal bar paths'}:
                    raise
                selected = dict(status='decode_failed', map=None, error=str(exc),
                                source_only=True, reference_read=False)
                alternatives = []
            prediction_path = folder / 'selected.json'
            save(prediction_path, selected)
            save(folder / 'alternatives.json', alternatives)
            rows.append(dict(id=ident, fixture_id=case_name, condition=condition_name,
                source=source, observations_sha256=digest(observation_path),
                prediction_path=str(prediction_path.resolve()),
                prediction_sha256=digest(prediction_path),
                perturbations_sha256=digest(folder / 'perturbations.json'),
                runtime_seconds=time.perf_counter()-run_started))
            save(args.output / 'predictions.json', dict(complete=False,
                reference_stage_started=False, rows=rows))
            print('predicted', ident, rows[-1]['runtime_seconds'], flush=True)
    frozen = dict(complete=True, reference_stage_started=False,
                  total_runtime_seconds=time.perf_counter()-started, rows=rows)
    save(args.output / 'predictions.json', frozen)
    # Only after ALL source-only predictions are immutable do we prepare targets
    # and invoke the untouched reference scorer.
    from experiments.tempo_meter_v2.score_generic13 import normal_score
    from experiments.tempo_meter_v2.score_scoped_primary import emitted_quarters, emitted_bars
    from experiments.analysis_legacy.music_map_contract import prepare_map
    from .calibrate_controls import error as labeled_bar_error
    results = []
    for row in rows:
        if digest(row['prediction_path']) != row['prediction_sha256']:
            raise ValueError('frozen prediction changed')
        clock, bars, source = references[row['id']]
        target = reference_map(clock, bars, source)
        prepared = prepare_map(target)
        target_quarters = emitted_quarters(prepared)
        oracle = normal_score(target, dict(map=target), target_quarters, False)
        if not oracle['all_gates_pass']:
            raise ValueError('manufactured reference self-score failed: ' + row['id'])
        save(args.output / row['id'] / 'reference.json', dict(map=target))
        prediction = json.loads(Path(row['prediction_path']).read_text())
        if prediction.get('status') == 'decode_failed':
            scored = dict(scores={key: None for key in oracle['scores']},
                          gates={key: False for key in oracle['gates']}, all_gates_pass=False,
                          status='decode_failed', error=prediction['error'])
            diagnostic = dict(expected_bars=len(bars), predicted_bars=None,
                              exact_bar_count_passed=False, fixed_index_quarter=None)
        else:
            scored = normal_score(target, prediction, target_quarters, False)
            actual_bars = emitted_bars(prepare_map(prediction['map']))
            diagnostic = dict(expected_bars=len(bars), predicted_bars=len(actual_bars),
                exact_bar_count_passed=len(actual_bars) == len(bars),
                wrong_labeled_bar_events=labeled_bar_error(bars,
                    prediction['diagnostics']['rhythmic_bars']),
                fixed_index_quarter=fixed_index_quarter_diagnostic(target, prediction))
        result = dict(**row, score=scored, diagnostics=diagnostic,
                      reference_self_score_passed=True)
        results.append(result)
        print('scored', row['id'], scored['all_gates_pass'],
              json.dumps(scored['scores']), flush=True)
    summary = dict(scope=protocol['scope'], complete=True,
        predictions_sha256=digest(args.output / 'predictions.json'),
        protocol_sha256=digest(args.output / 'protocol.json'),
        count=len(results), six_gate_passes=sum(row['score']['all_gates_pass'] for row in results),
        no_parameter_or_scorer_changes=True, rows=results,
        interpretation='Independent perturbation diagnostics on only two short manufactured cases; '
                       'failures preserved. This is not a probability estimate or an audio benchmark.')
    save(args.output / 'results.json', summary)
    lines = [
        '# Independent stochastic observation controls', '',
        protocol['scope'] + '.', '',
        'Seeds and costs were stored in `protocol.json` before predictions. All ten '
        'source-only predictions were frozen before unchanged six-gate scoring. '
        'No parameter or scorer change follows from these results.', '',
        '| Fixture | Condition | Six gates | In-source bars | Maximum fixed-index quarter error |',
        '| --- | --- | --- | --- | --- |',
    ]
    for row in results:
        drift = row['diagnostics'].get('fixed_index_quarter') or {}
        maximum = drift.get('maximum_absolute_error_seconds')
        shown = 'unavailable' if maximum is None else f'{maximum * 1000:.3f}ms'
        lines.append(f"| {row['fixture_id']} | {row['condition']} | "
            f"{'pass' if row['score']['all_gates_pass'] else 'fail'} | "
            f"{row['diagnostics']['predicted_bars']}/{row['diagnostics']['expected_bars']} | {shown} |")
    lines.extend(['', 'Independent per-channel jitter/dropout and uniform false detections '
        'alter detector inputs only. True clocks, source durations and labels stay fixed. '
        'Quarter and weak-eighth, downbeat and onset perturbations are all recorded in '
        'each `perturbations.json`. The original deterministic-floor/censored fixture '
        'results remain separate historical evidence.', '',
        'A single seed per condition and only two cases cannot establish robustness '
        'across music, uncertainty calibration, or unseen-song accuracy. Exact bar '
        'count and the fixed opening-index quarter diagnostic supplement the strict '
        'scorer; they do not waive extra events or replace any of its six gates.', ''])
    (args.output / 'RESULTS.md').write_text('\n'.join(lines))
    print('complete', summary['six_gate_passes'], '/', len(results), flush=True)


if __name__ == '__main__':
    main()
