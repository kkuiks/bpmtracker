"""Source-sample attack evidence and conservative shared-phase proposals.

Attack time is not automatically musical beat time. Calibration is explicit,
and disagreement produces abstention. No reference label enters selection.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import numpy as np


@dataclass(frozen=True)
class AttackConfig:
    hop_seconds: float = .001
    minimum_log_rise: float = .6
    minimum_spacing_seconds: float = .025
    background_seconds: float = .012
    search_back_seconds: float = .012
    peak_ahead_seconds: float = .008
    crossing_fraction: float = .2


@dataclass(frozen=True)
class PhaseConfig:
    radius_seconds: float = .050
    resolution_seconds: float = .001
    kernel_seconds: float = .004
    window_beats: int = 24
    minimum_window_beats: int = 12
    minimum_peak_support: float = .28
    minimum_profile_prominence: float = .12
    maximum_peak_width_seconds: float = .020
    band_agreement_seconds: float = .008
    window_agreement_seconds: float = .008
    minimum_agreeing_windows: int = 2
    minimum_window_fraction: float = .6
    minimum_move_seconds: float = .003


BANDS=('smooth_8ms','detail_1to8ms','detail_under1ms')


def _centered_mean(values,size):
    size=max(1,int(size)|1);half=size//2
    padded=np.pad(values,(half,half));sums=np.r_[0.,np.cumsum(padded,dtype=np.float64)]
    return ((sums[size:]-sums[:-size])/size).astype(np.float32)


def extract_attacks(audio,sample_rate,config=None):
    """Three complementary, explicitly centered filters and sample-bin energy.

    No spectral-maximum clipping is used. Filter responses and rise detection
    require synthetic timing calibration; centered filters can pre-ring.
    """
    config=config or AttackConfig();audio=np.asarray(audio,dtype=np.float32)
    if (not all(np.isfinite(v) for v in asdict(config).values()) or config.hop_seconds<=0 or
            config.minimum_log_rise<=0 or config.minimum_spacing_seconds<=0 or
            config.background_seconds<=0 or config.search_back_seconds<0 or config.peak_ahead_seconds<=0 or
            not 0<config.crossing_fraction<1):
        raise ValueError('invalid attack configuration')
    if audio.ndim==2:audio=audio.mean(axis=1)
    if audio.ndim!=1 or not len(audio) or not np.isfinite(audio).all() or not np.isfinite(sample_rate) or sample_rate<=0:
        raise ValueError('finite nonempty audio and positive sample rate required')
    hop=max(1,round(sample_rate*config.hop_seconds));dt=hop/sample_rate
    broad=_centered_mean(audio,round(sample_rate*.008))
    narrow=_centered_mean(audio,round(sample_rate*.001))
    signals=(broad,narrow-broad,audio-narrow)
    frames=int(np.ceil(len(audio)/hop));background=max(2,round(config.background_seconds/dt))
    back=max(1,round(config.search_back_seconds/dt));ahead=max(1,round(config.peak_ahead_seconds/dt))
    spacing=max(1,round(config.minimum_spacing_seconds/dt));bands={}
    for name,signal in zip(BANDS,signals):
        padded=np.pad(signal,(0,frames*hop-len(signal)))
        energy=np.mean(padded.reshape(frames,hop).astype(np.float64)**2,axis=1)
        if energy.max()<1e-15:
            bands[name]={'seconds':[],'strength':[],'rise_seconds':[]};continue
        floor=max(1e-15,float(np.quantile(energy,.9))*1e-3,float(energy.max())*1e-9)
        logs=np.log(energy+floor)
        past=np.pad(logs,(background,0),constant_values=logs.min())
        sums=np.r_[0.,np.cumsum(past)];mean_past=(sums[background:background+frames]-sums[:frames])/background
        novelty=np.maximum(0,logs-mean_past)
        peaks=np.flatnonzero((novelty>=config.minimum_log_rise)&
            (novelty>=np.r_[0.,novelty[:-1]])&(novelty>np.r_[novelty[1:],0.]))
        blocked=np.zeros(frames,dtype=bool);kept=[]
        for p in peaks[np.argsort(-novelty[peaks],kind='stable')]:
            if blocked[p]:continue
            left=max(0,p-back);right=min(frames,p+ahead+1)
            peak=p+int(np.argmax(energy[p:right]));base=float(np.median(energy[max(0,left-background):left])) if left else 0.
            height=energy[peak]-base
            if height<=floor:continue
            threshold=base+config.crossing_fraction*height
            above=energy[left:peak+1]>=threshold
            crossings=np.flatnonzero(above&~np.r_[False,above[:-1]])
            if not len(crossings):continue
            start=left+int(crossings[-1])
            # Frames are timestamped at their original source-bin beginning.
            if start*hop>=len(audio):continue
            kept.append((start*dt,float(novelty[p]),max(0.,(peak-start)*dt)))
            blocked[max(0,p-spacing):min(frames,p+spacing+1)]=True
        kept.sort();dedup={v[0]:v for v in kept}
        values=list(dedup.values())
        bands[name]={'seconds':[v[0] for v in values],'strength':[v[1] for v in values],
                     'rise_seconds':[v[2] for v in values]}
    return {'schema_version':'sample-bin-attacks-v1','source_sample_rate':int(sample_rate),
        'source_frames':len(audio),'source_origin_seconds':0,'sample_hop':hop,'actual_hop_seconds':dt,
        'configuration':asdict(config),'bands':bands,
        'timing_warning':'These are filtered attack candidates, not certified musical beats or independent instruments.'}


def _band_profile(beats,events,config):
    offsets=np.arange(-config.radius_seconds,config.radius_seconds+config.resolution_seconds/2,config.resolution_seconds)
    scores=np.zeros((len(beats),len(offsets)))
    for i,beat in enumerate(beats):
        left,right=np.searchsorted(events,[beat-config.radius_seconds-.015,beat+config.radius_seconds+.015])
        differences=events[left:right]-beat
        if len(differences):
            scores[i]=np.exp(-.5*((differences[:,None]-offsets)/config.kernel_seconds)**2).max(axis=0)
    profile=scores.mean(axis=0);best=int(np.argmax(profile));peak=float(profile[best]);background=float(np.median(profile))
    prominence=peak-background;half=background+prominence/2
    lo=best;hi=best
    while lo>0 and profile[lo-1]>=half:lo-=1
    while hi<len(profile)-1 and profile[hi+1]>=half:hi+=1
    width=(hi-lo)*config.resolution_seconds
    eligible=(peak>=config.minimum_peak_support and prominence>=config.minimum_profile_prominence and
              width<=config.maximum_peak_width_seconds and best not in (0,len(offsets)-1))
    return {'offset_seconds':float(offsets[best]),'peak_support':peak,'prominence':prominence,
            'width_seconds':width,'eligible':bool(eligible),'supported_beat_count':int(np.sum(scores[:,best]>=.5))}


def propose_phase(beats,attacks,calibration,config=None):
    config=config or PhaseConfig();beats=np.asarray(beats,dtype=float)
    if (not all(np.isfinite(v) for v in asdict(config).values()) or
            not 0<config.resolution_seconds<=config.radius_seconds<=.1 or config.kernel_seconds<=0 or
            config.window_beats!=int(config.window_beats) or config.window_beats<config.minimum_window_beats or
            config.minimum_window_beats<2 or config.minimum_agreeing_windows<2 or
            not 0<config.minimum_window_fraction<=1):
        raise ValueError('invalid phase configuration')
    if beats.ndim!=1 or not np.isfinite(beats).all() or np.any(np.diff(beats)<=0):
        raise ValueError('source-time beats must be finite and strictly increasing')
    if not calibration.get('synthetic_only') or calibration.get('reference_music_used'):
        raise ValueError('timing calibration must be independent of reference music')
    output={'schema_version':'shared-phase-proposal-v1','accepted':False,'reference_used_for_prediction':False,
        'configuration':asdict(config),'status':'insufficient_evidence','proposed_shift_seconds':0.,
        'applied_shift_seconds':0.,'windows':[],'source_audio_modified':False,
        'scope':'one constant shift per existing clock; no per-beat jitter or tempo changes',
        'calibration_scope':'synthetic attack timing only; not original metronome identification'}
    events={}
    for name,band in attacks['bands'].items():
        cal=calibration['bands'][name]
        if cal['eligible']:
            times=np.asarray(band['seconds']);rise=np.asarray(band['rise_seconds'])
            events[name]=times[rise<=.008]-cal['bias_seconds']
    for start in range(0,len(beats),config.window_beats):
        window=beats[start:start+config.window_beats]
        if len(window)<config.minimum_window_beats:continue
        profiles={name:_band_profile(window,times,config) for name,times in events.items()}
        eligible=[p for p in profiles.values() if p['eligible']]
        clusters=[[p for p in eligible if abs(p['offset_seconds']-center['offset_seconds'])<=config.band_agreement_seconds]
                  for center in eligible]
        cluster=max(clusters,key=lambda values:(len(values),sum(v['prominence'] for v in values)),default=[])
        record={'source_seconds':[float(window[0]),float(window[-1])],'beat_count':len(window),'bands':profiles,'eligible':False}
        if len(cluster)>=2:
            record.update(eligible=True,offset_seconds=float(np.median([v['offset_seconds'] for v in cluster])),
                          agreeing_bands=len(cluster))
        output['windows'].append(record)
    usable=[w for w in output['windows'] if w['eligible']]
    clusters=[[w for w in usable if abs(w['offset_seconds']-center['offset_seconds'])<=config.window_agreement_seconds] for center in usable]
    cluster=max(clusters,key=len,default=[])
    output['total_windows']=len(output['windows']);output['eligible_windows']=len(usable);output['agreeing_windows']=len(cluster)
    if len(cluster)<config.minimum_agreeing_windows or len(cluster)<config.minimum_window_fraction*len(output['windows']):
        output['status']='abstained_disagreement_or_low_coverage';return output
    shift=float(np.median([v['offset_seconds'] for v in cluster]));output['proposed_shift_seconds']=shift
    if abs(shift)<config.minimum_move_seconds:
        output['status']='no_material_shift_supported';return output
    output.update(status='unaccepted_source_supported_shift',applied_shift_seconds=shift,
                  window_shift_spread_seconds=float(np.ptp([v['offset_seconds'] for v in cluster])))
    return output


def shifted_clock(clock,shift,duration):
    """Shift an unaccepted grid on the immutable source axis; preserve all rates."""
    if (not np.isfinite(shift) or abs(shift)>.1 or not np.isfinite(duration) or duration<=0 or clock.get('accepted') or
            clock.get('anchor_checks') or clock.get('assistance') or clock.get('locked_knots')):
        raise ValueError('bounded source shift of an unaccepted, unanchored clock required')
    result=deepcopy(clock);result['coefficients'][0]+=shift
    for segment in result['segments']:
        segment['start_seconds']+=shift;segment['end_seconds']+=shift
    if 'support_seconds' in result:result['support_seconds']=[v+shift for v in result['support_seconds']]
    if 'beats_seconds' in result:result['beats_seconds']=[v+shift for v in result['beats_seconds'] if 0<=v+shift<duration]
    if 'indexed_grid' in result:
        result['indexed_grid']=[{**v,'source_seconds':v['source_seconds']+shift} for v in result['indexed_grid'] if 0<=v['source_seconds']+shift<duration]
    result.update(accepted=False,source_audio_modified=False,source_origin_seconds=0,
                  phase_adjustment_seconds=shift,status='unaccepted_shared_phase_adjustment')
    return result
