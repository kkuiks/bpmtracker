"""Change the initial choice only; reuse the unmodified six-second C_HOLD."""
from experiments.bpm_continuity_v1.core import source_base, bootstrap, predict
from experiments.metronome_reconstruction_v1.hinted import encode_tap_level


def permitted(base, initial, bpm):
    return (initial.get('kind') == 'proxy' and base is not None and
            encode_tap_level(base, bpm)['power'] == initial['power'])


def family_rate(family, base, initial):
    """Translate a prepared whole-input family into the COMMON local unit.

    A family can have a different automatic base. Passing the local power as
    the family power would silently change metrical units. No raw tap is used.
    """
    levels = [level for level in family.get('levels', [])
              if permitted(base, initial, level['best']['quarter_bpm'])]
    if not levels:
        return {'status': 'NO_RATE', 'reason': 'NO_PREPARED_FAMILY_IN_COMMON_UNIT'}
    level = sorted(levels, key=lambda x: (-x['best']['score'], x['power'],
                                        x['best']['quarter_bpm']))[0]
    best = level['best']
    alternatives = sorted(level.get('top_candidates', []), key=lambda x: -x['score'])
    rivals = [x for x in alternatives if abs(x['quarter_bpm'] - best['quarter_bpm']) > 1e-8]
    return {'status': 'RATE_SELECTED', 'bpm': best['quarter_bpm'],
            'whole_score': best['score'], 'family_power': level['power'],
            'family_audio_base_bpm': family.get('audio_base_bpm'),
            'common_local_audio_base_bpm': base,
            'fine_rate_score_gap': best['score'] - rivals[0]['score'] if rivals else None,
            'different_rate_rivals': [{'bpm': x['quarter_bpm'], 'score': x['score']}
                                      for x in rivals[:10]],
            'family_offset_used': False, 'family_meter_used': False,
            'whole_input_future_information': True}


def initialize(ev6, ev_seed, family, initial, method):
    if method == 'I0_LOCAL6':
        return bootstrap(ev6, initial)
    base = source_base(ev6)
    result = {'audio_base_bpm': base['audio_base_bpm'], 'base_time': base.get('time'),
              'input': initial, 'status': 'NO_SEED', 'seed': None, 'method': method}
    if initial.get('kind') != 'proxy' or base['audio_base_bpm'] is None:
        return dict(result, reason=initial.get('reason', 'NO_COMMON_SOURCE_BASE'))
    rate = None
    if method == 'I1_WHOLE_RATE_LOCAL6':
        choice = family_rate(family, base['audio_base_bpm'], initial)
        result['whole_rate_choice'] = choice
        if choice['status'] != 'RATE_SELECTED':
            return dict(result, reason=choice['reason'])
        rate = choice['bpm']
    allowed = {j for j, h in enumerate(ev6.bank)
               if permitted(base['audio_base_bpm'], initial, h['bpm']) and
               (rate is None or abs(h['bpm'] - rate) <= 1e-8)}
    result['allowed_bank_clocks'] = len(allowed)
    if not allowed:
        return dict(result, reason='SELECTED_RATE_OR_UNIT_ABSENT_FROM_UNCHANGED_BANK')
    minimum_time = 0. if method == 'I1_WHOLE_RATE_LOCAL6' else ev_seed.cfg['window']
    for i, t in enumerate(ev_seed.time):
        if t > ev6.cfg['seed_deadline']:
            break
        if t < minimum_time:
            continue
        # A long-window seed must also be emit-eligible under the unchanged
        # downstream six-second rule at the instant it is committed.
        local_allowed = set(ev6.qualified(i))
        candidates = [j for j in ev_seed.qualified(i, seed=True)
                      if j in allowed and j in local_allowed]
        groups = ev_seed.groups(i, candidates)
        if not groups:
            continue
        j = groups[0][0]
        margin = ev_seed.margin(i, j, groups)
        if margin + 1e-12 >= ev_seed.cfg['margin']:
            result.update(status='SEEDED', reason='FIRST_ELIGIBLE_INITIAL_CLOCK',
                          seed={'index': j, 'time': float(t), 'key': ev6.bank[j]['key'],
                                'clock': ev6.bank[j], 'evidence': ev_seed.detail(i, j, True),
                                'downstream_evidence': ev6.detail(i, j), 'margin': margin})
            break
    if result['seed'] is None:
        result['reason'] = 'INITIAL_CLOCK_NOT_QUALIFIED_OR_AMBIGUOUS_BY_DEADLINE'
    return result


def render(ev6, initialization):
    return predict(ev6, initialization, 'C_HOLD')


def seed_diagnostics(ev6, ev_seed, boot, initial):
    """Report fine-rate rivals INSIDE an equivalence group, without changing it."""
    if not boot.get('seed'):
        return {'status': 'NO_SEED', 'rate_rivals': [], 'seed_time': None}
    seed = boot['seed']; j = seed['index']
    i = round(seed['time'] / ev_seed.cfg['step'])
    allowed = [k for k in ev_seed.qualified(i, seed=True)
               if permitted(boot['audio_base_bpm'], initial, ev_seed.bank[k]['bpm'])]
    ranked = sorted(allowed, key=lambda k: (-ev_seed.S[i, k],
                                           -ev_seed.bank[k].get('source_score', 0), ev_seed.bank[k]['key']))
    seen = set(); rivals = []
    from experiments.bpm_continuity_v1.evidence import equivalent
    for k in ranked:
        h = ev_seed.bank[k]
        if h['bpm'] in seen:
            continue
        seen.add(h['bpm'])
        if abs(h['bpm'] - ev_seed.bank[j]['bpm']) <= 1e-8:
            continue
        rivals.append(dict(ev_seed.detail(i, k),
                           inside_seed_equivalence=equivalent(ev_seed.bank[j], h,
                                                              ev_seed.start[i], ev_seed.time[i], ev_seed.cfg),
                           seed_minus_rival_S=float(ev_seed.S[i, j] - ev_seed.S[i, k])))
    return {'status': 'SEEDED', 'seed_time': seed['time'], 'seed_bpm': ev_seed.bank[j]['bpm'],
            'seed_phase': ev_seed.bank[j]['phase'], 'reported_group_margin': seed['margin'],
            'seed_window_seconds': ev_seed.cfg['window'], 'rate_rivals': rivals[:12],
            'coarse_group_margin_is_not_fine_rate_confidence': True}
