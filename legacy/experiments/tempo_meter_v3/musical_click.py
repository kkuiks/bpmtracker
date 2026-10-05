"""Separate declared-meter/group clicks from quarter-clock diagnostics."""
from copy import deepcopy
import math
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis_legacy'))


def musical_events(raw):
    from experiments.analysis_legacy.music_map_contract import prepare_map,render_bars,interpolate_clock
    value=prepare_map(raw);extended=deepcopy(value);knots=extended['clock_knots']
    unit=value['quarters_per_pulse']['numerator']/value['quarters_per_pulse']['denominator']
    # A virtual final boundary exposes the last partial bar. Physical support
    # still clips every click; the frozen clock and reference are never edited.
    length=max(4*e['numerator']/e['denominator']/unit for e in value['meter_events'])
    a,b=knots[-2:];seconds_per_pulse=(b['source_seconds']-a['source_seconds'])/(b['pulse']-a['pulse'])
    knots.append(dict(pulse=b['pulse']+length*2,source_seconds=b['source_seconds']+length*2*seconds_per_pulse))
    rendered=render_bars(prepare_map(extended))
    if rendered['status']!='rendered':raise ValueError('meter click map cannot render')
    duration=value['duration_seconds'];beats=[];bars=[]
    def supported(t):return 0<=t<duration and any(lo-1e-9<=t<hi-1e-9 for lo,hi in value['support_seconds'])
    for bar in rendered['bars']:
        start=bar['start_seconds'];meter=bar['meter'];groups=meter.get('grouping')
        if groups:
            offsets=[];cursor=0
            for count in groups:offsets.append(cursor*4/meter['denominator']/unit);cursor+=count
        else:offsets=[i*4/meter['denominator']/unit for i in range(meter['numerator'])]
        for offset in offsets:
            t=interpolate_clock(knots,bar['start_pulse']+offset)
            if supported(t):beats.append(t)
        if supported(start):bars.append(start)
    return dict(meter_beats=sorted(set(beats)),meter_bars=sorted(set(bars)),
                meter_click_policy='explicit groups when declared; otherwise written denominator; no reference-derived correction')
