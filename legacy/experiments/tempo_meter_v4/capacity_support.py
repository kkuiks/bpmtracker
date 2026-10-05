"""Use confident no-grid observations during structural inference, not just export."""
import numpy as np
from . import fast_structure
from .learned_support import infer


def decode(clock,obs,parameters=None,**kwargs):
    if obs.get('grid_probability') is None:return fast_structure.decode(clock,obs,parameters,**kwargs)
    end,record=infer(obs,clock)
    if 'learned_grid_end_seconds' not in record:return fast_structure.decode(clock,obs,parameters,**kwargs)
    qend=float(np.interp(end,clock[:,1],clock[:,0]))
    clipped=clock[clock[:,1]<end]
    clipped=np.vstack([clipped,[qend,end]])
    if len(clipped)<2:return fast_structure.decode(clock,obs,parameters,**kwargs)
    return fast_structure.decode(clipped,dict(obs,duration=end),parameters,**kwargs)
