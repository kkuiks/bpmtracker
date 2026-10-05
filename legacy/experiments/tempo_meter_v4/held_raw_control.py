"""Raw-observation control on the exact frozen learned-validation excerpts.

Prediction workers receive no reference paths. All predictions freeze before
scoring with the existing evaluator and equal-source six-score criterion.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

EXPECTED_DECODE_FAILURES = frozenset({
    'insufficient source events', 'empty latent-coordinate beam',
    'no valid latent clock', 'no coherent hypotheses', 'no terminal bar paths',
})
SOURCE_KEYS = ('id', 'parent_id', 'group', 'source', 'initial_bpm', 'observations',
               'observations_sha256', 'parent_source_sha256', 'source_span_seconds')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def predict_case(case_path, parameters_path, output):
    from .observations import prepare
    from .coordinate_analyzer import install
    row = json.loads(Path(case_path).read_text())
    if set(row) != set(SOURCE_KEYS):
        raise ValueError('unexpected source-only case fields')
    parameters = json.loads(Path(parameters_path).read_text())['selected']
    if not parameters.get('coordinate_refinement'):
        raise ValueError('coordinate route required')
    if digest(row['observations']) != row['observations_sha256']:
        raise ValueError('bound held observations changed')
    with np.load(row['observations']) as z:
        features, logits, energy = (z[k].copy() for k in ('features', 'logits', 'energy'))
    obs = prepare(logits, energy, features=features)
    assert 'quarter_probability_supervision' not in obs and 'grid_probability' not in obs
    analyze = install()
    started = time.perf_counter()
    try:
        prediction, _ = analyze(obs, row['source'], row['initial_bpm'],
                    parameters=parameters, repetition='none', beam=32, rounds=2)
    except ValueError as exc:
        if str(exc) not in EXPECTED_DECODE_FAILURES:
            raise
        prediction = dict(status='decode_failed', error=str(exc), map=None,
            source_only=True, reference_read=False, observed_events=len(obs['events']),
            selection_contribution=0., fallback_used=False)
    prediction['raw_control'] = dict(observation_type='original Beat This beat/down logits plus RMS-derived onset',
        learned_model_used=False, quarter_probability_supervision=False,
        grid_probability_supplied=False, references_available_to_worker=False,
        parameters_sha256=digest(parameters_path), observations_sha256=row['observations_sha256'],
        beam=32, rounds=2, repetition='none', runtime_seconds=time.perf_counter()-started)
    Path(output).write_text(json.dumps(prediction, indent=2, allow_nan=False)+'\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cases', type=Path)
    p.add_argument('--case', type=Path)
    p.add_argument('--parameters', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--learned-selection', type=Path)
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--resume', action='store_true')
    a = p.parse_args()
    sys.path.insert(0, str(Path.cwd()/'experiments/analysis_legacy'))
    if a.case is not None:
        predict_case(a.case, a.parameters, a.output)
        return
    if a.cases is None or a.learned_selection is None:
        p.error('--cases and --learned-selection required for aggregate control')
    started = time.perf_counter()
    catalog = json.loads(a.cases.read_text())
    cases = catalog['rows']
    if len(cases) != 8 or len({r['parent_id'] for r in cases}) != 6:
        raise ValueError('exact eight held cases/six parent sources required')
    if len({r['id'] for r in cases}) != len(cases):
        raise ValueError('duplicate held case')
    a.output.mkdir(parents=True, exist_ok=a.resume)
    jobs = a.output/'source-cases'
    jobs.mkdir(exist_ok=a.resume)
    names = ('held_raw_control.py', 'coordinate_analyzer.py', 'analyzer.py',
             'observations.py', 'latent_clock.py', 'bar_structure.py',
             'fast_structure.py', 'repetition.py', 'support.py',
             'capacity_emissions.py', 'capacity_fit.py', 'capacity_objective.py',
             'capacity_support.py', 'capacity_vocabulary.py', 'learned_support.py')
    sources = {n: digest(Path(__file__).with_name(n)) for n in names}
    binding = dict(cases_sha256=digest(a.cases), parameters_sha256=digest(a.parameters),
                   implementation_sha256=sources)
    predictions = {}
    manifest_path = a.output/'predictions.json'
    if a.resume and manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if any(previous[k] != v for k,v in binding.items()):
            raise ValueError('raw control resume binding differs')
        for row in previous['rows']:
            if digest(row['prediction']) != row['sha256']:
                raise ValueError('frozen prediction changed')
            predictions[row['id']] = row
    def save(complete=False):
        value = dict(binding, complete=complete, observation_model_used=False,
            prediction_stage_reference_read=False, workers=a.workers,
            rows=[predictions[r['id']] for r in cases if r['id'] in predictions])
        temporary = manifest_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, indent=2)+'\n')
        os.replace(temporary, manifest_path)
    save()
    def execute(row):
        source_case = jobs/(row['id']+'.json')
        source_case.write_text(json.dumps({k:row[k] for k in SOURCE_KEYS}, indent=2)+'\n')
        target = a.output/(row['id']+'-prediction.json')
        command = [sys.executable, '-m', 'experiments.tempo_meter_v4.held_raw_control',
                   '--case', str(source_case), '--parameters', str(a.parameters), '--output', str(target)]
        with (jobs/(row['id']+'.log')).open('a') as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError('raw held prediction failed: '+row['id'])
        return dict(id=row['id'], prediction=str(target.resolve()), sha256=digest(target))
    pending = [r for r in cases if r['id'] not in predictions]
    with ThreadPoolExecutor(max_workers=a.workers) as executor:
        futures = {executor.submit(execute,r):r for r in pending}
        for future in as_completed(futures):
            row = future.result()
            predictions[row['id']] = row
            save()
            print('raw held prediction', row['id'], len(predictions), '/8', flush=True)
    assert len(predictions) == len(cases)
    save(True)
    # No reference JSON is opened above this completed-prediction freeze.
    from experiments.analysis_legacy.music_map_contract import prepare_map
    from experiments.tempo_meter_v3.evaluate_reviewed import score_extra
    results = []
    for row in cases:
        if digest(row['reference']) != row['reference_sha256']:
            raise ValueError('held reference changed')
        reference = prepare_map(json.loads(Path(row['reference']).read_text())['map'])
        tail = row['no_grid'][0] if row['no_grid'] else None
        oracle = score_extra(reference, dict(map=reference), tail, row['unknown_outside_support'])
        if not oracle['all_gates_pass']:
            raise ValueError('held reference self-score failed: '+row['id'])
        frozen = predictions[row['id']]
        if digest(frozen['prediction']) != frozen['sha256']:
            raise ValueError('prediction changed after freeze')
        prediction = json.loads(Path(frozen['prediction']).read_text())
        if prediction.get('status') == 'decode_failed':
            score = dict(status='decode_failed', error=prediction['error'],
                         scores={k:None for k in oracle['scores']},
                         gates={k:False for k in oracle['gates']},
                         all_gates_pass=False, map_metrics_computed=False)
            contribution = 0.
        else:
            score = score_extra(reference, prediction, tail, row['unknown_outside_support'])
            contribution = float(np.mean(list(score['scores'].values())))
        results.append(dict(id=row['id'], parent_id=row['parent_id'], group=row['group'],
                            score=score, selection_contribution=contribution))
    grouped = {}
    for row in results:
        grouped.setdefault(row['parent_id'], []).append(row['selection_contribution'])
    source_values = {k:float(np.mean(v)) for k,v in grouped.items()}
    raw = dict(binding, map_selection_value=float(np.mean(list(source_values.values()))),
        per_source_selection_values=source_values, rows=results,
        role='raw same-window held-group control; eight excerpts from six known sources, not whole-song/unseen accuracy',
        decode_failures=sum(r['score'].get('status')=='decode_failed' for r in results),
        failure_policy='Expected decode failure contributes zero to equal-source selection; metrics unavailable; no fallback',
        criterion='unchanged equal-source mean of six strict scores', runtime_seconds=time.perf_counter()-started)
    score_path = a.output/'scores.json'
    score_path.write_text(json.dumps(raw, indent=2)+'\n')
    selection = json.loads(a.learned_selection.read_text())
    if not selection['complete'] or selection['parameters_sha256'] != binding['parameters_sha256']:
        raise ValueError('learned selection is incomplete or decoder parameters differ')
    chosen = selection['selected']
    learned_path = a.learned_selection.parent/(str(chosen['seed'])+'-'+Path(chosen['selected']).stem)/'scores.json'
    learned = json.loads(learned_path.read_text())
    if learned['checkpoint_sha256'] != chosen['sha256'] or learned['checkpoint_sha256'] != digest(chosen['selected']):
        raise ValueError('learned selected checkpoint binding differs')
    other = {r['id']:r for r in learned['rows']}
    if set(other) != {r['id'] for r in cases}:
        raise ValueError('learned/raw held cases differ')
    case_comparisons = []
    for row in results:
        candidate = other[row['id']]
        keys = list(row['score']['scores'])
        differences = {k:(None if row['score']['scores'][k] is None or candidate['score']['scores'][k] is None
                         else candidate['score']['scores'][k]-row['score']['scores'][k]) for k in keys}
        case_comparisons.append(dict(id=row['id'], parent_id=row['parent_id'],
            raw_pass=row['score']['all_gates_pass'], learned_pass=candidate['score']['all_gates_pass'],
            raw_status=row['score'].get('status','scored'), learned_status=candidate['score'].get('status','scored'),
            raw_scores=row['score']['scores'], learned_scores=candidate['score']['scores'],
            learned_minus_raw_scores=differences,
            raw_contribution=row['selection_contribution'], learned_contribution=candidate['selection_contribution'],
            learned_minus_raw_contribution=candidate['selection_contribution']-row['selection_contribution']))
    current = {n:digest(Path(__file__).with_name(n)) for n in names}
    if current != sources:
        raise ValueError('raw control implementation changed during execution')
    comparison = dict(complete=True, raw_scores=dict(path=str(score_path.resolve()),sha256=digest(score_path)),
        learned_scores=dict(path=str(learned_path.resolve()),sha256=digest(learned_path)),
        learned_selection_sha256=digest(a.learned_selection), selected_checkpoint=chosen,
        raw_equal_source_mean=raw['map_selection_value'], learned_equal_source_mean=learned['map_selection_value'],
        learned_minus_raw_equal_source_mean=learned['map_selection_value']-raw['map_selection_value'],
        per_source={k:dict(raw=v,learned=learned['per_source_selection_values'][k],
            learned_minus_raw=learned['per_source_selection_values'][k]-v) for k,v in source_values.items()},
        raw_passed_cases=sum(r['score']['all_gates_pass'] for r in results),
        learned_passed_cases=sum(r['score']['all_gates_pass'] for r in learned['rows']),
        raw_decode_failures=raw['decode_failures'], learned_decode_failures=learned['decode_failures'],
        cases=case_comparisons,
        interpretation='Combined observation-learning route comparison: quarter/bar/grid posteriors plus learned-quarter semantic marker and grid-support behavior versus original Beat This/RMS observations. Not isolated bar-head or weight-only causality. Validation-selected checkpoint on these known held-from-fit cases; not unseen or whole-song accuracy.',
        execution_sources_unchanged=True)
    (a.output/'comparison.json').write_text(json.dumps(comparison, indent=2)+'\n')
    print(json.dumps({k:comparison[k] for k in ('raw_equal_source_mean','learned_equal_source_mean',
          'learned_minus_raw_equal_source_mean','raw_passed_cases','learned_passed_cases',
          'raw_decode_failures','learned_decode_failures')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
