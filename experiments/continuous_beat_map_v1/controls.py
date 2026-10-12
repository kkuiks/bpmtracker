"""Small, requested contract controls before the complete-song comparison."""
from pathlib import Path
import numpy as np
from .common import write
from .map import validate,sections,grid
from .score_audio import AudioScore
from .core import encode_unit

def main():
    checks=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append({'name':name,'pass':True})
    base={'status':'map','duration_seconds':8.,'initial':{'bpm':120.,'numerator':4,'denominator':4,'bar_zero_source_seconds':0.},'events':[]}
    tempo={**base,'events':[{'quarter':2.,'time':1.,'bpm':150.}]}
    partial={**base,'events':[{'quarter':2.,'time':1.,'numerator':3,'denominator':4}]}
    compound={**base,'initial':{**base['initial'],'numerator':6,'denominator':8},'events':[{'quarter':1.5,'time':.75,'numerator':4,'denominator':4}]}
    check('tempo_change_on_shared_old_beat',validate(tempo)['legal'])
    check('partial_old_bar_can_end_at_beat',validate(partial)['legal'])
    check('compound_eighth_boundary_is_legal',validate(compound)['legal'])
    check('tempo_continues_bar_accent',abs(grid(tempo,'bar')[1]-1.8)<1e-8)
    check('signature_starts_new_bar_on_same_tick',abs(grid(partial,'bar')[1]-1.)<1e-8)
    check('same_tempo_cannot_reset_phase',not validate({**base,'events':[{'quarter':2.,'time':1.2,'bpm':120.}]})['legal'])
    check('between_beats_rejected',not validate({**base,'events':[{'quarter':2.5,'time':1.25,'bpm':150.}]})['legal'])
    check('unchanged_declaration_rejected',not validate({**base,'events':[{'quarter':2.,'time':1.,'bpm':120.}]})['legal'])
    check('complete_click_coverage',validate(tempo)['continuous_source_coverage'])
    times=np.arange(0,8,.5);bars=np.arange(0,8,2.)
    events={'duration':8.,'times':times,'weights':np.ones(len(times)), 'downbeat_times':bars,'downbeat_weights':np.ones(len(bars)), 'pcm_times':times,'pcm_weights':np.ones(len(times))}
    audio=AudioScore(events)
    check('likelihood_scores_actual_derived_phase',audio.one(120,0,4,4,0,8)>audio.one(120,.2,4,4,0,8)+.4)
    prepared={'units':[{'id':0,'representative_bpm':120.,'source_score':1.},{'id':1,'representative_bpm':240.,'source_score':.9}]}
    check('same_unit_taps_discard_numeric_value',encode_unit(prepared,116.4)==encode_unit(prepared,123.6))
    check('packet_has_no_fine_tap',set(encode_unit(prepared,120.))=={'available','unit_id','source_prepared_units'})
    out=Path('data/research/design-reviews/20261011-continuous-beat-map-v1/implementation-checks/source-controls.json')
    write(out,{'checks':checks,'all_pass':True});print('SOURCE_CONTROLS',len(checks),'PASS')

if __name__=='__main__':main()
