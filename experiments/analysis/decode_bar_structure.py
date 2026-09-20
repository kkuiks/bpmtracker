"""Propose variable bar lengths on an immutable pulse grid.

Bar lengths count input pulses. They are not named time signatures until the
musical pulse unit is chosen. No bar hypothesis may move or add pulse times.
"""

import numpy as np

from run_beat_this import validate_events


def bar_path(grid, downbeat_logits, fps=50., lengths=(4,3,2), change_penalty=2., variable=True):
    grid = validate_events(grid)
    evidence = np.asarray(downbeat_logits,dtype=float)
    if evidence.ndim!=1 or not np.isfinite(evidence).all() or fps<=0 or not np.isfinite(fps):
        raise ValueError('finite logits and positive frame rate required')
    if not lengths or any(not isinstance(n,int) or n<2 for n in lengths) or not np.isfinite(change_penalty) or change_penalty<0:
        raise ValueError('bar lengths and change penalty must be valid')
    if not len(grid) or not len(evidence):
        return {'status':'insufficient_evidence','downbeats_seconds':[],'meter_events':[],'accepted':False}
    observations=[]
    radius=max(1,round(.04*fps))
    for event in grid:
        center=round(event*fps)
        left,right=max(0,center-radius),min(len(evidence),center+radius+1)
        observations.append(float(np.max(evidence[left:right])) if right>left else -12.)
    gain=np.clip(observations,-12,12)
    count,width=len(grid),len(lengths)
    scores=np.full((count,width),-np.inf)
    previous=np.full((count,width),-1,dtype=int)
    for index in range(count):
        for current,length in enumerate(lengths):
            if index<length:
                scores[index,current]=gain[index]
            for past,old_length in enumerate(lengths):
                if not variable and current!=past:continue
                prior=index-old_length
                if prior<0:continue
                score=scores[prior,past]+gain[index]-(change_penalty if current!=past else 0)
                if score>scores[index,current]:
                    scores[index,current]=score
                    previous[index,current]=past
    endings=[(scores[i,m],i,m) for m,length in enumerate(lengths) for i in range(max(0,count-length),count)]
    score,index,meter=max(endings,key=lambda item:item[0])
    path=[]
    while index>=0:
        path.append((index,meter))
        past=int(previous[index,meter])
        if past<0:break
        index-=lengths[past]
        meter=past
    path.reverse()
    events=[]
    for index,meter in path:
        length=lengths[meter]
        if not events or events[-1]['pulses_per_bar']!=length:
            events.append({'pulse_index':index,'time_seconds':float(grid[index]),'pulses_per_bar':length,
                           'quarter_note_denominator':None,'accepted':False})
    return {'status':'unreviewed_bar_proposal' if sum(gain>0)>=2 else 'weak_downbeat_evidence',
            'accepted':False,'downbeats_seconds':[float(grid[i]) for i,_ in path],
            'meter_events':events,'bar_start_pulse_indices':[i for i,_ in path],
            'path_score_not_confidence':float(score),'pulse_times_changed':False,
            'parameters':{'lengths':list(lengths),'change_penalty':change_penalty,'variable':variable},
            'scope':'Input-pulse bar structure; quarter-note level and meter denominator unresolved.'}
