"""Score explicit meter-change timing under a declared quarter-pulse hypothesis."""

from synthetic_groove import event_metrics


def score_bar_changes(reference, bars, tolerance=.5):
    if not reference.get('meter_events') or reference.get('downbeats_seconds') is None:
        return None
    if any(e['denominator']!=4 for e in reference['meter_events']):return None
    low,high=reference['evaluation_support_seconds']
    truth=[b for a,b in zip(reference['meter_events'],reference['meter_events'][1:])
           if low<b['time_seconds']<high
           and (a['numerator'],a['denominator'])!=(b['numerator'],b['denominator'])]
    predicted=[b for a,b in zip(bars['meter_events'],bars['meter_events'][1:])
               if low<b['time_seconds']<high and a['pulses_per_bar']!=b['pulses_per_bar']]
    matched=0
    by_meter={}
    for length in sorted({e['numerator'] for e in truth}|{e['pulses_per_bar'] for e in predicted}):
        ref=[e['time_seconds'] for e in truth if e['numerator']==length]
        est=[e['time_seconds'] for e in predicted if e['pulses_per_bar']==length]
        scores=event_metrics(ref,est,tolerance)
        by_meter[str(length)]=scores
        matched+=scores['matched_count']
    precision=matched/len(predicted) if predicted else 0.
    recall=matched/len(truth) if truth else 0.
    return {'assumption':'input pulse interpreted as a quarter note for scoring only; no oracle rescaling',
            'reference_change_count':len(truth),'predicted_change_count':len(predicted),'matched_count':matched,
            'f1':2*precision*recall/(precision+recall) if precision+recall else 0. if truth or predicted else None,
            'by_target_meter':by_meter,'false_changes_on_constant_meter':len(predicted) if not truth else None}
