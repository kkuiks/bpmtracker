"""Freeze and predict a small joint-guide pilot without opening reference labels.

The inference manifest contains input payloads, raw-evidence caches and optional
frozen baseline predictions only. Evaluation is a separate invocation/tool.
Manufactured decoder fixtures are not acoustic-model performance evidence.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import inspect
import platform
import json
import math
import os
from pathlib import Path
import resource
import re
import shutil
import time

import numpy as np
import soundfile as sf
import torch

from joint_music_lattice import JointConfig, TEMPLATES, GUIDE_UNITS, first_stable_window, infer_joint_music_map
from beat_this.model.postprocessor import Postprocessor
from joint_guide_controls import guided_candidate_selection
from run_crossed_benchmark import common_minimal, reconstruct_model

SOURCES = ('run_joint_guide_pilot.py', 'joint_music_lattice.py', 'joint_guide_controls.py',
    'musical_units.py', 'music_map_contract.py', 'clock_candidate_regions.py',
    'run_crossed_benchmark.py', 'clock_candidates.py', 'ablate_clock_inputs.py',
    'fit_clock.py', 'decode_pulses.py', 'legacy_dbn.py', 'run_beat_this.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bind(path):
    return {'path': str(path), 'sha256': sha(path)}


def read_bound(binding):
    path = Path(binding['path'])
    if sha(path) != binding['sha256']:
        raise ValueError(f'input hash mismatch: {path}')
    return json.loads(path.read_text())


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


def validate_payload(payload):
    allowed = {'schema_version', 'id', 'input_audio', 'guide', 'input_policy'}
    if set(payload)-allowed:
        raise ValueError('inference payload contains unapproved fields')
    if type(payload.get('schema_version')) is not int or payload.get('schema_version') != 1 or not isinstance(payload.get('id'), str):
        raise ValueError('invalid payload identity/schema')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', payload['id']) or '..' in payload['id']:
        raise ValueError('case ID must be a safe relative output name')
    audio = payload.get('input_audio')
    if not isinstance(audio, dict) or set(audio) != {'path', 'sha256'}:
        raise ValueError('audio input must contain only path and source hash')
    guide = payload.get('guide')
    if guide is None:
        return None
    if not isinstance(guide, dict) or set(guide)-{'bpm', 'approximate', 'scope', 'source', 'raw_tap_timestamps'}:
        raise ValueError('guide cannot contain a supplied meter, unit, anchor or timestamped section')
    bpm = guide.get('bpm')
    if isinstance(bpm, bool) or not isinstance(bpm, (float, int)) or not math.isfinite(bpm) or bpm <= 0:
        raise ValueError('guide BPM must be positive and finite')
    if guide.get('scope') != 'first_stable_section':
        raise ValueError('pilot guide scope must be first_stable_section')
    if guide.get('raw_tap_timestamps') is not None:
        raise ValueError('this scalar-only pilot does not consume individual tap timestamps')
    return float(bpm)


def freeze(manifest_path, output):
    document = json.loads(Path(manifest_path).read_text())
    if set(document)-{'schema_version', 'purpose', 'cases', 'scope'}:
        raise ValueError('prediction manifest may not contain evaluation/reference fields')
    if not document.get('cases'):
        raise ValueError('pilot requires at least one case')
    prepared = []; ids = set()
    for entry in document['cases']:
        if set(entry)-{'id', 'input_json', 'logits', 'baseline', 'model_provenance'}:
            raise ValueError('case contains unsupported or evaluation-side fields')
        payload = read_bound(entry['input_json']); guide = validate_payload(payload)
        if entry['id'] in ids:
            raise ValueError('duplicate case ID would overwrite prediction evidence')
        ids.add(entry['id'])
        if entry['id'] != payload['id']:
            raise ValueError('case and payload IDs differ')
        audio = payload['input_audio']
        if sha(audio['path']) != audio['sha256']:
            raise ValueError('source audio changed')
        info = sf.info(audio['path'])
        source = {'sha256': audio['sha256'], 'sample_rate': info.samplerate, 'sample_frames': info.frames}
        if sha(entry['logits']['path']) != entry['logits']['sha256']:
            raise ValueError('raw evidence cache changed')
        with np.load(entry['logits']['path'], allow_pickle=False) as cache:
            fps = float(cache['fps']); beat = np.asarray(cache['beat']); down = np.asarray(cache['downbeat'])
            for name in ('source_frame_offset', 'frame_time_offset_seconds'):
                if name in cache and float(cache[name]) != 0:
                    raise ValueError('nonzero cache origin requires an independently verified mapping')
        duration = info.frames/info.samplerate
        if not math.isfinite(fps) or fps <= 0 or beat.ndim != 1 or down.shape != beat.shape or not np.isfinite(beat).all() or not np.isfinite(down).all():
            raise ValueError('invalid finite native-frame cache')
        if len(beat)/fps < duration-1/fps:
            raise ValueError('cache does not cover the physical source')
        if entry.get('baseline'):
            core = read_bound(entry['baseline']['predictions']); read_bound(entry['baseline']['candidates'])
            if any(core['source'][k] != source[k] for k in source):
                raise ValueError('frozen baseline uses a different source')
            if core['source']['logits_sha256'] != entry['logits']['sha256']:
                raise ValueError('frozen baseline uses different raw evidence')
        prepared.append({**entry, 'source': source, 'duration_seconds': duration,
                         'fps': fps, 'frame_count': len(beat), 'guide_bpm': guide,
                         'guide_provenance': payload.get('guide')})
    configuration = {'schema_version': 1, 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'inference_manifest': bind(manifest_path), 'cases': prepared,
        'joint_configuration': asdict(JointConfig()),
        'joint_templates': [{'id': t[0], 'numerator': t[1], 'denominator': t[2], 'grouping': list(t[3])} for t in TEMPLATES],
        'joint_guide_units_quarters': [{'numerator': h.numerator, 'denominator': h.denominator} for h in GUIDE_UNITS],
        'external_sources': {'beat_this_postprocessor': bind(inspect.getsourcefile(Postprocessor))},
        'sources': {name: bind(Path(__file__).with_name(name)) for name in SOURCES},
        'reference_labels_opened': False, 'new_acoustic_model_inference': False,
        'model_inputs': 'two cached channels, native frame rate, physical source geometry, optional scalar BPM only',
        'joint_off_on_comparison': 'structural-package comparison, not isolated effect of one factor',
        'guide_only_unit_scope': 'finite native-pulse/tap ratios; no inferred quarter unit or meter declaration',
        'runtime': {'OPENBLAS_NUM_THREADS': os.environ.get('OPENBLAS_NUM_THREADS'),
                    'OMP_NUM_THREADS': os.environ.get('OMP_NUM_THREADS'), 'torch_threads': torch.get_num_threads(),
                    'python': platform.python_version(), 'numpy': np.__version__, 'torch': torch.__version__, 'soundfile': sf.__version__}}
    output.mkdir(parents=True)
    for name, binding in configuration['sources'].items():
        target = output/'source-snapshot'/name; target.parent.mkdir(exist_ok=True)
        shutil.copyfile(binding['path'], target)
    for name, artifact in configuration['external_sources'].items():
        shutil.copyfile(artifact['path'], output/'source-snapshot'/(name+'.py'))
    save(output/'configuration.json', configuration)
    return configuration


def baseline_for_case(case, beat, down):
    if case.get('baseline'):
        core = read_bound(case['baseline']['predictions']); pool = read_bound(case['baseline']['candidates'])
        return {'execution': 'exact_saved_predictions_reused', 'core': core, 'pool': pool,
                'binding': case['baseline']}
    # Manufactured caches have no old saved run. Apply the existing frozen
    # minimal/current/candidate paths to the same arrays, with no labels.
    minimal = common_minimal(beat, down, case['fps'], case['duration_seconds'])
    value = reconstruct_model(beat, down, case['fps'], minimal, case['duration_seconds'], candidate_ranking_policy='legacy')
    pool = value['candidate_set']
    return {'execution': 'unchanged_baseline_reconstructor_on_manufactured_channels',
            'core': value, 'pool': pool,
            'scope': 'decoder fixture control, not acoustic model inference or its official accuracy'}


def run(manifest_path, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError('pilot output must be a new directory')
    torch.set_num_threads(1)
    config = freeze(manifest_path, output)
    ledger = {'configuration': bind(output/'configuration.json'), 'complete': False, 'rows': [],
              'references_opened': False, 'scoring_performed': False}
    save(output/'manifest.json', ledger)
    for case in config['cases']:
        with np.load(case['logits']['path'], allow_pickle=False) as cache:
            beat = np.asarray(cache['beat'], dtype=float); down = np.asarray(cache['downbeat'], dtype=float)
        case_dir = output/'predictions'/case['id']; records = {}
        started = time.perf_counter()
        baseline = baseline_for_case(case, beat, down)
        save(case_dir/'existing-unhinted.json', baseline)
        records['existing_unhinted'] = bind(case_dir/'existing-unhinted.json')
        window = first_stable_window(beat, case['fps'], case['source'])
        save(case_dir/'source-guide-window.json', window)
        if case['guide_bpm'] is None:
            selection = {'status': 'no_guide_supplied', 'selected_candidate_id': None, 'full_map_supported': False}
        else:
            selection = guided_candidate_selection(baseline['pool']['candidates'], case['guide_bpm'], window)
        save(case_dir/'guide-only.json', selection)
        records['guide_only'] = bind(case_dir/'guide-only.json')
        for name, guide in [('joint_only', None), ('guide_joint', case['guide_bpm'])]:
            if name == 'guide_joint' and guide is None:
                result = {'status': 'no_guide_supplied', 'map': None}
            else:
                arm_start = time.perf_counter()
                try:
                    result = infer_joint_music_map(beat, down, case['fps'], case['source'], guide_bpm=guide)
                    if result.get('guide_window') != window:
                        raise AssertionError('joint arm changed the source-only guide window')
                except (ValueError, RuntimeError) as exc:
                    result = {'status': 'execution_error', 'map': None, 'error': f'{type(exc).__name__}: {exc}'}
                result['runner_elapsed_seconds'] = time.perf_counter()-arm_start
                result['runner_process_high_water_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
            save(case_dir/(name+'.json'), result)
            records[name] = bind(case_dir/(name+'.json'))
            print(case['id'], name, result['status'], flush=True)
        ledger['rows'].append({'id': case['id'], 'outputs': records,
                               'guide_window': bind(case_dir/'source-guide-window.json'),
                               'total_elapsed_seconds': time.perf_counter()-started})
        save(output/'manifest.json', ledger)
    for binding in list(config['sources'].values())+list(config['external_sources'].values()):
        if sha(binding['path']) != binding['sha256']:
            raise ValueError('implementation changed during frozen pilot')
    for case in config['cases']:
        for binding in (case['input_json'], case['logits']):
            if sha(binding['path']) != binding['sha256']:
                raise ValueError('input changed during pilot')
    ledger['complete'] = True; save(output/'manifest.json', ledger)
    return ledger


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.manifest, args.output_dir)
