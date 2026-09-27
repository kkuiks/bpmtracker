"""Validate status-audit references without consulting model predictions."""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from inspect_inputs import sha256


def increasing(values,allow_negative=False):
    try:
        values=np.asarray(values,dtype=float)
    except (TypeError,ValueError):
        return False
    return bool(values.ndim==1 and len(values) and np.isfinite(values).all()
                and (allow_negative or np.all(values>=0)) and np.all(np.diff(values)>0))


def reference_content(reference):
    """Distinguish declarations, actual changes in support, and scoring capability.

    Constant maps can evaluate false changes. Repeated declarations can express
    bar resets but are not signature changes. The evaluated interval is open
    for change events, matching the existing tempo-change scoring boundary.
    """
    support=reference.get('evaluation_support_seconds')
    if (not isinstance(support,(list,tuple)) or len(support)!=2
            or not np.isfinite(support).all() or not support[0]<support[1]):
        raise ValueError('invalid evaluation support')
    lo,hi=support;result={}
    for kind,keys in [('tempo',('bpm_quarter',)),('meter',('numerator','denominator'))]:
        events=reference.get(kind+'_events')
        if events is None:
            result[kind]={'labels_available':False,'declaration_count':0,
                'changes_in_support':[],'changes_outside_support':[],'repeated_declarations':[]}
            continue
        if events and not increasing([e['time_seconds'] for e in events],allow_negative=True):
            raise ValueError('invalid '+kind+' declaration times')
        if any(not np.isfinite([e[k] for k in keys]).all() or any(e[k]<=0 for k in keys) for e in events):
            raise ValueError('invalid '+kind+' declaration values')
        changes=[];outside=[];repeated=[]
        for previous,event in zip(events,events[1:]):
            record={'time_seconds':event['time_seconds'],
                'before':{k:previous[k] for k in keys},'after':{k:event[k] for k in keys}}
            if all(event[k]==previous[k] for k in keys):
                repeated.append(record)
            elif lo<event['time_seconds']<hi:
                changes.append(record)
            else:
                outside.append(record)
        result[kind]={'labels_available':bool(events),'declaration_count':len(events),
            'changes_in_support':changes,'changes_outside_support':outside,
            'repeated_declarations':repeated}
    return result


