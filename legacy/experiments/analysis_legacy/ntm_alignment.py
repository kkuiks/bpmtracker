"""Source selection and explicitly separated automatic/listening-only alignment."""
from pathlib import PurePosixPath
import re

import numpy as np


def source_candidates(rows):
    audio=[r for r in rows if PurePosixPath(r.filename).suffix.lower() in ('.wav','.flac')
           and not re.search(r'(?i)click|guide|metronome',r.filename)]
    groups=[
        (r'(?:^|[ _-])(?:kick|kik|bd|bass.?drum)(?:[ _.-]|$)',None,1),
        (r'(?:^|[ _-])(?:snare|snr|drums?)(?:[ _.-]|$)',None,1),
        (r'(?:rhy|rhythm).*?(?:gtr|guitar)|(?:gtr|guitar).*?(?:rhy|rhythm|amp)',r'(?:^|[ _-])di(?:[ _.-]|$)',2),
        (r'(?:^|[ _-])(?:vox|vocals?)(?:[ _.-]|$)',r'adt|print|fx|robot|inhale',1),
        (r'(?:^|[ _-])room(?:[ _.-]|$)',None,1),
        (r'(?:^|[ _-])bass(?:[ _.-]|$)',r'drop|hit',1),
    ]
    selected=[]
    for pattern,exclude,limit in groups:
        matches=[r for r in audio if re.search(pattern,PurePosixPath(r.filename).name,re.I)
                 and not (exclude and re.search(exclude,PurePosixPath(r.filename).name,re.I))]
        matches.sort(key=lambda r:(bool(re.search(r'(?i)sample|trig|midi',r.filename)),r.filename.casefold()))
        selected.extend(r for r in matches[:limit] if r not in selected)
    return selected


def alignment_signal(audio):
    if audio.ndim!=2 or not np.isfinite(audio).all():raise ValueError('Finite channels required')
    peaks=np.max(np.abs(audio),axis=0)
    if float(peaks.max())<1e-8:
        return None,{'status':'silent_source','native_channel_peaks':peaks.tolist()}
    mono=audio.mean(axis=1)
    if float(np.max(np.abs(mono))) < float(peaks.max())*1e-3:
        channel=int(np.argmax(np.mean(audio.astype('float64')**2,axis=0)))
        return audio[:,channel],{'status':'usable','channel_policy':'highest_energy_after_cancellation','channel':channel}
    return mono,{'status':'usable','channel_policy':'mono_mean'}


def coherent_review_proposal(result,rate):
    """Manual audition evidence only: NEVER change the original gate result."""
    all_rows=result.get('windows',[])
    rows=sorted((r for r in all_rows if r['normalized_correlation']>=.05),key=lambda r:r['stem_minus_mix_frames'])
    groups=[]
    for i,row in enumerate(rows):
        group=[r for r in rows[i:] if r['stem_minus_mix_frames']-row['stem_minus_mix_frames']<=round(rate*.001)]
        if len(group)<7:continue
        total_span=max(r['mix_start_frame'] for r in all_rows)-min(r['mix_start_frame'] for r in all_rows)
        span=max(r['mix_start_frame'] for r in group)-min(r['mix_start_frame'] for r in group)
        if total_span<=0 or span/total_span<.6:continue
        groups.append(group)
    if not groups:return None
    group=max(groups,key=lambda rs:(len(rs),np.median([r['normalized_correlation'] for r in rs])))
    return {'stem_minus_mix_frames':int(round(np.median([r['stem_minus_mix_frames'] for r in group]))),
            'consistent_windows':len(group),
            'spread_frames':max(r['stem_minus_mix_frames'] for r in group)-min(r['stem_minus_mix_frames'] for r in group),
            'median_correlation':float(np.median([r['normalized_correlation'] for r in group])),
            'minimum_correlation':min(r['normalized_correlation'] for r in group),
            'policy':{'minimum_correlation':.05,'minimum_windows':7,'maximum_spread_ms':1,'minimum_window_span_fraction':.6},
            'qualification':'provisional listening candidate, not a pass of the original automatic gate',
            'automatic_gate_passed':False}
