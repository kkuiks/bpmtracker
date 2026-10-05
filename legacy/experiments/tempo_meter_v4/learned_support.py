"""Common decoder input for qualified learned grid-support evidence.

No probability field means the frozen deterministic support route is used
unchanged. Low beat/downbeat strength alone never supplies this evidence.
Only a confident terminal no-grid posterior can shorten the grid; middle
rests remain under the clock. Thresholds are fixed before fitting weights.
"""
import numpy as np
from .support import infer as original


def infer(obs,clock):
    end,record=original(obs,clock)
    posterior=obs.get('grid_probability')
    if posterior is None:return end,record
    p=np.asarray(posterior,float);times=obs['times']
    if len(p)!=len(times) or not np.isfinite(p).all():raise ValueError('invalid support evidence')
    candidates=np.flatnonzero((p<.5)&np.r_[True,p[:-1]>=.5])
    selected=None
    for i in candidates:
        start=float(times[i]);tail=p[i:]
        if start<obs['duration']*.5 or obs['duration']-start<.5:continue
        if np.median(tail)>.2 or np.mean(tail<.5)<.9:continue
        before=p[max(0,i-int(8*obs['fps'])):i]
        if not len(before) or np.quantile(before,.8)<.8:continue
        high=np.flatnonzero(before>=.8)
        if not len(high):continue
        boundary=max(0,i-int(8*obs['fps']))+int(high[-1])+1
        selected=float(times[min(boundary,i)]);break
    if selected is not None:
        end=selected;record=dict(record,reason='confident_source_trained_terminal_no_grid',learned_grid_end_seconds=selected)
    record['learned_support_evidence']=dict(available=True,negative_threshold=.2,boundary_threshold=.8,negative_candidate_threshold=.5,
        minimum_terminal_seconds=.5,terminal_negative_fraction=.9,uncertainty_calibrated=False)
    return end,record
