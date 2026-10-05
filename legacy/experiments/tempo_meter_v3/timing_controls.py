"""Reuse reference-free v2 CLOCK proposals inside the common v3 search.

Their fixed meter selections and tail-stop rule are discarded. Every proposal
uses the same learned, changing-meter decoder and pulse-level selector in v3.
"""
import numpy as np
import torch
from beat_this.model.postprocessor import Postprocessor
from experiments.tempo_meter_v2.constant_grid import infer_constant_map
from experiments.tempo_meter_v2.tempo_segments import infer_tempo_segments
from experiments.tempo_meter_v2.barwise_tempo import propose_barwise_tempo
from experiments.tempo_meter_v2.compound_meter import propose_compound_6_8
from .clock_search import sigmoid


def proposals(logits,source,structural):
    beat,down=logits.T
    beats,bars=Postprocessor(type='minimal',fps=50)(torch.from_numpy(beat),torch.from_numpy(down))
    constant=infer_constant_map(beat,down,50,bars,source)
    bounded=infer_tempo_segments(constant,beat,down,50,beats)
    barwise,decision=propose_barwise_tempo(constant,beats,bars)
    compound,other=propose_compound_6_8(constant,beats)
    maps=[('periodic_clock',constant)]
    if bounded['diagnostics']['tempo_segments']['accepted']:maps.append(('step_clock',bounded))
    if decision['accepted']:maps.append(('event_clock',barwise))
    if other['accepted']:maps.append(('compound_clock',compound))
    result=[];evidence=.75*sigmoid(beat)+.25*np.interp(np.arange(len(beat)),np.arange(len(structural['events']))*4,sigmoid(structural['events'][:,0]))
    for name,value in maps:
        m=value['map'];unit=m['quarters_per_pulse']['numerator']/m['quarters_per_pulse']['denominator']
        clock=np.array([[k['pulse']*unit,k['source_seconds']] for k in m['clock_knots']],float)
        at_zero=np.interp(0,clock[:,1],clock[:,0]);first=np.ceil(at_zero-1e-9)
        first_time=np.interp(first,clock[:,0],clock[:,1])
        rest=clock[clock[:,0]>first+1e-9].copy();rest[:,0]-=first
        clock=np.vstack([[0,first_time],rest])
        if len(clock)<2:continue
        q=np.arange(0,np.floor(clock[-1,0])+1);t=np.interp(q,clock[:,0],clock[:,1])
        scores=np.interp(t,np.arange(len(evidence))/50,evidence)
        result.append(dict(name=name,clock=clock,score=float(np.mean(2*scores-.35)),
            fit=dict(segments=len(clock)-1,source='shared_acoustic_clock_proposal',meter_from_v2_used=False,tail_from_v2_used=False),observed_pulses=t))
    return result
