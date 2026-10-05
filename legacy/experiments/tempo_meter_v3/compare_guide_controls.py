"""Replay discrete hints with the same validity guard as the comparison runner."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from .clock_search import select_pulse_level
from .guide_controls import map_hash
from .probe_resources import digest


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    sys.path.insert(0, str(Path.cwd() / 'experiments/analysis_legacy'))
    from music_map_contract import prepare_map, render_bars
    rows = []
    for arm in ['A', 'B', 'C']:
        manifest = json.loads((a.run / f'predictions-{arm}/manifest.json').read_text())
        assert manifest['complete']
        for row in manifest['rows']:
            path = Path(row['selected']['path']).parent / 'candidate-bank.json'
            stored = json.loads(path.read_text())
            bank = []
            for candidate in stored:
                payload = candidate['prediction']
                knots = payload['map']['clock_knots']
                # declared_map only prepends/appends extrapolation knots. All
                # original fitted clocks start at q=0, with segments+1 knots.
                start = next(i for i, k in enumerate(knots) if k['pulse'] == 0)
                count = payload['diagnostics']['clock_fit']['segments'] + 1
                clock = np.array([[k['pulse'], k['source_seconds']]
                                  for k in knots[start:start+count]])
                assert len(clock) == count and clock[0, 0] == 0
                try:
                    valid = render_bars(prepare_map(payload['map']))['status'] == 'rendered'
                except (ValueError, TypeError, KeyError):
                    valid = False
                bank.append(dict(name=candidate['name'], joint_score=candidate['score'],
                                 clock=clock, prediction=payload, valid=valid))
            hint = row['initial_bpm']
            conditions = []
            for name, value in [('none', None), ('minus_one', hint-1), ('exact', hint),
                                ('plus_one', hint+1), ('half', hint/2), ('double', hint*2)]:
                ordered, decision = select_pulse_level(bank, value)
                selected = next(c for c in ordered if c['valid'])
                conditions.append(dict(condition=name, guide=value, decision=decision,
                                       selected=selected['name'],
                                       musical_map_sha256=map_hash(selected['prediction']['map'])))
            by_name = {c['condition']: c for c in conditions}
            actual = json.loads(Path(row['selected']['path']).read_text())
            assert by_name['exact']['musical_map_sha256'] == map_hash(actual['map'])
            rows.append(dict(arm=arm, id=row['id'], candidate_bank_sha256=digest(path),
                             exact_reproduces_inference=True,
                             nearby_hint_map_identical=len({by_name[c]['musical_map_sha256']
                                 for c in ['minus_one', 'exact', 'plus_one']}) == 1,
                             conditions=conditions))
    out = dict(complete=True, clocks_refitted=False, reference_read=False, rows=rows)
    (a.run / 'guide-sensitivity.json').write_text(json.dumps(out, indent=2)+'\n')
    print(json.dumps(dict(rows=len(rows), exact_reproduced=len(rows),
                          nearby_identical=sum(r['nearby_hint_map_identical'] for r in rows))))


if __name__ == '__main__':
    main()
