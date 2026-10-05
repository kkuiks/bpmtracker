"""Lossless display intervals derived from frozen musical maps; no rescoring."""
from bisect import bisect_right


def timeline_view(raw):
    unit = raw['quarters_per_pulse']['numerator']/raw['quarters_per_pulse']['denominator']
    knots = raw['clock_knots']; times = [k['source_seconds'] for k in knots]
    pulses = [k['pulse'] for k in knots]
    duration = raw['source']['sample_frames']/raw['source']['sample_rate']
    support = raw['support_seconds']

    def time_at(pulse):
        i = max(0, min(len(knots)-2, bisect_right(pulses, pulse)-1))
        return times[i]+(pulse-pulses[i])*(times[i+1]-times[i])/(pulses[i+1]-pulses[i])

    def clipped(start, end):
        return [(max(0., start, lo), min(duration, end, hi)) for lo,hi in support
                if min(duration,end,hi)>max(0.,start,lo)]

    tempo=[]
    for a,b in zip(knots,knots[1:]):
        rate = 60*unit*(b['pulse']-a['pulse'])/(b['source_seconds']-a['source_seconds'])
        for lo,hi in clipped(a['source_seconds'],b['source_seconds']):
            # Equal-rate knots encode geometry, not a new tempo declaration.
            if tempo and abs(tempo[-1]['end']-lo)<1e-9 and abs(tempo[-1]['bpm']-rate)<=1e-6:
                tempo[-1]['end']=hi
            else: tempo.append(dict(start=lo,end=hi,bpm=rate))
    meters=[]
    events=raw['meter_events'] or []
    for i,event in enumerate(events):
        start=time_at(event['pulse']);end=time_at(events[i+1]['pulse']) if i+1<len(events) else duration
        signature=f"{event['numerator']}/{event['denominator']}"
        for lo,hi in clipped(start,end):
            if meters and meters[-1]['signature']==signature and abs(meters[-1]['end']-lo)<1e-9:
                meters[-1]['end']=hi
            else: meters.append(dict(start=lo,end=hi,signature=signature))
    changes=[]
    for kind,segments,key in [('tempo',tempo,'bpm'),('meter',meters,'signature')]:
        for before,after in zip(segments,segments[1:]):
            if abs(before['end']-after['start'])<1e-9:
                changes.append(dict(time=after['start'],kind=kind,before=before[key],after=after[key]))
    return dict(tempo_segments=tempo,meter_segments=meters,
                map_changes=sorted(changes,key=lambda e:(e['time'],e['kind'])))


def outside_regions(raw, *, reference, known_tail=False):
    duration = raw['source']['sample_frames']/raw['source']['sample_rate']
    cursor = 0.; result = []
    end = raw['support_seconds'][-1][1] if raw['support_seconds'] else 0.
    for lo,hi in [*raw['support_seconds'],[duration,duration]]:
        lo = max(0.,min(duration,lo)); hi = max(0.,min(duration,hi))
        if lo > cursor:
            no_grid = not reference or (known_tail and cursor >= end-1e-9)
            result.append(dict(start=cursor,end=lo,kind='no_grid' if no_grid else 'unknown',
                               label='격자 없음' if no_grid else '미확인'))
        cursor=max(cursor,hi)
    return result
