"""Optional source-only coordinate proposals on the existing capacity route.

Installation is explicit and returns this module's analyze callable. It never
replaces analyzer.analyze or changes the frozen runner's entry point. Original
paths remain candidates; the existing complete objective ranks every proposal.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

from . import analyzer as shared
from .latent_clock import search, time_at
from .observations import initial_periods, pulse_family
from .repetition import links, messages

_HELPERS = None
_BINDING = None
_POLICY = 'source_only_coordinate_refinement_v1'


def install():
    """Explicitly bind the current capacity helpers; return the new callable."""
    global _HELPERS, _BINDING
    from . import capacity_emissions, capacity_fit, capacity_objective
    from . import capacity_support, learned_support
    capacity_emissions.install()
    expected = dict(fit=capacity_fit.fit, decode=capacity_support.decode,
                    objective=capacity_objective.objective,
                    infer_support=learned_support.infer)
    for name, function in expected.items():
        if getattr(shared, name) is not function:
            raise ValueError('unexpected capacity helper binding: ' + name)
    _HELPERS = {name: getattr(shared, name) for name in ('fit', 'decode', 'objective', 'map_payload')}
    names = ('coordinate_analyzer.py', 'analyzer.py', 'observations.py',
             'latent_clock.py', 'bar_structure.py', 'fast_structure.py',
             'repetition.py', 'support.py', 'capacity_emissions.py',
             'capacity_fit.py', 'capacity_objective.py', 'capacity_support.py',
             'capacity_vocabulary.py', 'learned_support.py')
    _BINDING = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in names}
    return analyze


def propose_coordinate_path(path, obs, *, bars=None, penalty=.025, stage='isolated'):
    """Propose one monotonic assignment using only the already fitted clock.

    No event is added, removed, or reassigned to a different source observation.
    Inverting time_at preserves its linear extrapolation at source margins.
    """
    if _HELPERS is None:
        raise RuntimeError('call coordinate_analyzer.install() explicitly first')
    record = dict(stage=stage, original_retained=True, changed_events=0,
                  proposal_evaluated=False, reason='unchanged_coordinates')
    assigned = np.asarray(path['assignments'], float)
    clock = np.asarray(path['clock'], float)
    if assigned.ndim != 2 or assigned.shape[1] != 2 or len(assigned) < 2:
        record['reason'] = 'insufficient_or_invalid_assignments'
        return None, record
    if (not np.isfinite(assigned).all() or not np.isfinite(clock).all()
            or clock.ndim != 2 or clock.shape[1] != 2 or len(clock) < 2
            or not np.all(np.diff(clock[:, 0]) > 0)
            or not np.all(np.diff(clock[:, 1]) > 0)):
        record['reason'] = 'invalid_clock_or_assignments'
        return None, record
    indices = assigned[:, 0].astype(int)
    if (not np.array_equal(indices, assigned[:, 0]) or np.any(indices < 0)
            or np.any(indices >= len(obs['events']))):
        record['reason'] = 'invalid_source_event_indices'
        return None, record
    inverse = time_at(clock[:, ::-1], obs['events'][indices])
    coordinates = np.round(inverse * 8) / 8
    if not np.isfinite(coordinates).all() or not np.all(np.diff(coordinates) > 0):
        record['reason'] = 'nonfinite_or_nonmonotonic_proposal'
        return None, record
    changed = np.flatnonzero(abs(coordinates - assigned[:, 1]) > 1e-8)
    if not len(changed):
        return None, record
    record.update(changed_events=int(len(changed)),
                  coordinate_examples=[dict(event_index=int(indices[i]),
                       before=float(assigned[i, 1]), after=float(coordinates[i]))
                       for i in changed[:16]],
                  reason='additional_source_only_assignment_candidate')
    replacement = assigned.copy()
    replacement[:, 1] = coordinates
    trial = dict(path, assignments=replacement)
    fitted, receipt = _HELPERS['fit'](trial, obs, bars, penalty=penalty)
    trial['clock'] = fitted
    record.update(proposal_evaluated=True, fit_receipt=receipt)
    trial['coordinate_refinement_history'] = [*path.get('coordinate_refinement_history', []), record]
    return trial, record


def analyze(obs, source, initial_bpm=None, *, parameters=None, repetition='none',
            known_links=None, beam=32, rounds=2, cache=None):
    """Preserve the capacity analyzer's search, adding bounded coordinate trials."""
    if _HELPERS is None:
        raise RuntimeError('call coordinate_analyzer.install() explicitly first')
    fit, decode, objective, map_payload = (_HELPERS[name] for name in
                                         ('fit', 'decode', 'objective', 'map_payload'))
    parameters = {} if parameters is None else parameters
    observation_identity = id(obs)
    physical_duration = source['sample_frames'] / source['sample_rate']
    if abs(obs['duration'] - physical_duration) > 1 / obs['fps'] + 1e-6:
        raise ValueError('source/frame duration mismatch')
    obs = dict(obs, duration=physical_duration)
    periods, anchor = initial_periods(obs)
    periods, guide = pulse_family(periods, anchor, initial_bpm)
    graph = links(obs) if repetition == 'automatic' else known_links if repetition == 'oracle' else []
    graph = [] if graph is None else graph
    cache = {} if cache is None else cache
    binding = (source['sha256'], json.dumps(parameters, sort_keys=True),
               json.dumps(guide, sort_keys=True), beam, observation_identity, _POLICY,
               json.dumps(_BINDING, sort_keys=True))
    if cache.get('binding', binding) != binding:
        raise ValueError('comparison cache binding mismatch')
    cache['binding'] = binding
    candidates, history, coordinate_receipts = [], [], []
    decoded = cache.setdefault('decoded', {})
    initial_reused = 'initial_candidates' in cache

    def structure_for(clock, feedback=None):
        key = (clock.tobytes(), None if feedback is None else tuple(x.tobytes() for x in feedback))
        if key not in decoded:
            decoded[key] = decode(clock, obs, parameters, repeat_targets=feedback)
        return decoded[key]

    def path_variants(path, *, bars=None, stage):
        proposal, receipt = propose_coordinate_path(path, obs, bars=bars,
                     penalty=parameters.get('segmentation_penalty', .025), stage=stage)
        coordinate_receipts.append(receipt)
        return [path] if proposal is None else [path, proposal]

    if not initial_reused:
        for proposal in periods:
            paths = search(obs, proposal['period'], beam=beam,
                           change_cost=parameters.get('tempo_change_cost', 8.), max_paths=3)
            for path in paths:
                fitted, receipt = fit(path, obs, penalty=parameters.get('segmentation_penalty', .025))
                path = dict(path, clock=fitted)
                for variant in path_variants(path, stage='initial'):
                    meter = structure_for(variant['clock'])
                    for alternative in [meter, *meter.get('alternatives', [])]:
                        candidates.append(dict(path=variant, meter=alternative,
                            score=objective(variant, obs, alternative, parameters, graph),
                            period=proposal['period']))
        cache['initial_candidates'] = [dict(c) for c in candidates]
        cache['coordinate_initial_receipts'] = list(coordinate_receipts)
    else:
        coordinate_receipts.extend(cache['coordinate_initial_receipts'])
        candidates = [dict(c, score=objective(c['path'], obs, c['meter'], parameters, graph))
                      for c in cache['initial_candidates']]
    if not candidates:
        raise ValueError('no coherent hypotheses')
    candidates.sort(key=lambda c: c['score'], reverse=True)
    for iteration in range(rounds):
        next_candidates = list(candidates)
        for old in candidates[:2]:
            path, meter = old['path'], old['meter']
            q = np.array([b['q'] for b in meter['bars']])
            t = time_at(path['clock'], q)
            expanded = search(obs, old['period'], beam=beam,
                              change_cost=parameters.get('tempo_change_cost', 8.),
                              bar_constraints=(q, t), max_paths=2)
            for new in [path, *expanded]:
                clock, receipt = fit(new, obs, meter['bars'],
                                     penalty=parameters.get('segmentation_penalty', .025))
                trial = dict(new, clock=clock)
                for variant in path_variants(trial, bars=meter['bars'], stage='bar_feedback'):
                    feedback = messages(variant['clock'], meter['bars'], graph)
                    structure = structure_for(variant['clock'], feedback)
                    for alternative in [structure, *structure.get('alternatives', [])]:
                        next_candidates.append(dict(path=variant, meter=alternative,
                            score=objective(variant, obs, alternative, parameters, graph),
                            period=old['period']))
        next_candidates.sort(key=lambda c: c['score'], reverse=True)
        history.append(dict(iteration=iteration, before=candidates[0]['score'],
                            after=next_candidates[0]['score']))
        improvement = next_candidates[0]['score'] - candidates[0]['score']
        candidates = next_candidates[:4]
        if improvement <= 1e-8:
            break
    from experiments.analysis_legacy.music_map_contract import prepare_map, render_bars
    valid, failures = [], []
    counts = dict(policy=_POLICY, lattice_subdivisions_per_quarter=8,
                  initial_candidates_reused=initial_reused,
                  initial_receipts_reused=initial_reused,
                  paths_considered=len(coordinate_receipts),
                  original_paths_retained=len(coordinate_receipts),
                  proposal_paths=sum(r['proposal_evaluated'] for r in coordinate_receipts),
                  changed_events_total=sum(r['changed_events'] for r in coordinate_receipts),
                  unchanged_paths=sum(r['reason'] == 'unchanged_coordinates' for r in coordinate_receipts),
                  rejected_paths=sum(r['reason'] not in ('unchanged_coordinates',
                     'additional_source_only_assignment_candidate') for r in coordinate_receipts),
                  helper_implementation_sha256=_BINDING,
                  proposal_receipts=coordinate_receipts)
    for candidate in candidates:
        try:
            raw, support = map_payload(candidate['path'], candidate['meter'], obs, source)
            raw['analysis_condition'] = 'user_bpm_guided' if initial_bpm is not None else 'unhinted'
            if render_bars(prepare_map(raw))['status'] != 'rendered':
                raise ValueError('nonrenderable bar path')
        except (ValueError, KeyError) as exc:
            failures.append(str(exc))
            continue
        selected_history = candidate['path'].get('coordinate_refinement_history', [])
        valid.append(dict(map=raw, source_only=True, reference_read=False,
            diagnostics=dict(score=candidate['score'], guide=guide, beam=beam,
                alternating_history=history,
                assigned_events=len(candidate['path']['assignments']), observed_events=len(obs['events']),
                latent_coordinates=candidate['path']['assignments'].tolist(),
                rhythmic_bars=candidate['meter']['bars'], support_states=support,
                repetition_mode=repetition, repetition_edges=graph,
                confidence_calibrated=False, invalid_candidates=failures,
                coordinate_refinement=dict(counts, selected_was_refined=bool(selected_history),
                                          selected_history=selected_history))))
    if not valid:
        raise ValueError('no valid final map: ' + str(failures))
    return valid[0], valid[1:]
