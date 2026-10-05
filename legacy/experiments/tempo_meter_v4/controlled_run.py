"""End-to-end constructed-observation controls, separate from real songs."""
import json
from pathlib import Path
import sys
import time
import numpy as np
from .fixtures import fixture
from .analyzer import analyze
from .latent_clock import time_at
from .calibrate_controls import error


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--parameters',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(Path.cwd()/'experiments/analysis_legacy'))
    params=json.loads(a.parameters.read_text())['selected'];a.output.mkdir(parents=True,exist_ok=False)
    cases=[('constant',dict(signatures=[(4,4)]*12)),('compound',dict(signatures=[(6,8)]*12)),
           ('odd',dict(signatures=[(7,8)]*12)),('long',dict(signatures=[(31,4)]*3)),
           ('short_meter',dict(signatures=[(4,4)]*5+[(2,4)]+[(4,4)]*5)),
           ('half_time',dict(signatures=[(4,4)]*12,half_time=True)),
           ('accent_332',dict(signatures=[(4,4)]*12,accent_332=True)),
           ('nonbar_riff',dict(signatures=[(4,4)]*12,riff=True)),
           ('missing_downbeats',dict(signatures=[(4,4)]*16,missing_bars=range(5,10))),
           ('rest_return',dict(signatures=[(4,4)]*12,rest=(12,24))),
           ('true_tempo_change',dict(signatures=[(4,4)]*12,tempo_changes=[(17.,.6)])),
           ('two_tempo_changes',dict(signatures=[(4,4)]*24,tempo_changes=[(17.,.6),(31.,.5)])),
           ('small_tempo_change',dict(signatures=[(4,4)]*32,tempo_changes=[(63.,.5025)]))]
    rows=[]
    from experiments.tempo_meter_v3.probe_resources import digest
    implementation={p.name:digest(p) for p in Path(__file__).parent.glob('*.py')}
    (a.output/'implementation.json').write_text(json.dumps(implementation,indent=2)+'\n')
    for name,kwargs in cases:
        start=time.perf_counter();obs,clock,gold=fixture(**kwargs)
        source=dict(sha256='0'*64,sample_rate=48000,sample_frames=int(round(obs['duration']*48000)))
        prediction,_=analyze(obs,source,120.,parameters=params,beam=32,rounds=2)
        actual=prediction['diagnostics']['rhythmic_bars'];predclock=np.array([[k['pulse'],k['source_seconds']] for k in prediction['map']['clock_knots']])
        # Align only the explicit fixed source quarter-zero convention, no
        # reference-based tempo or phase correction. Fixture origin is q=0.
        q=np.arange(1,clock[-1,0]);timing=float(np.max(abs(time_at(predclock,q)-time_at(clock,q))))
        wrong=error(gold,actual)
        qk,tk=predclock[:,0],predclock[:,1];rates=60*np.diff(qk)/np.diff(tk)
        predicted_changes=[float(tk[i+1]) for i in range(len(rates)-1) if abs(rates[i+1]-rates[i])>1e-6 and 0<=tk[i+1]<obs['duration']]
        expected_changes=[float(time_at(clock,q)) for q,_ in kwargs.get('tempo_changes',[])]
        change_ok=len(predicted_changes)==len(expected_changes) and all(abs(a-b)<=.5 for a,b in zip(predicted_changes,expected_changes))
        row=dict(id=name,wrong_labeled_bar_events=wrong,max_same_quarter_error_seconds=timing,
                 tempo_spans=len(predclock)-1,runtime_seconds=time.perf_counter()-start,
                 predicted_tempo_changes=predicted_changes,expected_tempo_changes=expected_changes,
                 tempo_changes_passed=change_ok,passed=wrong==0 and timing<.08 and change_ok)
        rows.append(row);(a.output/(name+'.json')).write_text(json.dumps(prediction,indent=2)+'\n')
        (a.output/'results.json').write_text(json.dumps(dict(scope='manufactured observations, not real audio accuracy',rows=rows),indent=2)+'\n')
        print(json.dumps(row),flush=True)


if __name__=='__main__':main()
