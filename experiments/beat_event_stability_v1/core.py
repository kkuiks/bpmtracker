"""Reuse legal beat-event search; change evidence, never force a constant map."""
from experiments.beat_event_map_v1 import core as base
from experiments.beat_event_map_v1.common import CONFIG as BASE_CONFIG
from .common import CONFIG, METHODS
from .scoring import Score


def fit(events, prepared, packet, method, progress=None):
    if not packet.get('available'):
        return {'status': 'no_source_clock', 'duration_seconds': float(events['duration']),
                'events': []}
    score = Score(events)
    filtered = 0
    if METHODS[method]['dense_proposals']:
        # A fast grid fitted to every second/third real observation is a weak
        # subdivision hypothesis, not independent evidence for musical acceleration.
        pulses = [r for r in prepared['pulses'] if r['observed_expected_pulse_fraction']
                  >= CONFIG['minimum_proposal_pulse_density']]
        filtered = len(prepared['pulses']) - len(pulses)
        prepared = {**prepared, 'pulses': pulses}
    unit = next(u for u in prepared['units'] if u['id'] == packet['unit_id'])
    heads = base.initial_heads(prepared, unit, score)
    best = max(heads, key=lambda h: h['score'])
    frontier = heads
    search = []
    stagnant = 0
    for depth in range(BASE_CONFIG['max_declarations']):
        next_heads, diagnostics = [], []
        for head in frontier:
            children, details = base.extend(head, prepared, score, True)
            next_heads.extend(children)
            diagnostics.append(details)
        search.append({'depth': depth, 'parents': len(frontier),
                       'improving_children': len(next_heads),
                       'old_beats_considered': sum(d['old_beats_considered'] for d in diagnostics),
                       'source_compatible_proposals': sum(d.get('source_compatible_proposals', 0)
                                                         for d in diagnostics)})
        if progress:
            progress(depth, len(next_heads), len(best['events']))
        if not next_heads:
            break
        next_heads.sort(key=lambda h: -h['score'])
        frontier, seen = [], set()

        def add(head):
            last = head['events'][-1]
            key = (head['active']['bpm'], head['active']['numerator'],
                   head['active']['denominator'], round(last['time'], 4))
            if key not in seen:
                seen.add(key)
                frontier.append(head)

        for head in next_heads:
            add(head)
            if len(frontier) >= BASE_CONFIG['map_path_budget']:
                break
        for head in sorted(next_heads, key=lambda h: -h['pending_prefix_quality']):
            add(head)
            if len(frontier) >= BASE_CONFIG['map_path_budget'] + BASE_CONFIG['pending_path_budget']:
                break
        winner = max(frontier, key=lambda h: h['score'])
        if winner['score'] > best['score'] + 1e-6:
            best, stagnant = winner, 0
        else:
            stagnant += 1
        if stagnant >= BASE_CONFIG['maximum_stagnant_search_depths']:
            search[-1]['stopped_after_nonimproving_search_depths'] = stagnant
            break
    result = base.prediction(best, score.duration, method, packet['unit_id'])
    result.update(search_trace=search, filtered_sparse_pulse_proposals=filtered,
                  stability_score='symmetric bar F1 and quarter PCM',
                  constant_tempo_forced=False)
    return result
