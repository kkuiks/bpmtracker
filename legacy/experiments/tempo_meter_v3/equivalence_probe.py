"""Unapproved local-rebarring policy probe; never a production score.

Inputs are complete contiguous bars in a shared quarter coordinate and a
piecewise-linear quarter-to-source clock. Missing grouping is not evidence
of musical equivalence. Eligible edits still need owner policy review.
"""
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
import math


@dataclass(frozen=True)
class Policy:
    timing_tolerance_seconds: float = .070
    max_block_bars: int = 4
    context_bars: int = 2


def time_at(clock, quarter):
    if quarter < clock[0][0]-1e-9 or quarter > clock[-1][0]+1e-9:
        raise ValueError('clock extrapolation forbidden')
    i = min(max(0, bisect_right([x[0] for x in clock], quarter)-1), len(clock)-2)
    q0, t0 = clock[i]; q1, t1 = clock[i+1]
    return t0+(quarter-q0)*(t1-t0)/(q1-q0)


def validate(value):
    clock, bars = value['clock'], value['bars']
    if len(clock) < 2 or not bars:
        raise ValueError('nonempty bars and clock required')
    if any(not math.isfinite(x) for point in clock for x in point):
        raise ValueError('finite clock required')
    if any(b[0] <= a[0] or b[1] <= a[1] for a,b in zip(clock,clock[1:])):
        raise ValueError('clock must be strictly monotonic')
    end = None
    for b in bars:
        n,d = b['n'],b['d']
        if type(n) is not int or n < 1 or type(d) is not int or d < 1 or d & (d-1):
            raise ValueError('positive numerator and power-of-two denominator required')
        if not math.isfinite(b['q']) or (end is not None and abs(b['q']-end)>1e-8):
            raise ValueError('contiguous finite bar coordinates required')
        group = b.get('grouping')
        if group is not None and (not group or any(type(x) is not int or x < 1 for x in group) or sum(group)!=n):
            raise ValueError('invalid grouping')
        end=b['q']+4*n/d
        time_at(clock,b['q']); time_at(clock,end)


def compare(reference, prediction, policy=Policy()):
    """Return a single coherent alignment, not metric-wise best alternatives."""
    if policy.context_bars < 1 or policy.max_block_bars < 2 or not math.isfinite(policy.timing_tolerance_seconds) or policy.timing_tolerance_seconds < 0:
        raise ValueError('invalid policy')
    validate(reference); validate(prediction)
    r,p = reference['bars'],prediction['bars']
    result={'policy_status':'unapproved_proposal','policy_revision':2,'strict':False,
            'eligible_local_rebar':False,'musical_equivalence_certified':False,'alignment':[]}
    r_end=r[-1]['q']+4*r[-1]['n']/r[-1]['d']
    p_end=p[-1]['q']+4*p[-1]['n']/p[-1]['d']
    if abs(r[0]['q']-p[0]['q'])>1e-8 or abs(r_end-p_end)>1e-8:
        return {**result,'reason':'different_coverage_or_quarter_origin'}
    sample=sorted({r[0]['q'],r_end}|{q for v in (reference,prediction) for q,t in v['clock'] if r[0]['q']<=q<=r_end})
    error=max(abs(time_at(reference['clock'],q)-time_at(prediction['clock'],q)) for q in sample)
    if error>policy.timing_tolerance_seconds:
        return {**result,'reason':'different_physical_clock','max_clock_error_seconds':error}
    # Stable-meter boundaries are protected in both directions. Inspect the
    # complete bar sequences, so a larger mixed block cannot hide their removal.
    # This is a general constraint, not a special case for any recording.
    def protected(sequence):
        return [b['q'] for a,b in zip(sequence,sequence[1:])
                if (a['n'],a['d']) == (b['n'],b['d'])]
    for origin, other, side in ((r,p,'reference'),(p,r,'prediction')):
        absent=[q for q in protected(origin)
                if not any(abs(q-b['q'])<1e-8 for b in other)]
        if absent:
            return {**result,'reason':'stable_meter_boundary_removed',
                    'protected_side':side,'missing_boundary_quarters':absent}
    def exact(i,j):
        if not (0<=i<len(r) and 0<=j<len(p)):
            return False
        a,b=r[i],p[j]
        return all(a.get(k)==b.get(k) for k in ('n','d','grouping')) and abs(a['q']-b['q'])<1e-8
    def edit(i,j,a,b):
        if a==b==1 or i+a>len(r) or j+b>len(p):
            return False
        if not all(exact(i-k,j-k) and exact(i+a+k-1,j+b+k-1) for k in range(1,policy.context_bars+1)):
            return False
        left,right=r[i:i+a],p[j:j+b]
        if abs(left[0]['q']-right[0]['q'])>1e-8:
            return False
        if abs(sum(4*x['n']/x['d'] for x in left)-sum(4*x['n']/x['d'] for x in right))>1e-8:
            return False
        if len({x['d'] for x in left+right})!=1:
            return False
        groups=[x.get('grouping') for x in left+right]
        if any(g is not None for g in groups):
            if any(g is None for g in groups):
                return False
            if [v for x in left for v in x['grouping']] != [v for x in right for v in x['grouping']]:
                return False
        return True
    @lru_cache(None)
    def solve(i,j):
        if i==len(r) and j==len(p):
            return ()
        if exact(i,j):
            rest=solve(i+1,j+1)
            if rest is not None:
                return ((i,j,1,1),)+rest
        for a in range(1,policy.max_block_bars+1):
            for b in range(1,policy.max_block_bars+1):
                if edit(i,j,a,b):
                    rest=solve(i+a,j+b)
                    if rest is not None:
                        return ((i,j,a,b),)+rest
        return None
    # Review windows are intentionally bounded; this is not a full-song scorer.
    if max(len(r),len(p))>256:
        raise ValueError('probe window exceeds 256 bars')
    path=solve(0,0)
    if path is None:
        return {**result,'reason':'no_permitted_local_alignment'}
    strict=all(a==b==1 for i,j,a,b in path)
    return {**result,'strict':strict,'eligible_local_rebar':not strict,
            'reason':'strict_match' if strict else 'local_rebar_requires_policy_approval',
            'alignment':[dict(reference_index=i,prediction_index=j,reference_count=a,prediction_count=b) for i,j,a,b in path],
            'max_clock_error_seconds':error}
