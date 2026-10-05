"""Compatibility export for the frozen musical-map evaluator.

The physical result is retained separately. This exporter does not read a
reference, select another decoder, alter the clock, or correct inferred meter.
"""
import numpy as np
from .clock import quarters_at, seconds_at


def export_map(timeline):
    source=timeline['source'];duration=source['sample_frames']/source['sample_rate'];clock=timeline['clock']['knots']
    bars=timeline['bar_events']
    if not bars or not any(b['signature'] for b in bars):raise ValueError('no resolved meter proposal')
    # Keep the physical opening phase; do not invent a snapped pickup origin.
    # Later grammar-derived versus physical boundaries remain diagnostic.
    origin=bars[0]['quarter']
    events=[];q=origin;last=None;displacements=[]
    for bar in bars:
        signature=bar['signature']
        if signature is None:
            if last is None:raise ValueError('unresolved first bar')
            n,d=last
        else:n,d=signature['numerator'],signature['denominator']
        displacements.append(float(seconds_at(clock,q)-bar['seconds']))
        if last!=(n,d):events.append(dict(pulse=float(q),numerator=n,denominator=d,grouping=None,bar_action='continue'))
        q+=4*n/d;last=(n,d)
    lo=float(quarters_at(clock,0));hi=float(quarters_at(clock,duration))
    # A first observed downbeat can follow a pickup. Declare the proposed first
    # signature over the source opening while keeping its separate bar anchor.
    # This is a disclosed continuation hypothesis, not reference information.
    events[0]['pulse']=min(events[0]['pulse'],lo)
    coordinates=np.r_[lo,[k['quarter'] for k in clock[1:-1]],hi]
    coordinates=np.unique(coordinates[(coordinates>=lo)&(coordinates<=hi)])
    seconds=seconds_at(clock,coordinates)
    # The endpoint coordinates are inverse(0) and inverse(duration); express
    # those exact requested bounds rather than a +/-1e-16 round-trip artifact.
    seconds[0]=0.;seconds[-1]=duration
    m=dict(schema_version=1,source=source,clock_knots=[dict(pulse=float(a),source_seconds=float(b)) for a,b in zip(coordinates,seconds)],
           quarters_per_pulse=dict(numerator=1,denominator=1),bar_anchor_pulse=origin,meter_events=events,
           support_seconds=timeline['grid_support_seconds'],analysis_condition='unhinted',shared_origin_id=None)
    return m,dict(max_export_bar_displacement_seconds=max(map(abs,displacements),default=0),
                  per_bar_displacement_seconds=displacements,physical_result_retained=True,
                  notation_changes_clock=False,reference_used=False,export_accuracy_certified=False)
