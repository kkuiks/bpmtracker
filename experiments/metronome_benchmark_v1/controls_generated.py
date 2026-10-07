"""Check independent transport coordinates and paired music transformations."""

import argparse
from fractions import Fraction
from pathlib import Path
import tempfile

import numpy as np
import soundfile as sf

from .generated_controls import RATE, references, render_case, verify_clock
from .inference import write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    cases=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        cases.append({'name':name,'passed':True})
    with tempfile.TemporaryDirectory(prefix='joljak-generated-origin-') as temporary:
        root=Path(temporary)
        a=render_case(root/'a','a',Fraction(257,2),4,4501,'straight',bars=3)
        b=render_case(root/'b','b',Fraction(257,2),4,4501,'leading_shift',bars=3)
        first=verify_clock(root/'a',a);second=verify_clock(root/'b',b)
        check('rational_transport_matches_independent_pcm_marker',first['maximum_marker_frame_difference']<=1
              and first['maximum_music_event_frame_difference']<=1)
        original,_=sf.read(root/'a/music.wav',dtype='float64')
        shifted,_=sf.read(root/'b/music.wav',dtype='float64')
        delta=int(Fraction(317,1000)*RATE)
        check('leading_shift_preserves_every_music_sample',np.array_equal(original,shifted[delta:delta+len(original)])
              and np.max(abs(shifted[:delta]))==0)
        ra,rb=references(a),references(b)
        check('paired_shift_moves_defined_clock_without_label_fitting',abs(rb['offset_seconds']-ra['offset_seconds']-.317)<1e-12)
        check('known_grid_period_independent_of_music_onsets',abs(ra['quarter_times_seconds'][1]-ra['quarter_times_seconds'][0]-120/257)<1e-12)
        check('marker_is_not_part_of_model_music',a['marker_supplied_to_model'] is False
              and first['marker_not_model_input'] is True)
        check('generated_clock_is_not_certified_real_producer_truth',ra['independent_real_producer_clock'] is False
              and a['real_recording_generalization_evidence'] is False)
        three=render_case(root/'three','three',60,3,4502,'syncopated',bars=3)
        rthree=references(three)
        check('three_quarter_bar_constructed_explicitly',abs(rthree['downbeat_times_seconds'][1]-rthree['downbeat_times_seconds'][0]-3)<1e-12
              and three['meter']=={'numerator':3,'denominator':4})
        verify_clock(root/'three',three)
    write_json(args.output,{'purpose':'Generated transport/audio coordinates and paired transformations; not music accuracy','cases':cases,'passed':True})
    print(f'PASS {len(cases)} generated-clock controls',flush=True)


if __name__=='__main__':main()
