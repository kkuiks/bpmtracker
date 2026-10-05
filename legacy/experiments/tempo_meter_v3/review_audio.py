"""Source-clock click rendering, including off-quarter bar boundaries."""
import math
import numpy as np


def render_click(rate, frames, beats, bars, groups=()):
    if rate <= 0 or frames <= 0:
        raise ValueError('positive sample clock required')
    result=np.zeros(frames,dtype=np.float32)
    events={}
    for priority, times in enumerate((beats,groups,bars)):
        for t in times:
            if not math.isfinite(t):
                raise ValueError('finite event required')
            index=round(t*rate)
            if 0<=t<frames/rate and 0<=index<frames:
                events[index]=max(events.get(index,-1),priority)
    for index,priority in events.items():
        count=min(round(rate*.035),frames-index)
        t=np.arange(count)/rate
        hz=(850,1250,1750)[priority]
        amp=(.23,.30,.40)[priority]
        result[index:index+count]+=amp*np.exp(-110*t)*np.cos(2*np.pi*hz*t)
    return result, sorted(events)
