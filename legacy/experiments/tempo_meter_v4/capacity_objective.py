"""Score event roles relative to the actual emitted-quarter origin."""
import numpy as np
from . import analyzer

_ORIGINAL=analyzer.objective


def objective(path,obs,meter,parameters,graph=()):
    score=_ORIGINAL(path,obs,meter,parameters,graph)
    clock=path['clock'];rates=60*np.diff(clock[:,0])/np.diff(clock[:,1])
    actual_changes=int(np.sum(abs(np.diff(rates))>1e-6))
    score+=(max(0,len(clock)-2)-actual_changes)*parameters.get('tempo_change_cost',8.)
    assignments=path['assignments'];q=assignments[:,1];origin=meter['bars'][0]['q']
    coordinate=q-origin
    roles=np.where(abs(coordinate-np.round(coordinate))<1e-7,0.,
        np.where(abs(coordinate*2-np.round(coordinate*2))<1e-7,.7,1.8))
    if not obs.get('quarter_probability_supervision',False):
        groups=[]
        for b in meter['bars']:groups.extend(b['q']+np.cumsum([0,*b['grouping'][:-1]])*4/b['d'])
        groups=np.sort(np.asarray(groups));ix=np.searchsorted(groups,q)
        distance=np.minimum(abs(q-groups[np.clip(ix,0,len(groups)-1)]),abs(q-groups[np.clip(ix-1,0,len(groups)-1)]))
        roles[distance<1e-7]=0.
    strength=obs['event_strength'][assignments[:,0].astype(int)]
    return score-float(np.sum(roles*np.maximum(.1,strength)))


def install_objective():
    if analyzer.objective is objective:return
    if analyzer.objective is not _ORIGINAL:raise ValueError('unexpected objective adapter')
    analyzer.objective=objective
