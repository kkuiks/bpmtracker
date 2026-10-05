"""Frozen-observation interventions. Oracle outputs are diagnosis, not inference."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import numpy as np
from . import analyzer
from .clock_search import clock_bank, select_pulse_level
from .meter_search import decode_meter, interpolate
from .timing_controls import proposals
from .evaluate_batch import references
from .build_reviewed_review import six_scores
from .probe_resources import digest


PROBES = ('daybreak_equilibrium', 'walker_he-will-hold-me-fast',
          'state_shirt_hospital_hill', 'wage_war')


def observations(row):
    folder = Path(row['selected']['path']).parent
    with np.load(folder/'structural-observations.npz') as z:
        structure = {k: z[k].copy() for k in z.files}
    cache = Path('data/cache/tempo-meter-v3/acoustic-v1')/(row['source']['sha256']+'.npz')
    receipt = json.loads(cache.with_suffix('.json').read_text())
    assert receipt['binding'] == row['feature_binding']
    with np.load(cache) as z:
        logits, energy = z['logits'].copy(), z['energy'].copy()
    return logits, energy, structure


def raw_rhythm(logits, structure):
    value = deepcopy(structure)
    times = np.arange(len(value['events']))/12.5
    raw_times = np.arange(len(logits))/50
    for i in [0, 1]:
        value['events'][:, i] = np.interp(times, raw_times, logits[:, i])
    value['events'][:, 2] = -20.  # no learned transition discount
    value['numerator'][:] = 0.
    value['denominator'][:] = 0.
    # Keep the unchanged tail head; this isolates rhythmic heads only.
    return value


def payload(candidate, row, structure, logits, energy, oracle=False):
    duration = row['source']['sample_frames']/row['source']['sample_rate']
    raw, tail = analyzer.declared_map(candidate, row['source'], duration, structure, logits, energy)
    raw['analysis_condition'] = 'reference_assisted_diagnostic' if oracle else 'user_bpm_guided'
    return dict(map=raw, source_only=not oracle, reference_read=oracle,
                diagnostics=dict(clock_family=candidate['name'], clock_fit=candidate['fit'],
                                 meter_search=candidate['meter']['diagnostics'], tail=tail))


def raw_analysis(row, logits, energy, structure):
    from experiments.analysis_legacy.music_map_contract import prepare_map, render_bars
    bank = clock_bank(logits, structure, energy)
    bank.extend(proposals(logits, row['source'], structure))
    for c in bank:
        c['meter'] = decode_meter(c['clock'], logits, structure)
        c['joint_score'] = c['score'] + .35*c['meter']['score']
    bank, decision = select_pulse_level(bank, row.get('initial_bpm'))
    rejected = []
    for c in bank:
        pred = payload(c, row, structure, logits, energy)
        try:
            assert render_bars(prepare_map(pred['map']))['status'] == 'rendered'
        except (ValueError, TypeError, KeyError, AssertionError) as error:
            rejected.append(str(error)); continue
        pred['diagnostics'].update(pulse_level_selection=decision, rejected=rejected)
        return pred
    raise ValueError('No valid ablation map')


def reference_clock(raw, duration):
    factor = raw['quarters_per_pulse']['numerator']/raw['quarters_per_pulse']['denominator']
    clock = np.array([[k['pulse']*factor, k['source_seconds']] for k in raw['clock_knots']])
    first = np.ceil(np.interp(0., clock[:, 1], clock[:, 0])-1e-8)
    first_time = interpolate(clock, [first])[0]
    rate = np.diff(clock[-2:, 0])[0]/np.diff(clock[-2:, 1])[0]
    end = clock[-1, 0] + (duration-clock[-1, 1])*rate
    middle = clock[(clock[:, 0] > first) & (clock[:, 0] < end)]
    clock = np.vstack([[first, first_time], middle, [end, duration]])
    clock[:, 0] -= first
    assert clock[0, 0] == 0 and np.all(np.diff(clock[:, 0]) > 0)
    return clock


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    import torch
    torch.set_num_threads(4)
    sys.path.insert(0, str(Path.cwd()/'experiments/analysis_legacy'))
    from experiments.tempo_meter_v2.score_generic13 import normal_score
    from experiments.tempo_meter_v2.score_scoped_primary import score_scoped
    manifest = json.loads((a.baseline/'predictions/manifest.json').read_text())
    rows = [r for r in manifest['rows'] if r['id'] in PROBES]
    refs = references(Path.cwd(), rows)
    results = []
    for row in rows:
        started = time.perf_counter()
        logits, energy, learned = observations(row)
        ablated = raw_rhythm(logits, learned)
        ref = refs[row['id']]
        if ref['policy']:
            scorer = lambda v: score_scoped(ref['accepted'], ref['policy'], v, row['source'])
        else:
            scorer = lambda v: normal_score(ref['map'], v, ref['accepted']['beats_seconds'], False)
        values = {'baseline': json.loads(Path(row['selected']['path']).read_text()),
                  'raw_rhythm': raw_analysis(row, logits, energy, ablated)}
        duration = row['source']['sample_frames']/row['source']['sample_rate']
        clock = reference_clock(ref['map'], duration)
        for name, structure in [('oracle_clock_learned', learned), ('oracle_clock_raw', ablated)]:
            c = dict(name=name, clock=clock, fit=dict(segments=len(clock)-1),
                     meter=decode_meter(clock, logits, structure))
            values[name] = payload(c, row, structure, logits, energy, oracle=True)
        for condition, value in values.items():
            path = a.output/f'{row["id"]}-{condition}.json'
            path.write_text(json.dumps(value, indent=2)+'\n')
            try:
                score = scorer(value)
                error = None
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                from experiments.analysis_legacy.music_map_contract import prepare_map, render_bars
                score = None
                try:
                    details = render_bars(prepare_map(value['map']))
                except Exception as inner:
                    details = str(inner)
                error = dict(message=str(exc), rendering=details)
            results.append(dict(id=row['id'], condition=condition,
                                oracle=condition.startswith('oracle'), score=score, error=error,
                                prediction=dict(path=str(path.resolve()), sha256=digest(path))))
            print(row['id'], condition, [round(100*x, 1) if x is not None else None for x in six_scores(score)] if score else error, flush=True)
        print('seconds', round(time.perf_counter()-started, 2), flush=True)
        (a.output/'results.json').write_text(json.dumps(dict(kind='stage_intervention_diagnosis',
            raw_ablation='No learned rhythmic heads or learned tempo preference; unchanged learned tail head retained.',
            oracle_clock='Reference quarter timing and tempo only, extended to source end; no reference meter or tail boundary supplied.',
            baseline_manifest_sha256=digest(a.baseline/'predictions/manifest.json'), rows=results), indent=2)+'\n')


if __name__ == '__main__':
    main()