def validate(track,semantic_flags=None):
    audio=Path(track['input']['path']);reference_path=Path(track['reference']['path'])
    if sha256(audio)!=track['input']['sha256'] or sha256(reference_path)!=track['reference']['sha256']:
        raise ValueError(f'{track["id"]}: catalog hash mismatch')
    info=sf.info(audio);reference=json.loads(reference_path.read_text());failures=[];warnings=[]
    beats=reference.get('beats_seconds');support=reference.get('evaluation_support_seconds')
    if not beats or not increasing(beats):failures.append('invalid_beat_times')
    if not support or len(support)!=2 or not np.isfinite(support).all() or not 0<=support[0]<support[1]<=info.duration+1/info.samplerate:
        failures.append('invalid_evaluation_support')
    if reference.get('source_audio_sha256')!=track['input']['sha256']:failures.append('reference_audio_hash_mismatch')
    if reference.get('alignment_fitted_to_predictions') is not False and track['reference_tier']!='synthetic_authored_clock':
        failures.append('prediction_independence_not_explicit')
    down=reference.get('downbeats_seconds')
    meters=reference.get('meter_events')
    if down is not None:
        if down and not increasing(down):failures.append('invalid_downbeat_times')
        # In denominator-8 meters a bar may span a fractional number of
        # quarter-note reference pulses, so downbeats need not be a subset.
        if not meters or all(e['denominator']==4 for e in meters):
            unmatched=[v for v in down if min(abs(np.asarray(beats)-v),default=np.inf)>1e-8]
            if unmatched:failures.append('downbeats_not_subset_of_quarter_beats')
        else:
            warnings.append('nonquarter_meter_downbeats_scored_separately_from_quarter_beats')
    tempos=reference.get('tempo_events')
    if tempos is not None:
        if not tempos or not increasing([e['time_seconds'] for e in tempos],allow_negative=True):failures.append('invalid_tempo_event_times')
        if any(not np.isfinite(e['bpm_quarter']) or e['bpm_quarter']<=0 for e in tempos):failures.append('invalid_tempo_rate')
    if meters is not None and meters:
        if not increasing([e['time_seconds'] for e in meters],allow_negative=True):failures.append('invalid_meter_event_times')
        if any(not isinstance(e[k],int) or isinstance(e[k],bool) or e[k]<=0 for e in meters for k in ('numerator','denominator')):
            failures.append('invalid_meter_value')
        if any(e['denominator']&(e['denominator']-1) for e in meters):failures.append('non_power_of_two_meter_denominator')
    tier=track.get('reference_tier',track.get('qualification_status'))
    if not tier:failures.append('reference_tier_missing')
    if tier=='user_reviewed_tempo_map':
        acceptance=track.get('acceptance',{});path=Path(acceptance.get('path',''))
        if not path.is_file() or sha256(path)!=acceptance.get('sha256'):failures.append('owner_acceptance_missing_or_changed')
        if reference.get('accepted_by')!='project_owner':failures.append('owner_acceptance_not_explicit')
        warnings.append('no_independent_original_click_millisecond_bound')
    elif tier=='creator_map_observed_click_alignment':
        if not reference.get('reference_click_sha256') or not reference.get('click_map_validation'):failures.append('creator_click_validation_missing')
        warnings.append('recording_session_click_use_not_attested')
    elif tier=='observed_click_beats_only':
        if tempos is not None or meters is not None or down is not None:failures.append('beat_only_tier_contains_unsupported_labels')
        warnings.append('tempo_meter_downbeat_unscored')
    elif tier=='publisher_aligned_metronome_midi':
        warnings.append('publisher_2ms_alignment_not_independently_remeasured')
    elif tier=='audited_creator_click_beats':
        if reference.get('source_mapping',{}).get('alignment_fitted_to_predictions'):failures.append('walker_mapping_used_predictions')
        warnings.append('original_recording_click_use_not_attested')
    elif tier=='synthetic_authored_clock':
        warnings.append('synthesized_music_not_recorded_band')
    if semantic_flags: warnings.extend(semantic_flags)
    lo,hi=support or [0,0]
    scored=sum(lo<=v<=hi for v in beats or [])
    try:
        content=reference_content(reference)
    except (KeyError,TypeError,ValueError):
        content=None
        failures.append('invalid_reference_change_content')
    return {'id':track['id'],'cohort':track['cohort'],'reference_tier':tier,'valid':not failures,
        'failures':failures,'warnings':sorted(set(warnings)),'audio_geometry':{'sample_rate':info.samplerate,
        'channels':info.channels,'frames':info.frames,'duration_seconds':info.duration},
        'score_capabilities':{'beat_events':bool(beats),'downbeat_events':down is not None,
            'tempo_events':bool(tempos),'tempo_change_scoring':bool(tempos),
            'meter_events':bool(meters),'meter_change_scoring':bool(meters)},
        'reference_content':content,
        'reference_events_in_support':scored,'evaluation_support_seconds':support}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--semantic-audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();catalog=json.loads(args.catalog.read_text());semantic=json.loads(args.semantic_audit.read_text())
    flags={t['id']:[f for f in t['qualification']['review_flags'] if f not in {
        'musical_quarter_intent_not_independently_verified','tick_zero_musical_phase_not_independently_verified',
        'synthesized_arrangement_not_recorded_studio_band'}] for t in semantic['tracks']}
    rows=[validate(track,flags.get(track['id'])) for track in catalog['tracks']]
    report={'schema_version':1,'prediction_results_used':False,'catalog_path':str(args.catalog),
        'catalog_sha256':sha256(args.catalog),'tracks':rows,'counts':{
            'tracks':len(rows),'valid':sum(r['valid'] for r in rows),'invalid':sum(not r['valid'] for r in rows),
            'beat_scored':sum(r['score_capabilities']['beat_events'] for r in rows),
            'downbeat_scored':sum(r['score_capabilities']['downbeat_events'] for r in rows),
            'tempo_change_scoring_available':sum(r['score_capabilities']['tempo_change_scoring'] for r in rows),
            'meter_change_scoring_available':sum(r['score_capabilities']['meter_change_scoring'] for r in rows),
            'tempo_change_positive_in_support':sum(bool(r['reference_content'] and r['reference_content']['tempo']['changes_in_support']) for r in rows),
            'meter_change_positive_in_support':sum(bool(r['reference_content'] and r['reference_content']['meter']['changes_in_support']) for r in rows)},
        'complete':len(rows)==len(catalog['tracks'])}
    if any(not r['valid'] for r in rows):raise ValueError('invalid references: '+str([(r['id'],r['failures']) for r in rows if not r['valid']]))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report['counts']))


if __name__=='__main__':main()
