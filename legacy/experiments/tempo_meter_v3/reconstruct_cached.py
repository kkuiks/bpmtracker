"""Source-only, fixed-clock comparison of the duration-normalized meter prior.

This runner opens frozen automatic observations/candidates, never references.
Recomputing the legacy meter path verifies that the intervention is isolated.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
from .analyzer import declared_map
from .clock_search import select_pulse_level
from .meter_search import decode_meter as legacy_decode
from .meter_duration import decode_meter
from .probe_resources import digest


def musical_hash(raw):
    value = deepcopy(raw)
    value.pop('analysis_condition', None)
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_observations(row):
    with np.load(Path(row['selected']['path']).parent/'structural-observations.npz') as z:
        structure = {k: z[k].copy() for k in z.files}
    cache = Path('data/cache/tempo-meter-v3/acoustic-v1')/(row['source']['sha256']+'.npz')
    receipt = json.loads(cache.with_suffix('.json').read_text())
    assert receipt['binding'] == row['feature_binding']
    with np.load(cache) as z:
        logits, energy = z['logits'].copy(), z['energy'].copy()
    return logits, energy, structure


def original_clock(candidate):
    pred = candidate['prediction']
    knots = pred['map']['clock_knots']
    start = next(i for i, k in enumerate(knots) if k['pulse'] == 0)
    count = pred['diagnostics']['clock_fit']['segments']+1
    clock = np.array([[k['pulse'], k['source_seconds']] for k in knots[start:start+count]])
    assert len(clock) == count and clock[0, 0] == 0
    return clock


def run(row, folder):
    from experiments.analysis_legacy.music_map_contract import prepare_map, render_bars
    started = time.perf_counter()
    logits, energy, structure = load_observations(row)
    source = row['source']
    duration = source['sample_frames']/source['sample_rate']
    bank_path = Path(row['selected']['path']).parent/'candidate-bank.json'
    stored = json.loads(bank_path.read_text())
    bank = []
    for candidate in stored:
        clock = original_clock(candidate)
        fit = candidate['prediction']['diagnostics']['clock_fit']
        old_meter = legacy_decode(clock, logits, structure)
        before, _ = declared_map(dict(clock=clock, meter=old_meter), source, duration, structure, logits, energy)
        if musical_hash(before) != musical_hash(candidate['prediction']['map']):
            raise ValueError('Legacy replay differs: '+row['id']+' '+candidate['name'])
        meter = decode_meter(clock, logits, structure)
        score = candidate['score'] + .35*(meter['score']-old_meter['score'])
        raw, tail = declared_map(dict(clock=clock, meter=meter), source, duration, structure, logits, energy)
        raw['analysis_condition'] = candidate['prediction']['map']['analysis_condition']
        pred = dict(map=raw, source_only=True, reference_read=False,
                    diagnostics=dict(clock_family=candidate['name'], clock_fit=fit,
                        joint_score=score, meter_search=meter['diagnostics'], tail=tail,
                        initial_bpm=row.get('initial_bpm'), initial_bpm_note_unit_supplied=False,
                        intervention='duration_normalized_existing_meter_length_prior'))
        bank.append(dict(name=candidate['name'], clock=clock, joint_score=score, score=score,
                         old_score=candidate['score'], old_meter_score=old_meter['score'],
                         new_meter_score=meter['score'], prediction=pred))
    bank, decision = select_pulse_level(bank, row.get('initial_bpm'))
    rejected = []
    selected = None
    for rank, c in enumerate(bank):
        c['prediction']['diagnostics'].update(pulse_level_selection=decision, alternative_rank=rank)
        try:
            if render_bars(prepare_map(c['prediction']['map']))['status'] != 'rendered':
                raise ValueError('bar map cannot render')
        except (ValueError, TypeError, KeyError) as error:
            rejected.append(dict(rank=rank, name=c['name'], reason=str(error)))
            continue
        if selected is None:
            selected = c
            selected_rank = rank
    if selected is None:
        raise ValueError('No valid candidate')
    folder.mkdir(parents=True)
    path = folder/'selected.json'
    path.write_text(json.dumps(selected['prediction'], indent=2, allow_nan=False)+'\n')
    (folder/'candidate-bank.json').write_text(json.dumps(
        [{k:v for k,v in c.items() if k not in ['clock','joint_score']} for c in bank], indent=2, allow_nan=False)+'\n')
    result = {k:row[k] for k in ['id','title','audio','source','initial_bpm','initial_bpm_source',
                                  'model_sha256','acoustic_checkpoint_sha256','feature_binding']}
    result.update(complete=True, references_available_to_runner=False,
                  selected=dict(path=str(path.resolve()),sha256=digest(path)),
                  runtime_seconds=time.perf_counter()-started,
                  runtime_scope='CPU replay of cached observations and fixed clocks; excludes feature extraction',
                  original_bank_sha256=digest(bank_path), legacy_candidates_reproduced=len(bank),
                  validity_guard=dict(selected_rank=selected_rank,rejected_before_selection=[x for x in rejected if x['rank']<selected_rank],all_invalid_candidates=rejected))
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ids', nargs='*')
    p.add_argument('--reuse', type=Path)
    a = p.parse_args()
    sys.path.insert(0, str(Path.cwd()/'experiments/analysis_legacy'))
    import torch
    torch.set_num_threads(4)
    baseline = json.loads((a.baseline/'predictions/manifest.json').read_text())
    assert baseline['complete'] and baseline['references_available_to_runner'] is False
    a.output.mkdir(parents=True, exist_ok=False)
    implementation = {name:digest(Path(__file__).with_name(name)) for name in
                      ['reconstruct_cached.py','meter_duration.py','meter_search.py','analyzer.py','clock_search.py']}
    reuse = {}
    if a.reuse:
        previous = json.loads(a.reuse.read_text())
        assert previous['complete'] and previous['implementation_sha256'] == implementation
        reuse = {r['id']:r for r in previous['rows']}
    manifest = dict(complete=False, references_available_to_runner=False,
                    source_only_cached_reconstruction=True, input_sha256=baseline['input_sha256'],
                    baseline_manifest_sha256=digest(a.baseline/'predictions/manifest.json'),
                    implementation_sha256=implementation, rows=[])
    for i, row in enumerate(baseline['rows']):
        if a.ids and row['id'] not in a.ids:
            continue
        if digest(row['audio']) != row['source']['sha256']:
            raise ValueError('source changed')
        if row['id'] in reuse:
            result = reuse[row['id']]
            assert result['source'] == row['source']
            assert digest(result['selected']['path']) == result['selected']['sha256']
            result = dict(result, reused_without_change=True)
        else:
            result = run(row, a.output/f'{i:02d}')
        manifest['rows'].append(result)
        (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(row['id'], round(result['runtime_seconds'],2), 'seconds', flush=True)
    manifest['complete'] = True
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__ == '__main__':
    main()
