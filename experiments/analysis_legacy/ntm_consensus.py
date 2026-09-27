"""Conservative operational source agreement; never strict beat ground truth."""
from pathlib import PurePosixPath
import math
import re
import numpy as np

POLICY = {
    'id': 'multisource-v1', 'minimum_families': 2,
    'maximum_disagreement_seconds': .002,
    'witness_minimum_correlation': .1, 'witness_minimum_windows': 4,
    'witness_maximum_spread_seconds': .001, 'minimum_span_fraction': .6,
    'verification_windows': 8, 'verification_minimum_windows': 6,
    'verification_minimum_correlation': .2,
    'qualification': 'Experimental operational acceptance; no measured strict timing error bound.',
}


def source_family(name):
    name=PurePosixPath(name).name
    if re.search(r'(?i)(?:kick|kik|snare|snr|drum|room|overhead|(?:^|[ _-])(?:bd|ohs?|toms?)(?:[ _.-]|$))',name):return 'drums'
    if re.search(r'(?i)(?:^|[ _-])bass(?:[ _.-]|$)',name):return 'bass'
    if re.search(r'(?i)gtr|guitar',name):return 'guitar'
    if re.search(r'(?i)(?:^|[ _-])(?:vox|vocals?)(?:[ _.-]|$)',name):return 'voice'
    return 'unknown'


def _rows(audit, minimum):
    rate=audit.get('source_sample_rate',0)
    origin=audit.get('project_origin',{}).get('file_zero_in_project_seconds')
    if rate<=0 or origin is None or not math.isfinite(origin):return []
    return [dict(offset=-r['stem_minus_mix_frames']/rate-origin,
                 start=r['mix_start_frame']/rate, correlation=r['normalized_correlation'])
            for r in audit.get('windows',[]) if minimum<=r['normalized_correlation']<=1]


def _coverage(rows, audit):
    starts=[r['mix_start_frame']/audit['source_sample_rate'] for r in audit.get('windows',[])]
    span=max(starts)-min(starts) if starts else 0
    return bool(rows and span>0 and max(r['start'] for r in rows)-min(r['start'] for r in rows)>=POLICY['minimum_span_fraction']*span
                and min(r['start'] for r in rows)<=min(starts)+.25*span
                and max(r['start'] for r in rows)>=max(starts)-.25*span)


def assess_sources(audits):
    """Count instrument families once; coherent conflicting sources veto acceptance."""
    sources=[];witnesses=[];strong=[];reasons=[]
    for a in audits:
        rows=sorted(_rows(a,POLICY['witness_minimum_correlation']),key=lambda r:r['offset'])
        clusters=[]
        for i,row in enumerate(rows):
            group=[r for r in rows[i:] if r['offset']-row['offset']<=POLICY['witness_maximum_spread_seconds']+1e-12]
            if len(group)>=POLICY['witness_minimum_windows'] and _coverage(group,a):clusters.append(group)
        family=source_family(a['source_member'])
        item={'source_member':a['source_member'],'family':family,'source_sha256':a.get('source_sha256'),
              'strong':False,'witness_offset_seconds':None}
        if clusters:
            cluster=max(clusters,key=lambda g:(len(g),np.median([r['correlation'] for r in g])))
            item.update(witness_offset_seconds=float(np.median([r['offset'] for r in cluster])),witness_windows=len(cluster))
            witnesses.append(item['witness_offset_seconds'])
            centers=[float(np.median([r['offset'] for r in g])) for g in clusters]
            if max(centers)-min(centers)>POLICY['maximum_disagreement_seconds']:
                reasons.append('ambiguous_source_clusters')
        eligible=_rows(a,.2)
        if a.get('qualified_constant_offset') and _coverage(eligible,a):
            item.update(strong=True,offset_seconds=float(np.median([r['offset'] for r in eligible])),strong_windows=len(eligible))
            if family!='unknown':strong.append(item)
        sources.append(item)
    if witnesses and max(witnesses)-min(witnesses)>POLICY['maximum_disagreement_seconds']+1e-12:
        reasons.append('source_disagreement')
    representatives=[];seen_hashes=set()
    for family in sorted({s['family'] for s in strong}):
        candidates=sorted([s for s in strong if s['family']==family],key=lambda s:(-s['strong_windows'],s['source_member']))
        chosen=next((s for s in candidates if s['source_sha256'] and s['source_sha256'] not in seen_hashes),None)
        if chosen:representatives.append(chosen);seen_hashes.add(chosen['source_sha256'])
    if len(representatives)<POLICY['minimum_families']:reasons.append('insufficient_distinct_instrument_families')
    values=[s['offset_seconds'] for s in representatives]
    if values and max(values)-min(values)>POLICY['maximum_disagreement_seconds']+1e-12:
        reasons.append('source_disagreement')
    return {'policy':dict(POLICY),'passed_initial':not reasons,'reasons':sorted(set(reasons)),
            'sources':sources,'supporting_sources':[s['source_member'] for s in representatives],
            'supporting_families':[s['family'] for s in representatives],
            'offset_seconds':float(np.median(values)) if values and not reasons else None,
            'witness_disagreement_seconds':max(witnesses)-min(witnesses) if witnesses else None}


def verify_consensus(initial, audits):
    """Validate the frozen offset at additional window positions, without refitting."""
    reasons=list(initial['reasons']);checks=[]
    for source in initial['supporting_sources']:
        matching=[a for a in audits if a['source_member']==source]
        a=matching[0] if len(matching)==1 else None
        rows=_rows(a,POLICY['verification_minimum_correlation']) if a else []
        residual=max(abs(r['offset']-initial['offset_seconds']) for r in rows) if rows and initial['offset_seconds'] is not None else None
        passed=bool(initial['passed_initial'] and len(rows)>=POLICY['verification_minimum_windows'] and _coverage(rows,a)
                    and a.get('qualified_constant_offset') and residual<=POLICY['maximum_disagreement_seconds']+1e-12)
        checks.append({'source_member':source,'passed':passed,'eligible_windows':len(rows),'maximum_offset_residual_seconds':residual})
        if not passed:reasons.append('additional_windows_disagree_or_insufficient')
    return {**initial,'passed':bool(initial['passed_initial'] and checks and not reasons),
            'reasons':sorted(set(reasons)),'verification':checks,'verification_audits':audits,
            'strict_timing_verified':False,'human_listening_performed':False}
