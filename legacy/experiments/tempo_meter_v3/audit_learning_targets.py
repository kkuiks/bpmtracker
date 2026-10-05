"""Evaluate field-specific supervision masks without training any model."""
import argparse
import json
from pathlib import Path
import numpy as np
from .train_structure import targets as original
from .structure_compare import targets as comparison
from .probe_resources import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    rows=json.loads(a.manifest.read_text())['rows'];report=[]
    for r in rows:
        count=int(np.ceil(r['duration']*12.5));old=original(r,count);new=comparison(r,count)
        tempos=[e['bpm_quarter'] for e in r['labels']['tempo']]
        report.append(dict(id=r['id'],dataset=r['dataset'],split=r['split'],weight=r['weight'],
            tempo_entries=len(tempos),tempo_unequal_transitions=sum(abs(b-a)>1e-6 for a,b in zip(tempos,tempos[1:])),
            old_change_supervised_frames=int(np.count_nonzero(old[1][:,2])),
            new_tempo_change_supervised_frames=int(np.count_nonzero(new[1][:,4])),
            new_tempo_change_positive_frames=int(np.count_nonzero((new[0][:,4]>.5)&(new[1][:,4]>0))),
            new_meter_change_supervised_frames=int(np.count_nonzero(new[1][:,2])),
            tempo_regression_supervised_frames=int(np.count_nonzero(new[-1]>0)),
            tempo_range=[min(tempos),max(tempos)],meter_known=r['labels']['meter_known']))
    value=dict(manifest_sha256=digest(a.manifest),implementation_sha256={n:digest(Path(__file__).with_name(n))
        for n in ('prepare_training.py','train_structure.py','structure_compare.py')},rows=report,
        conclusion='RWC change losses already masked in frozen and A/B/C; adjacent-annotation BPM remains supervised and influences shared representation / ranking; causal effect not measured. No model retrained.')
    a.output.write_text(json.dumps(value,indent=2)+'\n')


if __name__=='__main__':main()
