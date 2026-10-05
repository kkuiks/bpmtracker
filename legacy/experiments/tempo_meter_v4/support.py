"""Explicit weak-grid/rest/unknown/free-ending states; weak != no grid."""
import numpy as np


def infer(obs,clock):
    windows=[]
    for start in np.arange(0,obs['duration'],2.):
        stop=min(start+2,obs['duration']);mask=(obs['times']>=start)&(obs['times']<stop)
        events=obs['events'][(obs['events']>=start)&(obs['events']<stop)]
        q=np.interp(events,clock[:,1],clock[:,0])
        coherence=float(np.mean(abs(q*2-np.round(q*2))<.16)) if len(q) else None
        rms=float(np.mean(obs['energy'][mask]));flux=float(np.mean(obs['onset'][mask]))
        state='grid' if coherence is not None and coherence>=.65 else 'weak_grid' if not len(q) else 'unresolved'
        windows.append(dict(start=float(start),end=float(stop),state=state,coherence=coherence,event_count=len(q),rms=rms,onset=flux))
    end=obs['duration'];reason='weak_evidence_alone_does_not_end_grid'
    # Require positive evidence of an irregular sounding terminal passage;
    # a silent rest and a weak intro are explicitly not enough.
    for i,w in enumerate(windows):
        tail=windows[i:]
        if w['start']<obs['duration']*.5 or obs['duration']-w['start']<8:continue
        if not all(x['state']=='unresolved' and x['event_count']>=2 for x in tail):continue
        if not any(x['state']=='grid' for x in windows[max(0,i-4):i]):continue
        end=w['start'];reason='sustained_irregular_terminal_events_without_grid_return'
        for x in tail:x['state']='free_ending'
        break
    return end,dict(states=windows,reason=reason,uncertainty_calibrated=False)
